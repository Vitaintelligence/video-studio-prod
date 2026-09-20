#!/usr/bin/env bash
# Provision + deploy the two app services on Railway. Run from anywhere AFTER `railway login`
# and `railway init` (or `railway link`), with the Postgres/Redis/api/worker services created:
#
#   railway add --database postgres; railway add --database redis
#   railway add --service api;       railway add --service worker
#
# Written against Railway CLI 5.58.0 (`railway environment edit --service-config <svc> <dot.path> <value>`).
# NOTE: authored without an authenticated Railway session, so it has not been executed end to end;
# every step is an ordinary CLI call - if one fails, run it by hand / check `railway environment config --json`.
#
# Secrets come from the calling environment and are streamed over stdin (never echoed, never in argv).
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root: service root directory is set to backend/ on the Railway side

: "${DEV_API_TOKEN:?set DEV_API_TOKEN (python -c 'import secrets;print(secrets.token_urlsafe(32))')}"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY (worker only)}"
: "${R2_ENDPOINT_URL:?set R2_* (worker needs them; storage is ephemeral on Railway)}"
: "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_BUCKET:?}"

MAX_JOB_BUDGET_USD="${MAX_JOB_BUDGET_USD:-3.00}"
PG="${POSTGRES_SERVICE:-Postgres}"
RD="${REDIS_SERVICE:-Redis}"

secret() { # secret <service> <NAME>   (value taken from $NAME in this shell)
  local svc="$1" name="$2"
  printf '%s' "${!name}" | railway variable set "$name" --stdin --service "$svc" --skip-deploys >/dev/null
  echo "  set $name on $svc"
}
plain() { railway variable set "$2" --service "$1" --skip-deploys >/dev/null; echo "  set ${2%%=*} on $1"; }

echo "== service settings (root dir, commands, health check) =="
for svc in api worker; do
  railway environment edit --stage --service-config "$svc" source.rootDirectory backend >/dev/null
  railway environment edit --stage --service-config "$svc" build.dockerfilePath Dockerfile >/dev/null
done
railway environment edit --stage --service-config api deploy.startCommand "./scripts/start-api.sh" >/dev/null
railway environment edit --stage --service-config api deploy.healthcheckPath "/health" >/dev/null
railway environment edit --stage --service-config api deploy.preDeployCommand "alembic upgrade head" >/dev/null
railway environment edit --stage --service-config worker deploy.startCommand "./scripts/start-worker.sh" >/dev/null
railway environment edit -m "videogen service settings" >/dev/null

echo "== api variables (NO provider / Anthropic keys) =="
plain api "APP_ENV=production"
plain api "AUTH_MODE=dev_token"
plain api "DATABASE_URL=\${{${PG}.DATABASE_URL}}"
plain api "REDIS_URL=\${{${RD}.REDIS_URL}}"
plain api "STORAGE_BACKEND=r2"
secret api DEV_API_TOKEN
# API only needs R2 to presign uploads / sign output URLs:
plain api "R2_ENDPOINT_URL=${R2_ENDPOINT_URL}"
plain api "R2_BUCKET=${R2_BUCKET}"
secret api R2_ACCESS_KEY_ID
secret api R2_SECRET_ACCESS_KEY
[ -n "${R2_PUBLIC_BASE_URL:-}" ] && plain api "R2_PUBLIC_BASE_URL=${R2_PUBLIC_BASE_URL}"

echo "== worker variables =="
plain worker "APP_ENV=production"
plain worker "DATABASE_URL=\${{${PG}.DATABASE_URL}}"
plain worker "REDIS_URL=\${{${RD}.REDIS_URL}}"
plain worker "ORCHESTRATOR_PROVIDER=claude_agent_sdk"
plain worker "OPENMONTAGE_PIPELINE=app-cinematic"
plain worker "MAX_JOB_BUDGET_USD=${MAX_JOB_BUDGET_USD}"
plain worker "WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-1}"
# Time between SIGTERM and SIGKILL on redeploy, so the worker can stop the agent and re-queue the job:
plain worker "RAILWAY_DEPLOYMENT_DRAINING_SECONDS=60"
plain worker "STORAGE_BACKEND=r2"
plain worker "R2_ENDPOINT_URL=${R2_ENDPOINT_URL}"
plain worker "R2_BUCKET=${R2_BUCKET}"
[ -n "${R2_PUBLIC_BASE_URL:-}" ] && plain worker "R2_PUBLIC_BASE_URL=${R2_PUBLIC_BASE_URL}"
secret worker ANTHROPIC_API_KEY
secret worker R2_ACCESS_KEY_ID
secret worker R2_SECRET_ACCESS_KEY
# Provider keys: only the ones actually present in the caller's environment (names from upstream .env.example).
mapfile -t PROVIDERS < <(grep -oE '^#?[[:space:]]*[A-Z][A-Z0-9_]+=' "$(dirname "$0")/../.env.example" | tr -d '# =' | sed -n '/^FAL_KEY$/,$p')
for name in "${PROVIDERS[@]}" ATLASCLOUD_API_KEY; do
  if [ -n "${!name:-}" ]; then secret worker "$name"; fi
done

echo "== deploy =="
railway up --service worker --detach
railway up --service api --detach

echo "== public domain for the API only =="
railway domain --service api
echo "Done. Verify: curl https://<domain>/health ; railway logs --service api ; railway logs --service worker"
