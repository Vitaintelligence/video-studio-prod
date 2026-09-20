#!/usr/bin/env bash
set -euo pipefail

# Same image as the worker; Railway/compose select the service by start command.
# Migrations: Railway runs `alembic upgrade head` as a pre-deploy command (see railway.json);
# set RUN_MIGRATIONS=true to run them here instead (docker compose does).
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  alembic upgrade head
fi

exec uvicorn server.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --no-server-header
