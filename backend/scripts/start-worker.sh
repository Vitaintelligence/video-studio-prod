#!/usr/bin/env bash
set -euo pipefail

# One expensive video job per child process by default; children are recycled
# after each task so render/browser memory is returned to the OS.
exec celery -A server.worker.celery_app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${WORKER_CONCURRENCY:-1}" \
  --queues=generations \
  --prefetch-multiplier=1 \
  --max-tasks-per-child="${WORKER_MAX_TASKS_PER_CHILD:-1}" \
  -O fair
