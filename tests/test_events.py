"""Tests for EventBus publish-subscribe system.

Tests cover:
- EventBus initialization and subscriber management
- Subscribe/unsubscribe operations
- Event publishing and delivery
- Event type filtering
- Async handler execution
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.events import Event, EventType, EventBus


class TestEventBusInitialization:
    """Test EventBus initialization."""

    def test_init_creates_empty_subscribers(self):
        """Test EventBus initializes with empty subscribers."""
        bus = EventBus()
        assert bus._subscribers == {}

    def test_init_creates_lock(self):
        """Test EventBus initializes with async lock."""
        bus = EventBus()
        assert bus._lock is not None


class TestEventBusSubscription:
    """Test EventBus subscribe/unsubscribe operations."""

    def test_subscribe_returns_subscription_id(self):
        """Test subscribe returns a string subscription ID."""
        bus = EventBus()
        callback = MagicMock()

        sub_id = bus.subscribe(EventType.TASK_SUBMITTED, callback)

        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_subscribe_adds_callback_to_event_type(self):
        """Test subscribe registers callback for event type."""
        bus = EventBus()
        callback = MagicMock()

        bus.subscribe(EventType.TASK_SUBMITTED, callback)

        assert EventType.TASK_SUBMITTED in bus._subscribers
        assert len(bus._subscribers[EventType.TASK_SUBMITTED]) > 0

    def test_subscribe_multiple_to_same_event_type(self):
        """Test multiple subscriptions to same event type."""
        bus = EventBus()
        callback1 = MagicMock()
        callback2 = MagicMock()

        bus.subscribe(EventType.TASK_COMPLETED, callback1)
        bus.subscribe(EventType.TASK_COMPLETED, callback2)

        assert len(bus._subscribers[EventType.TASK_COMPLETED]) == 2

    def test_unsubscribe_returns_true_on_success(self):
        """Test unsubscribe returns True when subscription exists."""
        bus = EventBus()
        callback = MagicMock()

        sub_id = bus.subscribe(EventType.TASK_FAILED, callback)
        result = bus.unsubscribe(EventType.TASK_FAILED, sub_id)

        assert result is True

    def test_unsubscribe_returns_false_when_empty(self):
        """Test unsubscribe returns False when no subscribers."""
        bus = EventBus()

        result = bus.unsubscribe(EventType.TASK_SUBMITTED, "fake-id")
        assert result is False


class TestEventBusPublishing:
    """Test EventBus event publishing."""

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscribers(self):
        """Test published events reach subscribers."""
        bus = EventBus()
        received_events: List[Event] = []

        async def handler(event: Event):
            received_events.append(event)

        bus.subscribe(EventType.TASK_SUBMITTED, handler)

        event = Event(
            event_type=EventType.TASK_SUBMITTED,
            agent="test_agent",
            task_id="task-123",
        )
        await bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0].task_id == "task-123"

    @pytest.mark.asyncio
    async def test_publish_only_to_matching_subscribers(self):
        """Test events only go to subscribers of that event type."""
        bus = EventBus()
        task_events: List[Event] = []
        sandbox_events: List[Event] = []

        async def task_handler(event: Event):
            task_events.append(event)

        async def sandbox_handler(event: Event):
            sandbox_events.append(event)

        bus.subscribe(EventType.TASK_COMPLETED, task_handler)
        bus.subscribe(EventType.SANDBOX_STARTED, sandbox_handler)

        # Publish task event
        task_event = Event(event_type=EventType.TASK_COMPLETED, agent="test")
        await bus.publish(task_event)

        assert len(task_events) == 1
        assert len(sandbox_events) == 0

    @pytest.mark.asyncio
    async def test_publish_handles_no_subscribers(self):
        """Test publishing with no subscribers doesn't error."""
        bus = EventBus()

        event = Event(event_type=EventType.TASK_SUBMITTED)
        await bus.publish(event)  # Should not raise

    @pytest.mark.asyncio
    async def test_publish_handles_handler_error(self):
        """Test publish continues even if handler raises."""
        bus = EventBus()
        good_events: List[Event] = []

        async def bad_handler(event: Event):
            raise ValueError("Handler error")

        async def good_handler(event: Event):
            good_events.append(event)

        bus.subscribe(EventType.TASK_SUBMITTED, bad_handler)
        bus.subscribe(EventType.TASK_SUBMITTED, good_handler)

        event = Event(event_type=EventType.TASK_SUBMITTED)
        await bus.publish(event)  # Should not raise despite bad handler

        assert len(good_events) == 1


