"""Task decomposition and routing agent.

Uses Ollama qwen2.5-coder:7b to decompose tasks and route them to appropriate
agents based on task characteristics.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from core.config import get_config
from core.events import Event, EventType, get_event_bus
from core.memory import get_memory

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(Enum):
    """Task priority levels."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class SubTask:
    """A decomposed subtask."""

    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    assigned_agent: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class Task:
    """An orchestrated task."""

    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    subtasks: List[SubTask] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary.

        Returns:
            Dict[str, Any]: Task as dictionary.
        """
        return {
            "id": self.id,
            "description": self.description,
            "subtasks": [
                {
                    "id": st.id,
                    "description": st.description,
                    "assigned_agent": st.assigned_agent,
                    "dependencies": st.dependencies,
                    "status": st.status.value,
                }
                for st in self.subtasks
            ],
            "status": self.status.value,
            "priority": self.priority.value,
            "context": self.context,
        }


class HermesManager:
    """Task decomposition and routing manager.

    Uses Ollama qwen2.5-coder:7b to analyze tasks, decompose them into
    subtasks, and route to appropriate execution agents.

    Attributes:
        config: Application configuration.
        event_bus: Event bus for agent communication.
        memory: Persistent storage layer.
        _task_queue: Internal task queue.
    """

    AGENT_CAPABILITIES = {
        "sandbox_worker": ["code_execution", "docker_execution", "file_operations"],
        "review_agent": ["security_scan", "code_review", "quality_check"],
        "observer_agent": ["monitoring", "metrics", "logging", "alerts"],
    }

    def __init__(self) -> None:
        """Initialize HermesManager."""
        self.config = get_config()
        self.event_bus = get_event_bus()
        self._memory: Optional[Any] = None
        self._task_queue: Dict[str, Task] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        logger.info("HermesManager initialized")

    async def initialize(self) -> None:
        """Initialize async components."""
        self._memory = await get_memory()
        self._http_client = httpx.AsyncClient(timeout=60.0)
        logger.info("HermesManager async initialized")

    async def close(self) -> None:
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
        logger.info("HermesManager closed")

    async def _call_ollama(self, prompt: str, system: str) -> Optional[str]:
        """Call Ollama API for task decomposition.

        Args:
            prompt: User prompt for the model.
            system: System prompt with instructions.

        Returns:
            Optional[str]: Model response or None on error.
        """
        if not self._http_client:
            await self.initialize()

        try:
            response = await self._http_client.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.ollama_model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                },
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "").strip()
        except httpx.HTTPError as e:
            logger.error(f"Ollama HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return None

    async def decompose_task(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> Task:
        """Decompose a task into subtasks using LLM.

        Args:
            task_description: Description of the task to decompose.
            context: Optional execution context.

        Returns:
            Task: Decomposed task with subtasks.
        """
        logger.info(f"Decomposing task: {task_description[:100]}...")

        system_prompt = """You are a task decomposition expert. Given a task description,
break it down into smaller subtasks that can be executed in parallel or sequence.
For each subtask, specify:
1. A clear description
2. Which agent should handle it (sandbox_worker, review_agent, or observer_agent)
3. Any dependencies on other subtasks

Return your response as a JSON array of subtasks:
[
  {
    "description": "subtask description",
    "assigned_agent": "agent_name",
    "dependencies": ["subtask_id_1", "subtask_id_2"]
  }
]

