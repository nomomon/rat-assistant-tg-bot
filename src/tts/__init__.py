"""Text-to-speech via Gemini (WAV output)."""

from src.tts.generate import text_to_wav_file
from src.tts.wav_to_ogg_opus import wav_bytes_to_ogg_opus

__all__ = ["text_to_wav_file", "wav_bytes_to_ogg_opus"]
