"""Application configuration from environment variables."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment (and .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(
        ...,
        description="Bot token from BotFather",
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_KEY"),
    )
    openai_api_key: str = Field(..., description="OpenAI API key for Whisper")
    google_api_key: str = Field(
        ...,
        description="Google API key for Gemini",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    allowed_telegram_user_ids: str = Field(
        ...,
        description="Comma-separated list of allowed Telegram user IDs",
    )
    webhook_secret_token: str | None = Field(
        default=None,
        description="Optional secret for webhook verification (X-Telegram-Bot-Api-Secret-Token)",
    )

    @property
    def allowed_user_ids(self) -> set[int]:
        """Parsed set of allowed Telegram user IDs."""
        if not self.allowed_telegram_user_ids.strip():
            return set()
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(",") if x.strip()}
