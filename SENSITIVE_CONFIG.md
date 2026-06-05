# Sensitive Configuration

Do not commit real values for these variables. Keep them in `.env` or `.env.local`.

## Secrets

- `JIN10_WS_URL`: Jin10 WebSocket URL. It usually contains a token in the query string.
- `DEEPSEEK_API_KEY`: DeepSeek API key.
- `QQ_ACCESS_TOKEN`: OneBot/NapCat access token, if enabled.

## Private Runtime Identifiers

- `QQ_GROUP_ID`: Target QQ group ID.
- `QQ_BOT_API_URL`: Local or server OneBot HTTP endpoint.
- `AI_CHAT_HOST`: Bind address for the AI chat webhook.
- `AI_CHAT_PORT`: Bind port for the AI chat webhook.
- `MARKET_PROXY_URL`: Local proxy address, if needed for OKX market data.

## Files

- Commit: `.env.example`, source code, `README.md`.
- Do not commit: `.env`, `.env.local`, `logs/`, `data/`, `.venv/`, `backups/`, `.trash_*/`.

## Setup

```bash
cp .env.example .env
```

Then fill the real values in `.env`.
