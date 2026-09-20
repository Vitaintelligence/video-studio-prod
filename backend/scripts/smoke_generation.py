#!/usr/bin/env python
"""REAL, provider-backed generation smoke test. SPENDS MONEY.

Refuses to run unless ALLOW_PAID_SMOKE_TEST=true. (OpenMontage has a zero-key demo path,
`make demo`, but it renders fixed Remotion demos rather than exercising the agent runtime
or the API, so it is not a substitute for this test.)

    ALLOW_PAID_SMOKE_TEST=true DEV_API_TOKEN=... python scripts/smoke_generation.py --base-url https://<api>
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import httpx


def main() -> int:
    if os.environ.get("ALLOW_PAID_SMOKE_TEST", "").lower() != "true":
        print("SKIPPED: set ALLOW_PAID_SMOKE_TEST=true to run a real (paid) generation. Nothing was submitted.")
        return 0

    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--timeout", type=int, default=2700)
    args = ap.parse_args()
    auth = {"Authorization": f"Bearer {os.environ['DEV_API_TOKEN']}"}
    body = {"prompt": "A 15 second cinematic teaser: a lone lighthouse keeper watches a storm roll in at dusk.",
            "duration_seconds": 15, "aspect_ratio": "9:16", "pipeline": "app-cinematic",
            "voice_enabled": True, "captions_enabled": True, "quality": "standard"}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30, headers=auth) as c:
        caps = c.get("/v1/capabilities").json()
        if not caps["generation_available"]:
            print(f"generation is not available on this deployment: {caps}")
            return 1
        r = c.post("/v1/generations", json=body, headers={"Idempotency-Key": f"paid-smoke-{uuid.uuid4()}"})
        assert r.status_code == 202, r.text
        gid = r.json()["id"]
        print(f"submitted {gid}")
        deadline, last = time.monotonic() + args.timeout, None
        while time.monotonic() < deadline:
            st = c.get(f"/v1/generations/{gid}").json()
            snap = (st["status"], st["progress"], st["display_stage"])
            if snap != last:
                print(f"  {st['status']:<16} {st['progress']:>3}% {st['display_stage']}")
                last = snap
            if st["status"] in ("completed", "failed", "cancelled"):
                print(st.get("output_url") or st.get("error"))
                return 0 if st["status"] == "completed" else 1
            time.sleep(5)
    print("timed out")
    return 1


if __name__ == "__main__":
    sys.exit(main())
