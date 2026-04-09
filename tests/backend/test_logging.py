"""Tests for backend._logging — structured logging configuration."""
import json
import logging
import os
from pathlib import Path

import pytest
import structlog


def _reset_logging():
    """Reset stdlib logging state between tests."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_logging()
    yield
    _reset_logging()


def test_configure_logging_is_importable():
    from backend._logging import configure_logging, get_logger
    assert callable(configure_logging)
    assert callable(get_logger)


def test_console_json_format_emits_valid_json(capsys):
    from backend._logging import configure_logging, get_logger

    configure_logging(
        level="INFO",
        console=True,
        console_format="json",
        file=False,
    )
    log = get_logger("chatsune.test")
    log.info("job.enqueued", job_id="abc123", job_type="extraction")

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "job.enqueued"
    assert payload["job_id"] == "abc123"
    assert payload["job_type"] == "extraction"
    assert payload["level"] == "info"
    assert payload["logger"] == "chatsune.test"
    assert "timestamp" in payload


def test_stdlib_logger_routes_through_structlog(capsys):
    from backend._logging import configure_logging

    configure_logging(level="INFO", console=True, console_format="json", file=False)
    stdlib_log = logging.getLogger("chatsune.stdlib_bridge_test")
    stdlib_log.info("legacy message %s", "value")

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["logger"] == "chatsune.stdlib_bridge_test"
    assert "legacy message value" in payload["event"]


def test_context_binding_propagates(capsys):
    from backend._logging import configure_logging, get_logger

    configure_logging(level="INFO", console=True, console_format="json", file=False)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-42", job_id="job-7")
    log = get_logger("chatsune.test")
    log.info("job.started")
    structlog.contextvars.clear_contextvars()

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["correlation_id"] == "corr-42"
    assert payload["job_id"] == "job-7"


def test_file_handler_writes_json(tmp_path):
    from backend._logging import configure_logging, get_logger

    log_path = tmp_path / "chatsune.log"
    configure_logging(
        level="INFO",
        console=False,
        console_format="json",
        file=True,
        file_path=str(log_path),
    )
    log = get_logger("chatsune.test")
    log.info("job.completed", job_id="z")

    for h in logging.getLogger().handlers:
        h.flush()

    assert log_path.exists()
    content = log_path.read_text().strip()
    payload = json.loads(content.splitlines()[-1])
    assert payload["event"] == "job.completed"
    assert payload["job_id"] == "z"


def test_third_party_loggers_muted(capsys):
    from backend._logging import configure_logging

    configure_logging(
        level="INFO",
        console=True,
        console_format="json",
        file=False,
        uvicorn_access_level="WARNING",
        third_party_level="WARNING",
    )
    logging.getLogger("uvicorn.access").info("should not appear")
    logging.getLogger("httpx").info("should not appear either")

    captured = capsys.readouterr()
    out = (captured.err or captured.out)
    assert "should not appear" not in out
