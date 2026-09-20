"""Structured logging with secret redaction.

JSON in production, human-readable in development. Generation-scoped context
(generation_id, task_id, stage, runtime) is bound via contextvars so every log
line emitted while handling a job carries it.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(r"(authorization|api[_-]?key|secret|token|password|passwd|credential|cookie)", re.I)
_SECRET_VALUE = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]+|sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]+"
    r"|X-Amz-Signature=[0-9a-f]+|X-Amz-Credential=[^&\s]+|AKIA[0-9A-Z]{16})"
)
_URL_CREDS = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")


def redact_text(value: str) -> str:
    value = _SECRET_VALUE.sub("[redacted]", value)
    return _URL_CREDS.sub(r"\1[redacted]@", value)


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: "[redacted]" if isinstance(k, str) and _SENSITIVE_KEY.search(k) else _redact(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    return value


def _redact_processor(_, __, event_dict: dict) -> dict:
    return _redact(event_dict)


def prompt_fingerprint(prompt: str) -> dict:
    """Loggable stand-in for a user prompt: length + short hash, never the text."""
    return {
        "prompt_len": len(prompt),
        "prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
    }


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_processor,
    ]
    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    # Route stdlib logging (uvicorn, celery, boto3) through the same redaction.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared[:3] + [_redact_processor],
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind_generation(generation_id: str | None = None, task_id: str | None = None, **extra: Any) -> None:
    ctx = {k: v for k, v in {"generation_id": generation_id, "task_id": task_id, **extra}.items() if v is not None}
    structlog.contextvars.bind_contextvars(**ctx)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
