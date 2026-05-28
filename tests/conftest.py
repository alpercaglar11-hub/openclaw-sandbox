"""Pytest configuration and fixtures for OpenClaw test suite."""

import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio

# Set test environment variables before imports
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
os.environ.setdefault("DATABASE_URL", ":memory:")
os.environ.setdefault("LOG_LEVEL", "DEBUG")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def temp_db() -> AsyncGenerator[str, None]:
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def clean_memory(temp_db: str) -> AsyncGenerator["Memory", None]:
    """Provide a clean Memory instance with temporary database."""
    from core.memory import Memory

    memory = Memory(db_path=temp_db)
    await memory.initialize()
    yield memory
    await memory.close()


@pytest_asyncio.fixture
async def clean_event_bus() -> AsyncGenerator["EventBus", None]:
    """Provide a clean EventBus instance."""
    from core.events import EventBus

    bus = EventBus()
    yield bus
    # Clear subscribers
    bus._subscribers.clear()


@pytest.fixture
def mock_config() -> "Config":
    """Provide a mock configuration for testing."""
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class MockConfig:
        ollama_url: str = "http://localhost:11434"
        ollama_model: str = "qwen2.5-coder:7b"
        sandbox_memory_limit: str = "1g"
        sandbox_cpu_limit: float = 1.0
        sandbox_timeout_seconds: int = 30
        telegram_bot_token: Optional[str] = None
        admin_chat_id: Optional[str] = None

    return MockConfig()