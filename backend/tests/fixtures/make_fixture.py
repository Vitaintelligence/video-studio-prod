"""Generate the synthetic UGC-style test clip (no copyrighted content).

720x1280, 8 s, H.264 + AAC. Video is a moving test pattern with a running timestamp. Audio is a tone
with a deliberate 1.5 s silent gap (2.0-3.5 s) so silence removal has something real to remove.

    python tests/fixtures/make_fixture.py [output.mp4]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FONTS = ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def make(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    font = next((f for f in FONTS if Path(f).is_file()), None)
    vf = "format=yuv420p"
    cwd = out.parent
    if font:
        shutil.copyfile(font, cwd / "_font.ttf")
        vf = (r"drawtext=fontfile=_font.ttf:text='%{pts\:hms}':fontsize=96:fontcolor=white:box=1:boxcolor=black@0.5:"
              "x=(w-text_w)/2:y=h*0.15,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=8",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
           "-vf", vf, "-af", "volume=enable='between(t,2,3.5)':volume=0",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "34", "-c:a", "aac", "-shortest", "-movflags", "+faststart", out.name]
    subprocess.run(cmd, check=True, cwd=cwd)
    (cwd / "_font.ttf").unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("test_ugc.mp4")
    print(make(target))
