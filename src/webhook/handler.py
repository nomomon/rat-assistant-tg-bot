"""Process Telegram webhook updates: whitelist, text/voice/media, agent, history, reply."""

import asyncio
import logging
from dataclasses import dataclass
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, UserPromptPart

from src.telegram.models import Update
from src.telegram.client import TelegramClient
from src.services.history import HistoryService
from src.services.transcribe import TranscribeService
from src.agent.deps import AgentDeps

logger = logging.getLogger(__name__)

NOT_ALLOWED_MESSAGE = "Вам не разрешено использовать этого бота."
ERROR_MESSAGE = "Что-то пошло не так. Пожалуйста, попробуйте снова позже."
AUDIO_TRANSCRIPTION_ERROR_MESSAGE = "Не удалось распознать голосовое сообщение. Пожалуйста, попробуйте снова."
MEDIA_ERROR_MESSAGE = "Не удалось загрузить медиафайл. Пожалуйста, попробуйте снова."
HINT_MESSAGE = "Отправьте текстовое или голосовое сообщение, фото или документ (PDF / изображение), и я отвечу."

MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB inline limit for Gemini

# MIME types that Gemini can process as images or documents
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_DOCUMENT_MIME_TYPES = {"application/pdf"}


async def _download_binary(telegram: TelegramClient, file_id: str) -> bytes:
    """Resolve file_id to bytes via Telegram getFile + download."""
    file_info = await telegram.get_file(file_id)
    file_path = file_info.get("file_path")
    if not file_path:
        raise ValueError(f"Telegram getFile returned no file_path for {file_id}")
    return await telegram.download_file(file_path)


async def _resolve_user_content(update: Update, deps: "HandlerDeps") -> str | list[str | BinaryContent] | None:
    """Resolve one update into user content understood by the agent."""
    msg = update.message
    if not msg:
        return None

    chat_id = update.chat_id
    if chat_id is None:
        return None

    if msg.text:
        return msg.text.strip()

    if msg.voice:
        try:
            transcribed = await deps.transcribe.transcribe_voice(msg.voice.file_id)
        except Exception as e:
            logger.exception("Transcription failed: %s", e)
            try:
                await deps.telegram.send_message(chat_id, AUDIO_TRANSCRIPTION_ERROR_MESSAGE)
            except Exception as send_err:
                logger.warning("Failed to send error reply: %s", send_err)
            return None
        return transcribed or "(empty transcription)"

    if msg.photo:
        largest = max(msg.photo, key=lambda p: p.file_size or 0)
        try:
            data = await _download_binary(deps.telegram, largest.file_id)
        except Exception as e:
            logger.exception("Photo download failed: %s", e)
            try:
                await deps.telegram.send_message(chat_id, MEDIA_ERROR_MESSAGE)
            except Exception as send_err:
                logger.warning("Failed to send error reply: %s", send_err)
            return None
        if len(data) > MAX_MEDIA_BYTES:
            logger.warning("Photo too large (%d bytes), skipping binary", len(data))
            return msg.caption or "(photo too large to process)"
        parts: list[str | BinaryContent] = []
        if msg.caption:
            parts.append(msg.caption.strip())
        parts.append(BinaryContent(data=data, media_type="image/jpeg"))
        return parts

    if msg.document:
        doc = msg.document
        mime = (doc.mime_type or "").lower()
        if mime in _IMAGE_MIME_TYPES or mime in _DOCUMENT_MIME_TYPES:
            try:
                data = await _download_binary(deps.telegram, doc.file_id)
            except Exception as e:
                logger.exception("Document download failed: %s", e)
                try:
                    await deps.telegram.send_message(chat_id, MEDIA_ERROR_MESSAGE)
                except Exception as send_err:
                    logger.warning("Failed to send error reply: %s", send_err)
                return None
            if len(data) > MAX_MEDIA_BYTES:
                logger.warning("Document too large (%d bytes), skipping binary", len(data))
                return msg.caption or f"(file '{doc.file_name}' too large to process)"
            parts = []
            if msg.caption:
                parts.append(msg.caption.strip())
            parts.append(BinaryContent(data=data, media_type=mime))
            return parts
        # Unsupported file type — pass as descriptive text so the agent can acknowledge it.
        name_part = f"'{doc.file_name}'" if doc.file_name else "unknown filename"
        type_part = f" ({mime})" if mime else ""
        file_note = f"[Файл: {name_part}{type_part}]"
        return f"{file_note} {msg.caption or ''}".strip()

    return None

