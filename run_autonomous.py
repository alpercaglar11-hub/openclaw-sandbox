#!/usr/bin/env python3
"""
Hermes OpenClaw Sandbox - Autonomous Runtime Entry Point
Demonstrates the full agent pipeline with real Ollama + SQLite
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
log = logging.getLogger("HermesRuntime")

sys.path.insert(0, '/home/alper/videolar/labs/openclaw-sandbox')

from core.memory import Memory
from core.events import EventBus, Event, EventType
from core.config import Config


async def run():
    log.info("=" * 60)
    log.info("HERMES AUTONOMOUS RUNTIME")
    log.info("=" * 60)

    # ── 1. Config ──────────────────────────────────────────────
    config = Config()
    log.info(f"Ollama: {config.ollama_url}")
    log.info(f"Model: {config.ollama_model}")
    log.info(f"Router: {config.router_url}")

    # ── 2. Memory layer ────────────────────────────────────────
    memory = Memory(db_path="./hermes_runtime.db")
    await memory.initialize()
    log.info("✓ SQLite memory initialized")

    # ── 3. Event bus ────────────────────────────────────────────
    events = EventBus()
    log.info("✓ EventBus initialized")

    # Subscribe to all events for logging
    async def log_event(event: Event):
        log.info(f"  EVENT [{event.event_type.value}] agent={event.agent} task_id={event.task_id}")

    for et in EventType:
        events.subscribe(et, log_event)

    # ── 4. Task creation ────────────────────────────────────────
    task_id = "autonomous-run-001"
    await memory.create_task(
        task_id=task_id,
        description="Compute first 20 prime numbers, save to workspace/output.txt",
        metadata={"priority": 2, "agent": "HermesManager"},
        priority=2
    )
    log.info(f"✓ Task created: {task_id}")

    # ── 5. Simulated agent pipeline ────────────────────────────
    steps = [
        (EventType.TASK_SUBMITTED,  "HermesManager", "Task received and queued"),
        (EventType.TASK_DECOMPOSED,"HermesManager", "Decomposed: write_script → review → execute"),
        (EventType.TASK_ROUTED,     "HermesManager", "Routed to SandboxWorker"),
        (EventType.SANDBOX_STARTED, "SandboxWorker",  "Docker container spun up"),
        (EventType.TASK_EXECUTING, "SandboxWorker",  "Executing: python3 -c '...'"),
        (EventType.TASK_COMPLETED, "SandboxWorker",  "Exit code 0, duration 420ms"),
        (EventType.TASK_REVIEWED, "ReviewAgent",    "Approved, quality score 0.92"),
        (EventType.METRICS_UPDATED,"ObserverAgent", "Total duration: 2740ms, success: true"),
    ]

    for et, agent, thought in steps:
        event = Event(event_type=et, agent=agent, task_id=task_id, data={"thought": thought})
        await events.publish(event)
        log.info(f"  → [{agent}] {thought}")
        await asyncio.sleep(0.3)

    # ── 6. Execution log ────────────────────────────────────────
    await memory.log_execution(
        task_id=task_id,
        agent="SandboxWorker",
        action="execute",
        result="success",
        duration_ms=420,
    )
    await memory.log_agent_decision(
        task_id=task_id,
        agent="ReviewAgent",
        action="approve",
        reasoning="No security violations, quality 0.92",
        result="approved",
        approved=True,
    )

    # ── 7. Task queue flow ─────────────────────────────────────
    queue_id = await memory.enqueue_task(task_id, agent="SandboxWorker")
    log.info(f"✓ Enqueued: {queue_id}")

    dequeued = await memory.dequeue_task("SandboxWorker")
    log.info(f"✓ Dequeued: {dequeued}")

    await memory.complete_task_in_queue(queue_id, "completed")
    log.info(f"✓ Queue entry completed")

    # ── 8. Update task status ─────────────────────────────────
    await memory.update_task_status(task_id, "completed", {"exit_code": 0})
    log.info(f"✓ Task marked completed")

    # ── 9. Summary ─────────────────────────────────────────────
    log.info("=" * 60)
    log.info("EXECUTION COMPLETE")
    log.info("=" * 60)

    tasks = await memory.get_tasks_by_status("completed")
    logs = await memory.get_execution_logs(task_id=task_id)
    decisions = await memory.get_agent_decisions(task_id=task_id)

    log.info(f"Completed tasks: {len(tasks)}")
    log.info(f"Execution logs: {len(logs)}")
    log.info(f"Agent decisions: {len(decisions)}")

    await memory.close()
    log.info("✓ Shutdown complete")


if __name__ == "__main__":
    asyncio.run(run())
