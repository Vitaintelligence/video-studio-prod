"""Take analysis in its own process (cwd = OpenMontage engine dir), using OpenMontage's `take_analyzer`.

    python -m server.runtime.take_runner < spec.json

Ops
  analyze : media -> word-level transcript (faster-whisper) -> takes / scores + measured silences
  edl     : analysis + (optional, untrusted) decisions -> keep-ranges

No network, no provider keys. Prints one JSON result line; never prints paths outside the work dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from server.runtime.local_edit_runner import EditError, detect_silences


def _analyze(spec: dict) -> dict:
    from tools.analysis.take_analyzer import TakeAnalyzer

    src = Path(spec["source"])
    work = Path(spec["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    tool = TakeAnalyzer()
    res = tool.execute({
        "operation": "analyze", "input_path": str(src), "output_dir": str(work),
        "model_size": spec.get("model", "base"), "language": spec.get("language"),
    })
    if not res.success:
        raise EditError(f"take analysis failed: {res.error}")
    silences = [[round(a, 3), round(b if b != float("inf") else 1e9, 3)] for a, b in detect_silences(src, noise_db=-38, min_len=0.35)]
    return {"ok": True, "analysis_path": res.data["analysis_path"], "summary": res.data["summary"],
            "word_level": res.data["word_level"], "duration": res.data["duration_seconds"],
            "llm_view": res.data["llm_view"], "silences": silences}


def _edl(spec: dict) -> dict:
    from tools.analysis.take_analyzer import TakeAnalyzer

    tool = TakeAnalyzer()
    res = tool.execute({
        "operation": "edl", "analysis_path": spec["analysis_path"], "decisions": spec.get("decisions"),
        "silences": spec.get("silences", []), "remove_fillers": spec.get("remove_fillers", True),
    })
    if not res.success:
        raise EditError(f"edl failed: {res.error}")
    d = res.data
    return {"ok": True, "segments": d["segments"], "stats": d["stats"], "dropped": [
        {k: x[k] for k in ("id", "reason", "start", "end")} for x in d["dropped"]], "problems": d.get("decision_problems", [])}


def main() -> int:
    spec = json.loads(sys.stdin.read())
    try:
        out = _analyze(spec) if spec["op"] == "analyze" else _edl(spec)
    except EditError as exc:
        print(f"take error: {exc}", file=sys.stderr)
        print(json.dumps({"event": "result", "ok": False, "error": "take_analysis_failed"}), flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"take runner exception: {exc!r}", file=sys.stderr)
        print(json.dumps({"event": "result", "ok": False, "error": f"take_runner_exception:{type(exc).__name__}"}), flush=True)
        return 3
    print(json.dumps({"event": "result", **out}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
