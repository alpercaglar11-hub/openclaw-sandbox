# OpenClaw Sandbox

Autonomous runtime environment for orchestrating multi-agent video processing workflows.

## Architecture

- **FastAPI** — async REST API server
- **Telegram Bot** — operator interface via `@botfather`
- **WebSocket Events** — real-time pipeline status streaming
- **SQLite (aiosqlite)** — workflow state persistence
- **Autonomous Loop** — self-healing task scheduler

## Quickstart

```bash
# Install dependencies
make install

# Run tests
make test

# Start server
make run

# Docker
make docker-build
make docker-up

# Health check
make health-check
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `DATABASE_URL` | SQLite database path |
| `LOG_LEVEL` | Logging level (default: INFO) |
