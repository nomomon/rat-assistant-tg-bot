"""Convert WAV bytes to OGG/Opus for Telegram sendVoice (requires ffmpeg on PATH)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def wav_bytes_to_ogg_opus(wav: bytes) -> bytes:
    """Encode *wav* as OGG Opus (mono, 64k) for Telegram voice messages."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        wav_p = tmp_path / "in.wav"
        ogg_p = tmp_path / "out.ogg"
        wav_p.write_bytes(wav)
        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                str(wav_p),
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                "-ac",
                "1",
                str(ogg_p),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err}")
        if not ogg_p.is_file():
            raise RuntimeError("ffmpeg did not produce output file")
        return ogg_p.read_bytes()
