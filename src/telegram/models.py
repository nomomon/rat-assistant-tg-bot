"""Pydantic models for Telegram Bot API Update payload."""

from pydantic import BaseModel, Field


class User(BaseModel):
    """Telegram user."""

    id: int
    is_bot: bool = False
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class Chat(BaseModel):
    """Telegram chat."""

    id: int
    type: str = "private"
    title: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class Voice(BaseModel):
    """Voice message file."""

    file_id: str
    file_unique_id: str = ""
    duration: int = 0
    mime_type: str | None = None


class Message(BaseModel):
    """Telegram message."""

    message_id: int
    from_user: User | None = Field(None, alias="from")
    chat: Chat
    date: int = 0
    text: str | None = None
    voice: Voice | None = None

    model_config = {"populate_by_name": True}


class Update(BaseModel):
    """Telegram webhook Update."""

    update_id: int
    message: Message | None = None

    @property
    def user_id(self) -> int | None:
        """User ID from the message sender, if present."""
        if self.message and self.message.from_user:
            return self.message.from_user.id
        return None

    @property
    def chat_id(self) -> int | None:
        """Chat ID to reply to, if present."""
        return self.message.chat.id if self.message else None
