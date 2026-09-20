"""Best-take selection for talking-head / UGC footage.

LOCAL MODIFICATION (not upstream OpenMontage) - see backend/OPENMONTAGE_UPSTREAM.md.

Pipeline (all deterministic, stdlib only, no network):

    word-level transcript
      -> utterances            (split on pauses / sentence ends)
      -> off-script chatter    ("wait, let me start again")
      -> take groups           (the same line said several times, incl. half-said flubs)
      -> per-take scores       (completeness, fluency, ASR confidence, pacing)
      -> recommended pick per group
      -> edit decision list    (keep ranges on word boundaries, dead air and fillers removed)

An LLM may *override* which take wins in a group (`picks`), but it can only choose among take ids
that this module produced - it can never invent timestamps. That keeps model output verifiable.

The transcript shape is the one OpenMontage's `transcriber` tool writes:
    {"word_timestamps": [{"word","start","end","probability"}...], "segments": [...], "duration_seconds": float}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

FILLERS = frozenset({"um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm", "mm", "mmm"})

_META_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\bstart (?:again|over)\b",
        r"\b(?:one|once) more(?: time)?\b",
        r"\blet me (?:try|redo|start|do|say)\b",
        r"\blet'?s (?:go|try|do) (?:again|it again)\b",
        r"\btake (?:one|two|three|four|five|\d+)\b",
        r"\bfrom the top\b",
        r"\bhold on\b",
        r"\bwait\b",
        r"\bsorry\b",
        r"\bnope\b",
        r"\bcut\b",
        r"\bhow was that\b",
        r"\bdid (?:i|that)\b",
        r"\bmy bad\b",
        r"\bagain\b",
    )
]

_NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
    "hundred": "100",
}


# ---------------------------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------------------------
def normalize_token(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("%", " percent ")
    t = re.sub(r"[^a-z0-9' ]+", " ", t).strip()
    t = " ".join(t.split())
    return _NUM_WORDS.get(t, t)


def tokens_of(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.replace("%", " percent ").split():
        tok = normalize_token(raw)
        out.extend(tok.split() if " " in tok else ([tok] if tok else []))
    return [_NUM_WORDS.get(t, t) for t in out]


@dataclass
class Word:
    i: int
    text: str
    start: float
    end: float
    prob: float

    @property
    def token(self) -> str:
        return normalize_token(self.text)


def words_from_transcript(transcript: dict[str, Any]) -> tuple[list[Word], bool]:
    """Returns (words, word_level). Falls back to evenly spread segment text when timestamps per word are absent."""
    raw = transcript.get("word_timestamps") or []
    if not raw:
        for seg in transcript.get("segments", []):
            raw.extend(seg.get("words") or [])
    words: list[Word] = []
    if raw:
        for i, w in enumerate(sorted(raw, key=lambda x: (float(x["start"]), float(x["end"])))):
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            words.append(Word(len(words), text, float(w["start"]), max(float(w["end"]), float(w["start"]) + 0.01),
                              float(w.get("probability", 1.0))))
        _clamp_stretched_words(words)
        return words, True
    for seg in transcript.get("segments", []):
        toks = str(seg.get("text", "")).split()
        if not toks:
            continue
        s, e = float(seg["start"]), float(seg["end"])
        step = (e - s) / len(toks)
        for k, t in enumerate(toks):
            words.append(Word(len(words), t, s + k * step, s + (k + 1) * step, 0.8))
    return words, False


def _clamp_stretched_words(words: list[Word]) -> None:
    """Whisper sometimes stretches a short word across neighbouring silence ("so" lasting 1 s). Shrink such a
    word toward the side that borders the silence so cuts and pause detection use plausible timings."""
    for i, w in enumerate(words):
        max_dur = 0.30 + 0.10 * len(w.token)
        if w.end - w.start <= max_dur:
            continue
        gap_before = w.start - (words[i - 1].end if i else 0.0)
        if gap_before >= 0.3 or i == 0:
            w.start = w.end - max_dur  # speech is at the end of a word that follows a pause
        else:
            w.end = w.start + max_dur


# ---------------------------------------------------------------------------------------------
# utterances
# ---------------------------------------------------------------------------------------------
@dataclass
class Utterance:
    id: str
    w0: int  # first word index (inclusive)
    w1: int  # last word index (inclusive)
    start: float
    end: float
    text: str
    tokens: list[str]
    meta: bool = False
    unclear: bool = False
    group: str | None = None
    scores: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    fillers: int = 0
    repeats: int = 0
    internal_pauses: int = 0
    low_conf: int = 0
    hesitations: int = 0

    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id, "start": round(self.start, 3), "end": round(self.end, 3), "text": self.text,
            "words": [self.w0, self.w1], "meta": self.meta, "unclear": self.unclear, "group": self.group,
            "score": round(self.score, 4), "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "fillers": self.fillers, "repeats": self.repeats, "internal_pauses": self.internal_pauses,
            "low_conf": self.low_conf, "hesitations": self.hesitations,
        }


def split_utterances(words: list[Word], pause_split: float = 0.6, sentence_gap: float = 0.3) -> list[Utterance]:
    if not words:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    for k in range(1, len(words)):
        gap = words[k].start - words[k - 1].end
        ends_sentence = bool(re.search(r"[.!?]$", words[k - 1].text))
        if gap >= pause_split or (ends_sentence and gap >= sentence_gap):
            spans.append((start, k - 1))
            start = k
    spans.append((start, len(words) - 1))
    utts: list[Utterance] = []
    for n, (a, b) in enumerate(spans, start=1):
        text = " ".join(w.text for w in words[a:b + 1]).strip()
        utts.append(Utterance(f"u{n}", a, b, words[a].start, words[b].end, text, tokens_of(text)))
    return utts


# ---------------------------------------------------------------------------------------------
# similarity / grouping
# ---------------------------------------------------------------------------------------------
def _content(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in FILLERS]


def similarity(a: list[str], b: list[str]) -> float:
    a, b = _content(a), _content(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _lead(a: list[str], b: list[str]) -> int:
    a, b = _content(a), _content(b)
    n = 0
    for x, y in zip(a, b):
        if x == y or (len(x) > 3 and len(y) > 3 and SequenceMatcher(None, x, y).ratio() >= 0.8):
            n += 1
        else:
            break
    return n


def same_line(a: list[str], b: list[str]) -> bool:
    ca, cb = _content(a), _content(b)
    if len(ca) < 2 or len(cb) < 2:
        return False
    ratio = similarity(a, b)
    if ratio >= 0.62:
        return True
    if _lead(a, b) >= 3 and ratio >= 0.4:  # re-said the opening, then diverged (a flub)
        return True
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    m = SequenceMatcher(None, shorter, longer, autojunk=False).find_longest_match(0, len(shorter), 0, len(longer))
    return len(shorter) >= 4 and m.size / len(shorter) >= 0.7  # one is contained in the other


def is_meta_talk(u: Utterance) -> bool:
    return len(_content(u.tokens)) <= 9 and any(p.search(u.text) for p in _META_PATTERNS)


# ---------------------------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------------------------
def _fluency_features(u: Utterance, words: list[Word], internal_pause_max: float) -> None:
    ws = words[u.w0:u.w1 + 1]
    u.fillers = sum(1 for w in ws if w.token in FILLERS)
    toks = [w.token for w in ws if w.token and w.token not in FILLERS]
    repeats = 0
    for i, t in enumerate(toks):
        if len(t) < 3:
            continue
        for j in range(i + 1, min(i + 4, len(toks))):
            if toks[j] == t:
                repeats += 1
                break
    u.repeats = repeats
    u.internal_pauses = sum(1 for a, b in zip(ws, ws[1:]) if b.start - a.end > internal_pause_max)
    # a garbled word (very low ASR confidence) is usually a half-said word or a mispronunciation
    u.low_conf = sum(1 for w in ws if w.prob < 0.55 and w.token not in FILLERS)
    # "twen, twenty": a short, shaky word closed by a comma is a self-correction
    u.hesitations = sum(1 for w in ws[:-1] if w.text.rstrip().endswith(",") and w.prob < 0.7 and len(w.token) <= 6)


def _score_group(members: list[Utterance], words: list[Word]) -> None:
    longest = max(members, key=lambda m: len(_content(m.tokens)))
    ref = _content(longest.tokens)
    for rank, m in enumerate(members):
        mine = _content(m.tokens)
        matched = sum(b.size for b in SequenceMatcher(None, ref, mine, autojunk=False).get_matching_blocks()) if ref else 0
        completeness = matched / len(ref) if ref else 0.0
        fluency = max(0.0, 1.0 - min(1.0, 0.25 * m.fillers + 0.3 * m.repeats + 0.15 * m.internal_pauses
                                       + 0.25 * m.low_conf + 0.2 * m.hesitations))
        probs = [w.prob for w in words[m.w0:m.w1 + 1]]
        mean_p = sum(probs) / len(probs) if probs else 0.0
        blended = 0.6 * mean_p + 0.4 * (min(probs) if probs else 0.0)  # one garbled word should hurt
        confidence = max(0.0, min(1.0, (blended - 0.5) / 0.5))
        dur = max(m.end - m.start, 0.1)
        wps = len(mine) / dur
        if 2.0 <= wps <= 3.8:
            pacing = 1.0
        elif wps < 2.0:
            pacing = max(0.0, (wps - 1.0) / 1.0)
        else:
            pacing = max(0.0, (5.2 - wps) / 1.4)
        recency = 0.02 * (rank / max(len(members) - 1, 1))  # people tend to improve: tie-break toward later takes
        m.scores = {"completeness": completeness, "fluency": fluency, "confidence": confidence, "pacing": pacing}
        m.score = 0.42 * completeness + 0.24 * fluency + 0.20 * confidence + 0.08 * pacing + recency


def _reasons(best: Utterance, others: list[Utterance]) -> list[str]:
    out: list[str] = []
    if all(best.scores["completeness"] >= o.scores["completeness"] for o in others):
        out.append("most_complete")
    if best.fillers == 0 and any(o.fillers for o in others):
        out.append("no_filler_words")
    if best.repeats + best.hesitations + best.low_conf == 0 and any(o.repeats + o.hesitations + o.low_conf for o in others):
        out.append("no_stumbles")
    if all(best.scores["confidence"] >= o.scores["confidence"] for o in others):
        out.append("clearest_speech")
    return out or ["highest_overall_score"]


# ---------------------------------------------------------------------------------------------
# public: analysis
# ---------------------------------------------------------------------------------------------
def analyze_transcript(
    transcript: dict[str, Any],
    *,
    pause_split: float = 0.6,
    internal_pause_max: float = 0.6,
    lookback_groups: int = 4,
    max_group_gap_seconds: float = 90.0,
) -> dict[str, Any]:
    words, word_level = words_from_transcript(transcript)
    utts = split_utterances(words, pause_split=pause_split)
    for u in utts:
        _fluency_features(u, words, internal_pause_max)
        u.meta = is_meta_talk(u)

    groups: list[list[Utterance]] = []
    for u in utts:
        if u.meta:
            continue
        joined = None
        for g in reversed(groups[-lookback_groups:]):
            if u.start - g[-1].end > max_group_gap_seconds:
                continue
            if any(same_line(u.tokens, m.tokens) for m in g):
                joined = g
                break
        if joined is None:
            groups.append([u])
        else:
            joined.append(u)

    group_dicts: list[dict[str, Any]] = []
    for gi, g in enumerate(groups, start=1):
        gid = f"g{gi}"
        for m in g:
            m.group = gid
        _score_group(g, words)
        best = max(g, key=lambda m: m.score)
        if len(g) == 1:
            m = g[0]
            n = len(_content(m.tokens))
            if n < 2 or m.scores["confidence"] < 0.15:
                m.unclear = True
        others = [m for m in g if m is not best]
        group_dicts.append({
            "id": gid, "take_ids": [m.id for m in g], "recommended": best.id if not best.unclear else None,
            "reasons": _reasons(best, others) if others else (["only_take"] if not best.unclear else ["unclear_speech"]),
            "order": gi,
        })

    for u in utts:
        if u.meta and u.group is None:
            u.scores = {}
    dur = float(transcript.get("duration_seconds") or (words[-1].end if words else 0.0))
    return {
        "version": 1,
        "language": transcript.get("language"),
        "duration": round(dur, 3),
        "word_level": word_level,
        "words": [{"i": w.i, "text": w.text, "start": round(w.start, 3), "end": round(w.end, 3), "prob": round(w.prob, 3)} for w in words],
        "utterances": [u.brief() for u in utts],
        "groups": group_dicts,
        "meta_ids": [u.id for u in utts if u.meta],
        "summary": {
            "utterances": len(utts), "groups": len(groups),
            "repeated_lines": sum(1 for g in groups if len(g) > 1),
            "retakes": sum(len(g) - 1 for g in groups),
            "meta_talk": sum(1 for u in utts if u.meta),
        },
    }


def llm_view(analysis: dict[str, Any], max_words: int = 6000) -> dict[str, Any]:
    """Compact, model-safe view: ids, times, text and scores only (never raw file paths)."""
    utt = {u["id"]: u for u in analysis["utterances"]}
    out_groups = []
    budget = max_words
    for g in analysis["groups"]:
        takes = []
        for tid in g["take_ids"]:
            u = utt[tid]
            budget -= len(u["text"].split())
            takes.append({"id": tid, "start": u["start"], "end": u["end"], "text": u["text"], "score": u["score"],
                          "fillers": u["fillers"], "stumbles": u["repeats"], "completeness": u["scores"].get("completeness")})
        out_groups.append({"group": g["id"], "recommended": g["recommended"], "takes": takes})
        if budget <= 0:
            break
    meta = [{"id": i, "text": utt[i]["text"]} for i in analysis["meta_ids"]]
    return {"duration": analysis["duration"], "groups": out_groups, "off_script_candidates": meta}


def validate_picks(analysis: dict[str, Any], decisions: Any) -> tuple[dict[str, str | None], list[str], list[str]]:
    """Validate untrusted (LLM) decisions. Returns (picks, drop_ids, problems). Unknown ids are ignored."""
    problems: list[str] = []
    picks: dict[str, str | None] = {}
    drop: list[str] = []
    groups = {g["id"]: g for g in analysis["groups"]}
    meta = set(analysis["meta_ids"])
    if not isinstance(decisions, dict):
        return {}, [], ["decisions is not an object"]
    for d in decisions.get("decisions", []) if isinstance(decisions.get("decisions"), list) else []:
        if not isinstance(d, dict):
            continue
        gid, keep = d.get("group"), d.get("keep")
        if gid not in groups:
            problems.append(f"unknown group {gid!r}")
            continue
        if keep is None or keep == "none":
            picks[gid] = None
        elif keep in groups[gid]["take_ids"]:
            picks[gid] = keep
        else:
            problems.append(f"take {keep!r} is not in {gid}")
    for i in decisions.get("drop_meta", []) if isinstance(decisions.get("drop_meta"), list) else []:
        if isinstance(i, str) and i in meta:
            drop.append(i)
        else:
            problems.append(f"unknown meta id {i!r}")
    return picks, drop, problems


# ---------------------------------------------------------------------------------------------
# public: edit decision list
# ---------------------------------------------------------------------------------------------
def resolve_keep(analysis: dict[str, Any], picks: dict[str, str | None] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    """Which utterance ids survive (in script order) and why the rest were dropped."""
    picks = picks or {}
    utt = {u["id"]: u for u in analysis["utterances"]}
    keep: list[str] = []
    dropped: list[dict[str, Any]] = []
    for g in analysis["groups"]:
        chosen = picks[g["id"]] if g["id"] in picks else g["recommended"]
        for tid in g["take_ids"]:
            if tid == chosen:
                keep.append(tid)
            else:
                dropped.append({"id": tid, "reason": "unclear_speech" if utt[tid]["unclear"] else "retake_superseded",
                                "start": utt[tid]["start"], "end": utt[tid]["end"], "text": utt[tid]["text"]})
    for mid in analysis["meta_ids"]:
        dropped.append({"id": mid, "reason": "off_script", "start": utt[mid]["start"], "end": utt[mid]["end"], "text": utt[mid]["text"]})
    return keep, dropped


def _snap_to_silence(start: float, end: float, silences: list[tuple[float, float]], lead: float, tail: float) -> tuple[float, float]:
    """ASR word times can include leading/trailing silence. If a boundary sits inside a measured silence,
    pull it in so the cut starts (ends) just before (after) the actual sound."""
    for a, b in silences:
        if a <= start < b:
            start = max(start, min(b - lead, end - 0.05))
        if a < end <= b:
            end = min(end, max(a + tail, start + 0.05))
    return start, end


def build_edl(
    analysis: dict[str, Any],
    picks: dict[str, str | None] | None = None,
    *,
    keep_meta: list[str] | None = None,
    lead: float = 0.12,
    tail: float = 0.18,
    internal_pause_max: float = 0.6,
    remove_fillers: bool = True,
    min_segment: float = 0.2,
    silences: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Turn a decision into keep-ranges on word boundaries.

    * dead air between takes and long pauses inside a take are cut (a natural ~0.3 s beat remains)
    * isolated filler words (um/uh) are cut out of the kept takes
    * ranges never extend into a neighbouring word, so a dropped take never leaks into the cut
    """
    words = analysis["words"]
    utt = {u["id"]: u for u in analysis["utterances"]}
    keep_ids, dropped = resolve_keep(analysis, picks)
    if keep_meta:
        keep_ids += [i for i in keep_meta if i not in keep_ids]
        dropped = [d for d in dropped if d["id"] not in keep_meta]
    n = len(words)

    def prev_end(i: int) -> float:
        return words[i - 1]["end"] if i > 0 else 0.0

    def next_start(i: int) -> float:
        return words[i + 1]["start"] if i + 1 < n else float(analysis["duration"])

    segments: list[dict[str, Any]] = []
    for uid in keep_ids:
        u = utt[uid]
        i0, i1 = u["words"]
        idxs = list(range(i0, i1 + 1))
        if remove_fillers:
            idxs = [i for i in idxs if normalize_token(words[i]["text"]) not in FILLERS]
        if not idxs:
            continue
        # split the take wherever there is a long pause (or a removed filler) between remaining words
        runs: list[list[int]] = [[idxs[0]]]
        for a, b in zip(idxs, idxs[1:]):
            gap = words[b]["start"] - words[a]["end"]
            if b != a + 1 or gap > internal_pause_max:
                runs.append([b])
            else:
                runs[-1].append(b)
        for r in runs:
            a, b = r[0], r[-1]
            # pad for a natural breath, but never into a neighbouring word (or a removed take)
            start = min(words[a]["start"], max(words[a]["start"] - lead, prev_end(a) + 0.02))
            end = max(words[b]["end"], min(words[b]["end"] + tail, next_start(b) - 0.02))
            start, end = _snap_to_silence(start, end, silences or [], lead, tail)
            if end - start >= min_segment:
                segments.append({"start": round(start, 3), "end": round(end, 3), "take": uid, "group": u["group"],
                                 "text": " ".join(words[i]["text"] for i in r)})
    # segments stay in script (group) order, which is normally also source order
    merged: list[dict[str, Any]] = []
    for s in segments:
        if merged and merged[-1]["take"] == s["take"] and s["start"] - merged[-1]["end"] < 0.05:
            merged[-1]["end"] = s["end"]
            merged[-1]["text"] += " " + s["text"]
        else:
            merged.append(dict(s))
    out_len = sum(s["end"] - s["start"] for s in merged)
    src = float(analysis["duration"]) or (words[-1]["end"] if words else 0.0)
    return {
        "version": 1,
        "segments": merged,
        "dropped": dropped,
        "stats": {
            "source_seconds": round(src, 2), "output_seconds": round(out_len, 2),
            "removed_seconds": round(max(src - out_len, 0.0), 2),
            "kept_takes": len(keep_ids), "dropped_takes": sum(1 for d in dropped if d["reason"] != "off_script"),
            "off_script_removed": sum(1 for d in dropped if d["reason"] == "off_script"),
        },
    }
