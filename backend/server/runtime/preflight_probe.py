"""Run INSIDE the OpenMontage engine directory (cwd) in a subprocess.

Uses the real registry (``discover`` + ``provider_menu_summary``) and prints a
sanitized JSON summary on stdout: counts and capability names only, never
credentials, env values or install instructions.

    python -m server.runtime.preflight_probe   (cwd = openmontage/, PYTHONPATH includes backend/)
"""

from __future__ import annotations

import importlib.util
import json
import sys


def main() -> int:
    out: dict = {"registry_ok": False}
    try:
        from tools.tool_registry import registry

        registry.discover()
        summary = registry.provider_menu_summary()
        caps = {
            c["capability"]: {"configured": int(c["configured"]), "total": int(c["total"])}
            for c in summary.get("capabilities", [])
        }
        runtimes = {k: bool(v) for k, v in summary.get("composition_runtimes", {}).items()}
        out.update(
            registry_ok=True,
            tool_count=len(registry.list_all()),
            capabilities=caps,
            composition_runtimes=runtimes,
            warning_count=len(summary.get("runtime_warnings", [])),
            whisper=importlib.util.find_spec("faster_whisper") is not None,
        )
    except Exception as exc:  # report class only; details go to stderr
        out["error"] = type(exc).__name__
        print(f"preflight probe failed: {exc!r}", file=sys.stderr)
    print(json.dumps(out))
    return 0 if out["registry_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
