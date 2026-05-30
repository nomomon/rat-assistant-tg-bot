"""Exceptions and helpers for errors that should be shown to Telegram users."""

from openai import APIError

OPENAI_QUOTA_EXHAUSTED_MESSAGE = (
    "Голосовые сообщения временно недоступны: исчерпана квота OpenAI. "
    "Пополните баланс API-ключа (Billing) и попробуйте снова."
)


class UserFacingError(Exception):
    """A service failure with a message safe to send to the user in chat."""

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        super().__init__(user_message)


def openai_error_code(exc: APIError) -> str | None:
    """Extract OpenAI error code from an APIError (top-level or nested under error)."""
    if exc.code:
        return exc.code
    body = exc.body
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    if isinstance(code, str):
        return code
    nested = body.get("error")
    if not isinstance(nested, dict):
        return None
    nested_code = nested.get("code")
    if isinstance(nested_code, str):
        return nested_code
    nested_type = nested.get("type")
    if isinstance(nested_type, str):
        return nested_type
    return None


def is_openai_insufficient_quota(exc: APIError) -> bool:
    return openai_error_code(exc) == "insufficient_quota"
