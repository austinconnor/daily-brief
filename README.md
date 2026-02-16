# AI RSS Daily Brief

Containerized RSS aggregation + Gemini summarization + Discord webhook posting.

## Included services

- **postgres** (`postgres:16-alpine`) for Miniflux storage
- **miniflux** (`miniflux/miniflux:latest`) with web UI on `:8081`
- **ai-daily-brief** (custom Python 3.12 container) to post one daily digest to Discord

## Project layout

```text
.
├── compose.yml
├── daily-brief
│   ├── Dockerfile
│   └── main.py
├── data
│   └── postgres
└── .env.example
```

## Setup

1. Copy environment file and fill in real values:
   ```bash
   cp .env.example .env
   ```
2. Start stack:
   ```bash
   docker compose up -d
   ```
3. Open Miniflux UI:
   - `http://UNRAID_IP:8300`
4. In Miniflux: **Settings -> API Keys** -> create key.
5. Put key into `MINIFLUX_API_TOKEN` in `.env` and restart the brief service:
   ```bash
   docker compose up -d --build ai-daily-brief
   ```

## Notes

- Discord payloads are chunked to stay below 2000 chars (sent as <= 1900).
- The brief container waits until `RUN_AT_LOCAL_TIME` in timezone `TZ`, runs once, then waits for the next day.
- If there are no unread entries in the lookback window, it posts a short "No unread items found" message.
