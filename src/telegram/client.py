"""Telegram Bot API client using httpx."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class TelegramClient:
    """Async client for Telegram Bot API."""

    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        self._token = token
        self._base = f"{TELEGRAM_API_BASE}{token}"
        self._timeout = timeout

    async def get_file(self, file_id: str) -> dict[str, Any]:
        """Get file path for download. Returns {'file_path': '...'}."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base}/getFile", params={"file_id": file_id})
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getFile failed: {data}")
        return data["result"]

    async def download_file(self, file_path: str) -> bytes:
        """Download file bytes from Telegram (file_path from getFile)."""
        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        """Send a chat action (e.g. 'typing'). Logs and ignores failures."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    f"{self._base}/sendChatAction",
                    json={"chat_id": chat_id, "action": action},
                )
                r.raise_for_status()
        except Exception as e:
            logger.warning("send_chat_action failed: %s", e)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = "markdown",
        disable_web_page_preview: bool | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a chat."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            payload["disable_web_page_preview"] = disable_web_page_preview
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base}/sendMessage", json=payload)
            r.raise_for_status()
            return r.json()

    async def send_audio(
        self,
        chat_id: int,
        audio: bytes,
        *,
        filename: str = "reply.wav",
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Send an audio file (e.g. WAV) as a Telegram audio message."""
        data: dict[str, Any] = {"chat_id": chat_id}
        if caption is not None:
            data["caption"] = caption
        files = {"audio": (filename, audio, "audio/wav")}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/sendAudio",
                data=data,
                files=files,
            )
            r.raise_for_status()
            return r.json()
