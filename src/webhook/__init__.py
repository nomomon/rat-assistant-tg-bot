"""Webhook handling for Telegram updates."""

from src.webhook.handler import process_update, HandlerDeps

__all__ = ["process_update", "HandlerDeps"]
