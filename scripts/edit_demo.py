"""Edit the raw demo recording into the final video.

    python scripts/edit_demo.py
    -> docs/demo/Zensar_Content_Studio_Demo.mp4

Reads docs/demo/scenes.json (written by record_demo.py). Normal scenes are kept as recorded;
"fast" scenes (waiting for a conversion to finish) are sped up to a few seconds, and result
screens are held a little longer so they can be read.

The recorder's clock and the video's timeline drift apart while the computer is busy (image
generation), so scenes after the last waiting scene are aligned to the end of the video.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo"
OUT = DEMO / "Zensar_Content_Studio_Demo.mp4"
FAST_SECONDS = {"brand-wait": 24.0}  # length of a sped-up waiting scene (default 6 s)
HOLD = {"dashboard": 4, "project": 8, "papers-result": 10, "brand-result": 6, "brand-pages": 20, "tour": 8}


def duration(path: Path) -> float:
    err = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, sec = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(sec)


def main() -> int:
    info = json.loads((DEMO / "scenes.json").read_text(encoding="utf-8"))
    raw = DEMO / "raw" / info["video"]
    scenes = info["scenes"]
    drift = duration(raw) - scenes[-1]["end"] - 1.0  # the video runs ~1 s past the last scene while closing
    last_fast = max((i for i, sc in enumerate(scenes) if sc.get("fast")), default=-1)
    parts, labels, total = [], [], 0.0
    for i, sc in enumerate(scenes):
        start = sc["start"] + (drift if i > last_fast else 0)
        end = sc["end"] + (drift if i >= last_fast else 0)
        if end - start < 0.2:
            continue
        target = FAST_SECONDS.get(sc["name"], 6.0)
        speed = max(1.0, (end - start) / target) if sc.get("fast") else 1.0
        hold = HOLD.get(sc["name"], 0)
        parts.append(f"[0:v]trim=start={start:.2f}:end={end:.2f},setpts=(PTS-STARTPTS)/{speed:.3f},fps=30,"
                     f"tpad=stop_mode=clone:stop_duration={hold}[v{i}]")
        labels.append(f"[v{i}]")
        length = (end - start) / speed + hold
        total += length
        print(f"{sc['name']:<14} {end - start:7.1f}s -> {length:6.1f}s")
    print(f"total {total / 60:.1f} min (timeline drift {drift:.1f}s)")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[out]"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(raw),
           "-filter_complex", graph, "-map", "[out]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
