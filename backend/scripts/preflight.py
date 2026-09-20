#!/usr/bin/env python
"""Sanitized environment preflight. Prints booleans/counts only, never secrets.

    python scripts/preflight.py            # human-readable
    python scripts/preflight.py --json     # machine-readable
Exit code 0 when DB + Redis + registry are healthy.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from sqlalchemy import text

    from server.core.config import get_settings
    from server.db.session import get_engine
    from server.services.capabilities import normalize, run_probe
    from server.services.pipelines import enabled_pipelines
    from server.services.ratelimit import get_redis
    from server.services.storage import get_storage

    s = get_settings()
    report: dict = {
        "app_env": s.app_env,
        "orchestrator_provider": s.orchestrator_provider,
        "anthropic_key_configured": bool(s.anthropic_api_key),
        "max_job_budget_usd": s.max_job_budget_usd,
        "binaries": {b: bool(shutil.which(b)) for b in ("ffmpeg", "ffprobe", "node", "npm")},
    }
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        report["database"] = "ok"
    except Exception as exc:
        report["database"] = f"unavailable ({type(exc).__name__})"
    try:
        get_redis().ping()
        report["redis"] = "ok"
    except Exception as exc:
        report["redis"] = f"unavailable ({type(exc).__name__})"
    try:
        st = get_storage()
        report["storage"] = {"backend": st.backend, "healthy": st.healthcheck(), "presigned_uploads": st.supports_presign}
    except Exception as exc:
        report["storage"] = {"backend": s.storage_backend, "healthy": False, "error": type(exc).__name__}

    raw = run_probe(s)
    report["openmontage"] = {
        "registry_ok": raw.get("registry_ok", False),
        "tool_count": raw.get("tool_count"),
        "composition_runtimes": raw.get("composition_runtimes"),
        "capability_categories": {k: f"{v['configured']}/{v['total']}" for k, v in raw.get("capabilities", {}).items()},
    }
    doc = normalize(raw, s)
    report["enabled_pipelines"] = enabled_pipelines()
    report["default_pipeline"] = s.openmontage_pipeline
    report["generation_available"] = doc["generation_available"]
    report["features"] = doc["features"]

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print("== Preflight ==")
        for k, v in report.items():
            if isinstance(v, dict):
                print(f"{k}:")
                for kk, vv in v.items():
                    print(f"  {kk}: {vv}")
            else:
                print(f"{k}: {v}")
    ok = report["database"] == "ok" and report["redis"] == "ok" and report["openmontage"]["registry_ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