Only output valid JSON, no markdown or explanation."""

        response = await self._call_ollama(
            prompt=f"Decompose this task: {task_description}\n\nContext: {context or {}}",
            system=system_prompt,
        )

        task = Task(
            description=task_description,
            context=context or {},
        )

        if response:
            import json
            try:
                subtask_data = json.loads(response)
                for st_data in subtask_data:
                    subtask = SubTask(
                        description=st_data.get("description", ""),
                        assigned_agent=st_data.get("assigned_agent", "sandbox_worker"),
                        dependencies=st_data.get("dependencies", []),
                    )
                    task.subtasks.append(subtask)
                logger.info(f"Decomposed into {len(task.subtasks)} subtasks")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse LLM response: {e}")
                # Create single subtask fallback
                task.subtasks.append(
                    SubTask(description=task_description, assigned_agent="sandbox_worker")
                )
        else:
            # Fallback: single subtask
            task.subtasks.append(
                SubTask(description=task_description, assigned_agent="sandbox_worker")
            )

        # Publish decomposition event
        event = Event(
            event_type=EventType.TASK_DECOMPOSED,
            agent="hermes_manager",
            task_id=task.id,
            data={"subtask_count": len(task.subtasks)},
        )
        await self.event_bus.publish(event)

        return task

    def _route_subtask(self, subtask: SubTask) -> str:
        """Route a subtask to appropriate agent.

        Args:
            subtask: The subtask to route.

        Returns:
            str: Agent name to handle the subtask.
        """
        # Check explicit assignment first
        if subtask.assigned_agent:
            return subtask.assigned_agent

        # Analyze description for routing hints
        description_lower = subtask.description.lower()

        if any(kw in description_lower for kw in ["security", "scan", "review", "check"]):
            return "review_agent"
        elif any(kw in description_lower for kw in ["monitor", "log", "metric", "alert"]):
            return "observer_agent"
        else:
            return "sandbox_worker"

    async def submit_task(
        self,
        task_description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        context: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Submit a new task for orchestration.

        Args:
            task_description: Description of the task.
            priority: Task priority.
            context: Optional execution context.

        Returns:
            Task: The submitted task with decomposed subtasks.
        """
        task = await self.decompose_task(task_description, context)
        task.priority = priority

        # Route each subtask
        for subtask in task.subtasks:
            agent = self._route_subtask(subtask)
            subtask.assigned_agent = agent

            # Publish routing event
            event = Event(
                event_type=EventType.TASK_ROUTED,
                agent="hermes_manager",
                task_id=task.id,
                data={
                    "subtask_id": subtask.id,
                    "assigned_agent": agent,
                },
            )
            await self.event_bus.publish(event)

        self._task_queue[task.id] = task
        await self._memory.create_task(
            task_id=task.id,
            description=task_description,
            metadata=task.to_dict(),
            priority=priority.value,
        )

        logger.info(f"Task submitted: {task.id} with {len(task.subtasks)} subtasks")
        return task

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a task.

        Args:
            task_id: Task identifier.

        Returns:
            Optional[Dict[str, Any]]: Task status or None if not found.
        """
        task = self._task_queue.get(task_id)
        if not task:
            task_data = await self._memory.get_task(task_id)
            return task_data
        return task.to_dict()

    async def execute_task(self, task_id: str) -> Dict[str, Any]:
        """Execute a task by processing all subtasks.

        Args:
            task_id: Task identifier.

        Returns:
            Dict[str, Any]: Execution results.
        """
        task = self._task_queue.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        logger.info(f"Executing task: {task_id}")
        task.status = TaskStatus.IN_PROGRESS

        # Publish execution started event
        event = Event(
            event_type=EventType.TASK_EXECUTING,
            agent="hermes_manager",
            task_id=task_id,
        )
        await self.event_bus.publish(event)

        results = []
        for subtask in task.subtasks:
            # Check dependencies
            if subtask.dependencies:
                unmet = [
                    dep for dep in subtask.dependencies
                    if not self._is_subtask_completed(task, dep)
                ]
                if unmet:
                    subtask.status = TaskStatus.BLOCKED
                    results.append({
                        "subtask_id": subtask.id,
                        "status": "blocked",
                        "reason": f"Dependencies not met: {unmet}",
                    })
                    continue

            subtask.status = TaskStatus.IN_PROGRESS

            # Simulate execution (in production, would invoke actual agent)
            result = await self._execute_subtask(subtask)
            results.append(result)

            if result.get("status") == "failed":
                task.status = TaskStatus.FAILED
                break

        # Check if all completed
        if all(st.status == TaskStatus.COMPLETED for st in task.subtasks):
            task.status = TaskStatus.COMPLETED

        event = Event(
            event_type=EventType.TASK_COMPLETED if task.status == TaskStatus.COMPLETED else EventType.TASK_FAILED,
            agent="hermes_manager",
            task_id=task_id,
            data={"results": results},
        )
        await self.event_bus.publish(event)

        return {
            "task_id": task_id,
            "status": task.status.value,
            "results": results,
        }

    async def _execute_subtask(self, subtask: SubTask) -> Dict[str, Any]:
        """Execute a single subtask.

        Args:
            subtask: Subtask to execute.

        Returns:
            Dict[str, Any]: Execution result.
        """
        start_time = asyncio.get_event_loop().time()

        try:
            # In production, would route to actual agent
            await asyncio.sleep(0.1)  # Simulate execution

            subtask.status = TaskStatus.COMPLETED

            return {
                "subtask_id": subtask.id,
                "agent": subtask.assigned_agent,
                "status": "completed",
            }
        except Exception as e:
            logger.error(f"Subtask {subtask.id} failed: {e}")
            subtask.status = TaskStatus.FAILED
            subtask.error = str(e)
            return {
                "subtask_id": subtask.id,
                "agent": subtask.assigned_agent,
                "status": "failed",
                "error": str(e),
            }
        finally:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            await self._memory.log_execution(
                task_id=subtask.id,
                agent=subtask.assigned_agent or "hermes_manager",
                action="execute_subtask",
                result="completed" if subtask.status == TaskStatus.COMPLETED else "failed",
                duration_ms=duration_ms,
                error=subtask.error,
            )

    def _is_subtask_completed(self, task: Task, subtask_id: str) -> bool:
        """Check if a subtask is completed.

        Args:
            task: Parent task.
            subtask_id: Subtask ID to check.

        Returns:
            bool: True if subtask is completed.
        """
        for st in task.subtasks:
            if st.id == subtask_id:
                return st.status == TaskStatus.COMPLETED
        return False

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all pending tasks.

        Returns:
            List[Dict[str, Any]]: List of pending task dictionaries.
        """
        return [
            task.to_dict()
            for task in self._task_queue.values()
            if task.status == TaskStatus.PENDING
        ]