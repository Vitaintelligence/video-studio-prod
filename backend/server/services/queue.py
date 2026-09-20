"""Task enqueue seam (API -> Celery/Redis). Tests replace ``enqueue_generation``."""

from __future__ import annotations

import uuid

TASK_NAME = "server.worker.tasks.run_generation"


class QueueUnavailable(Exception):
    pass


def enqueue_generation(generation_id: uuid.UUID) -> str:
    """Send the task by name so the API never imports worker/engine code."""
    from server.worker.celery_app import celery_app

    try:
        result = celery_app.send_task(TASK_NAME, args=[str(generation_id)], task_id=str(generation_id))
    except Exception as exc:  # kombu/redis connection errors
        raise QueueUnavailable("queue unavailable") from exc
    return result.id
