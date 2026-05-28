"""Docker execution wrapper with resource limits.

Provides sandboxed code execution with configurable memory, CPU, and timeout
constraints using Docker.
"""

import asyncio
import logging
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import aiosqlite

from core.config import get_config
from core.events import Event, EventType, get_event_bus

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Execution status codes."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """Structured result from code execution."""

    status: ExecutionStatus = ExecutionStatus.PENDING
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary.

        Returns:
            Dict[str, Any]: Result as dictionary.
        """
        return {
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


class SandboxWorker:
    """Docker-based sandboxed execution worker.

    Provides secure code execution in Docker containers with resource limits
    including memory (default 1g), CPU (default 1.0), and timeout (default 30s).

    Attributes:
        config: Application configuration.
        event_bus: Event bus for agent communication.
        memory_limit: Memory limit for containers.
        cpu_limit: CPU limit for containers.
        timeout_seconds: Maximum execution time.
    """

    def __init__(
        self,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        """Initialize SandboxWorker.

        Args:
            memory_limit: Memory limit (e.g., "1g", "512m").
            cpu_limit: CPU limit as fraction (e.g., 1.0 = 1 CPU).
            timeout_seconds: Maximum execution timeout.
        """
        self.config = get_config()
        self.event_bus = get_event_bus()

        self.memory_limit = memory_limit or self.config.sandbox_memory_limit
        self.cpu_limit = cpu_limit or self.config.sandbox_cpu_limit
        self.timeout_seconds = timeout_seconds or self.config.sandbox_timeout_seconds

        self._active_executions: Dict[str, asyncio.Task] = {}
        logger.info(
            f"SandboxWorker initialized (memory={self.memory_limit}, "
            f"cpu={self.cpu_limit}, timeout={self.timeout_seconds}s)"
        )

    async def execute(
        self,
        code: str,
        language: str = "python",
        task_id: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        mounts: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute code in a sandboxed Docker container.

        Args:
            code: Code to execute.
            language: Programming language (python, node, bash).
            task_id: Optional task ID for tracking.
            environment: Environment variables for the container.
            mounts: Volume mounts in host:container format.

        Returns:
            ExecutionResult: Structured execution result.
        """
        execution_id = task_id or f"exec_{datetime.utcnow().timestamp()}"

        logger.info(f"Starting execution {execution_id} for language: {language}")

        # Publish sandbox started event
        event = Event(
            event_type=EventType.SANDBOX_STARTED,
            agent="sandbox_worker",
            task_id=execution_id,
            data={
                "language": language,
                "code_length": len(code),
                "memory_limit": self.memory_limit,
                "cpu_limit": self.cpu_limit,
            },
        )
        await self.event_bus.publish(event)

        start_time = asyncio.get_event_loop().time()
        result = ExecutionResult()

        try:
            # Build docker command
            docker_cmd = self._build_docker_command(
                code=code,
                language=language,
                environment=environment,
                mounts=mounts,
            )

            # Execute with timeout
            process = await asyncio.create_subprocess_shell(
                docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self._active_executions[execution_id] = asyncio.current_task()

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
                result.stdout = stdout_bytes.decode("utf-8", errors="replace")
                result.stderr = stderr_bytes.decode("utf-8", errors="replace")
                result.exit_code = process.returncode
                result.status = ExecutionStatus.COMPLETED if process.returncode == 0 else ExecutionStatus.FAILED

            except asyncio.TimeoutError:
                # Kill the process
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()

                result.status = ExecutionStatus.TIMEOUT
                result.error = f"Execution timed out after {self.timeout_seconds}s"
                logger.warning(f"Execution {execution_id} timed out")

        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            logger.error(f"Execution {execution_id} failed: {e}", exc_info=True)

        finally:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            result.duration_ms = duration_ms

            # Cleanup
            self._active_executions.pop(execution_id, None)

            # Publish sandbox stopped event
            event = Event(
                event_type=EventType.SANDBOX_STOPPED,
                agent="sandbox_worker",
                task_id=execution_id,
                data={
                    "status": result.status.value,
                    "duration_ms": duration_ms,
                    "exit_code": result.exit_code,
                },
            )
            await self.event_bus.publish(event)

        logger.info(
            f"Execution {execution_id} completed: {result.status.value} "
            f"in {duration_ms}ms"
        )
        return result

    def _build_docker_command(
        self,
        code: str,
        language: str,
        environment: Optional[Dict[str, str]],
        mounts: Optional[Dict[str, str]],
    ) -> str:
        """Build the docker run command.

        Args:
            code: Code to execute.
            language: Programming language.
            environment: Environment variables.
            mounts: Volume mounts.

        Returns:
            str: Complete docker command.
        """
        # Escape code for shell safety
        escaped_code = code.replace("'", "'\\''")

        # Base docker command with resource limits
        docker_args = [
            "docker",
            "run",
            "--rm",
            "--memory", self.memory_limit,
            "--cpus", str(self.cpu_limit),
            "--network", "none",
            "--cap-drop", "all",
            "--security-opt", "no-new-privileges",
        ]

        # Add environment variables
        env_vars = environment or {}
        env_vars.update({
            "EXECUTION_ID": f"exec_{datetime.utcnow().timestamp()}",
        })
        for key, value in env_vars.items():
            docker_args.extend(["-e", f"{key}={value}"])

        # Add mounts
        for host_path, container_path in (mounts or {}).items():
            docker_args.extend(["-v", f"{host_path}:{container_path}:ro"])

        # Determine image and run command based on language
        image, run_cmd = self._get_image_and_command(language, escaped_code)
        docker_args.append(image)

        if run_cmd:
            docker_args.extend(["sh", "-c", run_cmd])

        return " ".join(docker_args)

    def _get_image_and_command(
        self,
        language: str,
        code: str,
    ) -> tuple:
        """Get Docker image and command for language.

        Args:
            language: Programming language.
            code: Escaped code.

        Returns:
            tuple: (image_name, run_command).
        """
        # Simple mapping - in production would be more sophisticated
        lang_lower = language.lower()

        if lang_lower in ("python", "py"):
            return (
                "python:3.11-slim",
                f"python3 -c '{code}'",
            )
        elif lang_lower in ("node", "nodejs", "javascript"):
            return (
                "node:20-slim",
                f"node -e '{code}'",
            )
        elif lang_lower in ("bash", "sh"):
            return (
                "bash:5.2",
                code,
            )
        elif lang_lower in ("ruby", "rb"):
            return (
                "ruby:3.2-slim",
                f"ruby -e '{code}'",
            )
        elif lang_lower in ("go", "golang"):
            return (
                "golang:1.21-alpine",
                f"go run -e '{code}'",
            )
        else:
            # Default to python
            return (
                "python:3.11-slim",
                f"python3 -c '{code}'",
            )

    async def execute_batch(
        self,
        executions: List[Dict[str, Any]],
    ) -> List[ExecutionResult]:
        """Execute multiple code blocks in parallel.

        Args:
            executions: List of execution specifications.

        Returns:
            List[ExecutionResult]: Results for each execution.
        """
        tasks = []
        for exec_spec in executions:
            task = self.execute(
                code=exec_spec.get("code", ""),
                language=exec_spec.get("language", "python"),
                task_id=exec_spec.get("task_id"),
                environment=exec_spec.get("environment"),
                mounts=exec_spec.get("mounts"),
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution.

        Args:
            execution_id: ID of execution to cancel.

        Returns:
            bool: True if cancellation was successful.
        """
        task = self._active_executions.get(execution_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled execution: {execution_id}")
            return True
        return False

    def get_active_count(self) -> int:
        """Get number of active executions.

        Returns:
            int: Number of running executions.
        """
        return len(self._active_executions)

    async def health_check(self) -> Dict[str, Any]:
        """Check sandbox worker health.

        Returns:
            Dict[str, Any]: Health status information.
        """
        try:
            # Check if docker is accessible
            process = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.wait(), timeout=10.0)

            docker_available = process.returncode == 0

            return {
                "status": "healthy" if docker_available else "degraded",
                "docker_available": docker_available,
                "active_executions": self.get_active_count(),
                "memory_limit": self.memory_limit,
                "cpu_limit": self.cpu_limit,
                "timeout_seconds": self.timeout_seconds,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "active_executions": self.get_active_count(),
            }


# Global sandbox worker instance
_sandbox_worker: Optional[SandboxWorker] = None


def get_sandbox_worker() -> SandboxWorker:
    """Get the global sandbox worker instance.

    Returns:
        SandboxWorker: The global sandbox worker instance.
    """
    global _sandbox_worker
    if _sandbox_worker is None:
        _sandbox_worker = SandboxWorker()
    return _sandbox_worker