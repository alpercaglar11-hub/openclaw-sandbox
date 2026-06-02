"""Hermes Brain Agent - migrated from hermes_brain.py.

Provides a simple ask_hermes() interface that wraps the HermesManager
for task decomposition with direct command execution via the router's
/execute endpoint.

The tool-calling loop (prompt -> Ollama -> run_in_sandbox -> result)
mirrors the original hermes_brain.py behavior.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from core.config import get_config

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS (compatible with Ollama tool-calling format)
# =============================================================================

SANDBOX_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "run_in_sandbox",
        "description": "Izole Linux ortamında güvenli komut, script veya test çalıştırmak için bu aracı kullan.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Çalıştırılacak Linux terminal komutu. Örn: 'node -e \"console.log(1+1)\"'"
                }
            },
            "required": ["command"]
        }
    }
}

SYSTEM_PROMPT = """Hermes AI. Alper'in asistanı. Türkçe yanıt ver. Kod/terminal için run_in_sandbox kullan. Kısa ve net ol."""


class HermesBrain:
    """Hermes Brain agent wrapping HermesManager with simple ask_hermes interface.

    Uses Ollama qwen2.5-coder:1.5b for reasoning and tool-calling, with direct
    command execution via the router's /execute endpoint.

    Attributes:
        config: Application configuration.
        _http_client: HTTP client for Ollama API calls.
        router_url: URL of the router's /execute endpoint.
    """

    def __init__(self, router_url: Optional[str] = None) -> None:
        """Initialize HermesBrain.

        Args:
            router_url: Optional router URL. Defaults to config.router_url.
        """
        self.config = get_config()
        self._http_client: Optional[httpx.AsyncClient] = None
        self.router_url = router_url or self.config.router_url or "http://localhost:8000/execute"
        import os
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        logger.info(
           f"HermesBrain initialized (model={self.deepseek_model}, router={self.router_url})"
        )

    async def initialize(self) -> None:
        """Initialize async components."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _call_ollama(self, messages: list, tools=None):
        """DeepSeek API with tool calling support."""
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.deepseek_model,
            "messages": messages,
            "temperature": 0.7
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            url = self.deepseek_base_url.rstrip(chr(47)) + chr(47) + "chat/completions"
            response = await self._http_client.post(url, json=payload, headers=headers, timeout=60.0)
            res_json = response.json()
            choice = res_json["choices"][0]
            message = choice["message"]
            # Tool call requested
            if message.get("tool_calls"):
                return {"tool_calls": message["tool_calls"], "content": message.get("content", "")}
            # Normal response
            return message.get("content", "")
        except Exception as e:
            return f"Sistem hatasi: {str(e)}"
    async def _execute_command(self, command: str) -> Dict[str, Any]:
        """Execute a command via the router's /execute endpoint.

        Args:
            command: Linux command to execute.

        Returns:
            Dict[str, Any]: Execution result.
        """
        if self._http_client is None:
            await self.initialize()

        try:
            response = await self._http_client.post(
                self.router_url,
                json={"command": command},
                timeout=65.0,
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "failed",
                    "error": f"Router returned {response.status_code}: {response.text}",
                }
        except Exception as e:
            logger.error(f"Router execution error: {e}")
            return {
                "status": "failed",
                "error": f"Router bağlantı hatası: {str(e)}",
            }

    async def get_history(self, chat_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Load conversation history from SQLite."""
        import aiosqlite
        async with aiosqlite.connect("./hermes_memory.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            cursor = await db.execute(
                "SELECT role, content FROM chat_history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit)
            )
            rows = await cursor.fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    async def save_message(self, chat_id: str, role: str, content: str) -> None:
        """Save a message to SQLite."""
        import aiosqlite
        async with aiosqlite.connect("./hermes_memory.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "INSERT INTO chat_history (chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, role, content)
            )
            await db.commit()

    async def ask_hermes(self, user_prompt: str, chat_id: str = "default") -> Dict[str, Any]:
        """Process a user prompt through Hermes Brain."""
        logger.info(f"HermesBrain processing: {user_prompt[:100]}...")

        history = await self.get_history(chat_id)
        await self.save_message(chat_id, "user", user_prompt)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        # Detect if task needs tool use or is just conversation
        needs_tool = any(kw in user_prompt.lower() for kw in ["çalıştır", "yaz", "kod", "python", "node", "bash", "ls", "cat", "script", "run", "execute", "dosya", "file"])
        response = await self._call_ollama(messages, tools=[SANDBOX_TOOL_DEFINITION])
        if isinstance(response, str) and response.startswith("Sistem hatasi"):
            return {"status": "failed", "error": response, "response": None}
        # Tool call requested by model
        if isinstance(response, dict) and response.get("tool_calls"):
            tool_results = []
            for tc in response["tool_calls"]:
                func_name = tc["function"]["name"]
                import json as _json
                try:
                    args = _json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                if func_name == "run_in_sandbox":
                    command = args.get("command", "")
                    logger.info(f"Executing sandbox command: {command}")
                    exec_result = await self._execute_command(command)
                    tool_results.append({"tool": func_name, "command": command, "result": exec_result})
            return {"status": "success", "response": response.get("content", ""), "tool_calls": tool_results}
        return {"status": "success", "response": response, "tool_calls": []}

    async def decompose_and_execute(
        self, task_description: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Decompose task using HermesManager and execute subtasks.

        Args:
            task_description: Description of the task.
            context: Optional execution context.

        Returns:
            Dict[str, Any]: Execution results.
        """
        from agents.hermes_manager import HermesManager

        manager = HermesManager()
        await manager.initialize()
        await manager.async_initialize()
        try:
            # Decompose task
            task = await manager.decompose_task(task_description, context)
            logger.info(f"Decomposed into {len(task.subtasks)} subtasks")

            results = []
            for subtask in task.subtasks:
                if subtask.assigned_agent == "sandbox_worker":
                    # Execute via HermesBrain ask_hermes
                    result = await self.ask_hermes(subtask.description)
                    results.append({
                        "subtask_id": subtask.id,
                        "description": subtask.description,
                        "result": result,
                    })

            return {
                "task_id": task.id,
                "status": "completed",
                "results": results,
            }
        finally:
            await manager.close()


# =============================================================================
# BACKWARDS COMPATIBILITY: Simple functions matching original hermes_brain.py
# =============================================================================

# Global instance for simple function interface
_brain_instance: Optional[HermesBrain] = None


def get_brain() -> HermesBrain:
    """Get or create the global HermesBrain instance.

    Returns:
        HermesBrain: Global instance.
    """
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = HermesBrain()
    return _brain_instance


async def ask_hermes_async(user_prompt: str) -> Dict[str, Any]:
    """Async version of ask_hermes - processes prompt through Hermes Brain.

    Args:
        user_prompt: User's request/prompt.

    Returns:
        Dict[str, Any]: Result with status, response, and tool outputs.
    """
    brain = get_brain()
    return await brain.ask_hermes(user_prompt)


# For synchronous compatibility - runs in new event loop
def ask_hermes(user_prompt: str) -> Dict[str, Any]:
    """Synchronous wrapper for ask_hermes_async.

    Note: This creates a new event loop per call. For high-frequency usage,
    prefer using ask_hermes_async directly with a shared loop.

    Args:
        user_prompt: User's request/prompt.

    Returns:
        Dict[str, Any]: Result with status, response, and tool outputs.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        # Already in async context, can't use run_coroutine_threadsafe
        # Fall back to creating a new loop (not ideal but works for simple use)
        return asyncio.run(ask_hermes_async(user_prompt))
    except RuntimeError:
        # No running loop, we can safely create one
        return asyncio.run(ask_hermes_async(user_prompt))


def run_in_sandbox(command: str) -> str:
    """Synchronous sandbox execution via router.

    Args:
        command: Linux command to execute.

    Returns:
        str: JSON stringified result.
    """
    import asyncio
    import requests

    try:
        response = requests.post(
            "http://localhost:8000/execute",
            json={"command": command},
            timeout=65,
        )
        return json.dumps(response.json(), indent=2)
    except Exception as e:
        return json.dumps({"status": "failed", "error": str(e)})


# Tool definition for external use (matching original interface)
sandbox_tool_definition = SANDBOX_TOOL_DEFINITION
