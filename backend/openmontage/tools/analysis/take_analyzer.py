"""Take analyzer: find repeated takes in talking-head footage and build a best-take cut.

LOCAL MODIFICATION (not upstream OpenMontage) - see backend/OPENMONTAGE_UPSTREAM.md.

Two operations, designed so an AI agent (or a server-side LLM) makes the *editorial* call and this tool
does the *measurement*:

  analyze  media (or transcript) -> word-level transcript -> utterances -> take groups -> scores
           + a compact `llm_view` the agent can reason over. Nothing is cut yet.
  edl      analysis (+ optional picks) -> keep-ranges on word boundaries, retakes / off-script talk /
           dead air / filler words removed. Feed the ranges to video_trimmer (cut + concat).

Timestamps come only from the transcript, so a decision can only select among ids the tool produced.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from lib.take_selection import analyze_transcript, build_edl, llm_view, validate_picks
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ResumeSupport,
    ToolResult,
    ToolStability,
    ToolStatus,
    ToolTier,
)


def transcribe_words(path: Path, model_size: str, language: str | None) -> dict[str, Any]:
    """faster-whisper with settings that keep repeated phrases (no cross-segment conditioning)."""
    from faster_whisper import WhisperModel

    device, compute_type = "cpu", "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            device, compute_type = "cuda", "float16"
    except Exception:
        pass
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,  # otherwise Whisper tends to collapse repeated lines
        beam_size=5,
    )
    words, segments = [], []
    for seg in segments_iter:
        segments.append({"id": seg.id, "start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()})
        for w in seg.words or []:
            words.append({"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3), "probability": round(w.probability, 3)})
    return {
        "segments": segments,
        "word_timestamps": words,
        "language": language or info.language,
        "duration_seconds": round(info.duration, 3),
        "model_size": model_size,
        "device": device,
    }


class TakeAnalyzer(BaseTool):
    name = "take_analyzer"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []  # transcript input needs nothing; media input needs faster-whisper (checked at run time)
    install_instructions = "pip install faster-whisper   # only needed when analysing media directly"
    agent_skills = ["take-selection"]

    capabilities = ["take_detection", "best_take_selection", "dead_air_removal", "filler_word_removal", "edit_decision_list"]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["analyze", "edl"]},
            "input_path": {"type": "string", "description": "analyze: audio/video file to transcribe"},
            "transcript_path": {"type": "string", "description": "analyze: existing transcriber-format JSON (skips transcription)"},
            "model_size": {"type": "string", "enum": ["tiny", "base", "small", "medium", "large-v2", "large-v3"], "default": "base"},
            "language": {"type": "string"},
            "output_dir": {"type": "string"},
            "analysis_path": {"type": "string", "description": "edl: JSON written by operation=analyze"},
            "decisions": {
                "type": "object",
                "description": "edl: optional {decisions:[{group,keep}], drop_meta:[ids]}. keep must be a take id of that group, or null to drop the group.",
            },
            "keep_meta": {"type": "array", "items": {"type": "string"}, "description": "edl: off-script utterance ids to keep anyway"},
            "lead_seconds": {"type": "number", "default": 0.12},
            "tail_seconds": {"type": "number", "default": 0.18},
            "remove_fillers": {"type": "boolean", "default": True},
            "silences": {"type": "array", "description": "edl: measured silences [[start,end],...] (e.g. ffmpeg silencedetect) used to tighten cut points"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "object"},
            "llm_view": {"type": "object"},
            "analysis_path": {"type": "string"},
            "segments": {"type": "array"},
            "dropped": {"type": "array"},
            "stats": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=2048, vram_mb=0, disk_mb=500, network_required=False)
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["operation", "input_path", "transcript_path", "analysis_path", "decisions"]
    side_effects = ["writes <name>_takes.json / <name>_edl.json to output_dir"]
    fallback = None
    user_visible_verification = [
        "Listen to the chosen take for each repeated line",
        "Confirm no cut lands inside a word",
    ]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    @staticmethod
    def whisper_available() -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 60.0 if inputs.get("operation") == "analyze" and inputs.get("input_path") else 2.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation")
        t0 = time.time()
        try:
            if op == "analyze":
                res = self._analyze(inputs)
            elif op == "edl":
                res = self._edl(inputs)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {op}")
        except FileNotFoundError as exc:
            return ToolResult(success=False, error=f"File not found: {exc.filename}")
        except ImportError:
            return ToolResult(success=False, error="faster-whisper is not installed. Run: pip install faster-whisper")
        res.duration_seconds = round(time.time() - t0, 2)
        return res

    # ------------------------------------------------------------------------------------
    def _analyze(self, inputs: dict[str, Any]) -> ToolResult:
        if inputs.get("transcript_path"):
            src = Path(inputs["transcript_path"])
            transcript = json.loads(src.read_text(encoding="utf-8"))
            stem = src.stem.replace("_transcript", "")
        elif inputs.get("input_path"):
            src = Path(inputs["input_path"])
            if not src.exists():
                return ToolResult(success=False, error=f"Input file not found: {src}")
            transcript = transcribe_words(src, inputs.get("model_size") or os.environ.get("TRANSCRIBE_MODEL", "base"),
                                          inputs.get("language"))
            stem = src.stem
        else:
            return ToolResult(success=False, error="provide input_path or transcript_path")
        out_dir = Path(inputs.get("output_dir") or src.parent)
        out_dir.mkdir(parents=True, exist_ok=True)

        analysis = analyze_transcript(transcript)
        path = out_dir / f"{stem}_takes.json"
        path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        return ToolResult(
            success=True,
            data={"summary": analysis["summary"], "duration_seconds": analysis["duration"], "word_level": analysis["word_level"],
                  "analysis_path": str(path), "llm_view": llm_view(analysis)},
            artifacts=[str(path)],
        )

    def _edl(self, inputs: dict[str, Any]) -> ToolResult:
        ap = Path(inputs["analysis_path"])
        analysis = json.loads(ap.read_text(encoding="utf-8"))
        picks, drop_meta, problems = ({}, [], [])
        if inputs.get("decisions") is not None:
            picks, drop_meta, problems = validate_picks(analysis, inputs["decisions"])
        keep_meta = [i for i in inputs.get("keep_meta", []) if i in analysis["meta_ids"]]
        edl = build_edl(
            analysis, picks, keep_meta=keep_meta,
            lead=float(inputs.get("lead_seconds", 0.12)), tail=float(inputs.get("tail_seconds", 0.18)),
            remove_fillers=bool(inputs.get("remove_fillers", True)),
            silences=[(float(a), float(b)) for a, b in inputs.get("silences", [])],
        )
        edl["decision_problems"] = problems
        out = Path(inputs.get("output_dir") or ap.parent) / f"{ap.stem.replace('_takes', '')}_edl.json"
        out.write_text(json.dumps(edl, indent=2), encoding="utf-8")
        return ToolResult(success=True, data={**edl, "edl_path": str(out)}, artifacts=[str(out)])
