# AI Video Generation - Backend (Phase 1)

iOS-first AI video generation product. **Phase 1 is backend only**: a REST API, an async
generation worker and a server-hosted [OpenMontage](https://github.com/calesthio/OpenMontage)
engine, driven headlessly by the Claude Agent SDK. The Flutter app (Phase 2) lives in `mobile/`
and never needs to know OpenMontage exists.

```
Flutter iOS app (Phase 2)
        |  HTTPS + Bearer token
        v
FastAPI API (Railway, public)  ---- PostgreSQL (generations, progress, keys)
        |                     \--- Redis  (rate limits, capability snapshot)
        |  enqueue (Celery)
        v
Redis queue  -->  Worker (Railway, private)
                     |  spawns, with a scrubbed environment
                     v
             Claude Agent SDK runner  --reads-->  OpenMontage (AGENT_GUIDE, pipeline YAML, skills)
                     |                                 |
                     +---- tools --> image/video/TTS provider APIs, FFmpeg, Remotion
                     v
        checkpoints (projects/<id>/checkpoint_*.json) --> progress in Postgres
                     v
   ffprobe validation -> upload MP4 + thumbnail -> Cloudflare R2 -> status API returns URL
```

## Repository layout

| Path | What |
|---|---|
| `backend/server/` | FastAPI app, Celery worker, DB models, storage, runtime adapters |
| `backend/openmontage/` | Vendored upstream engine (AGPL-3.0). One local addition: `pipeline_defs/app-cinematic.yaml` |
| `backend/migrations/` | Alembic |
| `backend/scripts/` | start scripts, `preflight.py`, `smoke_*.py` |
| `backend/tests/` | server test suite (no network, no paid APIs) |
| `mobile/` | Reserved for Phase 2 (Flutter) |
| `docker-compose.yml` | Local Postgres + Redis + API + worker |

Details: [backend/README.md](backend/README.md).

## Local quick start

```bash
cp backend/.env.example backend/.env      # optional for the mock stack
docker compose up --build                 # postgres, redis, api (:8000), worker
```

The compose worker runs the **zero-cost mock runtime** by default (real checkpoints, a real short MP4,
real validation/upload path - no LLM, no providers). In another shell:

```bash
export DEV_API_TOKEN=dev-token-change-me-0123456789abcdef
curl http://localhost:8000/health
curl -X POST http://localhost:8000/v1/generations \
  -H "Authorization: Bearer $DEV_API_TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"prompt":"A cinematic short about a futuristic city waking at sunrise.","duration_seconds":30,"aspect_ratio":"9:16"}'
python backend/scripts/smoke_api.py --mock-worker      # end-to-end: submit + poll to completion
```

Real generations: put `ANTHROPIC_API_KEY` and at least one visual provider key (e.g. `FAL_KEY`) in
`backend/.env`, then `ORCHESTRATOR_PROVIDER=claude_agent_sdk docker compose up --build`.
Real runs cost money; `MAX_JOB_BUDGET_USD` (default 3.00) and `AGENT_MAX_LLM_BUDGET_USD` (default 2.00) cap them.

## API (what the mobile app uses)

All `/v1` routes need `Authorization: Bearer <DEV_API_TOKEN>` (Phase 1 placeholder auth).

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/generations` | `202` immediately. Header `Idempotency-Key` makes retries safe |
| GET | `/v1/generations` | newest first; `limit`, `cursor`, `status` |
| GET | `/v1/generations/{id}` | status, `progress`, friendly `display_stage`, `output_url` |
| POST | `/v1/generations/{id}/cancel` | best effort |
| GET | `/v1/capabilities` | what the deployment can currently do |
| POST | `/v1/uploads/presign` | direct-to-R2 upload (R2 only) |
| GET | `/health`, `/ready` | unauthenticated probes |

Request fields are structured only (`prompt`, `duration_seconds` 15/30/45/60, `aspect_ratio`
9:16/1:1/16:9, `style`, `voice_enabled`, `captions_enabled`, `quality`, `pipeline`). There is no endpoint
that accepts instructions for the agent.

## Railway

One Railway project, four services: `Postgres`, `Redis`, `api` (public domain), `worker` (no domain).
`api` and `worker` are the **same repo, same `backend/` root, same Dockerfile**; only the start command differs.
Step-by-step commands are in [backend/README.md#deploying-to-railway](backend/README.md#deploying-to-railway).

## Security notes

- The public API accepts validated, structured fields only. The agent prompt is built server-side; the user's
  brief is embedded as delimited untrusted DATA and can never form part of a shell command.
- The agent runs in a **separate process with an allowlisted environment**: no `DATABASE_URL`, `REDIS_URL`,
  R2 or API-token variables. Its tools are limited (Read/Write/Edit/Glob/Grep/Bash/WebSearch), writes are confined
  to `projects/<generation-id>/`, and a PreToolUse policy blocks env dumps, other jobs' directories, network
  tooling, installs and engine/server edits. `max_turns`, LLM budget, provider budget and wall-clock limits apply.
  **This is defence in depth, not a sandbox**: provider keys must exist in the agent's environment for OpenMontage
  tools to work, so use provider-side spend limits and per-environment keys.
- API service holds no Anthropic/provider keys. Worker runs as non-root (`uid 10001`) with a read-only source tree.
- Errors returned to clients are fixed, sanitized messages; details stay in server logs (which redact secrets and never
  log prompts, only length + hash).
- CORS is off unless `CORS_ALLOWED_ORIGINS` is set; docs are off in production; request bodies are capped at 64 KB.

## Licensing

OpenMontage is **AGPL-3.0**. Its license and notices are preserved in `backend/openmontage/LICENSE`. Because the
service exposes it over a network, AGPL section 13 obligations apply to the OpenMontage portion. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [backend/OPENMONTAGE_UPSTREAM.md](backend/OPENMONTAGE_UPSTREAM.md)
(upstream URL, pinned commit SHA, local modifications).
