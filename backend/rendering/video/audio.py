"""Audio helpers for the composer: decode any media to PCM, speed without pitch change, TTS with a
cache, mixing, music looping/fades and ducking under narration. Mono 44.1 kHz float32 internally."""
from __future__ import annotations

import hashlib
import subprocess
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from backend.rendering.video.ffmpeg import NO_WINDOW
from backend.rendering.video.narration import TTSError, get_tts_engine

RATE = 44100


def atempo_chain(speed: float) -> str:
    """ffmpeg atempo accepts 0.5..2.0 per stage; chain stages for larger factors."""
    parts, s = [], float(speed)
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-3:
        parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def decode(ff: str, path: Path, start: float = 0.0, duration: Optional[float] = None, speed: float = 1.0) -> np.ndarray:
    args = [ff, "-hide_banner", "-loglevel", "error"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE)]
    chain = atempo_chain(speed)
    if chain:
        args += ["-af", chain]
    args += ["-f", "s16le", "-"]
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        return np.zeros(0, np.float32)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, arr: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(arr, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return path


def seconds(arr: np.ndarray) -> float:
    return len(arr) / RATE


def tts_batch(texts: list[str], cache_dir: Path, *, engine: str = "auto", voice: str = "", speed: float = 1.0,
              ff: str = "") -> tuple[dict[str, np.ndarray], list[str]]:
    """Synthesize every distinct text once (cached on disk by text+voice+speed)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, np.ndarray] = {}
    warnings: list[str] = []
    todo: list[tuple[str, Path]] = []
    for t in dict.fromkeys(x.strip() for x in texts if x and x.strip()):
        key = hashlib.sha1(f"{t}|{voice}|{speed:.2f}|{engine}".encode()).hexdigest()[:20]
        p = cache_dir / f"{key}.wav"
        if p.exists() and p.stat().st_size > 100:
            out[t] = decode(ff, p) if ff else np.zeros(0, np.float32)
        else:
            todo.append((t, p))
    if todo:
        eng = get_tts_engine(engine)
        if eng is None:
            warnings.append("No offline voice is available; the video has no generated narration.")
            return out, warnings
        try:
            eng.synthesize_many(todo, voice=voice, speed=speed)
        except TTSError as exc:
            warnings.append(f"Narration could not be synthesised ({exc}).")
            return out, warnings
        for t, p in todo:
            if p.exists():
                out[t] = decode(ff, p)
    return out, warnings


def fit(arr: np.ndarray, max_seconds: float, ff: str, tmp: Path, max_speedup: float = 1.3) -> np.ndarray:
    """Make narration fit a window: speed up (pitch preserved) up to max_speedup, then trim with a fade."""
    if max_seconds <= 0 or seconds(arr) <= max_seconds:
        return arr
    factor = min(max_speedup, seconds(arr) / max_seconds)
    if factor > 1.02:
        p = write_wav(tmp, arr)
        arr = decode(ff, p, speed=factor)
    n = int(max_seconds * RATE)
    if len(arr) > n:
        arr = arr[:n].copy()
        fade = min(len(arr), int(0.25 * RATE))
        arr[-fade:] *= np.linspace(1, 0, fade)
    return arr


def envelope(arr: np.ndarray, window: float = 0.35) -> np.ndarray:
    """0..1 activity envelope (used to duck music under narration)."""
    if len(arr) == 0:
        return arr
    k = max(1, int(window * RATE))
    a = np.abs(arr)
    csum = np.cumsum(np.concatenate([[0.0], a]))
    avg = (csum[k:] - csum[:-k]) / k
    avg = np.concatenate([avg, np.full(k - 1, avg[-1] if len(avg) else 0)])[: len(arr)]
    return np.clip(avg / 0.02, 0, 1)


def music_track(ff: str, path: Path, total: float, volume: float, fade_in: float, fade_out: float,
                duck_env: Optional[np.ndarray] = None) -> np.ndarray:
    src = decode(ff, path)
    n = int(total * RATE)
    if len(src) == 0 or n == 0:
        return np.zeros(n, np.float32)
    reps = int(np.ceil(n / len(src)))
    m = np.tile(src, reps)[:n] * volume
    fi, fo = int(fade_in * RATE), int(fade_out * RATE)
    if fi:
        m[:fi] *= np.linspace(0, 1, min(fi, n))[: min(fi, n)]
    if fo:
        m[-min(fo, n):] *= np.linspace(1, 0, min(fo, n))
    if duck_env is not None and len(duck_env):
        env = np.zeros(n, np.float32)
        env[: min(n, len(duck_env))] = duck_env[:n]
        m *= 1.0 - 0.7 * env  # music drops to ~30% while someone speaks
    return m


def place(track: np.ndarray, clip: np.ndarray, start: float, gain: float = 1.0) -> None:
    s = int(start * RATE)
    if s >= len(track) or len(clip) == 0:
        return
    e = min(len(track), s + len(clip))
    track[s:e] += clip[: e - s] * gain
