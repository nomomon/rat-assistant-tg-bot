"""Exceptions and helpers for errors that should be shown to Telegram users."""

from openai import APIError
from pydantic_ai.exceptions import ModelHTTPError

OPENAI_QUOTA_EXHAUSTED_MESSAGE = (
    "Голосовые сообщения временно недоступны: исчерпана квота OpenAI. "
    "Пополните баланс API-ключа (Billing) и попробуйте снова."
)

GEMINI_BILLING_MESSAGE = (
    "Бот временно недоступен: проблема с оплатой Gemini API. "
    "Проверьте и пополните биллинг Gemini (Google Cloud) и попробуйте снова."
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


def _body_message_matches_billing(text: str) -> bool:
    lowered = text.lower()
    return "dunning" in lowered or "billing" in lowered


def is_gemini_billing_error(exc: ModelHTTPError) -> bool:
    """True when Gemini returns 403 PERMISSION_DENIED due to billing/dunning."""
    if exc.status_code != 403:
        return False

    body = exc.body
    if body is None:
        return False

    if isinstance(body, str):
        lowered = body.lower()
        return "permission_denied" in lowered or _body_message_matches_billing(body)

    if not isinstance(body, dict):
        return False

    error = body.get("error")
    if isinstance(error, dict):
        status = error.get("status")
        if isinstance(status, str) and status.upper() == "PERMISSION_DENIED":
            return True
        message = error.get("message")
        if isinstance(message, str) and _body_message_matches_billing(message):
            return True

    return False
