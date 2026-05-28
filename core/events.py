"""Event bus for agent communication.

Provides a publish-subscribe event system for inter-agent communication.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Standard event types in the agent system."""

    TASK_SUBMITTED = "task.submitted"
    TASK_DECOMPOSED = "task.decomposed"
    TASK_ROUTED = "task.routed"
    TASK_EXECUTING = "task.executing"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_REVIEWED = "task.reviewed"
    SANDBOX_STARTED = "sandbox.started"
    SANDBOX_STOPPED = "sandbox.stopped"
    AGENT_ERROR = "agent.error"
    METRICS_UPDATED = "metrics.updated"
    ALERT_TRIGGERED = "alert.triggered"


@dataclass
class Event:
    """An event in the system."""

    id: str = field(default_factory=lambda: str(uuid4()))
    event_type: EventType = EventType.TASK_SUBMITTED
    agent: Optional[str] = None
    task_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "agent": self.agent,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
        }


class EventBus:
    """Publish-subscribe event bus for agent communication."""

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}
        self._lock = threading.Lock()
        logger.info("EventBus initialized")

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
        agent_name: Optional[str] = None,
    ) -> str:
        """Subscribe to an event type.

        Args:
            event_type: The type of event to subscribe to.
            callback: The callback function to invoke when event occurs.
            agent_name: Optional name of the subscribing agent.

        Returns:
            str: Subscription ID for later unsubscription.
        """
        subscription_id = str(uuid4())

        async def wrapper(event: Event) -> None:
            try:
                callback(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event_type.value}: {e}",
                    exc_info=True,
                )

        self._lock.acquire()
        try:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(wrapper)
        finally:
            self._lock.release()

        logger.debug(
            f"Subscribed to {event_type.value} with ID {subscription_id}"
        )
        return subscription_id

    def unsubscribe(self, event_type: EventType, subscription_id: str) -> bool:
        """Unsubscribe from an event type."""
        self._lock.acquire()
        try:
            if event_type in self._subscribers and self._subscribers[event_type]:
                self._subscribers[event_type].pop()
                return True
        finally:
            self._lock.release()
        return False

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers (async)."""
        logger.debug(f"Publishing event: {event.event_type.value} - {event.id}")

        self._lock.acquire()
        try:
            handlers = self._subscribers.get(event.event_type, []).copy()
        finally:
            self._lock.release()

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event.event_type.value}: {e}",
                    exc_info=True,
                )

    def publish_sync(self, event: Event) -> None:
        """Synchronously publish an event (for non-async contexts)."""
        logger.debug(f"Sync publishing event: {event.event_type.value}")

        self._lock.acquire()
        try:
            handlers = self._subscribers.get(event.event_type, []).copy()
        finally:
            self._lock.release()

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event.event_type.value}: {e}",
                    exc_info=True,
                )

    def get_subscriber_count(self, event_type: EventType) -> int:
        """Get the number of subscribers for an event type."""
        return len(self._subscribers.get(event_type, []))


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
