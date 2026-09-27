"""Video assembly: slide frames + narration timeline + subtitles -> MP4 (graceful degradation)."""
from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from backend.planning.video_planner import LEAD_IN, TRANSITION, build_subtitles, plan_storyboard, to_srt, to_vtt
from backend.rendering.video.ffmpeg import encode_slideshow, find_ffmpeg, media_duration
from backend.rendering.video.narration import TTSError, get_tts_engine, wav_duration
from backend.schemas import ContentPlan
from backend.utils.logging import get_logger

log = get_logger(__name__)
RATE = 22050


@dataclass
class VideoResult:
    video: Optional[Path] = None
    subtitles_vtt: Optional[Path] = None
    subtitles_srt: Optional[Path] = None
    duration: float = 0.0
    narrated: bool = False
    warnings: list[str] = field(default_factory=list)


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16 if width == 2 else np.uint8)
    if width != 2:
        data = ((data.astype(np.int16) - 128) << 8).astype(np.int16)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if rate != RATE:  # simple linear resample
        n = int(len(data) * RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.int16)
    return data


def render_video(plan: ContentPlan, slide_images: dict[int, Path], out_dir: Path, work_dir: Path, *,
                 narration: bool = True, tts_engine: str = "auto", voice: str = "", speed: float = 1.0,
                 subtitles: bool = True, ffmpeg_path: str = "", fade_color: str = "#000000") -> VideoResult:
    res = VideoResult()
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        res.warnings.append("FFmpeg is not available, so the video was not generated. Presentation and images are unaffected.")
        return res

    # ---- narration (optional; failures degrade to a silent video)
    audio_len: dict[int, float] = {}
    wavs: dict[int, Path] = {}
    if narration:
        engine = get_tts_engine(tts_engine)
        if engine is None:
            res.warnings.append("No offline text-to-speech engine is available; the video was generated without narration.")
        else:
            items = [(s.narration, work_dir / "audio" / f"slide_{s.slide_number:02d}.wav")
                     for s in plan.slides if s.narration.strip()]
            try:
                engine.synthesize_many(items, voice=voice, speed=speed)
                for s in plan.slides:
                    p = work_dir / "audio" / f"slide_{s.slide_number:02d}.wav"
                    if s.narration.strip() and p.exists():
                        wavs[s.slide_number] = p
                        audio_len[s.slide_number] = wav_duration(p)
                res.narrated = bool(wavs)
                log.info("Narration generated", engine=engine.name, clips=len(wavs))
            except TTSError as exc:
                res.warnings.append(f"Narration failed ({exc}); the video was generated without narration.")
                wavs, audio_len = {}, {}

    scenes = plan_storyboard(plan, audio_len)
    frames = [(slide_images[sc.slide_number], sc.duration) for sc in scenes if sc.slide_number in slide_images]
    if len(frames) != len(scenes):
        res.warnings.append("Some slide images were missing and were skipped in the video.")
    total = sum(d for _, d in frames) - TRANSITION * max(0, len(frames) - 1)

    # ---- mix narration into one exactly-timed track
    audio_path = None
    if wavs:
        track = np.zeros(int((total + 1) * RATE), dtype=np.int32)
        for sc in scenes:
            if sc.slide_number in wavs:
                clip = _read_wav(wavs[sc.slide_number])
                start = int((sc.start + LEAD_IN) * RATE)
                end = min(len(track), start + len(clip))
                track[start:end] += clip[: end - start]
        audio_path = work_dir / "narration.wav"
        with wave.open(str(audio_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(np.clip(track, -32768, 32767).astype(np.int16).tobytes())

    srt_path = None
    if subtitles and wavs:
        build_subtitles(scenes)
        res.subtitles_srt = out_dir / "presentation.srt"
        res.subtitles_vtt = out_dir / "presentation.vtt"
        out_dir.mkdir(parents=True, exist_ok=True)
        res.subtitles_srt.write_text(to_srt(scenes), encoding="utf-8")
        res.subtitles_vtt.write_text(to_vtt(scenes), encoding="utf-8")
        srt_path = res.subtitles_srt

    out = out_dir / "presentation.mp4"
    encode_slideshow(ffmpeg, frames, out, audio=audio_path, subtitles=srt_path, transition=TRANSITION,
                     fade_color=fade_color.replace("#", "0x"))
    res.video = out
    res.duration = round(media_duration(ffmpeg, out), 2)
    return res
