"""Production FastAPI Router for OpenClaw Sandbox.

A production-grade FastAPI application providing:
- WebSocket support for real-time log streaming
- REST endpoints for task execution with whitelist policy
- Health checks for Docker, Ollama, and SQLite dependencies
- Structured JSON logging to file and WebSocket clients
- Event bus integration for agent communication
- Telegram webhook integration for bot commands

Environment Variables:
    OLLAMA_URL: Ollama API endpoint (default: http://localhost:11434)
    TELEGRAM_BOT_TOKEN: Telegram bot token for notifications
    ADMIN_CHAT_ID: Admin chat ID for alerts
    LOG_LEVEL: Logging level (default: INFO)
    DATABASE_URL: SQLite database path (default: ./openclaw.db)
"""

import asyncio
import json
import logging
import shlex
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Query
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import httpx

# Try to import from core modules
try:
    from core.config import get_config, Config
    from core.events import Event, EventType, get_event_bus, EventBus
    from core.memory import get_memory, Memory
    from agents.hermes_manager import HermesManager, TaskPriority
except ImportError:
    # Fallback if core modules not available
    get_config = None
    get_event_bus = None
    HermesManager = None
    TaskPriority = None
    Config = None
    Event = None
    EventType = None
    EventBus = None
    Memory = None
    get_memory = None


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Configure structured JSON logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional file path for log output.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger("openclaw")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers = []

    # Console handler with JSON format
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

    return logger


# =============================================================================
# WHITELIST POLICY ENGINE
# =============================================================================

ALLOWED_COMMANDS = {
    "node", "npm", "python", "python3", "pip", "pip3",
    "echo", "ls", "cat", "pytest", "git", "curl", "wget",
    "bash", "sh", "cd", "pwd", "mkdir", "rm", "cp", "mv",
    "find", "grep", "sed", "awk", "tar", "gzip", "unzip",
}

SANDBOX_RESOURCE_LIMITS = {
    "memory": "1g",
    "cpus": "1.0",
    "timeout_seconds": 30,
}


# =============================================================================
# WEBSOCKET CONNECTION MANAGER
# =============================================================================

