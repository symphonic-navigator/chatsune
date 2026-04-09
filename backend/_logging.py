"""Structured logging configuration for Chatsune.

Single source of truth for logging setup. Uses structlog with a stdlib
ProcessorFormatter bridge so that both structlog-native loggers and legacy
`logging.getLogger(...)` callers emit records through the same processor
chain.

Two sinks are supported simultaneously:

- Console (stderr): pretty colourful output locally, JSON in Docker.
- File: JSON lines to `backend/logs/chatsune.log`, daily rotation, 14
  backups. Intended for local development and lnav/jq consumption; in
  Docker the file sink is turned off and logs go only to stdout/stderr
  where Grafana picks them up.

Context (`correlation_id`, `user_id`, `job_id`, `job_type`, `lock_key`,
...) is carried through `structlog.contextvars` so it can be bound once
and automatically appear on every downstream event.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog


def _build_shared_processors() -> list[Any]:
    """Processors shared by structlog-native and stdlib-bridged records."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(
    *,
    level: str = "INFO",
    console: bool = True,
    console_format: str = "pretty",  # "pretty" | "json"
    file: bool = True,
    file_path: str = "backend/logs/chatsune.log",
    file_backup_count: int = 14,
    uvicorn_access_level: str = "WARNING",
    third_party_level: str = "WARNING",
) -> None:
    """Configure stdlib logging + structlog.

    Idempotent: calling repeatedly resets previous handlers.
    """
    shared_processors = _build_shared_processors()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if console_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.setLevel(logging.getLevelName(level.upper()))

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if file:
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_path),
            when="midnight",
            backupCount=file_backup_count,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(file_formatter)
        root.addHandler(file_handler)

    # Tame noisy libraries.
    logging.getLogger("uvicorn.access").setLevel(
        logging.getLevelName(uvicorn_access_level.upper())
    )
    for noisy in ("httpx", "httpcore", "pymongo"):
        logging.getLogger(noisy).setLevel(
            logging.getLevelName(third_party_level.upper())
        )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog-bound logger. Prefer this over `logging.getLogger`."""
    return structlog.get_logger(name)
