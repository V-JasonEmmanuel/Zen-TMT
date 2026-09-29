"""Scene segmentation for demo videos (screen recordings, product walkthroughs).

A low-resolution grey sample stream is analysed for visual change; scene boundaries are placed
at significant changes, scenes are merged/split to useful narration lengths, and one keyframe
per scene is extracted at full quality for the vision model and for slides.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.rendering.video.ffmpeg import NO_WINDOW, find_ffmpeg, media_duration

SAMPLE_W, SAMPLE_H = 160, 90


@dataclass
class SceneSpan:
    index: int
    start: float
    end: float
    frame: str = ""  # keyframe path

    @property
    def duration(self) -> float:
        return self.end - self.start


def sample_frames(ff: str, video: Path, duration: float) -> tuple[np.ndarray, float]:
    step = max(0.5, duration / 600)  # at most ~600 samples
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", str(video), "-vf",
                        f"fps=1/{step:.3f},scale={SAMPLE_W}:{SAMPLE_H},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, creationflags=NO_WINDOW)
    raw = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(raw) // (SAMPLE_W * SAMPLE_H)
    return raw[: n * SAMPLE_W * SAMPLE_H].reshape(n, SAMPLE_H, SAMPLE_W).astype(np.float32), step


def detect_scenes(video: Path, min_len: float = 2.5, max_len: float = 14.0, max_scenes: int = 36) -> list[SceneSpan]:
    ff = find_ffmpeg()
    duration = media_duration(ff, video)
    frames, step = sample_frames(ff, video, duration)
    if len(frames) < 2:
        return [SceneSpan(1, 0.0, duration)]
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    thr = max(4.0, float(np.median(diff)) * 5 + 3.0)  # robust: big cuts do not inflate the threshold
    cuts = [0.0] + [(i + 1) * step for i, d in enumerate(diff) if d > thr] + [duration]
    # merge short spans
    spans: list[list[float]] = []
    for a, b in zip(cuts, cuts[1:]):
        if spans and (b - a < min_len or spans[-1][1] - spans[-1][0] < min_len):
            spans[-1][1] = b
        else:
            spans.append([a, b])
    # split long spans so narration stays in step with the picture
    out: list[list[float]] = []
    for a, b in spans:
        n = max(1, int(np.ceil((b - a) / max_len)))
        for k in range(n):
            out.append([a + (b - a) * k / n, a + (b - a) * (k + 1) / n])
    while len(out) > max_scenes:  # merge the shortest neighbours
        i = min(range(len(out) - 1), key=lambda j: (out[j][1] - out[j][0]) + (out[j + 1][1] - out[j + 1][0]))
        out[i] = [out[i][0], out[i + 1][1]]
        del out[i + 1]
    return [SceneSpan(i + 1, round(a, 2), round(b, 2)) for i, (a, b) in enumerate(out)]


def extract_keyframes(video: Path, scenes: list[SceneSpan], out_dir: Path, width: int = 1280) -> None:
    ff = find_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    for sc in scenes:
        at = sc.start + sc.duration * 0.45
        p = out_dir / f"scene_{sc.index:02d}.png"
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", str(p)], capture_output=True, creationflags=NO_WINDOW)
        if p.exists():
            sc.frame = str(p)