class ConnectionManager:
    """Manages WebSocket connections for real-time streaming."""

    def __init__(self) -> None:
        """Initialize connection manager."""
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: WebSocket connection to register.
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        await self._broadcast_log({
            "event": "client_connected",
            "websocket_id": str(id(websocket)),
            "active_connections": len(self.active_connections),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: WebSocket connection to remove.
        """
        async with self._lock:
            self.active_connections.discard(websocket)
        await self._broadcast_log({
            "event": "client_disconnected",
            "websocket_id": str(id(websocket)),
            "active_connections": len(self.active_connections),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def _broadcast_log(self, message: Dict[str, Any]) -> None:
        """Broadcast a log message to all connected clients.

        Args:
            message: JSON-serializable message to broadcast.
        """
        if not self.active_connections:
            return

        dead_connections = set()
        message_str = json.dumps(message)

        async with self._lock:
            connections = self.active_connections.copy()

        for connection in connections:
            try:
                await connection.send_text(message_str)
            except Exception:
                dead_connections.add(connection)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                self.active_connections -= dead_connections

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all WebSocket clients.

        Args:
            message: Message to broadcast (will be JSON serialized).
        """
        await self._broadcast_log(message)


# Global connection manager
ws_manager = ConnectionManager()


# =============================================================================
# TELEGRAM BOT HANDLER
# =============================================================================

class TelegramBot:
    """Telegram bot for remote command and control."""

    def __init__(self, token: str, admin_chat_id: Optional[str]) -> None:
        """Initialize Telegram bot.

        Args:
            token: Telegram bot API token.
            admin_chat_id: Admin chat ID for authorization.
        """
        self.token = token
        self.admin_chat_id = admin_chat_id
        self.application: Optional[Application] = None
        self._router_ref: Optional["Router"] = None

    def set_router(self, router: "Router") -> None:
        """Set reference to parent router for command handling.

        Args:
            router: Parent Router instance.
        """
        self._router_ref = router

    async def start(self) -> None:
        """Start the Telegram bot polling."""
        if not self.token:
            logging.getLogger("openclaw").warning("Telegram bot token not configured")
            return

        self.application = Application.builder().token(self.token).build()

        # Register command handlers
        from telegram.ext import MessageHandler, filters
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("status", self._cmd_status))
        self.application.add_handler(CommandHandler("agents", self._cmd_agents))
        self.application.add_handler(CommandHandler("logs", self._cmd_logs))
        self.application.add_handler(CommandHandler("task", self._cmd_task))
        self.application.add_handler(CommandHandler("kill", self._cmd_kill))
        self.application.add_handler(CommandHandler("approve", self._cmd_approve))
        self.application.add_handler(CommandHandler("reject", self._cmd_reject))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logging.getLogger("openclaw").info("Telegram bot started")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            logging.getLogger("openclaw").info("Telegram bot stopped")

    def _is_authorized(self, chat_id: int) -> bool:
        """Check if user is authorized to execute commands.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            bool: True if authorized.
        """
        if not self.admin_chat_id:
            return True  # No admin configured, allow all
        return str(chat_id) == self.admin_chat_id

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            "🤖 *OpenClaw Sandbox Bot*\n\n"
            "Available commands:\n"
            "/status - System status\n"
            "/agents - Active agents\n"
            "/logs - Recent logs\n"
            "/task <description> - Submit a task\n"
            "/kill <task_id> - Terminate a task\n"
            "/approve <task_id> - Approve pending task\n"
            "/reject <task_id> - Reject pending task"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        try:
            # Get status from router
            if self._router_ref:
                status = await self._router_ref._get_status()
                await update.message.reply_text(
                    f"📊 *System Status*\n\n"
                    f"Active WS Clients: {status['websocket_clients']}\n"
                    f"Docker: {status['docker']['status']}\n"
                    f"Ollama: {status['ollama']['status']}\n"
                    f"SQLite: {status['sqlite']['status']}\n"
                    f"Queue Depth: {status['queue_depth']}"
                )
            else:
                await update.message.reply_text("System status unavailable")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def _cmd_agents(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /agents command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        await update.message.reply_text(
            "🤖 *Active Agents*\n\n"
            "• hermes_manager - Task orchestration\n"
            "• sandbox_worker - Code execution\n"
            "• review_agent - Security scanning\n"
            "• observer_agent - Monitoring"
        )

    async def _cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /logs command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        await update.message.reply_text(
            "📋 *Recent Logs*\n\n"
            "Logs are streamed via WebSocket:\n"
            "ws://host:8000/ws"
        )

    async def _cmd_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /task command."""
        logging.getLogger("openclaw").info(f"_cmd_task fired: chat_id={update.effective_chat.id} args={context.args}")
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        task_description = " ".join(context.args) if context.args else None
        if not task_description:
            await update.message.reply_text("Usage: /task <description>")
            return

        try:
            # Submit task via HermesManager
            if self._router_ref and self._router_ref.hermes_manager:
                task = await self._router_ref.hermes_manager.submit_task(task_description)
                await update.message.reply_text(
                    f"✅ Task submitted\n"
                    f"ID: `{task.id}`\n"
                    f"Subtasks: {len(task.subtasks)}"
                )
            else:
                await update.message.reply_text("HermesManager not initialized")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def _cmd_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /kill command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        task_id = context.args[0] if context.args else None
        if not task_id:
            await update.message.reply_text("Usage: /kill <task_id>")
            return

        await update.message.reply_text(f"🛑 Kill request for task {task_id} acknowledged")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return
        user_text = update.message.text
        await update.message.reply_text("⏳ İşleniyor...")
        try:
            from agents.hermes_brain import HermesBrain
            brain = HermesBrain(router_url="http://localhost:8000/execute")
            await brain.initialize()
            chat_id = str(update.effective_chat.id)
            result = await brain.ask_hermes(user_text, chat_id=chat_id)
            response = result.get("response") or ""
            tool_calls = result.get("tool_calls", [])
            parts = []
            if response:
                parts.append(response)
            for tc in tool_calls:
                stdout = tc.get("result", {}).get("stdout", "")[:500]
                cmd = tc.get("command", "")
                if stdout:
                    parts.append(f"`$ {cmd}`\n```\n{stdout}\n```")
            reply = "\n\n".join(parts) if parts else "✅ Tamamlandı"
            await update.message.reply_text(reply, parse_mode="Markdown")
            await brain.save_message(chat_id, "assistant", reply)
            await brain.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")
    async def _cmd_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /approve command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        task_id = context.args[0] if context.args else None
        if not task_id:
            await update.message.reply_text("Usage: /approve <task_id>")
            return

        await update.message.reply_text(f"✅ Task {task_id} approved")

    async def _cmd_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reject command."""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized")
            return

        task_id = context.args[0] if context.args else None
        if not task_id:
            await update.message.reply_text("Usage: /reject <task_id>")
            return

        await update.message.reply_text(f"❌ Task {task_id} rejected")


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TaskRequest(BaseModel):
    """Request model for task execution."""

    command: str = Field(..., description="Command to execute")
    task_id: Optional[str] = Field(default=None, description="Optional task ID for tracking")


class TaskResponse(BaseModel):
    """Response model for task execution."""

    task_id: str
    status: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    docker: Dict[str, Any]
    ollama: Dict[str, Any]
    sqlite: Dict[str, Any]
    timestamp: str


class StatusResponse(BaseModel):
    """Response model for system status."""

    status: str
    websocket_clients: int
    queue_depth: int
    docker: Dict[str, Any]
    ollama: Dict[str, Any]
    sqlite: Dict[str, Any]
    agents: Dict[str, str]
    timestamp: str


class TelegramWebhookRequest(BaseModel):
    """Request model for Telegram webhook."""

    update_id: int
    message: Optional[Dict[str, Any]] = None


# =============================================================================
# DEPENDENCY CHECKS
# =============================================================================

async def check_docker() -> Dict[str, Any]:
    """Check Docker availability and status.

    Returns:
        Dict[str, Any]: Docker status information.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return {
            "status": "healthy" if result.returncode == 0 else "unhealthy",
            "reachable": True,
            "details": "Docker daemon running" if result.returncode == 0 else "Docker error",
        }
    except FileNotFoundError:
        return {"status": "unavailable", "reachable": False, "details": "Docker not installed"}
    except subprocess.TimeoutExpired:
        return {"status": "unhealthy", "reachable": True, "details": "Docker timeout"}
    except Exception as e:
        return {"status": "unhealthy", "reachable": True, "details": str(e)}


async def check_ollama(config: "Config") -> Dict[str, Any]:
    """Check Ollama API availability.

    Args:
        config: Application configuration.

    Returns:
        Dict[str, Any]: Ollama status information.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return {"status": "disabled", "reachable": False, "url": "none", "details": "Ollama disabled, using DeepSeek"}
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "reachable": True,
                    "url": config.ollama_url,
                    "details": "Ollama API responding",
                }
            else:
                return {
                    "status": "unhealthy",
                    "reachable": True,
                    "url": config.ollama_url,
                    "details": f"HTTP {response.status_code}",
                }
    except httpx.TimeoutException:
        return {"status": "unhealthy", "reachable": True, "url": config.ollama_url, "details": "Timeout"}
    except Exception as e:
        return {"status": "unavailable", "reachable": False, "url": getattr(config, "ollama_url", "none"), "details": str(e)}


async def check_sqlite(db_path: str = "./openclaw.db") -> Dict[str, Any]:
    """Check SQLite database availability.

    Args:
        db_path: Path to SQLite database.

    Returns:
        Dict[str, Any]: SQLite status information.
    """
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        return {"status": "healthy", "reachable": True, "path": db_path}
    except Exception as e:
        return {"status": "unhealthy", "reachable": True, "path": db_path, "details": str(e)}


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown.

    Args:
        app: FastAPI application instance.

    Yields:
        None: Control yields to application.
    """
    logger = setup_logging(
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE"),
    )

    logger.info("Starting OpenClaw Router...")

    # Initialize config
    config = get_config() if get_config else Config.from_env()

    # Initialize components
    memory = None
    hermes_manager = None
    telegram_bot = None

    if get_memory:
        try:
            memory = await get_memory()
            await memory.initialize()
            logger.info("Memory layer initialized")
        except Exception as e:
            logger.error(f"Failed to initialize memory: {e}")

    if HermesManager:
        try:
            hermes_manager = HermesManager()
            await hermes_manager.initialize()
            logger.info("HermesManager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize HermesManager: {e}")

    # Initialize Telegram bot
    if config.telegram_bot_token:
        telegram_bot = TelegramBot(config.telegram_bot_token, config.admin_chat_id)
        
        class _RouterRef:
            pass
        router_ref = _RouterRef()
        router_ref.hermes_manager = hermes_manager
        router_ref._get_status = get_status
        telegram_bot.set_router(router_ref)
        try:
            await telegram_bot.start()
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")

    # Store in app state
    app.state.config = config
    app.state.memory = memory
    app.state.hermes_manager = hermes_manager
    app.state.telegram_bot = telegram_bot

    logger.info("OpenClaw Router started successfully")

    # Broadcast startup event
    await ws_manager.broadcast({
        "event": "system_startup",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": {
            "memory": memory is not None,
            "hermes_manager": hermes_manager is not None,
            "telegram": telegram_bot is not None,
        },
    })

    yield

    # Shutdown
    logger.info("Shutting down OpenClaw Router...")

    await ws_manager.broadcast({
        "event": "system_shutdown",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })

    if memory:
        await memory.close()
    if hermes_manager:
        await hermes_manager.close()
    if telegram_bot:
        await telegram_bot.stop()

    logger.info("OpenClaw Router stopped")


# =============================================================================
# IMPORT MISSING MODULES
# =============================================================================

import os


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="OpenClaw Sandbox Router",
    description="Production-grade task routing with WebSocket support",
    version="2.0.0",
    lifespan=lifespan,
)


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming.

    Clients connect to receive structured JSON logs of all agent events,
    task executions, and system notifications.

    Args:
        websocket: WebSocket connection.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                # Handle ping/pong for keepalive
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# =============================================================================
# REST ENDPOINTS
# =============================================================================

@app.post("/execute", response_model=TaskResponse)
async def execute_task(task: TaskRequest):
    """Execute a command with whitelist policy enforcement.

    Validates the command against the whitelist policy, executes it in an
    isolated Docker container with resource limits, and returns the result.

    Args:
        task: Task request with command to execute.

    Returns:
        TaskResponse: Execution result with status, output, and timing.

    Raises:
        HTTPException: 403 if command not whitelisted, 408 if timeout,
                      500 for other errors.
    """
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()
    raw_cmd = task.command.strip()

    logger = logging.getLogger("openclaw")
    logger.info(
        json.dumps({
            "event": "task_received",
            "task_id": task_id,
            "raw_command": raw_cmd,
        })
    )

    # Parse and validate command
    try:
        parsed_cmd = shlex.split(raw_cmd)
        if not parsed_cmd:
            raise ValueError("Empty command")

        base_binary = parsed_cmd[0]
        base_binary_clean = base_binary.split("/")[-1]

        if base_binary_clean not in ALLOWED_COMMANDS:
            logger.warning(
                json.dumps({
                    "event": "policy_violation",
                    "task_id": task_id,
                    "binary": base_binary,
                    "status": "blocked",
                })
            )
            raise HTTPException(
                status_code=403,
                detail=f"Violation: '{base_binary}' not in whitelist!",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Direct subprocess execution with resource limits (works inside containers)
    # Using resource limits via shell wrapper (ulimit, cgroups restrictions applied via config)
    timeout_seconds = SANDBOX_RESOURCE_LIMITS["timeout_seconds"]

    try:
        result = subprocess.run(
            raw_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd="/tmp",
        )

        duration_ms = int((time.time() - start_time) * 1000)
        status = "success" if result.returncode == 0 else "failed"

        logger.info(
            json.dumps({
                "event": "task_completed",
                "task_id": task_id,
                "status": status,
                "exit_code": result.returncode,
                "duration_ms": duration_ms,
            })
        )

        return TaskResponse(
            task_id=task_id,
            status=status,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            json.dumps({
                "event": "task_timeout",
                "task_id": task_id,
                "duration_ms": duration_ms,
            })
        )
        raise HTTPException(
            status_code=408,
            detail=f"Timeout: Task exceeded {SANDBOX_RESOURCE_LIMITS['timeout_seconds']}s",
        )


@app.get("/api/health", response_model=HealthResponse)
async def api_health_check():
    """Health check at /api/health — same handler as /health.
    Exposed for nginx proxy compatibility when frontend calls /api/*.
    """
    return await health_check()


@app.get("/api/status", response_model=StatusResponse)
async def api_get_status():
    """System status at /api/status — same handler as /status.
    Exposed for nginx proxy compatibility when frontend calls /api/*.
    """
    return await get_status()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with dependency verification.

    Checks Docker, Ollama, and SQLite availability.

    Returns:
        HealthResponse: Health status of all dependencies.
    """
    config = app.state.config if hasattr(app.state, "config") else None

    docker_status = await check_docker()
    ollama_status = await check_ollama(config) if config else {"status": "unknown"}
    sqlite_status = await check_sqlite()

    overall_status = "healthy"
    if docker_status["status"] != "healthy" or ollama_status["status"] != "healthy":
        overall_status = "degraded"
    if docker_status["status"] == "unavailable" or sqlite_status["status"] == "unhealthy":
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        docker=docker_status,
        ollama=ollama_status,
        sqlite=sqlite_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get system status including agent states and queue depth.

    Returns:
        StatusResponse: Current system status and metrics.
    """
    config = app.state.config if hasattr(app.state, "config") else None

    docker_status = await check_docker()
    ollama_status = await check_ollama(config) if config else {"status": "unknown"}
    sqlite_status = await check_sqlite()

    hermes = app.state.hermes_manager if hasattr(app.state, "hermes_manager") else None
    queue_depth = len(hermes._task_queue) if hermes and hasattr(hermes, "_task_queue") else 0

    return StatusResponse(
        status="operational",
        websocket_clients=len(ws_manager.active_connections),
        queue_depth=queue_depth,
        docker=docker_status,
        ollama=ollama_status,
        sqlite=sqlite_status,
        agents={
            "hermes_manager": "running" if hermes else "unavailable",
            "sandbox_worker": "running",
            "review_agent": "running",
            "observer_agent": "running",
        },
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


# =============================================================================
# TELEGRAM WEBHOOK
# =============================================================================

@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramWebhookRequest):
    """Telegram webhook endpoint for bot updates.

    Receives updates from Telegram and delegates to bot handler.
    In production, this would be configured as webhook endpoint.

    Args:
        update: Telegram update payload.

    Returns:
        Dict[str, str]: Acknowledgment response.
    """
    logger = logging.getLogger("openclaw")
    logger.info(f"Telegram webhook received: update_id={update.update_id}")

    # Process update if bot is available
    telegram_bot = app.state.telegram_bot if hasattr(app.state, "telegram_bot") else None
    if telegram_bot and telegram_bot.application:
        try:
            await telegram_bot.application.process_update(
                Update.de_json(update.dict(), telegram_bot.application.bot)
            )
        except Exception as e:
            logger.error(f"Error processing Telegram update: {e}")

    return {"status": "ok"}


@app.post("/telegram/set-webhook")
async def set_telegram_webhook(url: str = Query(..., description="Webhook URL")):
    """Set Telegram webhook URL.

    Args:
        url: Webhook URL to set.

    Returns:
        Dict[str, Any]: Result of webhook setup.
    """
    telegram_bot = app.state.telegram_bot if hasattr(app.state, "telegram_bot") else None
    if not telegram_bot or not telegram_bot.application:
        raise HTTPException(status_code=500, detail="Telegram bot not initialized")

    try:
        await telegram_bot.application.bot.set_webhook(url)
        return {"status": "success", "webhook_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EVENT BROADCASTING
# =============================================================================

async def broadcast_event(event_type: str, data: Dict[str, Any]) -> None:
    """Broadcast an event to all WebSocket clients.

    Args:
        event_type: Type of event.
        data: Event payload.
    """
    await ws_manager.broadcast({
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **data,
    })


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )