"""Voice message transcription via OpenAI Whisper API."""

import io
import logging
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from src.telegram.client import TelegramClient

logger = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-1"
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


class TranscribeService:
    """Download voice from Telegram and transcribe with OpenAI Whisper."""

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        telegram_client: "TelegramClient",
    ) -> None:
        self._openai = openai_client
        self._telegram = telegram_client

    async def transcribe_voice(self, file_id: str) -> str:
        """
        Get voice file from Telegram, send to Whisper, return transcribed text.
        Raises ValueError if file is too large or transcription fails.
        """
        file_info = await self._telegram.get_file(file_id)
        file_path = file_info.get("file_path")
        if not file_path:
            raise ValueError("Telegram getFile did not return file_path")

        audio_bytes = await self._telegram.download_file(file_path)
        if len(audio_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"Voice file too large ({len(audio_bytes)} bytes, max {MAX_FILE_SIZE_BYTES})"
            )

        # OpenAI API expects a file-like object; Whisper accepts common formats including ogg
        file_like = io.BytesIO(audio_bytes)
        file_like.name = "voice.ogg"

        response = await self._openai.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=file_like,
        )
        text = (response.text or "").strip()
        logger.debug("Transcribed %d bytes -> %d chars", len(audio_bytes), len(text))
        return text
