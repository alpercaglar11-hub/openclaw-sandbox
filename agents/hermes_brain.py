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

SYSTEM_PROMPT = """Sen Hermes Agent'ın beynisin. Kod yazma, dosya okuma/yazma veya test çalıştırma isteklerinde 'run_in_sandbox' aracını çağirmalisin. Sadece listedeki güvenli komutları üret.

Mevcut araçlar:
- run_in_sandbox: Güvenli Linux komut çalıştırma (node, python, bash, echo, ls, cat, pytest, git, curl, wget, vb.)

Yasaklı komutlar: rm -rf /, dd, mkfs, fdisk, vb. Sistem değişikliği yapan komutlar yasaktır."""


class HermesBrain:
    """Hermes Brain agent wrapping HermesManager with simple ask_hermes interface.

    Uses Ollama qwen2.5-coder:7b for reasoning and tool-calling, with direct
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
        self.ollama_url = self.config.ollama_url or "http://localhost:11434"
        self.model = self.config.ollama_model or "qwen2.5-coder:7b"
        logger.info(
            f"HermesBrain initialized (ollama={self.ollama_url}, router={self.router_url})"
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

    async def _call_ollama(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Call Ollama API with messages and tools.

        Args:
            messages: List of message dicts with role and content.
            tools: Optional list of tool definitions.

        Returns:
            Dict[str, Any]: Ollama response.
        """
        if self._http_client is None:
            await self.initialize()

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            response = await self._http_client.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return {"error": str(e)}

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

    async def ask_hermes(self, user_prompt: str) -> Dict[str, Any]:
        """Process a user prompt through Hermes Brain.

        Implements the tool-calling loop:
        1. Send prompt + system to Ollama with tools
        2. If model requests tool call, execute via router
        3. Return result or response

        Args:
            user_prompt: User's request/prompt.

        Returns:
            Dict[str, Any]: Result with status, response, and any tool outputs.
        """
        logger.info(f"HermesBrain processing: {user_prompt[:100]}...")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # First call to Ollama with tool definitions
        response = await self._call_ollama(messages, tools=[SANDBOX_TOOL_DEFINITION])

        if "error" in response:
            return {
                "status": "failed",
                "error": response["error"],
                "response": None,
            }

        message = response.get("message", {})

        # Check for tool calls
        if "tool_calls" in message:
            tool_results = []
            for tool_call in message["tool_calls"]:
                func_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": arguments}

                if func_name == "run_in_sandbox":
                    command = arguments.get("command", "")
                    logger.info(f"Executing sandbox command: {command}")

                    exec_result = await self._execute_command(command)
                    tool_results.append({
                        "tool": func_name,
                        "command": command,
                        "result": exec_result,
                    })

                    logger.info(f"Sandbox output: {exec_result}")

            return {
                "status": "success",
                "response": message.get("content", ""),
                "tool_calls": tool_results,
            }
        else:
            # No tool call, return content directly
            return {
                "status": "success",
                "response": message.get("content", ""),
                "tool_calls": [],
            }

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