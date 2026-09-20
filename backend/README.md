# Backend

FastAPI API + Celery worker + vendored OpenMontage engine, in one Docker image.

## How a generation runs

1. `POST /v1/generations` validates the request, inserts a `generations` row (`queued`), enqueues
   `server.worker.tasks.run_generation(<id>)` on Redis and returns **202** without waiting.
2. The worker claims the job (`starting` -> `running`), creates `openmontage/projects/<generation-uuid>/`
   and starts the runtime selected by `ORCHESTRATOR_PROVIDER`.
3. **Claude runtime** (`server/runtime/claude_agent_runtime.py`): OpenMontage has no `generate()` API - the coding agent *is*
   its control plane (reads `AGENT_GUIDE.md`, the pipeline YAML and stage-director skills, calls registry tools, writes
   checkpoints). The runtime therefore spawns `server.runtime.claude_agent_runner` in a **separate process with an allowlisted
   environment**, feeding it a server-built prompt (system rules + JOB/SETTINGS + the user's brief as delimited DATA).
   If the agent ends early it is resumed (`AGENT_MAX_CONTINUATIONS`).
4. While it runs, the worker polls every `CANCEL_POLL_SECONDS`: cancel requested? SIGTERM? provider spend over
   `MAX_JOB_BUDGET_USD`? a stage stuck on a human gate? It also maps `checkpoint_<stage>.json` -> `progress` /
   `current_stage` (`server/services/checkpoint_monitor.py`) and persists them. Progress is `5 + 85 * (done stages + partial) / stages`,
   capped at 90 by the pipeline; validation/upload own the rest, so 100 only means "deliverable".
5. On success: locate `renders/final.mp4` -> **ffprobe validation** (video stream, duration > 0, size > 0, audio when
   narration was requested) -> thumbnail -> upload to storage (`generations/<id>/final.mp4`, `thumbnail.jpg`) -> persist keys ->
   `completed` -> delete large local media. Nothing is `completed` before the upload succeeded.
6. Failures store a sanitized code (`GENERATION_FAILED`, `BUDGET_EXCEEDED`, `STORAGE_FAILED`, `OUTPUT_INVALID`, `TIMEOUT`, ...)
   and log the detail server-side. Clients only ever see fixed messages.

Storage upload errors are retried by Celery with backoff; a retry **reuses the already-rendered video** instead of paying to
re-run the agent. Worker death is covered by `acks_late` + `reject_on_worker_lost`; SIGTERM (Railway deploy) stops the agent,
puts the job back to `queued` and re-publishes it.


### Storage providers (S3-compatible)

`STORAGE_BACKEND=s3` (or `r2`) works with any S3-compatible store. Preferred variable names: `S3_ENDPOINT_URL`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_PUBLIC_BASE_URL` (the older `R2_*` names still work).

| Provider | `S3_ENDPOINT_URL` | `S3_REGION` | `S3_PUBLIC_BASE_URL` (optional) |
|---|---|---|---|
| Supabase Storage | `https://<project-ref>.storage.supabase.co/storage/v1/s3` | your project's region, e.g. `ap-south-1` | `https://<project-ref>.supabase.co/storage/v1/object/public/<bucket>` (public bucket) |
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` | `auto` | the bucket's public r2.dev / custom domain |

Supabase: create a bucket (Storage), then Project Settings -> Storage -> S3 Connection -> create access keys. Those keys
have full access to every bucket in the project: keep them on Railway (api + worker) only. Watch the plan's per-file upload
limit (the free plan's is small; raw UGC clips are often larger) and egress allowance.

### Runtimes

`ORCHESTRATOR_PROVIDER` selects one; `server/runtime/base.py` is the only contract the rest of the backend imports.

| value | what |
|---|---|
| `claude_agent_sdk` | real generation (needs `ANTHROPIC_API_KEY` + provider keys on the **worker**) |
| `mock` | zero-cost: writes real checkpoints, renders a 2 s MP4 with ffmpeg. Tests, compose default, smoke tests |

### The app pipeline

Upstream pipelines have human approval gates (`human_approval_default: true`) and `lib/checkpoint.py` refuses to write a gated
stage as `completed` without `human_approved=True`. We do not fake approvals. `openmontage/pipeline_defs/app-cinematic.yaml`
(derived from `cinematic.yaml`, reusing its director skills/tools) has all gates off, drops the human-facing `publish` stage and
keeps checkpoints, schema validation, self-review, cost governance and render verification. The API whitelist
(`server/services/pipelines.py`) exposes only this pipeline.

## Configuration

See [.env.example](.env.example) (provider variables are copied verbatim from upstream's `.env.example`). Key points:

- `DATABASE_URL` accepts Railway's `postgresql://` form. `ENABLE_API_DOCS` defaults to off in production.
- The container fallback is SQLite at `/workspace/storage/dev.db`; its parent directory is created automatically. This is
  useful for a single-container trial or an attached volume, but API + worker deployments must share Postgres by setting
  `DATABASE_URL` on both services.
- Production requires `DEV_API_TOKEN` (>= 24 chars); the app refuses to start otherwise.
- `STORAGE_BACKEND=r2` needs `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. With
  `R2_PUBLIC_BASE_URL` set, URLs are public/CDN; without it they are signed and expire after `SIGNED_URL_TTL_SECONDS`.
  The DB stores object **keys**; URLs are derived at read time.
- `GENERATION_SOFT_TIMEOUT_SECONDS` < `GENERATION_HARD_TIMEOUT_SECONDS` < `CELERY_VISIBILITY_TIMEOUT_SECONDS` (validated).

| Service | needs |
|---|---|
| api | `APP_ENV`, `AUTH_MODE`, `DEV_API_TOKEN`, `DATABASE_URL`, `REDIS_URL`, (R2 vars if presigning uploads / signed URLs) |
| worker | `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `ORCHESTRATOR_PROVIDER`, `ANTHROPIC_API_KEY`, `MAX_JOB_BUDGET_USD`, R2 vars, provider keys |

`/v1/capabilities` is computed by the **worker** from the real OpenMontage registry (`discover()` +
`provider_menu_summary()`), reduced to counts/booleans, and published to Redis every 5 minutes. The API (which has no provider
keys) serves that snapshot; until a worker reports it says `status: "unknown"`, and once a worker reports
`generation_available: false`, `POST /v1/generations` returns 503 instead of queueing a doomed job.

## Development

```bash
python -m venv .venv && . .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r openmontage/requirements.txt -r requirements-test.txt
pytest                                                     # 119 tests (also runnable against Postgres via TEST_DATABASE_URL), no paid APIs
python scripts/preflight.py                                # sanitized environment report
(cd openmontage && make test-contracts)                    # upstream engine contract tests
```

Scripts: `scripts/smoke_api.py` (health/auth/capabilities + mock generation), `scripts/smoke_worker.py` (in-process worker
run, `--ping` to check a live worker), `scripts/smoke_generation.py` (**real, paid**, refuses unless `ALLOW_PAID_SMOKE_TEST=true`).

Migrations: `alembic upgrade head` (never `create_all` outside tests). `alembic revision --autogenerate -m "..."` after model
changes; `tests/test_platform.py` fails if models and migrations drift.

## Security model of the agent runtime (read this)

- **Structured input only.** No route accepts agent instructions. Everything interpolated into the prompt outside the brief is a
  UUID or a whitelisted enum/int. The brief is sanitized (control chars stripped, forged `USER_BRIEF_*` markers removed) and
  placed between `USER_BRIEF_BEGIN`/`USER_BRIEF_END`, with the system prompt declaring it untrusted data.
- **Separate process, allowlisted env** (`build_agent_env`): PATH/locale + `ANTHROPIC_API_KEY` + the provider variable names read
  from upstream's `.env.example`. `DATABASE_URL`, `REDIS_URL`, `R2_*`, `DEV_API_TOKEN` never reach it.
  The Claude CLI's own `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` is **not** used: it requires bubblewrap (unprivileged user
  namespaces), which Railway-style containers do not provide, so we pin it to `0`. Consequence: `ANTHROPIC_API_KEY` and provider
  keys are visible to the agent's Bash subprocesses; the tool policy blocks the obvious ways to read them, nothing more.
