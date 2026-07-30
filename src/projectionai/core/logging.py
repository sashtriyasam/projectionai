"""Application logging configuration.

Provides structured logging with:
- Console output (colorized in development)
- Rotating file output (all environments)
- JSON-formatted records for production / log aggregation
- Per-module logger hierarchy with inherited configuration
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

from platformdirs import user_log_dir

from projectionai.core.config import AppConfig

# ---------------------------------------------------------------------------
# Log record fields
# ---------------------------------------------------------------------------

_EXTRA_FIELDS = ("session_id", "scene_id", "job_id", "provider", "duration_ms")


# ---------------------------------------------------------------------------
# JSON formatter (production)
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Outputs JSON lines for log aggregation tools (Datadog, Loki, etc.)."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)

        # Inject extra fields
        for field in _EXTRA_FIELDS:
            val = getattr(record, field, None)
            if val is not None:
                payload[field] = val

        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _console_handler(config: AppConfig) -> logging.Handler:
    """Return a console handler with optional color support."""
    handler = logging.StreamHandler(sys.stdout)

    if config.is_debug:
        fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    else:
        handler.setFormatter(JSONFormatter())

    return handler


def _file_handler(config: AppConfig, log_dir: Path) -> logging.Handler:
    """Return a rotating file handler."""
    _ = config
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "projectionai.log"

    handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(JSONFormatter())
    return handler


def configure_logging(config: AppConfig) -> None:
    """Configure the root logger based on *config*.

    Call this once at application startup, before any other module
    acquires a logger.
    """
    log_dir = Path(
        config.data_dir
        if config.data_dir
        else user_log_dir("projectionai", ensure_exists=True)
    )

    root = logging.getLogger()
    root.setLevel(config.log_level)

    # Remove default handlers (e.g., from PySide6)
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.addHandler(_console_handler(config))
    root.addHandler(_file_handler(config, log_dir))

    # Quiet noisy third-party loggers
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("google.genai").setLevel(logging.WARNING)

    root.info(
        "Logging initialized: level=%s dir=%s",
        config.log_level,
        log_dir,
    )
