"""SQLite persistent layer for OpenClaw.

Provides async SQLite storage for tasks, agent decisions, execution logs,
and task queue using aiosqlite.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import aiosqlite

logger = logging.getLogger(__name__)

DATABASE_PATH = "./openclaw.db"


class Memory:
    """Async SQLite memory layer for agent orchestration.

    Manages persistent storage for tasks, agent decisions, execution logs,
    and task queue using aiosqlite for async operations.
    """

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        """Initialize memory with database path.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        logger.info(f"Memory initialized with database: {db_path}")

    async def initialize(self) -> None:
        """Initialize database schema and connection."""
        async with self._lock:
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
            await self._create_tables()
            logger.info("Database schema initialized")

    async def _create_tables(self) -> None:
        """Create all required tables if they don't exist."""
        async with self._connection.execute("PRAGMA journal_mode=WAL") as cursor:
            await cursor.fetchone()

        # Tasks table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata JSON
            )
        """)

        # Agent decisions table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                action TEXT NOT NULL,
                reasoning TEXT,
                result TEXT,
                approved BOOLEAN,
                created_at TEXT NOT NULL,
                metadata JSON,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)

        # Execution logs table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT,
                duration_ms INTEGER,
                error TEXT,
                created_at TEXT NOT NULL,
                metadata JSON,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)

        # Task queue table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent TEXT,
                status TEXT NOT NULL,
                position INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                metadata JSON,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)

        await self._connection.commit()

    async def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Update task fields.

        Args:
            task_id: Task identifier.
            updates: Fields to update (status, metadata, etc.)

        Returns:
            bool: True if update was successful.
        """
        status = updates.get("status")
        if status:
            return await self.update_task_status(task_id, status, updates)
        return False

    async def get_task_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all tasks.

        Returns:
            Dict[str, Any]: Summary with total_tasks, success_rate, avg_duration_ms.
        """
        async with self.get_connection() as conn:
            # Count by status
            async with conn.execute(
                "SELECT status, COUNT(*) as count FROM tasks GROUP BY status"
            ) as cursor:
                rows = await cursor.fetchall()
                status_counts = {row["status"]: row["count"] for row in rows}

            total = sum(status_counts.values())
            completed = status_counts.get("completed", 0)
            success_rate = completed / total if total > 0 else 0.0

            # Avg duration from execution logs
            async with conn.execute(
                "SELECT AVG(duration_ms) as avg FROM execution_logs WHERE duration_ms IS NOT NULL"
            ) as cursor:
                row = await cursor.fetchone()
                avg_duration = row["avg"] if row and row["avg"] else 0

            return {
                "total_tasks": total,
                "status_counts": status_counts,
                "success_rate": success_rate,
                "avg_duration_ms": float(avg_duration),
            }

    async def close(self) -> None:
        """Close database connection."""
        async with self._lock:
            if self._connection:
                await self._connection.close()
                self._connection = None
                logger.info("Database connection closed")

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection from the pool.

        Yields:
            aiosqlite.Connection: Database connection.
        """
        if self._connection is None:
            await self.initialize()
        yield self._connection

    # Task operations
    async def create_task(
        self,
        task_id: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
        priority: int = 0,
    ) -> str:
        """Create a new task.

        Args:
            task_id: Unique task identifier.
            description: Task description.
            metadata: Optional task metadata.
            priority: Task priority (higher = more important).

        Returns:
            str: Created task ID.
        """
        async with self.get_connection() as conn:
            now = datetime.utcnow().isoformat()
            await conn.execute(
                """
                INSERT INTO tasks (id, task_id, description, status, priority, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    task_id,
                    description,
                    "pending",
                    priority,
                    now,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await conn.commit()
            logger.debug(f"Created task: {task_id}")
            return task_id

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task by ID.

        Args:
            task_id: Task identifier.

        Returns:
            Optional[Dict[str, Any]]: Task data or None if not found.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return None

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update task status.

        Args:
            task_id: Task identifier.
            status: New status.
            metadata: Optional metadata to merge.

        Returns:
            bool: True if update was successful.
        """
        async with self.get_connection() as conn:
            now = datetime.utcnow().isoformat()
            if metadata:
                existing = await self.get_task(task_id)
                existing_meta = json.loads(existing["metadata"] or "{}") if existing else {}
                existing_meta.update(metadata)
                metadata = existing_meta

            await conn.execute(
                """
                UPDATE tasks SET status = ?, updated_at = ?, metadata = ?
                WHERE task_id = ?
                """,
                (status, now, json.dumps(metadata) if metadata else None, task_id),
            )
            await conn.commit()
            logger.debug(f"Updated task {task_id} status to {status}")
            return True

    async def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get all tasks with a specific status.

        Args:
            status: Task status to filter by.

        Returns:
            List[Dict[str, Any]]: List of matching tasks.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at ASC",
                (status,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # Agent decision operations
    async def log_agent_decision(
        self,
        task_id: str,
        agent: str,
        action: str,
        reasoning: Optional[str] = None,
        result: Optional[str] = None,
        approved: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Log an agent decision.

        Args:
            task_id: Associated task ID.
            agent: Agent name.
            action: Action taken.
            reasoning: Reasoning for the decision.
            result: Result of the action.
            approved: Whether the action was approved.
            metadata: Additional metadata.

        Returns:
            int: Decision ID.
        """
        async with self.get_connection() as conn:
            now = datetime.utcnow().isoformat()
            cursor = await conn.execute(
                """
                INSERT INTO agent_decisions
                (task_id, agent, action, reasoning, result, approved, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    agent,
                    action,
                    reasoning,
                    result,
                    approved,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await conn.commit()
            decision_id = cursor.lastrowid
            logger.debug(f"Logged agent decision: {agent} - {action}")
            return decision_id

    async def get_agent_decisions(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all agent decisions for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List[Dict[str, Any]]: List of decisions.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM agent_decisions WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # Execution log operations
    async def log_execution(
        self,
        task_id: str,
        agent: str,
        action: str,
        result: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Log an execution event.

        Args:
            task_id: Associated task ID.
            agent: Agent name.
            action: Action executed.
            result: Result of execution.
            duration_ms: Duration in milliseconds.
            error: Error message if failed.
            metadata: Additional metadata.

        Returns:
            int: Log entry ID.
        """
        async with self.get_connection() as conn:
            now = datetime.utcnow().isoformat()
            cursor = await conn.execute(
                """
                INSERT INTO execution_logs
                (task_id, agent, action, result, duration_ms, error, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    agent,
                    action,
                    result,
                    duration_ms,
                    error,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await conn.commit()
            log_id = cursor.lastrowid
            logger.debug(f"Logged execution: {agent} - {action} ({duration_ms}ms)")
            return log_id

    async def get_execution_logs(
        self,
        task_id: Optional[str] = None,
        agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get execution logs with optional filtering.

        Args:
            task_id: Optional task ID filter.
            agent: Optional agent filter.
            limit: Maximum number of results.

        Returns:
            List[Dict[str, Any]]: List of execution logs.
        """
        async with self.get_connection() as conn:
            query = "SELECT * FROM execution_logs WHERE 1=1"
            params = []

            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            if agent:
                query += " AND agent = ?"
                params.append(agent)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # Task queue operations
    async def enqueue_task(
        self,
        task_id: str,
        agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a task to the queue.

        Args:
            task_id: Task identifier.
            agent: Optional assigned agent.
            metadata: Additional metadata.

        Returns:
            str: Queue entry ID.
        """
        async with self.get_connection() as conn:
            queue_id = str(uuid4())
            now = datetime.utcnow().isoformat()

            # Get current max position
            async with conn.execute(
                "SELECT MAX(position) FROM task_queue WHERE status = 'queued'"
            ) as cursor:
                row = await cursor.fetchone()
                max_pos = row[0] if row and row[0] is not None else -1

            await conn.execute(
                """
                INSERT INTO task_queue (id, task_id, agent, status, position, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    queue_id,
                    task_id,
                    agent,
                    "queued",
                    max_pos + 1,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await conn.commit()
            logger.debug(f"Enqueued task: {task_id}")
            return queue_id

    async def dequeue_task(self, agent: str) -> Optional[Dict[str, Any]]:
        """Dequeue the next task for an agent.

        Args:
            agent: Agent name to assign task to.

        Returns:
            Optional[Dict[str, Any]]: Dequeued task or None if queue empty.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                """
                SELECT * FROM task_queue
                WHERE status = 'queued'
                ORDER BY position ASC
                LIMIT 1
                """
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None

            queue_entry = dict(row)
            now = datetime.utcnow().isoformat()

            await conn.execute(
                """
                UPDATE task_queue
                SET status = 'in_progress', agent = ?, started_at = ?
                WHERE id = ?
                """,
                (agent, now, queue_entry["id"]),
            )
            await conn.commit()
            logger.debug(f"Dequeued task for {agent}: {queue_entry['task_id']}")
            return queue_entry

    async def complete_task_in_queue(
        self,
        queue_id: str,
        status: str = "completed",
    ) -> bool:
        """Mark a queued task as completed.

        Args:
            queue_id: Queue entry ID.
            status: Completion status (completed, failed, cancelled).

        Returns:
            bool: True if update was successful.
        """
        async with self.get_connection() as conn:
            now = datetime.utcnow().isoformat()
            await conn.execute(
                """
                UPDATE task_queue
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, now, queue_id),
            )
            await conn.commit()
            logger.debug(f"Completed queue entry: {queue_id} with status {status}")
            return True

    async def get_queue_status(self) -> Dict[str, int]:
        """Get counts of tasks by queue status.

        Returns:
            Dict[str, int]: Status counts.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                """
                SELECT status, COUNT(*) as count FROM task_queue GROUP BY status
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return {row["status"]: row["count"] for row in rows}

    # Metrics operations
    async def compute_task_metrics(
        self,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute execution metrics.

        Args:
            task_id: Optional task ID to filter by.

        Returns:
            Dict[str, Any]: Computed metrics.
        """
        async with self.get_connection() as conn:
            query = """
                SELECT
                    COUNT(*) as total_executions,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as error_count
                FROM execution_logs
            """
            params = []

            if task_id:
                query += " WHERE task_id = ?"
                params.append(task_id)

            async with conn.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}

    async def get_agent_stats(self, agent: str) -> Dict[str, Any]:
        """Get statistics for a specific agent.

        Args:
            agent: Agent name.

        Returns:
            Dict[str, Any]: Agent statistics.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                """
                SELECT
                    COUNT(*) as total_decisions,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved_count,
                    SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as rejected_count
                FROM agent_decisions
                WHERE agent = ?
                """,
                (agent,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}


# Global memory instance
_memory: Optional[Memory] = None


async def get_memory() -> Memory:
    """Get the global memory instance.

    Returns:
        Memory: The global memory instance.
    """
    global _memory
    if _memory is None:
        _memory = Memory()
        await _memory.initialize()
    return _memory


async def close_memory() -> None:
    """Close the global memory instance."""
    global _memory
    if _memory:
        await _memory.close()
        _memory = None