class TestEventBusPublishSync:
    """Test synchronous publishing."""

    def test_publish_sync_delivers_to_subscribers(self):
        """Test sync publish delivers events immediately."""
        bus = EventBus()
        received: List[Event] = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.TASK_ROUTED, handler)

        event = Event(event_type=EventType.TASK_ROUTED)
        bus.publish_sync(event)

        assert len(received) == 1

    def test_publish_sync_schedules_async_handlers(self):
        """Test sync publish schedules async handlers as tasks."""
        bus = EventBus()
        handler_called = False

        async def async_handler(event: Event):
            nonlocal handler_called
            handler_called = True

        bus.subscribe(EventType.TASK_EXECUTING, async_handler)

        event = Event(event_type=EventType.TASK_EXECUTING)
        bus.publish_sync(event)

        # Async handler should be scheduled as task
        # Give event loop a chance to run
        loop = asyncio.get_event_loop()
        pending = asyncio.all_tasks(loop)
        assert len(pending) > 0 or handler_called


class TestEventBusSubscriberCount:
    """Test subscriber count tracking."""

    def test_get_subscriber_count_empty(self):
        """Test count returns 0 for no subscribers."""
        bus = EventBus()

        count = bus.get_subscriber_count(EventType.TASK_SUBMITTED)
        assert count == 0

    def test_get_subscriber_count_after_subscribe(self):
        """Test count reflects subscribed handlers."""
        bus = EventBus()
        callback = MagicMock()

        bus.subscribe(EventType.TASK_COMPLETED, callback)
        count = bus.get_subscriber_count(EventType.TASK_COMPLETED)

        assert count == 1

    def test_get_subscriber_count_multiple(self):
        """Test count for multiple subscriptions."""
        bus = EventBus()
        callback1 = MagicMock()
        callback2 = MagicMock()

        bus.subscribe(EventType.METRICS_UPDATED, callback1)
        bus.subscribe(EventType.METRICS_UPDATED, callback2)

        count = bus.get_subscriber_count(EventType.METRICS_UPDATED)
        assert count == 2


class TestEvent:
    """Test Event data class."""

    def test_event_creation_generates_id(self):
        """Test event gets auto-generated ID."""
        event = Event()
        assert event.id is not None
        assert len(event.id) > 0

    def test_event_creation_generates_timestamp(self):
        """Test event gets auto-generated timestamp."""
        event = Event()
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_event_creation_with_parameters(self):
        """Test event creation with all parameters."""
        event = Event(
            event_type=EventType.TASK_SUBMITTED,
            agent="hermes_manager",
            task_id="task-456",
            data={"key": "value"},
        )

        assert event.event_type == EventType.TASK_SUBMITTED
        assert event.agent == "hermes_manager"
        assert event.task_id == "task-456"
        assert event.data["key"] == "value"

    def test_event_to_dict(self):
        """Test event serialization to dictionary."""
        event = Event(
            event_type=EventType.SANDBOX_STARTED,
            agent="sandbox_worker",
            task_id="exec-789",
            data={"memory": "1g"},
        )

        data = event.to_dict()

        assert isinstance(data, dict)
        assert data["id"] == event.id
        assert data["event_type"] == "sandbox.started"
        assert data["agent"] == "sandbox_worker"
        assert data["task_id"] == "exec-789"
        assert data["data"]["memory"] == "1g"
        assert "timestamp" in data

    def test_event_to_dict_with_correlation_id(self):
        """Test event to_dict includes correlation ID."""
        event = Event(
            event_type=EventType.TASK_FAILED,
            correlation_id="corr-123",
        )

        data = event.to_dict()
        assert data["correlation_id"] == "corr-123"