- **Tool surface**: Read/Write/Edit/Glob/Grep/Bash/TodoWrite (+WebSearch). `WebFetch`, sub-agents, skills, MCP are denied.
  `server/runtime/policy.py` runs as a PreToolUse hook: writes only under `projects/<this-id>/`, no reading other jobs or `.env`,
  Bash denylist (env dumps, `/proc`, curl/wget/ssh, package installs, git, process control, server/celery commands).
- **Limits**: `AGENT_MAX_TURNS`, `AGENT_MAX_LLM_BUDGET_USD` (SDK `max_budget_usd`), `MAX_JOB_BUDGET_USD` (enforced from checkpoint
  cost snapshots), wall-clock timeout, Celery soft/hard limits, process-group kill on cancel/timeout.
- **OS**: non-root uid 10001, source tree root-owned, writable only: `openmontage/projects`, Remotion scratch dirs,
  `/workspace/*`, `$HOME`. No curl/wget/git in the image.
- **Known limits.** The Bash policy is a denylist, and the agent legitimately needs provider keys in its environment, so a
  determined prompt injection could try to misuse them. There is no kernel sandbox (bubblewrap needs user namespaces that
  Railway containers do not grant). Mitigations to keep: provider-side spend caps, dedicated keys for this service, monitoring. Future hardening: an
  Anthropic-key-injecting local proxy (agent gets a dummy key) and provider-call proxies.
  A real production auth system and per-user quotas are Phase 2+.


## Best-take selection ("say it five times, post the best one")

For talking-head / UGC footage the worker can turn a messy recording into a clean cut. It triggers when the edit
instruction mentions retakes, mistakes, messy footage, filler words, "best take", etc. (see `server/services/edit_planner.py`).

