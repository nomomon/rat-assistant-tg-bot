"""Process Telegram webhook updates: whitelist, text/voice, agent, history, reply."""

import asyncio
import logging
from dataclasses import dataclass
from pydantic_ai import Agent

from src.telegram.models import Update
from src.telegram.client import TelegramClient
from src.services.history import HistoryService
from src.services.transcribe import TranscribeService
from src.agent.deps import AgentDeps

logger = logging.getLogger(__name__)

NOT_ALLOWED_MESSAGE = "Вам не разрешено использовать этого бота."
ERROR_MESSAGE = "Что-то пошло не так. Пожалуйста, попробуйте снова позже."
AUDIO_TRANSCRIPTION_ERROR_MESSAGE = "Не удалось распознать голосовое сообщение. Пожалуйста, попробуйте снова."
HINT_MESSAGE = "Отправьте текстовое или голосовое сообщение, и я отвечу."

@dataclass
class HandlerDeps:
    """Dependencies for the webhook handler."""

    telegram: TelegramClient
    history: HistoryService
    transcribe: TranscribeService
    agent: Agent[AgentDeps, str]
    allowed_user_ids: set[int]


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

    typing_task: asyncio.Task[None] | None = None

    async def typing_loop() -> None:
        try:
            await deps.telegram.send_chat_action(chat_id, "typing")
            while True:
                await asyncio.sleep(4)
                await deps.telegram.send_chat_action(chat_id, "typing")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Typing action failed: %s", e)

    try:
        typing_task = asyncio.create_task(typing_loop())

        # Resolve user message text
        msg = update.message
        if msg.text:
            user_text = msg.text.strip()
        elif msg.voice:
            try:
                user_text = await deps.transcribe.transcribe_voice(msg.voice.file_id)
            except Exception as e:
                logger.exception("Transcription failed: %s", e)
                try:
                    await deps.telegram.send_message(
                        chat_id,
                        AUDIO_TRANSCRIPTION_ERROR_MESSAGE,
                    )
                except Exception as send_err:
                    logger.warning("Failed to send error reply: %s", send_err)
                return
            if not user_text:
                user_text = "(empty transcription)"
        else:
            try:
                await deps.telegram.send_message(
                    chat_id,
                    HINT_MESSAGE,
                )
            except Exception as e:
                logger.warning("Failed to send hint: %s", e)
            return

        # Full conversation (user + model messages) from the last hour; agent sees all of it.
        message_history = await deps.history.get(user_id)
        agent_deps = AgentDeps(telegram_client=deps.telegram, chat_id=chat_id)
        result = await deps.agent.run(
            user_text,
            deps=agent_deps,
            message_history=message_history or None,
        )
        # The agent replies via the send_message tool; we only persist history here.
        new_messages = result.new_messages()
        await deps.history.append(user_id, new_messages)
    except Exception as e:
        logger.exception("Agent or send failed: %s", e)
        try:
            await deps.telegram.send_message(chat_id, ERROR_MESSAGE)
        except Exception as send_err:
            logger.warning("Failed to send error reply: %s", send_err)
    finally:
        if typing_task is not None:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
