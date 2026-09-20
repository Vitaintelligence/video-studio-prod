#!/usr/bin/env python
"""API smoke test against a running stack (local or deployed).

Hits /health and /ready, authenticates, reads capabilities, submits a generation,
and polls it to a terminal state. Intended for a worker running with
ORCHESTRATOR_PROVIDER=mock (zero cost). With a real runtime it would spend money,
so it refuses unless ALLOW_PAID_SMOKE_TEST=true (use smoke_generation.py for that).

    DEV_API_TOKEN=... python scripts/smoke_api.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--no-generate", action="store_true", help="only check health/auth/capabilities")
    ap.add_argument("--mock-worker", action="store_true", default=os.environ.get("SMOKE_MOCK_WORKER") == "true",
                    help="assert the worker runs the zero-cost mock runtime (required to submit a generation)")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    token = os.environ.get("DEV_API_TOKEN", "")
    auth = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=base, timeout=30) as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}, f"/health -> {r.status_code}"
        print("GET /health            ok")
        r = c.get("/ready")
        print(f"GET /ready             {r.status_code} {r.json().get('checks')}")
        assert r.status_code == 200, "not ready"
        assert c.get("/v1/capabilities").status_code == 401
        print("unauthenticated /v1    401 (as expected)")
        r = c.get("/v1/capabilities", headers=auth)
        assert r.status_code == 200, f"/v1/capabilities -> {r.status_code} (is DEV_API_TOKEN set?)"
        caps = r.json()
        print(f"GET /v1/capabilities   generation_available={caps['generation_available']} features={caps['features']}")
        if args.no_generate:
            return 0

        if not (args.mock_worker or os.environ.get("ALLOW_PAID_SMOKE_TEST") == "true"):
            print("Refusing to submit a generation: pass --mock-worker (worker uses the zero-cost mock runtime) "
                  "or set ALLOW_PAID_SMOKE_TEST=true.")
            return 2

        body = {"prompt": "A short smoke-test video about a lighthouse in a storm.", "duration_seconds": 15,
                "aspect_ratio": "9:16", "pipeline": "app-cinematic", "voice_enabled": True,
                "captions_enabled": True, "quality": "standard"}
        key = f"smoke-{uuid.uuid4()}"
        t0 = time.monotonic()
        r = c.post("/v1/generations", json=body, headers={**auth, "Idempotency-Key": key})
        assert r.status_code == 202, f"POST /v1/generations -> {r.status_code} {r.text}"
        created_ms = int((time.monotonic() - t0) * 1000)
        gid = r.json()["id"]
        print(f"POST /v1/generations   202 in {created_ms} ms id={gid}")
        again = c.post("/v1/generations", json=body, headers={**auth, "Idempotency-Key": key})
        assert again.json()["id"] == gid, "idempotency replay returned a different generation"
        print("idempotent replay      same id")

        deadline = time.monotonic() + args.timeout
        last = None
        while time.monotonic() < deadline:
            st = c.get(f"/v1/generations/{gid}", headers=auth).json()
            snapshot = (st["status"], st["progress"], st["display_stage"])
            if snapshot != last:
                print(f"  status={st['status']:<16} progress={st['progress']:>3}  stage={st['display_stage']}")
                last = snapshot
            if st["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(1.5)
        else:
            print("timed out waiting for a terminal state")
            return 1
        if st["status"] != "completed":
            print(f"generation ended as {st['status']}: {st.get('error')}")
            return 1
        print(f"completed: output_url={st['output_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
