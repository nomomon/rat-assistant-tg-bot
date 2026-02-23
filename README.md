# Krysatich Bot

Telegram bot with Pydantic AI (Gemini), webhooks, OpenAI Whisper for voice, and in-memory 20-message context per user.

## Setup

1. Copy `.env.example` to `.env` and set:
   - `TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` or `GEMINI_API_KEY`, `ALLOWED_TELEGRAM_USER_IDS`
2. Install: `uv sync` or `pip install -e .`
3. Start the app: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
4. Set webhook (once, with HTTPS URL): `python -m scripts.set_webhook https://your-domain.com/webhook --secret YOUR_SECRET`

## Docker Compose

Runs the app only (conversation history is in-memory; no Redis).

```bash
cp .env.example .env   # edit with your keys
docker compose up --build
```

App: http://localhost:8000. Set webhook to your public HTTPS URL (e.g. via ngrok for local testing).

## Endpoints

- `POST /webhook` — Telegram sends updates here.
- `GET /health` — Liveness check.
