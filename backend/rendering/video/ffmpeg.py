"""FFmpeg discovery and presentation-video encoding (subtle crossfades, still frames, AAC audio)."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from backend.utils.logging import get_logger

log = get_logger(__name__)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class FFmpegError(Exception):
    pass


def find_ffmpeg(configured: str = "") -> Optional[str]:
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and Path(exe).exists() else None
    except Exception:
        return None


def media_duration(ffmpeg: str, path: Path) -> float:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        raise FFmpegError("Could not read media duration")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def media_streams(ffmpeg: str, path: Path) -> dict[str, int]:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    return {k: len(re.findall(rf"Stream #\d+:\d+.*?: {k}:", r.stderr)) for k in ("Video", "Audio", "Subtitle")}


def encode_slideshow(ffmpeg: str, frames: list[tuple[Path, float]], out: Path, *, audio: Optional[Path] = None,
                     subtitles: Optional[Path] = None, transition: float = 0.6, fps: int = 25,
                     width: int = 1920, height: int = 1080, fade_color: str = "black") -> Path:
    """frames: (image, seconds visible incl. transition overlap). Crossfades between consecutive frames."""
    if not frames:
        raise FFmpegError("No frames to encode")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for img, dur in frames:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(img)]
    n = len(frames)
    audio_idx = sub_idx = None
    if audio:
        audio_idx = n
        args += ["-i", str(audio)]
    if subtitles:
        sub_idx = n + (1 if audio else 0)
        args += ["-i", str(subtitles)]

    filters = []
    for i in range(n):
        filters.append(f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,fps={fps},format=yuv420p[v{i}]")
    last = "v0"
    offset = 0.0
    for i in range(1, n):
        offset += frames[i - 1][1] - transition
        filters.append(f"[{last}][v{i}]xfade=transition=fade:duration={transition}:offset={offset:.3f}[x{i}]")
        last = f"x{i}"
    total = sum(d for _, d in frames) - transition * (n - 1)
    filters.append(f"[{last}]fade=t=in:st=0:d=0.8:color={fade_color},"
                   f"fade=t=out:st={max(0.0, total - 0.8):.3f}:d=0.8:color={fade_color}[vout]")
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_idx is not None:
        args += ["-map", f"{audio_idx}:a", "-c:a", "aac", "-b:a", "160k", "-af", f"apad,atrim=0:{total:.3f}"]
    if sub_idx is not None:
        args += ["-map", f"{sub_idx}:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "20", "-r", str(fps),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(args, capture_output=True, text=True, timeout=max(600, int(total * 10)), creationflags=NO_WINDOW)
    if r.returncode != 0 or not out.exists():
        log.error("FFmpeg failed", code=r.returncode, stderr_tail=r.stderr[-300:].replace("\n", " "))
        raise FFmpegError("Video encoding failed")
    log.info("Video encoded", seconds=round(total, 1), frames=n)
    return out
