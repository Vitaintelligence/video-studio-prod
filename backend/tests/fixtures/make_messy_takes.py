"""Generate `messy_takes.mp4` + `messy_takes_truth.json`: a synthetic "messy UGC" clip with KNOWN ground truth.

Windows only (uses the built-in offline SAPI voice). The generated files are committed so the tests run on any OS.

The clip contains, in order:
  line 1 ("serum") : 4 attempts  - complete / flubbed-with-filler / best (extended) / identical repeat
  line 2 ("code")  : 2 attempts  - stumble / clean
  off-script chatter ("okay wait let me start again") between attempts
  long dead-air gaps between everything

    python tests/fixtures/make_messy_takes.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent

# (label, text, gap_before_seconds, sapi_rate)   rate: -10..10
SCRIPT = [
    ("serum_a", "So I have been using this serum for two weeks.", 0.8, 0),
    ("chatter1", "Okay wait, let me start again.", 1.6, 1),
    ("serum_b_flub", "So I have been using this, um, this serum for two.", 1.4, 0),
    ("serum_c_best", "So I have been using this serum for two weeks and my skin looks amazing.", 1.9, -1),
    ("serum_d_repeat", "So I have been using this serum for two weeks and my skin looks amazing.", 1.5, 2),
    ("code_a_stumble", "Use code glow for twen, twenty percent off.", 1.7, 0),
    ("code_b_clean", "Use code glow for twenty percent off today.", 1.3, -1),
]


def speak(text: str, rate: int, out: Path) -> None:
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {rate};"
        f"$s.SetOutputToWaveFile('{out}');"
        f"$s.Speak('{text}');"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("generation needs Windows SAPI; use the committed fixture instead")
    tmp = Path(tempfile.mkdtemp(prefix="messy-"))
    parts: list[Path] = []
    truth = []
    t = 0.0
    for i, (label, text, gap, rate) in enumerate(SCRIPT):
        gap_wav = tmp / f"gap{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(gap), str(gap_wav)], check=True)
        parts.append(gap_wav)
        t += gap
        wav = tmp / f"u{i}.wav"
        speak(text, rate, wav)
        d = duration(wav)
        truth.append({"label": label, "text": text, "start": round(t, 2), "end": round(t + d, 2)})
        parts.append(wav)
        t += d
    tail = tmp / "tail.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "1.2", str(tail)], check=True)
    parts.append(tail)
    t += 1.2

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    audio = tmp / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "22050", "-ac", "1", str(audio)], check=True)
    total = duration(audio)

    font = next((f for f in ("C:/Windows/Fonts/arialbd.ttf",) if Path(f).is_file()), None)
    vf = "format=yuv420p"
    if font:
        shutil.copyfile(font, tmp / "font.ttf")
        vf = r"drawtext=fontfile=font.ttf:text='%{pts\:hms}':fontsize=44:fontcolor=white:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h*0.1,format=yuv420p"
    out = HERE / "messy_takes.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=360x640:rate=24:duration={total:.2f}",
                    "-i", str(audio), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "38",
                    "-c:a", "aac", "-b:a", "48k", "-shortest", "-movflags", "+faststart", str(out)], check=True, cwd=tmp)
    (HERE / "messy_takes_truth.json").write_text(json.dumps({"duration": round(total, 2), "utterances": truth}, indent=2), encoding="utf-8")
    print(out, round(total, 2), "s")


if __name__ == "__main__":
    main()
