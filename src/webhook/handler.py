"""Process Telegram webhook updates: whitelist, text/voice/media, agent, history, reply."""

import asyncio
import logging
from dataclasses import dataclass
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import UnexpectedModelBehavior

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
    """
    Handle one Telegram update: whitelist, resolve text (or transcribe voice),
    run agent with history, persist history, send reply.
    """
    if not update.message or not update.message.from_user:
        return

    user_id = update.user_id
    chat_id = update.chat_id
    if user_id is None or chat_id is None:
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
        # Resolve user message into text or a list of content parts for the agent
        msg = update.message
        user_content: str | list[str | BinaryContent]

        if msg.text:
            user_content = msg.text.strip()

        elif msg.voice:
            try:
                transcribed = await deps.transcribe.transcribe_voice(msg.voice.file_id)
            except Exception as e:
                logger.exception("Transcription failed: %s", e)
                try:
                    await deps.telegram.send_message(chat_id, AUDIO_TRANSCRIPTION_ERROR_MESSAGE)
                except Exception as send_err:
                    logger.warning("Failed to send error reply: %s", send_err)
                return
            user_content = transcribed or "(empty transcription)"

        elif msg.photo:
            # Telegram sends multiple sizes; take the largest (last entry)
            largest = max(msg.photo, key=lambda p: p.file_size or 0)
            try:
                data = await _download_binary(deps.telegram, largest.file_id)
            except Exception as e:
                logger.exception("Photo download failed: %s", e)
                try:
                    await deps.telegram.send_message(chat_id, MEDIA_ERROR_MESSAGE)
                except Exception as send_err:
                    logger.warning("Failed to send error reply: %s", send_err)
                return
            if len(data) > MAX_MEDIA_BYTES:
                logger.warning("Photo too large (%d bytes), skipping binary", len(data))
                user_content = msg.caption or "(photo too large to process)"
            else:
                parts: list[str | BinaryContent] = []
                if msg.caption:
                    parts.append(msg.caption.strip())
                parts.append(BinaryContent(data=data, media_type="image/jpeg"))
                user_content = parts

        elif msg.document:
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
                    return
                if len(data) > MAX_MEDIA_BYTES:
                    logger.warning("Document too large (%d bytes), skipping binary", len(data))
                    user_content = msg.caption or f"(file '{doc.file_name}' too large to process)"
                else:
                    parts = []
                    if msg.caption:
                        parts.append(msg.caption.strip())
                    parts.append(BinaryContent(data=data, media_type=mime))
                    user_content = parts
            else:
                # Unsupported file type — pass as descriptive text so the agent can acknowledge it
                name_part = f"'{doc.file_name}'" if doc.file_name else "unknown filename"
                type_part = f" ({mime})" if mime else ""
                file_note = f"[Файл: {name_part}{type_part}]"
                user_content = f"{file_note} {msg.caption or ''}".strip()

        else:
            try:
                await deps.telegram.send_message(chat_id, HINT_MESSAGE)
            except Exception as e:
                logger.warning("Failed to send hint: %s", e)
            return

        # Full conversation (user + model messages) from the last hour; agent sees all of it.
        message_history = await deps.history.get(user_id)

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
            user_content,
            deps=agent_deps,
            message_history=message_history or None,
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
