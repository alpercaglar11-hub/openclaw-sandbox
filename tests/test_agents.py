"""Tests for agent components.

Tests cover:
- HermesManager task decomposition and routing
- SandboxWorker Docker execution
- ReviewAgent security scanning
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hermes_manager import HermesManager, Task, TaskPriority, TaskStatus, SubTask
from agents.sandbox_worker import SandboxWorker, ExecutionResult, ExecutionStatus
from agents.review_agent import ReviewAgent, ReviewDecision, SecurityViolation, ReviewResult


class TestHermesManagerTaskDecomposition:
    """Test HermesManager task decomposition functionality."""

    @pytest.mark.asyncio
    async def test_decompose_task_creates_subtasks(self):
        """Test that decompose_task creates proper subtasks."""
        manager = HermesManager()
        manager._http_client = AsyncMock()

        # Mock the Ollama response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "response": json.dumps([
                {"description": "First subtask", "assigned_agent": "sandbox_worker", "dependencies": []},
                {"description": "Second subtask", "assigned_agent": "review_agent", "dependencies": ["subtask-1"]},
            ])
        })
        manager._http_client.post = AsyncMock(return_value=mock_response)

        task = await manager.decompose_task("Build a web server")

        assert isinstance(task, Task)
        assert task.description == "Build a web server"
        assert len(task.subtasks) == 2
        assert task.subtasks[0].description == "First subtask"
        assert task.subtasks[1].assigned_agent == "review_agent"

    @pytest.mark.asyncio
    async def test_decompose_task_fallback_on_llm_failure(self):
        """Test fallback to single subtask when LLM fails."""
        manager = HermesManager()
        manager._http_client = AsyncMock()
        manager._http_client.post = AsyncMock(return_value=None)

        task = await manager.decompose_task("Simple task")

        assert isinstance(task, Task)
        assert len(task.subtasks) == 1
        assert task.subtasks[0].assigned_agent == "sandbox_worker"

    @pytest.mark.asyncio
    async def test_decompose_task_fallback_on_json_error(self):
        """Test fallback when LLM returns invalid JSON."""
        manager = HermesManager()
        manager._http_client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": "not valid json {"})
        manager._http_client.post = AsyncMock(return_value=mock_response)

        task = await manager.decompose_task("Task with bad response")

        assert isinstance(task, Task)
        assert len(task.subtasks) == 1  # Fallback to single subtask


class TestHermesManagerRouting:
    """Test HermesManager task routing."""

    def test_route_subtask_explicit_assignment(self):
        """Test routing uses explicit assignment when provided."""
        manager = HermesManager()
        subtask = SubTask(description="Run tests", assigned_agent="review_agent")

        agent = manager._route_subtask(subtask)
        assert agent == "review_agent"

    def test_route_subtask_security_keyword(self):
        """Test routing to review_agent for security-related tasks."""
        manager = HermesManager()
        subtask = SubTask(description="Scan for vulnerabilities")

        agent = manager._route_subtask(subtask)
        assert agent == "review_agent"

    def test_route_subtask_monitoring_keyword(self):
        """Test routing to observer_agent for monitoring tasks."""
        manager = HermesManager()
        subtask = SubTask(description="Monitor system metrics")

        agent = manager._route_subtask(subtask)
        assert agent == "observer_agent"

    def test_route_subtask_default_to_sandbox_worker(self):
        """Test default routing to sandbox_worker."""
        manager = HermesManager()
        subtask = SubTask(description="Execute some code")

        agent = manager._route_subtask(subtask)
        assert agent == "sandbox_worker"

    def test_route_subtask_code_execution_keyword(self):
        """Test routing for code execution tasks."""
        manager = HermesManager()
        subtask = SubTask(description="Run Python script")

        agent = manager._route_subtask(subtask)
        assert agent == "sandbox_worker"


class TestHermesManagerSubmit:
    """Test HermesManager task submission."""

    @pytest.mark.asyncio
    async def test_submit_task_stores_in_queue(self):
        """Test submitted tasks are stored in queue."""
        manager = HermesManager()
        manager._memory = AsyncMock()
        manager._memory.create_task = AsyncMock()
        manager._memory.get_task = AsyncMock(return_value=None)
        manager._http_client = AsyncMock()

        # Mock decompose
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "response": json.dumps([{"description": "Test", "assigned_agent": "sandbox_worker", "dependencies": []}])
        })
        manager._http_client.post = AsyncMock(return_value=mock_response)

        manager._event_bus = AsyncMock()
        manager._event_bus.publish = AsyncMock()

        task = await manager.submit_task("Test task")

        assert task.id in manager._task_queue
        assert len(task.subtasks) > 0

    @pytest.mark.asyncio
    async def test_submit_task_with_priority(self):
        """Test task submission with priority setting."""
        manager = HermesManager()
        manager._memory = AsyncMock()
        manager._memory.create_task = AsyncMock()
        manager._memory.get_task = AsyncMock(return_value=None)
        manager._http_client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "response": json.dumps([{"description": "Test", "assigned_agent": "sandbox_worker", "dependencies": []}])
        })
        manager._http_client.post = AsyncMock(return_value=mock_response)

        manager._event_bus = AsyncMock()
        manager._event_bus.publish = AsyncMock()

        task = await manager.submit_task("High priority task", priority=TaskPriority.HIGH)

        assert task.priority == TaskPriority.HIGH


class TestHermesManagerStatus:
    """Test HermesManager task status tracking."""

    @pytest.mark.asyncio
    async def test_get_task_status_from_memory(self):
        """Test retrieving task status from memory layer."""
        manager = HermesManager()
        manager._memory = AsyncMock()
        manager._memory.get_task = AsyncMock(return_value={
            "id": "task-123",
            "status": "in_progress",
            "description": "Test task"
        })

        status = await manager.get_task_status("task-123")
        assert status["status"] == "in_progress"

    def test_get_pending_tasks(self):
        """Test retrieving all pending tasks."""
        manager = HermesManager()

        # Add some tasks to the queue
        task1 = Task(description="Task 1")
        task1.status = TaskStatus.PENDING

        task2 = Task(description="Task 2")
        task2.status = TaskStatus.COMPLETED

        manager._task_queue[task1.id] = task1
        manager._task_queue[task2.id] = task2

        pending = manager.get_pending_tasks()
        assert len(pending) == 1


class TestSandboxWorker:
    """Test SandboxWorker Docker execution."""

    @pytest.mark.asyncio
    async def test_execute_returns_result_structure(self):
        """Test execute returns proper ExecutionResult structure."""
        worker = SandboxWorker()
        worker.event_bus = AsyncMock()

        with patch("asyncio.create_subprocess_shell") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"hello", b""))
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            result = await worker.execute("print('hello')", language="python")

            assert isinstance(result, ExecutionResult)
            assert result.status == ExecutionStatus.COMPLETED
            assert result.stdout == "hello"
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_handles_timeout(self):
        """Test execution timeout handling."""
        worker = SandboxWorker()
        worker.event_bus = AsyncMock()

        with patch("asyncio.create_subprocess_shell") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_process.terminate = MagicMock()
            mock_process.wait = AsyncMock()
            mock_subprocess.return_value = mock_process

            result = await worker.execute("sleep(100)", language="python")

            assert result.status == ExecutionStatus.TIMEOUT
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_batch_parallel(self):
        """Test batch execution runs in parallel."""
        worker = SandboxWorker()
        worker.event_bus = AsyncMock()

        executions = [
            {"code": "print(1)", "language": "python", "task_id": "batch-1"},
            {"code": "print(2)", "language": "python", "task_id": "batch-2"},
        ]

        with patch("asyncio.create_subprocess_shell") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"output", b""))
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            results = await worker.execute_batch(executions)

            assert len(results) == 2
            assert all(isinstance(r, ExecutionResult) for r in results)

    @pytest.mark.asyncio
    async def test_cancel_execution(self):
        """Test execution cancellation."""
        worker = SandboxWorker()
        worker.event_bus = AsyncMock()

        # Create a mock task that can be cancelled
        async def slow_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(slow_task())
        execution_id = "exec-cancel-test"
        worker._active_executions[execution_id] = task

        result = await worker.cancel_execution(execution_id)
        assert result is True
        assert task.cancelled()

    def test_get_active_count(self):
        """Test active execution count tracking."""
        worker = SandboxWorker()

        async def running_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(running_task())
        worker._active_executions["exec-1"] = task

        count = worker.get_active_count()
        assert count == 1

        task.cancel()


class TestSandboxWorkerBuildCommand:
    """Test SandboxWorker docker command building."""

    def test_build_docker_command_python(self):
        """Test Docker command building for Python."""
        worker = SandboxWorker()

        cmd = worker._build_docker_command(
            code="print('hello')",
            language="python",
            environment=None,
            mounts=None,
        )

        assert "docker run" in cmd
        assert "--memory" in cmd
        assert "--cpus" in cmd
        assert "--network" in cmd
        assert "python:3.11-slim" in cmd

    def test_build_docker_command_with_environment(self):
        """Test Docker command includes environment variables."""
        worker = SandboxWorker()

        cmd = worker._build_docker_command(
            code="echo $MY_VAR",
            language="bash",
            environment={"MY_VAR": "test_value"},
            mounts=None,
        )

        assert "-e" in cmd
        assert "MY_VAR=test_value" in cmd

    def test_build_docker_command_with_mounts(self):
        """Test Docker command includes volume mounts."""
        worker = SandboxWorker()

        cmd = worker._build_docker_command(
            code="cat /data/input.txt",
            language="bash",
            environment=None,
            mounts={"/host/path": "/data:ro"},
        )

        assert "-v" in cmd
        assert "/host/path:/data:ro" in cmd


class TestReviewAgent:
    """Test ReviewAgent security scanning."""

    @pytest.mark.asyncio
    async def test_review_approves_safe_code(self):
        """Test review approves non-dangerous code."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        safe_code = """
