"""Worker lifecycle: startup preflight, capability publishing, graceful shutdown."""

from __future__ import annotations

import os
import signal
import threading

import structlog
from celery.signals import worker_process_init, worker_ready, worker_shutting_down

from server.core.config import get_settings
from server.services.capabilities import publish_snapshot
from server.services.ratelimit import get_redis
from server.worker.celery_app import celery_app  # noqa: F401  (ensures signals bind to this app)

log = structlog.get_logger(__name__)

_shutdown = threading.Event()
_parent_pid = os.getppid()
CAPABILITY_REFRESH_SECONDS = 300


def shutdown_requested() -> bool:
    """True once SIGTERM arrived in this process or the Celery parent went away."""
    return _shutdown.is_set() or os.getppid() != _parent_pid


def request_shutdown(*_args) -> None:
    _shutdown.set()


def reset_shutdown_for_tests() -> None:
    _shutdown.clear()


@worker_process_init.connect
def _child_init(**_kwargs) -> None:
    """Pool child: remember the parent and turn SIGTERM into a graceful stop request."""
    global _parent_pid
    _parent_pid = os.getppid()
    signal.signal(signal.SIGTERM, request_shutdown)
    log.info("worker_process_ready", pid=os.getpid())


@worker_shutting_down.connect
def _shutting_down(**_kwargs) -> None:
    _shutdown.set()
    log.info("worker_shutting_down")


def _publish_loop() -> None:
    settings = get_settings()
    redis_client = get_redis()
    while not _shutdown.is_set():
        try:
            doc = publish_snapshot(redis_client, settings)
            log.info("capabilities_published", generation_available=doc["generation_available"], features=doc["features"])
        except Exception:
            log.exception("capabilities_publish_failed")
        _shutdown.wait(CAPABILITY_REFRESH_SECONDS)


@worker_ready.connect
def _on_ready(**_kwargs) -> None:
    settings = get_settings()
    log.info(
        "worker_ready",
        runtime=settings.orchestrator_provider,
        pipeline=settings.openmontage_pipeline,
        concurrency=settings.worker_concurrency,
        storage=settings.storage_backend,
        anthropic_key_configured=bool(settings.anthropic_api_key),
    )
    threading.Thread(target=_publish_loop, name="capabilities-publisher", daemon=True).start()
