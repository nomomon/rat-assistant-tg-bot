#!/usr/bin/env python3
"""Set or delete the Telegram bot webhook. Run once after deployment.

Usage:
  python -m scripts.set_webhook https://your-domain.com/webhook [--secret YOUR_SECRET]
  python -m scripts.set_webhook --delete
"""

import argparse
import os
import sys

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def main() -> None:
    parser = argparse.ArgumentParser(description="Set or delete Telegram bot webhook")
    parser.add_argument(
        "url",
        nargs="?",
        help="Webhook URL (e.g. https://your-domain.com/webhook)",
    )
    parser.add_argument("--secret", default=None, help="Secret token for webhook verification")
    parser.add_argument("--delete", action="store_true", help="Remove webhook")
    parser.add_argument(
        "--token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help="Bot token (default: TELEGRAM_BOT_TOKEN)",
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: TELEGRAM_BOT_TOKEN not set and --token not provided", file=sys.stderr)
        sys.exit(1)

    base = f"{TELEGRAM_API_BASE}{args.token}"

    if args.delete:
        r = httpx.post(f"{base}/deleteWebhook")
    else:
        if not args.url:
            print("Error: URL required unless using --delete", file=sys.stderr)
            sys.exit(1)
        payload: dict = {"url": args.url}
        if args.secret:
            payload["secret_token"] = args.secret
        r = httpx.post(f"{base}/setWebhook", json=payload)

    data = r.json()
    if not data.get("ok"):
        print("Error:", data, file=sys.stderr)
        sys.exit(1)
    print("OK:", data.get("description", data))


if __name__ == "__main__":
    main()
