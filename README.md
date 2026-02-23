# Krysatich Bot

Telegram bot with Pydantic AI (Gemini), webhooks, OpenAI Whisper for voice, and Redis for a 20-message context per user.

## Setup

1. Copy `.env.example` to `.env` and set:
   - `TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` or `GEMINI_API_KEY`, `REDIS_URL`, `ALLOWED_TELEGRAM_USER_IDS`
2. Install: `uv sync` or `pip install -e .`
3. Run Redis locally or set `REDIS_URL`.
4. Start the app: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
5. Set webhook (once, with HTTPS URL): `python -m scripts.set_webhook https://your-domain.com/webhook --secret YOUR_SECRET`

## Docker Compose

Runs the app and Redis; `.env` is loaded and `REDIS_URL` is set to the Redis service.

```bash
cp .env.example .env   # edit with your keys
docker compose up --build
```

App: http://localhost:8000. Set webhook to your public HTTPS URL (e.g. via ngrok for local testing).

Redis uses the Chainguard image (`cgr.dev/chainguard/redis`) so no Docker Hub login is needed. If you see auth errors when pulling the app image, run `docker logout` and try again.

## Endpoints

- `POST /webhook` — Telegram sends updates here.
- `GET /health` — Checks Redis connectivity.