```
video -> speech-to-text with word timestamps (faster-whisper, local)
      -> utterances -> groups of repeated takes (the same line said again, incl. half-said flubs)
      -> off-script chatter flagged ("wait, let me start again")
      -> per-take scores: completeness, fluency (fillers, stumbles, pauses), ASR confidence, pacing
      -> [OpenRouter / Qwen] editorial choice among the candidate takes   (optional; falls back to the scores)
      -> keep-ranges on word boundaries; dead air, fillers, retakes removed; audio fades at joins
      -> OpenMontage video_trimmer cut + concat -> FFmpeg render
```

- The engine and tool live inside OpenMontage: `openmontage/lib/take_selection.py`, tool `take_analyzer`
  (`analyze` / `edl`), skill `.agents/skills/take-selection/SKILL.md` - so the Claude agent path can use the same
  measurements. They are listed as local modifications in `OPENMONTAGE_UPSTREAM.md`.
- **The model cannot invent cuts.** It sees only text (ids, times, transcript, scores) and answers with choices among
  ids the engine produced; the engine validates them and ignores anything else. Transcript text is treated as untrusted data.
- Configure the model with `OPENROUTER_EDITING_MODEL` (any OpenRouter text model, e.g. a Qwen 3.7 id such as
  `qwen/qwen3.7-flash`). Without it, or if the call fails, the engine's own recommendation is used
  (the response then carries the `takes_llm_unavailable` warning when a model was configured but unusable).
- Speech-to-text runs on the worker's CPU (`TRANSCRIBE_MODEL`, default `base`; ~4x real time). The model is baked into the image.
- The edit response includes safe `insights` (e.g. `retakes_removed`, `off_script_removed`, `source_seconds`,
  `output_seconds`) and warnings (`no_speech_detected`, `take_analysis_failed`, `takes_unavailable`).
- A target length only ever drops whole segments; a sentence is never cut in half.
- Verified end to end on real speech: a 37 s clip with 4 retakes, an off-script remark, filler words and long pauses becomes ~8 s
  containing only the best take of each line (checked by re-transcribing the output).
- Limits: v1 assumes one speaker; it judges from the transcript and audio, not from what is on screen (no visual take
  scoring yet); non-English quality depends on the Whisper model size.

## Deploying to Railway

Topology: `Postgres` + `Redis` (private) + `api` (public domain, health check `/health`) + `worker` (no domain).
Both app services deploy `backend/` with the same `Dockerfile`.

```bash
npm i -g @railway/cli            # or: brew install railway   (verified against CLI 5.58.0)
railway login
railway init --name videogen     # or: railway link  (existing project)

railway add --database postgres  # creates service "Postgres"
railway add --database redis     # creates service "Redis"
railway add --service api
railway add --service worker

# one-shot helper that sets variables/commands (edit the top of the script for your secrets first):
DEV_API_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))") \
ANTHROPIC_API_KEY=... R2_ENDPOINT_URL=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=... \
R2_PUBLIC_BASE_URL=... FAL_KEY=... ./scripts/railway_deploy.sh
```

What the helper does (each step is a plain CLI call you can run by hand):

| Step | Command |
|---|---|
| root dir + Dockerfile | `railway environment edit --service-config api source.rootDirectory backend` (and `worker`) |
| api start/health/migrate | `deploy.startCommand ./scripts/start-api.sh`, `deploy.healthcheckPath /health`, `deploy.preDeployCommand "alembic upgrade head"` |
| worker start | `deploy.startCommand ./scripts/start-worker.sh` |
| shared refs | `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `REDIS_URL=${{Redis.REDIS_URL}}` on both |
| api-only | `APP_ENV=production AUTH_MODE=dev_token DEV_API_TOKEN=...` (+ R2 vars if presigning/signing) |
| worker-only | `ORCHESTRATOR_PROVIDER=claude_agent_sdk ANTHROPIC_API_KEY=... MAX_JOB_BUDGET_USD=3.00 R2_* provider keys` |
| domain | `railway domain --service api` (never for the worker) |
| deploy | `railway up --service api --detach` / `railway up --service worker --detach` |

Alternatively the repo ships `railway.api.json` / `railway.worker.json` (config-as-code) - point each service's *Config as Code
path* at the matching file - and `scripts/start.sh` dispatches on `SERVICE_ROLE=api|worker` if you would rather not set start commands.

Verify:

```bash
API=https://<your-api-domain>
curl $API/health                                             # {"status":"ok"}
curl $API/ready                                              # database + redis ok
curl -H "Authorization: Bearer $DEV_API_TOKEN" $API/v1/capabilities
railway logs --service api      # look for: api_boot, alembic "Running upgrade", no tracebacks
railway logs --service worker   # look for: worker_ready, capabilities_published, celery "ready"
```

Notes: the Railway filesystem is ephemeral - outputs always go to R2 (`STORAGE_BACKEND=r2`). Give the worker enough memory for
Remotion/Chrome renders (>= 4 GB recommended). Keep `WORKER_CONCURRENCY=1` until you have measured memory per job.
