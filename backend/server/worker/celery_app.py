"""Celery application (Redis broker). Shared by the API (send_task only) and
the worker. The database, not a result backend, is the source of truth."""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from server.core.config import get_settings
from server.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("server", broker=settings.redis_url, include=["server.worker.tasks"])

celery_app.conf.update(
    task_default_queue="generations",
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Expensive, long jobs: one at a time per process, ack only after completion,
    # redeliver if the worker dies mid-task.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    task_track_started=False,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": settings.celery_visibility_timeout_seconds},
    task_soft_time_limit=settings.generation_soft_timeout_seconds,
    task_time_limit=settings.generation_hard_timeout_seconds,
    worker_hijack_root_logger=False,
    worker_send_task_events=False,
)


@setup_logging.connect
def _configure_logging(**_kwargs) -> None:
    s = get_settings()
    configure_logging(s.log_level, json_logs=s.is_production)
