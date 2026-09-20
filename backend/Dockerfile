# syntax=docker/dockerfile:1.7
#
# ONE image for both the API and the worker. The service is chosen by the start
# command (./scripts/start-api.sh | ./scripts/start-worker.sh) - see README.
#
# Build context: this directory (backend/).

FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies:
#  - python3/venv (OpenMontage + server), ffmpeg/ffprobe (composition, validation)
#  - Chromium runtime libs + fonts (Remotion renders through headless Chrome)
#  - tini (PID 1: forwards SIGTERM for graceful worker shutdown, reaps ffmpeg/chrome children)
#  - deliberately NO curl/wget/git/ssh: the headless agent has no need for them
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates tini \
        python3 python3-venv python3-pip \
        ffmpeg \
        libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 libxrandr2 libxkbcommon0 \
        libxfixes3 libxcomposite1 libxdamage1 libpango-1.0-0 libcairo2 libcups2 libxshmfence1 libglib2.0-0 \
        fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. HOME is writable (Claude CLI state, npm cache, piper models).
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app

# ---- Python environment (cached until requirements change) -------------------------------
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" VIRTUAL_ENV=/opt/venv

WORKDIR /app
COPY openmontage/requirements.txt /tmp/req/openmontage-requirements.txt
COPY requirements-server.txt /tmp/req/requirements-server.txt
# Upstream requirements first (untouched), then the server pins, in one resolution
# so pip reports any incompatibility at build time.
RUN pip install -r /tmp/req/openmontage-requirements.txt -r /tmp/req/requirements-server.txt \
    && (pip install piper-tts || echo "piper-tts unavailable: offline TTS disabled (cloud TTS still works)")

# ---- Remotion (cached until the lockfile changes) ---------------------------------------
WORKDIR /app/openmontage/remotion-composer
COPY openmontage/remotion-composer/package.json openmontage/remotion-composer/package-lock.json ./
RUN npm ci --no-audit --no-fund
# Upstream's lockfile omits the "libc" field on Remotion's platform packages, so on Debian (glibc)
# `npm ci` installs only the *musl* compositor and Remotion cannot start. Install the matching glibc
# build explicitly (same version as remotion), without touching the upstream lockfile.
RUN V="$(node -p "require('remotion/package.json').version")" \
    && case "$(dpkg --print-architecture)" in amd64) A=x64;; arm64) A=arm64;; *) echo "unsupported arch" >&2; exit 1;; esac \
    && npm install --no-save --no-audit --no-fund "@remotion/compositor-linux-${A}-gnu@${V}" \
    && ls node_modules/@remotion | grep compositor

# ---- Application source -----------------------------------------------------------------
WORKDIR /app
COPY . /app
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod 0755 /app/scripts/*.sh

# Pre-download the headless Chrome Remotion renders with, so first render needs no network.
WORKDIR /app/openmontage/remotion-composer
RUN npx remotion browser ensure

# ---- Permissions: source read-only, only job/output dirs writable ------------------------
# Everything under /app stays root-owned (app can read/execute, not modify). The engine
# also needs a handful of scratch locations, which are the ONLY writable paths:
RUN mkdir -p /workspace/storage /workspace/agent-logs /app/openmontage/projects \
        /app/openmontage/remotion-composer/out /app/openmontage/remotion-composer/public \
        /app/openmontage/remotion-composer/node_modules/.cache \
    && chown -R app:app /workspace /app/openmontage/projects /app/openmontage/remotion-composer/out \
        /app/openmontage/remotion-composer/public /app/openmontage/remotion-composer/node_modules/.cache \
    && chmod -R a-w /app/server /app/scripts /app/migrations /app/openmontage/tools /app/openmontage/lib \
        /app/openmontage/skills /app/openmontage/pipeline_defs /app/openmontage/schemas /app/openmontage/pipeline_defs \
    && find /app -maxdepth 1 -type f -exec chmod a-w {} +

ENV PYTHONPATH=/app:/app/openmontage \
    HOME=/home/app \
    STORAGE_BACKEND=local \
    LOCAL_STORAGE_PATH=/workspace/storage \
    AGENT_TRANSCRIPT_DIR=/workspace/agent-logs \
    WORKER_CONCURRENCY=1

USER app

# Warm the HyperFrames npx cache exactly as upstream's Makefile does (best effort).
RUN npx --yes hyperframes --version >/dev/null 2>&1 || echo "hyperframes cache-warm skipped"

WORKDIR /app
EXPOSE 8000
# -g: forward SIGTERM to the whole process group so the Celery pool child (which owns the running job)
# sees it and can stop the agent + re-queue the job; the agent runner has its own session and is killed explicitly.
ENTRYPOINT ["tini", "-g", "--"]
CMD ["./scripts/start.sh"]