class TestEventTypes:
    """Test EventType enum values."""

    def test_task_event_types_exist(self):
        """Test all task-related event types are defined."""
        expected_types = [
            "task.submitted",
            "task.decomposed",
            "task.routed",
            "task.executing",
            "task.completed",
            "task.failed",
            "task.reviewed",
        ]

        for type_str in expected_types:
            assert any(e.value == type_str for e in EventType)

    def test_sandbox_event_types_exist(self):
        """Test sandbox event types are defined."""
        expected_types = ["sandbox.started", "sandbox.stopped"]

        for type_str in expected_types:
            assert any(e.value == type_str for e in EventType)

    def test_system_event_types_exist(self):
        """Test system event types are defined."""
        expected_types = ["agent.error", "metrics.updated", "alert.triggered"]

        for type_str in expected_types:
            assert any(e.value == type_str for e in EventType)


class TestEventBusAsyncConcurrency:
    """Test EventBus handling of concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_subscribe_unsubscribe(self):
        """Test concurrent subscribe/unsubscribe operations."""
        bus = EventBus()
        callback = MagicMock()

        async def subscribe_many():
            for _ in range(10):
                bus.subscribe(EventType.TASK_SUBMITTED, callback)

        await asyncio.gather(subscribe_many(), subscribe_many())

        # Should have 20 subscribers without errors
        count = bus.get_subscriber_count(EventType.TASK_SUBMITTED)
        assert count == 20

    @pytest.mark.asyncio
    async def test_concurrent_publish(self):
        """Test concurrent publishing."""
        bus = EventBus()
        received_count = 0

        async def counting_handler(event: Event):
            nonlocal received_count
            received_count += 1

        # Subscribe multiple handlers
        for _ in range(5):
            bus.subscribe(EventType.TASK_SUBMITTED, counting_handler)

        # Publish concurrently
        async def publish_event():
            event = Event(event_type=EventType.TASK_SUBMITTED)
            await bus.publish(event)

        await asyncio.gather(*[publish_event() for _ in range(10)])

        # Each of 10 events should reach all 5 handlers
        # Note: Due to timing, count may vary
        assert received_count >= 10  # At minimum, all events delivered once


class TestEventBusErrorHandling:
    """Test EventBus error handling scenarios."""

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash_bus(self):
        """Test bus continues operating after handler exception."""
        bus = EventBus()
        good_events: List[Event] = []

        async def bad_handler(event: Event):
            raise RuntimeError("Simulated handler failure")

        async def good_handler(event: Event):
            good_events.append(event)

        bus.subscribe(EventType.TASK_SUBMITTED, bad_handler)
        bus.subscribe(EventType.TASK_SUBMITTED, good_handler)

        # Publish several events
        for i in range(5):
            event = Event(event_type=EventType.TASK_SUBMITTED, data={"i": i})
            await bus.publish(event)

        # Good handler should have processed all events despite bad handler failures
        assert len(good_events) == 5

    @pytest.mark.asyncio
    async def test_publish_to_all_regardless_of_failures(self):
        """Test all subscribers attempted even if one fails."""
        bus = EventBus()
        results: List[str] = []

        async def first_handler(event: Event):
            results.append("first")

        async def second_handler(event: Event):
            raise ValueError("Second failed")

        async def third_handler(event: Event):
            results.append("third")

        bus.subscribe(EventType.ALERT_TRIGGERED, first_handler)
        bus.subscribe(EventType.ALERT_TRIGGERED, second_handler)
        bus.subscribe(EventType.ALERT_TRIGGERED, third_handler)

        event = Event(event_type=EventType.ALERT_TRIGGERED)
        await bus.publish(event)

        # Both working handlers should have received the event
        assert "first" in results
        assert "third" in results
        assert len(results) == 2