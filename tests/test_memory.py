"""Tests for SQLite memory layer.

Tests cover:
- Memory initialization and schema creation
- Task CRUD operations
- Agent decision logging
- Execution log management
- Task queue operations
"""

import json
import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.memory import Memory


class TestMemoryInitialization:
    """Test Memory layer initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_connection(self, clean_memory: Memory):
        """Test that initialize creates database connection."""
        assert clean_memory._connection is not None

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, clean_memory: Memory):
        """Test that schema tables are created."""
        async with clean_memory._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
            table_names = [row[0] for row in rows]

        required_tables = ["tasks", "agent_decisions", "execution_logs", "task_queue"]
        for table in required_tables:
            assert table in table_names, f"Table {table} not found"

    @pytest.mark.asyncio
    async def test_initialize_sets_wal_mode(self, clean_memory: Memory):
        """Test that WAL journal mode is enabled."""
        async with clean_memory._connection.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row[0].upper() == "WAL"


class TestTaskOperations:
    """Test task CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_task_returns_task_id(self, clean_memory: Memory):
        """Test task creation returns correct ID."""
        task_id = await clean_memory.create_task(
            task_id="test-task-1",
            description="Test task creation",
            metadata={"source": "test"},
            priority=1,
        )

        assert task_id == "test-task-1"

    @pytest.mark.asyncio
    async def test_create_and_get_task(self, clean_memory: Memory):
        """Test creating and retrieving a task."""
        task_id = await clean_memory.create_task(
            task_id="test-task-2",
            description="Test task",
            metadata={"key": "value"},
        )

        task = await clean_memory.get_task(task_id)
        assert task is not None
        assert task["task_id"] == "test-task-2"
        assert task["description"] == "Test task"
        assert task["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, clean_memory: Memory):
        """Test getting a task that doesn't exist."""
        task = await clean_memory.get_task("nonexistent-id")
        assert task is None

    @pytest.mark.asyncio
    async def test_update_task_status(self, clean_memory: Memory):
        """Test updating task status."""
        task_id = await clean_memory.create_task(
            task_id="test-task-3",
            description="Task to update",
        )

        result = await clean_memory.update_task_status(task_id, "completed")
        assert result is True

        task = await clean_memory.get_task(task_id)
        assert task["status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_task_status_with_metadata(self, clean_memory: Memory):
        """Test updating task status merges metadata."""
        task_id = await clean_memory.create_task(
            task_id="test-task-4",
            description="Task with metadata",
            metadata={"original": "value"},
        )

        await clean_memory.update_task_status(
            task_id,
            "in_progress",
            metadata={"started_at": "2024-01-01"},
        )

        task = await clean_memory.get_task(task_id)
        metadata = json.loads(task["metadata"] or "{}")
        assert metadata["original"] == "value"
        assert metadata["started_at"] == "2024-01-01"

    @pytest.mark.asyncio
    async def test_get_tasks_by_status(self, clean_memory: Memory):
        """Test filtering tasks by status."""
        # Create tasks with different statuses
        await clean_memory.create_task(task_id="task-pending-1", description="Pending 1")
        await clean_memory.create_task(task_id="task-pending-2", description="Pending 2")

        await clean_memory.update_task_status("task-pending-1", "in_progress")
        await clean_memory.update_task_status("task-pending-2", "completed")

        pending_tasks = await clean_memory.get_tasks_by_status("pending")
        assert len(pending_tasks) == 0  # All updated

        in_progress = await clean_memory.get_tasks_by_status("in_progress")
        assert len(in_progress) == 1

        completed = await clean_memory.get_tasks_by_status("completed")
        assert len(completed) == 1


class TestAgentDecisionOperations:
    """Test agent decision logging."""

    @pytest.mark.asyncio
    async def test_log_agent_decision(self, clean_memory: Memory):
        """Test logging an agent decision."""
        await clean_memory.create_task(task_id="decision-task-1", description="Test")

        decision_id = await clean_memory.log_agent_decision(
            task_id="decision-task-1",
            agent="review_agent",
            action="APPROVED",
            reasoning="Code passed all checks",
            result="execution_approved",
            approved=True,
        )

        assert decision_id > 0

    @pytest.mark.asyncio
    async def test_get_agent_decisions(self, clean_memory: Memory):
        """Test retrieving agent decisions for a task."""
        task_id = "decision-task-2"
        await clean_memory.create_task(task_id=task_id, description="Test")

        await clean_memory.log_agent_decision(
            task_id=task_id,
            agent="review_agent",
            action="APPROVED",
            reasoning="First review",
        )

        await clean_memory.log_agent_decision(
            task_id=task_id,
            agent="hermes_manager",
            action="ROUTED",
            reasoning="Sent to worker",
        )

        decisions = await clean_memory.get_agent_decisions(task_id)
        assert len(decisions) == 2
        assert decisions[0]["agent"] == "review_agent"
        assert decisions[1]["agent"] == "hermes_manager"

    @pytest.mark.asyncio
    async def test_log_decision_with_metadata(self, clean_memory: Memory):
        """Test logging decision with additional metadata."""
        task_id = "decision-task-3"
        await clean_memory.create_task(task_id=task_id, description="Test")

        decision_id = await clean_memory.log_agent_decision(
            task_id=task_id,
            agent="sandbox_worker",
            action="EXECUTED",
            metadata={"duration_ms": 150, "exit_code": 0},
        )

        decisions = await clean_memory.get_agent_decisions(task_id)
        metadata = json.loads(decisions[0]["metadata"] or "{}")
        assert metadata["duration_ms"] == 150


class TestExecutionLogOperations:
    """Test execution log operations."""

    @pytest.mark.asyncio
    async def test_log_execution(self, clean_memory: Memory):
        """Test logging execution events."""
        await clean_memory.create_task(task_id="exec-task-1", description="Test")

        log_id = await clean_memory.log_execution(
            task_id="exec-task-1",
            agent="sandbox_worker",
            action="execute_code",
            result="success",
            duration_ms=200,
        )

        assert log_id > 0

    @pytest.mark.asyncio
    async def test_log_execution_with_error(self, clean_memory: Memory):
        """Test logging failed execution."""
        await clean_memory.create_task(task_id="exec-task-2", description="Test")

        log_id = await clean_memory.log_execution(
            task_id="exec-task-2",
            agent="sandbox_worker",
            action="execute_code",
            error="Syntax error in code",
        )

        logs = await clean_memory.get_execution_logs(task_id="exec-task-2")
        assert logs[0]["error"] == "Syntax error in code"

    @pytest.mark.asyncio
    async def test_get_execution_logs_filtered_by_agent(self, clean_memory: Memory):
        """Test filtering execution logs by agent."""
        task_id = "exec-task-3"
        await clean_memory.create_task(task_id=task_id, description="Test")

        await clean_memory.log_execution(
            task_id=task_id,
            agent="sandbox_worker",
            action="execute",
        )

        await clean_memory.log_execution(
            task_id=task_id,
            agent="review_agent",
            action="scan",
        )

        worker_logs = await clean_memory.get_execution_logs(agent="sandbox_worker")
        assert all(log["agent"] == "sandbox_worker" for log in worker_logs)

    @pytest.mark.asyncio
    async def test_get_execution_logs_with_limit(self, clean_memory: Memory):
        """Test execution log limit parameter."""
        task_id = "exec-task-4"
        await clean_memory.create_task(task_id=task_id, description="Test")

        # Create multiple logs
        for i in range(5):
            await clean_memory.log_execution(
                task_id=task_id,
                agent="sandbox_worker",
                action=f"action_{i}",
            )

        logs = await clean_memory.get_execution_logs(task_id=task_id, limit=3)
        assert len(logs) == 3


class TestTaskQueueOperations:
    """Test task queue operations."""

    @pytest.mark.asyncio
    async def test_enqueue_task(self, clean_memory: Memory):
        """Test adding task to queue."""
        await clean_memory.create_task(task_id="queue-task-1", description="Test")

        queue_id = await clean_memory.enqueue_task(
            task_id="queue-task-1",
            agent="sandbox_worker",
            metadata={"priority": "high"},
        )

        assert queue_id is not None
        assert len(queue_id) > 0

    @pytest.mark.asyncio
    async def test_dequeue_task(self, clean_memory: Memory):
        """Test dequeuing next task."""
        # Create and enqueue multiple tasks
        for i in range(3):
            await clean_memory.create_task(task_id=f"queue-task-{i}", description=f"Task {i}")
            await clean_memory.enqueue_task(task_id=f"queue-task-{i}")

        # Dequeue should return first-in order
        dequeued = await clean_memory.dequeue_task(agent="sandbox_worker")

        assert dequeued is not None
        assert dequeued["task_id"] == "queue-task-0"
        assert dequeued["status"] == "in_progress"
        assert dequeued["agent"] == "sandbox_worker"

    @pytest.mark.asyncio
    async def test_dequeue_empty_queue(self, clean_memory: Memory):
        """Test dequeuing from empty queue."""
        result = await clean_memory.dequeue_task(agent="observer_agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_task_in_queue(self, clean_memory: Memory):
        """Test marking queued task as completed."""
        task_id = "queue-task-complete"
        await clean_memory.create_task(task_id=task_id, description="Test")
        queue_id = await clean_memory.enqueue_task(task_id=task_id)

        # Dequeue then complete
        await clean_memory.dequeue_task(agent="sandbox_worker")
        result = await clean_memory.complete_task_in_queue(queue_id, "completed")

        assert result is True

    @pytest.mark.asyncio
    async def test_complete_task_with_failed_status(self, clean_memory: Memory):
        """Test completing task with failed status."""
        task_id = "queue-task-failed"
        await clean_memory.create_task(task_id=task_id, description="Test")
        queue_id = await clean_memory.enqueue_task(task_id=task_id)

        await clean_memory.dequeue_task(agent="sandbox_worker")
        await clean_memory.complete_task_in_queue(queue_id, "failed")

        # Verify the task was marked as failed
        async with clean_memory._connection.execute(
            "SELECT status FROM task_queue WHERE id = ?", (queue_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == "failed"


class TestMemoryConcurrency:
    """Test memory layer concurrency handling."""

    @pytest.mark.asyncio
    async def test_concurrent_task_creation(self, clean_memory: Memory):
        """Test concurrent task creation is thread-safe."""
        import asyncio

        async def create_task(idx: int):
            return await clean_memory.create_task(
                task_id=f"concurrent-task-{idx}",
                description=f"Concurrent task {idx}",
            )

        # Create 10 tasks concurrently
        results = await asyncio.gather(*[create_task(i) for i in range(10)])

        assert len(results) == 10
        assert all(r.startswith("concurrent-task-") for r in results)

    @pytest.mark.asyncio
    async def test_connection_lock_prevents_conflicts(self, clean_memory: Memory):
        """Test that connection lock prevents concurrent access issues."""
        import asyncio

        async def create_and_update(idx: int):
            task_id = f"lock-test-{idx}"
            await clean_memory.create_task(task_id=task_id, description=f"Task {idx}")
            await clean_memory.update_task_status(task_id, "completed")
            return await clean_memory.get_task(task_id)

        results = await asyncio.gather(*[create_and_update(i) for i in range(5)])

        # All tasks should complete successfully
        assert len(results) == 5
        for task in results:
            assert task["status"] == "completed"


class TestMemoryClose:
    """Test memory layer cleanup."""

    @pytest.mark.asyncio
    async def test_close_terminates_connection(self, clean_memory: Memory):
        """Test close properly terminates database connection."""
        await clean_memory.close()
        assert clean_memory._connection is None

    @pytest.mark.asyncio
    async def test_close_can_be_called_multiple_times(self, clean_memory: Memory):
        """Test multiple close calls don't raise errors."""
        await clean_memory.close()
        await clean_memory.close()  # Should not raise