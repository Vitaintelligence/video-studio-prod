"""Edit decision engine: LOCAL / DETERMINISTIC FIRST.

Turns a free-text edit instruction into a structured plan. Anything that can be done with
FFmpeg / OpenMontage tools (cut, silence removal, pacing, reframe, hook/CTA text) is a local
operation and never costs generation credits. Only an explicit request for *new pixels*
("generate a shot of ...") becomes a generative request. Creative judgement calls that have no
deterministic implementation ("reorder", "strongest moment") are flagged `needs_agent`.

Rule-based on purpose: predictable, free, unit-testable. The instruction is never executed or
interpolated into a shell - it is only pattern-matched here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SAFE_TEXT = re.compile(r"[^A-Za-z0-9 !?.,'\-:&]")

HOOK_STRATEGIES: dict[str, tuple[str, str | None]] = {
    # strategy -> (label, on-screen hook text). Text is generic on purpose: no invented product claims.
    "problem": ("Problem Hook", "Sound familiar?"),
    "curiosity": ("Curiosity Hook", "Wait for it..."),
    "benefit": ("Benefit Hook", "Here's why it works"),
    "testimonial": ("Testimonial Hook", "Real results, real people"),
    "product_first": ("Product-first Hook", "Meet your new favorite"),
}
DEFAULT_HOOK_STRATEGIES = ["problem", "curiosity", "benefit", "testimonial", "product_first"]
ALLOWED_VARIANT_STRATEGIES = ("hooks",) + tuple(HOOK_STRATEGIES)


def clean_overlay_text(text: str | None, limit: int = 60) -> str | None:
    if not text:
        return None
    cleaned = _SAFE_TEXT.sub("", text).strip()[:limit]
    return cleaned or None


@dataclass
class EditPlan:
    remove_silence: bool = False
    trim_start_seconds: float = 0.0
    target_duration_seconds: float | None = None
    shorten: bool = False  # "shorter"/"tighter" with no explicit target
    speed_opening: bool = False
    speed_all: float = 1.0
    best_takes: bool = False  # transcribe, group repeated takes, keep the best of each
    captions: bool = False
    cta_text: str | None = None
    hook_text: str | None = None
    generative_prompts: list[str] = field(default_factory=list)
    needs_agent: bool = False
    recognized: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def deterministic_only(self) -> bool:
        return not self.needs_agent and not self.generative_prompts

    def to_dict(self) -> dict:
        return {
            "remove_silence": self.remove_silence,
            "trim_start_seconds": self.trim_start_seconds,
            "target_duration_seconds": self.target_duration_seconds,
            "shorten": self.shorten,
            "speed_opening": self.speed_opening,
            "speed_all": self.speed_all,
            "best_takes": self.best_takes,
            "captions": self.captions,
            "cta_text": self.cta_text,
            "hook_text": self.hook_text,
        }


_RE_SILENCE = re.compile(r"\b(pauses?|silence|dead air|awkward|gaps?|filler|ums?|uhs?)\b", re.I)
_RE_TRIM_START = re.compile(r"\b(?:remove|cut|trim|drop|skip)\s+(?:off\s+)?(?:the\s+)?first\s+(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)\b", re.I)
_RE_TARGET = re.compile(r"\b(?:to|under|within|down to|about|around|of)\s+(\d{1,2})\s*(?:s|secs?|seconds?)\b", re.I)
_RE_SHORTER = re.compile(r"\b(shorter|shorten|tighter|tighten|trim it down|cut it down|snappier|leaner)\b", re.I)
_RE_OPENING_FAST = re.compile(
    r"(\b(opening|intro|hook|beginning|start)\b[^.]{0,40}\b(faster|punchier|tighter|snappier|quicker)\b)"
    r"|(\b(faster|punchier|tighter|snappier|quicker)\b[^.]{0,20}\b(opening|intro|hook|beginning|start)\b)", re.I)
_RE_FASTER = re.compile(r"\b(speed up|faster pacing|fast[- ]paced|quicker pacing|tight pacing|tight(?:er)? pacing|keep the pacing tight)\b", re.I)
_RE_TAKES = re.compile(
    r"\b(re-?takes?|best takes?|good takes?|bad takes?|multiple takes|several takes|(?:said|say|says|repeat(?:ed|s)?|did)\s+(?:it|this|the same)?\s*(?:\w+\s+)?times|"
    r"same (?:thing|line|sentence)|repeated|repeat(?:s|ing)?|flubs?|mistakes?|bloopers?|messy|clean(?:ed)?[- ]?up|"
    r"fillers?|ums?|uhs?|stumbl\w*|start(?:ed|s)? over|false starts?|dead air)\b", re.I)
_RE_CAPTIONS = re.compile(r"\b(captions?|subtitles?)\b", re.I)
_RE_CTA = re.compile(r"\b(cta|call[- ]to[- ]action|end card|ending|outro)\b", re.I)
_RE_GENERATE = re.compile(
    r"\b(generate|generated|ai[- ]generated|create a new|synthesi[sz]e)\b[^.]*\b(shot|scene|b-?roll|footage|clip|video)\b", re.I)
_RE_CREATIVE = re.compile(
    r"\b(re-?order|rearrange|swap|after (?:she|he|they) says|when (?:she|he|they) says|put the [^.]{0,40}clip|"
    r"strongest (?:moment|hook)|best moment|highlight)\b", re.I)


def plan_edit(
    instruction: str,
    *,
    duration_target_seconds: int | None = None,
    cta_text: str | None = None,
    hook_text: str | None = None,
) -> EditPlan:
    text = " ".join(instruction.split())
    plan = EditPlan(hook_text=clean_overlay_text(hook_text))

    if _RE_SILENCE.search(text):
        plan.remove_silence = True
        plan.recognized.append("remove_pauses")
    m = _RE_TRIM_START.search(text)
    if m:
        plan.trim_start_seconds = min(float(m.group(1)), 30.0)
        plan.recognized.append("trim_start")
    m = _RE_TARGET.search(text)
    if m and 3 <= int(m.group(1)) <= 90:
        plan.target_duration_seconds = float(m.group(1))
        plan.recognized.append("target_duration")
    if plan.target_duration_seconds is None and duration_target_seconds:
        plan.target_duration_seconds = float(duration_target_seconds)
    if _RE_SHORTER.search(text):
        plan.shorten = True
        plan.recognized.append("shorten")
    if _RE_OPENING_FAST.search(text):
        plan.speed_opening = True
        plan.recognized.append("faster_opening")
    if _RE_FASTER.search(text):
        plan.speed_all = 1.12
        plan.recognized.append("faster_pacing")
    if _RE_TAKES.search(text):
        plan.best_takes = True
        plan.remove_silence = True
        plan.recognized.append("best_takes")
    if _RE_CAPTIONS.search(text):
        plan.captions = True
        plan.recognized.append("captions")
    if _RE_CTA.search(text) or cta_text:
        plan.cta_text = clean_overlay_text(cta_text) or "Learn more"
        plan.recognized.append("cta")

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _RE_GENERATE.search(sentence):
            plan.generative_prompts.append(sentence.strip()[:400])
            plan.reasons.append("generative_request")
    if plan.generative_prompts:
        plan.recognized.append("generate_broll")

    if _RE_CREATIVE.search(text):
        plan.needs_agent = True
        plan.reasons.append("creative_judgement")
    if not plan.recognized:
        plan.needs_agent = True
        plan.reasons.append("no_deterministic_operation_recognized")
    return plan
