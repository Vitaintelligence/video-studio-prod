#!/usr/bin/env bash
set -euo pipefail

# Role dispatcher so ONE image can serve either service purely via configuration.
# Railway: set SERVICE_ROLE=api|worker (or set an explicit start command instead).
case "${SERVICE_ROLE:-api}" in
  api)    exec ./scripts/start-api.sh ;;
  worker) exec ./scripts/start-worker.sh ;;
  *) echo "unknown SERVICE_ROLE: ${SERVICE_ROLE}" >&2; exit 64 ;;
esac
