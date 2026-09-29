"""Editable video timeline.

A project's video is described by a Timeline (stored as projects/<id>/timeline.json):
    clips      slide | image | video | intro | outro, each with trim / crop / speed / transition /
               motion / narration (text, uploaded audio, or timed segments for demo videos)
    music      background track (volume, ducking under narration, fades)
    narration  tts | upload (one audio file for the whole video) | none, plus an optional script
The timeline is built automatically from the content plan, then edited by the user in the
video editor. The composer renders it; unchanged clips are reused from cache.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.schemas import ContentPlan, utcnow
from backend.utils.files import new_id

Transition = Literal["zensar_grid", "fade", "wipe", "none"]


class Crop(BaseModel):
    x: float = Field(0.0, ge=0, le=1)
    y: float = Field(0.0, ge=0, le=1)
    w: float = Field(1.0, gt=0, le=1)
    h: float = Field(1.0, gt=0, le=1)


class NarrationSegment(BaseModel):
    start: float  # seconds in SOURCE time (before trim/speed)
    end: float
    text: str


class Clip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clip_"))
    type: Literal["slide", "image", "video", "intro", "outro"]
    label: str = ""
    slide_number: Optional[int] = None
    asset_id: Optional[str] = None  # media library asset (image / video)
    trim_start: float = Field(0.0, ge=0)
    trim_end: Optional[float] = None  # None = to the end of the source
    speed: float = Field(1.0, ge=0.25, le=4.0)
    crop: Optional[Crop] = None
    duration: float = Field(0.0, ge=0)  # stills/slides: 0 = automatic from narration
    transition: Transition = "zensar_grid"
    motion: Literal["none", "subtle", "ken_burns"] = "subtle"
    keep_audio: bool = True  # original audio of video clips
    audio_volume: float = Field(1.0, ge=0, le=2)
    narration_text: str = ""
    narration_locked: bool = False  # True once edited in the video editor (not re-synced from slides)
    narration_asset_id: Optional[str] = None  # user-recorded narration for this clip
    narration_segments: list[NarrationSegment] = Field(default_factory=list)
    source_duration: float = 0.0  # video clips: length of the source file (seconds)


class MusicTrack(BaseModel):
    asset_id: Optional[str] = None
    volume: float = Field(0.18, ge=0, le=1)
    duck: bool = True  # lower the music while narration plays
    fade_in: float = 1.5
    fade_out: float = 2.5


class NarrationSettings(BaseModel):
    mode: Literal["tts", "upload", "none"] = "tts"
    voice: str = ""
    speed: float = Field(1.0, ge=0.5, le=2.0)
    asset_id: Optional[str] = None  # whole-video narration audio (mode=upload)
    script: str = ""  # user script; overrides generated narration text


class Timeline(BaseModel):
    version: int = 1
    width: int = 1920
    height: int = 1080
    fps: int = 25
    clips: list[Clip] = Field(default_factory=list)
    music: MusicTrack = Field(default_factory=MusicTrack)
    narration: NarrationSettings = Field(default_factory=NarrationSettings)
    subtitles: bool = True
    updated_at: str = Field(default_factory=utcnow)

    @field_validator("clips")
    @classmethod
    def _limit(cls, v):
        if len(v) > 200:
            raise ValueError("A timeline can hold at most 200 clips")
        return v


def clip_output_seconds(c: Clip) -> Optional[float]:
    """Visible length of a video clip after trim + speed (None for auto-length clips)."""
    if c.type != "video":
        return c.duration or None
    end = c.trim_end if c.trim_end is not None else c.source_duration
    return max(0.1, (end - c.trim_start) / c.speed) if end else None


def timeline_path(work_dir: Path) -> Path:
    return work_dir / "timeline.json"


def load_timeline(work_dir: Path) -> Optional[Timeline]:
    p = timeline_path(work_dir)
    if p.exists():
        try:
            return Timeline.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_timeline(work_dir: Path, tl: Timeline) -> Timeline:
    work_dir.mkdir(parents=True, exist_ok=True)
    tl.updated_at = utcnow()
    timeline_path(work_dir).write_text(tl.model_dump_json(indent=2), encoding="utf-8")
    return tl


def build_default_timeline(plan: ContentPlan, *, video_sources: list[dict], transition: str = "zensar_grid",
                           motion: str = "subtle", intro: bool = True, outro: bool = True,
                           extra_assets: list[dict] | None = None, music_asset: Optional[str] = None,
                           narration: Optional[NarrationSettings] = None) -> Timeline:
    """Slides (with motion graphics) + demo videos placed after the explanatory slides + optional
    user images/videos, framed by a brand intro and outro.

    video_sources: [{"asset_id", "duration", "name", "segments": [{start,end,text}]}]
    extra_assets:  [{"asset_id", "kind": image|video, "duration"}]  user media to include
    """
    tr = transition if transition in ("zensar_grid", "fade", "wipe", "none") else "fade"
    clips: list[Clip] = []
    if intro:
        clips.append(Clip(type="intro", label="Brand intro", transition="none", duration=2.6))
    slides = [s for s in plan.slides if s.layout != "references"]
    tail_layouts = ("conclusion",)
    head = [s for s in slides if s.layout not in tail_layouts]
    tail = [s for s in slides if s.layout in tail_layouts]
    for s in head:
        clips.append(Clip(type="slide", label=f"Slide {s.slide_number}: {s.title}"[:80], slide_number=s.slide_number,
                          transition=tr if clips else "none", motion=motion, narration_text=s.narration))
    for v in video_sources:
        clips.append(Clip(type="video", label=f"Demo: {v.get('name', 'video')}"[:80], asset_id=v["asset_id"], transition="fade",
                          source_duration=float(v.get("duration") or 0), keep_audio=False,
                          narration_segments=[NarrationSegment(**seg) for seg in v.get("segments", []) if seg.get("text")]))
    for a in extra_assets or []:
        if a.get("kind") == "video":
            clips.append(Clip(type="video", label="Media clip", asset_id=a["asset_id"], transition="fade",
                              source_duration=float(a.get("duration") or 0)))
        else:
            clips.append(Clip(type="image", label="Image", asset_id=a["asset_id"], transition="fade", motion="ken_burns",
                              duration=float(a.get("duration") or 5.0)))
    for s in tail:
        clips.append(Clip(type="slide", label=f"Slide {s.slide_number}: {s.title}"[:80], slide_number=s.slide_number,
                          transition=tr, motion=motion, narration_text=s.narration))
    if outro:
        clips.append(Clip(type="outro", label="Brand outro", transition="fade", duration=3.0))
    return Timeline(clips=clips, music=MusicTrack(asset_id=music_asset), narration=narration or NarrationSettings())


def to_json(tl: Timeline) -> dict:
    return json.loads(tl.model_dump_json())
