# Third-party notices

## OpenMontage (AGPL-3.0)

`backend/openmontage/` is a vendored copy of **OpenMontage** - https://github.com/calesthio/OpenMontage
(commit `08e2151fa02de28a5d6a312b3d575692bf147ad7`), licensed under the **GNU Affero General Public
License v3.0**. Its `LICENSE` and all upstream copyright notices are preserved unmodified.

- The only local change is an added pipeline manifest (see `backend/OPENMONTAGE_UPSTREAM.md`).
- The AGPL applies to OpenMontage and to modified versions of it. **Because this service exposes
  OpenMontage's functionality to users over a network, AGPL section 13 requires that the corresponding
  source of the OpenMontage portion (including any modifications) be offered to those users.** Make sure
  your distribution/compliance plan covers this before shipping. Nothing in this repository relicenses
  OpenMontage source as proprietary; the server code in `backend/server/` is separate and communicates
  with the engine by running it as a subprocess/tool runtime. This note is engineering documentation,
  not legal advice - have counsel confirm the licensing boundary.
- OpenMontage in turn bundles or depends on further components (Remotion, HyperFrames, Piper, etc.)
  under their own licenses. Notably **Remotion has its own license with company-size-based commercial
  terms** - review https://www.remotion.dev/license before commercial use.

## Other important components

| Component | License |
|---|---|
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| SQLAlchemy, Alembic | MIT |
| Celery, kombu | BSD-3-Clause |
| redis-py | MIT |
| psycopg 3 | LGPL-3.0 (dynamically linked, unmodified) |
| boto3 / botocore | Apache-2.0 |
| httpx | BSD-3-Clause |
| structlog | MIT / Apache-2.0 |
| claude-agent-sdk (Anthropic) | Anthropic Commercial Terms of Service |
| FFmpeg | LGPL/GPL depending on build (Debian's `ffmpeg` package is GPL-enabled) |
| Node.js | MIT |
| Chromium headless shell (downloaded by Remotion) | BSD-style and others |

Use of the Claude Agent SDK / Anthropic API is governed by Anthropic's terms and usage policies.
Each generation provider used through OpenMontage (fal.ai, ElevenLabs, OpenAI, Google, ...) has its own terms.
