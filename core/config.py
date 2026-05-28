"""Configuration loader for OpenClaw sandbox.

Loads configuration from environment variables with validation and defaults.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Ollama configuration
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))

    # Router/service URLs
    router_url: str = field(default_factory=lambda: os.getenv("ROUTER_URL", "http://localhost:8000"))

    # Telegram configuration
    telegram_bot_token: Optional[str] = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    admin_chat_id: Optional[str] = field(
        default_factory=lambda: os.getenv("ADMIN_CHAT_ID")
    )

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Sandbox defaults
    sandbox_memory_limit: str = field(default_factory=lambda: os.getenv("SANDBOX_MEMORY_LIMIT", "1g"))
    sandbox_cpu_limit: float = field(default_factory=lambda: float(os.getenv("SANDBOX_CPU_LIMIT", "1.0")))
    sandbox_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "30"))
    )

    # Database
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./openclaw.db")
    )

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self._validate_log_level()
        self._validate_urls()
        self._configure_logging()

    def _validate_log_level(self) -> None:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level not in valid_levels:
            logger.warning(
                f"Invalid LOG_LEVEL '{self.log_level}', defaulting to INFO"
            )
            self.log_level = "INFO"

    def _validate_urls(self) -> None:
        """Validate that URLs are properly formatted."""
        if not self.ollama_url.startswith(("http://", "https://")):
            logger.warning(
                f"Ollama URL '{self.ollama_url}' may be invalid, "
                "should start with http:// or https://"
            )

    def _configure_logging(self) -> None:
        """Configure Python logging based on log level."""
        logging.basicConfig(
            level=getattr(logging, self.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    @classmethod
    def from_env(cls) -> "Config":
        """Create Config instance from environment variables.

        Returns:
            Config: A new Config instance with values from environment.

        Example:
            >>> config = Config.from_env()
        """
        return cls()


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance.

    Returns:
        Config: The global configuration instance.

    Note:
        Initializes config on first call if not already initialized.
    """
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment variables.

    Returns:
        Config: The reloaded configuration instance.
    """
    global _config
    _config = Config.from_env()
    return _config