@dataclass
class HandlerDeps:
    """Dependencies for the webhook handler."""

    telegram: TelegramClient
    history: HistoryService
    transcribe: TranscribeService
    agent: Agent[AgentDeps, str]
    allowed_user_ids: set[int]
    google_api_key: str


async def process_update(update: Update, deps: HandlerDeps) -> None:
    """Handle one Telegram update."""
    await process_updates_batch([update], deps)


async def process_updates_batch(updates: list[Update], deps: HandlerDeps) -> None:
    """Handle a burst of Telegram updates as one agent run."""
    if not updates:
        return

    first = updates[0]
    if not first.message or not first.message.from_user:
        return

    user_id = first.user_id
    chat_id = first.chat_id
    if user_id is None or chat_id is None:
        return

    for update in updates[1:]:
        if update.user_id != user_id or update.chat_id != chat_id:
            logger.warning("Skipping mixed-user mixed-chat batch")
            return

    # Whitelist
    if user_id not in deps.allowed_user_ids:
        try:
            await deps.telegram.send_message(chat_id, NOT_ALLOWED_MESSAGE)
        except Exception as e:
            logger.warning("Failed to send not-allowed message: %s", e)
        return

    reply_action_task: asyncio.Task[None] | None = None

    async def begin_reply_chat_action(as_voice: bool) -> None:
        nonlocal reply_action_task
        if reply_action_task is not None:
            reply_action_task.cancel()
            try:
                await reply_action_task
            except asyncio.CancelledError:
                pass
        # Telegram sendChatAction: typing for text; record_voice for voice-note style replies.
        action = "record_voice" if as_voice else "typing"

        async def reply_action_loop() -> None:
            try:
                await deps.telegram.send_chat_action(chat_id, action)
                while True:
                    await asyncio.sleep(4)
                    await deps.telegram.send_chat_action(chat_id, action)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Reply chat action failed: %s", e)

        reply_action_task = asyncio.create_task(reply_action_loop())

    try:
        user_contents: list[str | list[str | BinaryContent]] = []
        for update in updates:
            user_content = await _resolve_user_content(update, deps)
            if user_content is None:
                continue
            if isinstance(user_content, str) and not user_content.strip():
                continue
            user_contents.append(user_content)

        if not user_contents:
            try:
                await deps.telegram.send_message(chat_id, HINT_MESSAGE)
            except Exception as e:
                logger.warning("Failed to send hint: %s", e)
            return

        # Full conversation (user + model messages) from the last hour; agent sees all of it.
        message_history = await deps.history.get(user_id)
        pre_messages = [
            ModelRequest(parts=[UserPromptPart(content=content)])
            for content in user_contents[:-1]
        ]

        # Start "typing" indicator right away so the user sees feedback
        # while the agent is thinking.  The loop keeps running until
        # the finally-block cancels it.
        await begin_reply_chat_action(False)

        send_lock = asyncio.Lock()
        agent_deps = AgentDeps(
            telegram_client=deps.telegram,
            chat_id=chat_id,
            google_api_key=deps.google_api_key,
            begin_reply_chat_action=begin_reply_chat_action,
            send_lock=send_lock,
        )
        result = await deps.agent.run(
            user_contents[-1],
            deps=agent_deps,
            message_history=(message_history + pre_messages) or None,
        )
        # The agent replies via the send_message tool; we only persist history here.
        new_messages = result.new_messages()
        await deps.history.append(user_id, new_messages)
    except UnexpectedModelBehavior as e:
        logger.exception("Agent output validation failed: %s", e)
        try:
            await deps.telegram.send_message(chat_id, ERROR_MESSAGE)
        except Exception as send_err:
            logger.warning("Failed to send error reply: %s", send_err)
    except Exception as e:
        logger.exception("Agent or send failed: %s", e)
        try:
            await deps.telegram.send_message(chat_id, ERROR_MESSAGE)
        except Exception as send_err:
            logger.warning("Failed to send error reply: %s", send_err)
    finally:
        if reply_action_task is not None:
            reply_action_task.cancel()
            try:
                await reply_action_task
            except asyncio.CancelledError:
                pass
