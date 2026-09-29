"""Project video: build / sync the editable timeline from the content plan and sources, then render."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from backend.branding.theme import Theme
from backend.media.library import MediaLibrary
from backend.pipeline.outputs import OutputWriter, project_work_dir
from backend.pipeline.sources import project_document_ids
from backend.rendering.layouts import build_slide_scene
from backend.rendering.video.composer import ComposeResult, Composer
from backend.rendering.video.timeline import (
    Clip, NarrationSettings, Timeline, build_default_timeline, load_timeline, save_timeline,
)
from backend.schemas import ContentPlan
from backend.services.documents import process_document
from backend.storage.database import Database


def video_sources(db: Database, project: dict) -> list[dict]:
    out = []
    for did in project_document_ids(project):
        row = db.get_document(did) or {}
        if row.get("format") not in ("mp4", "mov", "webm", "mkv", "avi", "m4v"):
            continue
        doc, _, _ = process_document(db, did)
        scenes = doc.metadata.get("scenes", [])
        asset = (row.get("meta") or {}).get("media_asset_id")
        if not asset:
            continue
        out.append({"asset_id": asset, "duration": doc.metadata.get("duration", 0), "name": row.get("filename", "video"),
                    "segments": [{"start": s["start"], "end": s["end"], "text": s.get("narration", "")} for s in scenes if s.get("narration")]})
    return out


def _extra_assets(project: dict) -> list[dict]:
    lib = MediaLibrary()
    out = []
    for aid in project["options"].get("video_media", []) or []:
        a = lib.get(aid)
        if a and a.kind in ("image", "video"):
            out.append({"asset_id": a.id, "kind": a.kind, "duration": a.meta.get("duration", 5.0) if a.kind == "video" else 5.0})
    return out


def _narration_from_options(opts: dict, rs) -> NarrationSettings:
    mode = opts.get("narration_mode") or ("tts" if opts.get("narration", rs.tts_enabled) else "none")
    return NarrationSettings(mode=mode if mode in ("tts", "upload", "none") else "tts",
                             voice=opts.get("voice") or rs.tts_voice, speed=float(opts.get("speed") or rs.tts_rate),
                             asset_id=opts.get("narration_asset_id"), script=opts.get("script", "") or "")


def sync_timeline(tl: Timeline, plan: ContentPlan) -> Timeline:
    """Keep user edits; add clips for new slides, drop clips for removed slides, refresh narration."""
    slides = {s.slide_number: s for s in plan.slides if s.layout != "references"}
    tl.clips = [c for c in tl.clips if c.type != "slide" or c.slide_number in slides]
    present = {c.slide_number for c in tl.clips if c.type == "slide"}
    for n, s in sorted(slides.items()):
        if n in present:
            continue
        idx = next((i for i, c in enumerate(tl.clips) if c.type == "slide" and (c.slide_number or 0) > n), None)
        if idx is None:
            idx = next((i for i, c in enumerate(tl.clips) if c.type == "outro"), len(tl.clips))
        tl.clips.insert(idx, Clip(type="slide", slide_number=n, label=f"Slide {n}: {s.title}"[:80], narration_text=s.narration))
    for c in tl.clips:
        if c.type == "slide" and not c.narration_locked and c.slide_number in slides:
            c.narration_text = slides[c.slide_number].narration
            c.label = f"Slide {c.slide_number}: {slides[c.slide_number].title}"[:80]
    return tl


def ensure_timeline(db: Database, project: dict, plan: ContentPlan, theme: Theme, rebuild: bool = False) -> Timeline:
    work = project_work_dir(project)
    tl = None if rebuild else load_timeline(work)
    if tl is None:
        vs = theme.video_style
        opts = project["options"]
        tl = build_default_timeline(
            plan, video_sources=video_sources(db, project),
            transition=(opts.get("transition") or (vs.transition if vs else "fade")),
            motion=opts.get("motion", vs.motion if vs else "subtle"),
            intro=bool(opts.get("intro", vs.intro if vs else False)), outro=bool(opts.get("outro", vs.outro if vs else False)),
            extra_assets=_extra_assets(project), music_asset=opts.get("music_asset_id"),
            narration=_narration_from_options(opts, db.runtime_settings()))
        tl.subtitles = bool(opts.get("subtitles", True))
    else:
        tl = sync_timeline(tl, plan)
    return save_timeline(work, tl)


def media_path_resolver() -> Callable[[str], Optional[Path]]:
    lib = MediaLibrary()

    def resolve(asset_id: str) -> Optional[Path]:
        a = lib.get(asset_id) if asset_id else None
        if not a:
            return None
        return lib.raster_path(a) if a.kind in ("image", "logo", "illustration", "reference", "visual") else lib.path(a)

    return resolve


def render_project_video(db: Database, project: dict, plan: ContentPlan, theme: Theme, writer: OutputWriter,
                         quality: str = "final", on_progress: Optional[Callable[[str], None]] = None) -> ComposeResult:
    tl = ensure_timeline(db, project, plan, theme)
    scenes = {s.slide_number: build_slide_scene(s, theme, writer.ctx) for s in plan.slides}
    rs = db.runtime_settings()
    comp = Composer(tl, plan=plan, theme=theme, scenes=scenes, media_path=media_path_resolver(), out_dir=writer.out / "video",
                    work_dir=project_work_dir(project), ffmpeg_path=rs.ffmpeg_path, quality=quality, tts_engine=rs.tts_engine,
                    on_progress=on_progress)
    res = comp.render()
    work = project_work_dir(project)
    (work / f"rendered_{quality}.json").write_text(json.dumps({"clips": res.clips, "duration": res.duration}),
                                                   encoding="utf-8")
    return res

