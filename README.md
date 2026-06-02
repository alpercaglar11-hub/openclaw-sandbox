# OpenClaw Sandbox

> Autonomous AI agent platform with Telegram interface, tool calling, and distributed systems integration.

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Docker](https://img.shields.io/badge/Docker-Compose-blue) ![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-orange) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)

## What This Is

OpenClaw is a production-grade autonomous agent runtime. You send a message on Telegram, the agent reasons with DeepSeek, executes shell commands in an isolated sandbox, and reports back — all in one loop.

It is integrated with [The Cascade Simulation](https://github.com/alpercaglar11-hub/the-cascade-simulation) — a distributed systems failure simulation engine — enabling autonomous simulation runs, telemetry analysis, and failure prediction via chat.

## Architecture

\`\`\`
Telegram
    ↓
FastAPI Router (Uvicorn)
    ↓
HermesBrain Agent
    ├── DeepSeek API  (reasoning + tool calling)
    ├── Sandbox Executor  (whitelisted shell commands)
    ├── SQLite Memory  (conversation history)
    └── Cascade Bridge  (simulation engine integration)
\`\`\`

## Features

- **Telegram Bot** — natural language interface, no /task prefix needed
- **Tool Calling** — agent autonomously executes shell commands via DeepSeek function calling
- **Conversation Memory** — SQLite-backed chat history per user
- **Cascade Integration** — trigger distributed systems simulations, read telemetry
- **WebSocket Streaming** — real-time log streaming to dashboard
- **Production Docker** — health checks, structured JSON logging, async lifecycle
- **Whitelist Policy** — command execution restricted to safe binaries

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn (async) |
| LLM | DeepSeek (OpenAI-compatible) |
| Bot | python-telegram-bot v20 |
| Memory | SQLite + aiosqlite |
| HTTP | httpx (async) |
| Container | Docker Compose |
| Dashboard | Nginx + Vite |

## Quickstart

\`\`\`bash
git clone https://github.com/alpercaglar11-hub/openclaw-sandbox.git
cd openclaw-sandbox
cp .env.example .env
docker compose up --build -d
curl http://localhost:8000/health
\`\`\`

## Environment Variables

| Variable | Description |
|----------|-------------|
| TELEGRAM_BOT_TOKEN | Telegram bot token from @BotFather |
| DEEPSEEK_API_KEY | DeepSeek API key |
| DEEPSEEK_BASE_URL | DeepSeek endpoint (default: https://api.deepseek.com/v1) |
| DEEPSEEK_MODEL | Model name (default: deepseek-chat) |
| ADMIN_CHAT_ID | Telegram chat ID for authorization |
| LOG_LEVEL | Logging level (default: INFO) |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| /health | GET | Health check |
| /status | GET | System status and agent states |
| /execute | POST | Execute whitelisted shell command |
| /ws | WS | Real-time log streaming |

## Cascade Integration

OpenClaw is connected to The Cascade Simulation engine:

\`\`\`
Telegram: "run simulation and show results"
    ↓
HermesBrain → run_in_sandbox
    ↓
python -c "from simulations.recovery_engine import RecoveryEngine; ..."
    ↓
outcome: converged | stability: 0.96 | health: 0.997
    ↓
Telegram response with analysis
\`\`\`

## Security

- Command whitelist: node, python, bash, echo, ls, cat, git, curl, wget, pytest, pip
- Blocked: rm -rf /, mkfs, fdisk and all system-destructive commands
- Admin chat ID authorization for Telegram commands

## Related

- [The Cascade Simulation](https://github.com/alpercaglar11-hub/the-cascade-simulation) — Distributed systems failure simulation with ML failure prediction (XGBoost, AUC-ROC 0.76)