def hello():
    print("Hello, World!")
    return 42
"""
        result = await agent.review(safe_code, "python", task_id="safe-1")

        assert isinstance(result, ReviewResult)
        assert result.decision == ReviewDecision.APPROVED
        assert len(result.violations) == 0

    @pytest.mark.asyncio
    async def test_review_detects_shell_injection(self):
        """Test review detects shell injection patterns."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        dangerous_code = "os.system('rm -rf /tmp/*')"

        result = await agent.review(dangerous_code, "python", task_id="dangerous-1")

        assert len(result.violations) > 0
        # Should detect system calls
        violation_rules = [v.rule for v in result.violations]
        assert any("shell" in r or "execution" in r for r in violation_rules)

    @pytest.mark.asyncio
    async def test_review_detects_eval_usage(self):
        """Test review detects dangerous eval usage."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        code_with_eval = "eval('print(1)')"

        result = await agent.review(code_with_eval, "python", task_id="eval-1")

        violation_rules = [v.rule for v in result.violations]
        assert any("code_execution" in r or "eval" in r for r in violation_rules)

    @pytest.mark.asyncio
    async def test_review_detects_path_traversal(self):
        """Test review detects path traversal attempts."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        code_with_traversal = "open('../etc/passwd')"

        result = await agent.review(code_with_traversal, "python", task_id="traversal-1")

        assert len(result.violations) > 0

    @pytest.mark.asyncio
    async def test_review_scores_code_correctly(self):
        """Test code scoring based on violations."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        # No violations should give perfect score
        clean_code = "x = 1 + 2"
        result = await agent.review(clean_code, "python")
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_review_rejects_critical_violations(self):
        """Test rejection of code with critical violations."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        # Code with critical shell injection
        critical_code = "import os; os.system(';rm -rf /')"

        result = await agent.review(critical_code, "python")
        assert result.decision == ReviewDecision.REJECTED

    @pytest.mark.asyncio
    async def test_review_detects_unapproved_language(self):
        """Test rejection of unapproved programming languages."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        code = "echo 'hello'"  # Shell is not in approved languages

        result = await agent.review(code, "powershell")

        # Should flag the language as not approved
        language_violations = [v for v in result.violations if "language" in v.rule]
        assert len(language_violations) > 0


class TestReviewAgentQualityChecks:
    """Test ReviewAgent code quality checks."""

    @pytest.mark.asyncio
    async def test_review_detects_long_lines(self):
        """Test detection of lines exceeding length limit."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        # Create code with a very long line
        long_line = "x = " + "a" * 150
        code = f"""
def func():
    {long_line}
"""
        result = await agent.review(code, "python")

        assert len(result.warnings) > 0
        assert any("120 characters" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_review_detects_todo_fixes(self):
        """Test detection of TODO/FIXME comments."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        code = """
def broken():
    # TODO: fix this
    pass
"""
        result = await agent.review(code, "python")

        assert any("TODO" in w or "FIXME" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_review_detects_hardcoded_credentials(self):
        """Test detection of potential hardcoded credentials."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        code = 'password = "super_secret_password_123"'

        result = await agent.review(code, "python")

        assert any("credential" in w.lower() for w in result.warnings)


class TestReviewAgentReasoning:
    """Test ReviewAgent decision reasoning generation."""

    @pytest.mark.asyncio
    async def test_review_generates_reasoning(self):
        """Test that reasoning is generated for review decisions."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        result = await agent.review("print('hello')", "python")

        assert len(result.reasoning) > 0

    @pytest.mark.asyncio
    async def test_review_includes_metadata(self):
        """Test that review metadata is populated."""
        agent = ReviewAgent()
        agent.event_bus = AsyncMock()

        result = await agent.review("x = 1", "python", task_id="meta-test")

        assert "task_id" in result.metadata
        assert "language" in result.metadata
        assert "code_length" in result.metadata
        assert "review_duration_ms" in result.metadata