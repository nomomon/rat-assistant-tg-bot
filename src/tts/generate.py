"""Gemini TTS: text to WAV (chunked for long input)."""

from __future__ import annotations

import mimetypes
import struct
import tempfile
import wave
from pathlib import Path

from google import genai
from google.genai import types

CHUNK_SIZE = 3000
TTS_MODEL = "gemini-2.5-pro-preview-tts"
TTS_VOICE = "Achernar"


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split *text* into chunks of ~*size* chars, breaking at paragraph boundaries."""
    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def parse_audio_mime_type(mime_type: str) -> dict[str, int]:
    bits_per_sample = 16
    rate = 24000
    for param in mime_type.split(";"):
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    params = parse_audio_mime_type(mime_type)
    bits_per_sample = params["bits_per_sample"]
    sample_rate = params["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + audio_data


def generate_audio_for_chunk(client: genai.Client, text: str, out_path: str | Path) -> None:
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=f"Read aloud in a warm and friendly tone:\n{text}"
                )
            ],
        )
    ]
    config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=TTS_VOICE
                )
            )
        ),
    )

    audio_parts: list[tuple[bytes, str]] = []
    for chunk in client.models.generate_content_stream(
        model=TTS_MODEL,
        contents=contents,
        config=config,
    ):
        if chunk.parts is None:
            continue
        part = chunk.parts[0]
        if part.inline_data and part.inline_data.data:
            audio_parts.append((part.inline_data.data, part.inline_data.mime_type))

    if not audio_parts:
        raise RuntimeError(f"No audio returned for chunk: {text[:60]!r}")

    raw_audio = b"".join(data for data, _ in audio_parts)
    mime_type = audio_parts[0][1]

    ext = mimetypes.guess_extension(mime_type or "")
    if ext is None:
        wav_data = convert_to_wav(raw_audio, mime_type or "audio/L16;rate=24000")
    else:
        wav_data = raw_audio

    out = Path(out_path)
    out.write_bytes(wav_data)


def join_wavs(input_files: list[str | Path], output_path: str | Path) -> None:
    out_p = Path(output_path)
    with wave.open(str(out_p), "wb") as out:
        for i, path in enumerate(input_files):
            with wave.open(str(path), "rb") as w:
                if i == 0:
                    out.setparams(w.getparams())
                out.writeframes(w.readframes(w.getnframes()))


def text_to_wav_file(text: str, output_path: Path, *, api_key: str) -> None:
    """Generate WAV at *output_path* from *text* using Gemini TTS."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("text_to_wav_file: empty text")

    client = genai.Client(api_key=api_key)
    chunks = chunk_text(stripped)
    out = Path(output_path)

    if len(chunks) == 1:
        generate_audio_for_chunk(client, chunks[0], out)
        return

    with tempfile.TemporaryDirectory() as tmp:
        chunk_paths: list[Path] = []
        for i, ch in enumerate(chunks):
            p = Path(tmp) / f"chunk_{i:03d}.wav"
            generate_audio_for_chunk(client, ch, p)
            chunk_paths.append(p)
        join_wavs(chunk_paths, out)
