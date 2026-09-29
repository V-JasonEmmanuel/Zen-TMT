"""Video adapter: demo videos / screen recordings become a traceable, scene-by-scene source.

Pipeline: scene detection -> keyframe per scene -> local vision model description ->
presenter narration per scene (sized to the scene length) -> blocks with timestamps.
Scene descriptions (what is visibly on screen) are the facts; slides and narration are
verified against them like any other document.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from backend.ingestion.base import DocumentAdapter, ExtractionError, register_adapter
from backend.schemas import Block, ContentType, ExtractedDocument
from backend.utils.logging import get_logger
from backend.utils.progress import report

log = get_logger(__name__)
WORDS_PER_SECOND = 2.6  # comfortable presenter pace


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


class SceneNarration(BaseModel):
    index: int
    narration: str


class NarrationPlan(BaseModel):
    title: str = ""
    scenes: list[SceneNarration] = Field(default_factory=list)


NARRATION_PROMPT = """You are writing the voice-over for a product demo video, scene by scene.
Use ONLY what the scene descriptions say is visible. Do not invent features, numbers or names.
Write in a clear, professional presenter voice ("Here we open...", "Next, the dashboard shows...").
Each narration must fit its scene: at most the given number of words. Do not mention "scene" or timestamps.
Also give a short title for the whole demo (max 8 words, based only on what is visible).

SCENES:
{scenes}

Return JSON: {{"title": "...", "scenes": [{{"index": 1, "narration": "..."}}, ...]}}"""


def fit_sentences(text: str, max_words: int) -> str:
    """Keep whole sentences within the word budget (never cut mid-sentence); at least one sentence."""
    from backend.intelligence.chunking import split_sentences

    out, n = [], 0
    for s in split_sentences(" ".join(text.split())):
        w = len(s.split())
        if out and n + w > max_words:
            break
        out.append(s if s.endswith((".", "!", "?")) else s + ".")
        n += w
    return " ".join(out)


def _fallback_narration(desc: str, words: int, first: bool) -> str:
    text = re.sub(r"\s+", " ", desc).strip()
    if not text:
        return ""
    text = text[0].lower() + text[1:] if len(text) > 1 else text
    lead = "Here, " if first else "Next, "
    return fit_sentences(lead + text, words)


def write_narration(scenes: list[dict]) -> tuple[str, dict[int, str]]:
    """LLM narration when a local text model is available, deterministic otherwise."""
    budgets = {s["index"]: max(5, int((s["duration"] - 0.4) * WORDS_PER_SECOND)) for s in scenes}
    try:
        from backend.llm import get_llm
        from backend.llm.prompts import system_prompt
        from backend.llm.structured_output import generate_structured

        llm = get_llm()
        if llm.is_available():
            lines = "\n".join(f"{s['index']}. ({budgets[s['index']]} words max) {s['description']}"
                              + (f" | visible text: {s['visible_text']}" if s.get("visible_text") else "") for s in scenes)
            plan = generate_structured(llm, NARRATION_PROMPT.format(scenes=lines), NarrationPlan, system=system_prompt(),
                                       retries=1, max_tokens=min(2400, 60 * len(scenes) + 200))
            got = {s.index: fit_sentences(s.narration, budgets[s.index]) for s in plan.scenes if s.index in budgets}
            if got:
                return plan.title, got
    except Exception as exc:  # any LLM problem -> deterministic narration
        log.warning("Scene narration via LLM unavailable", reason=type(exc).__name__)
    return "", {s["index"]: _fallback_narration(s["description"], budgets[s["index"]], i == 0) for i, s in enumerate(scenes)}


def _numbers_ok(text: str, evidence: str) -> str:
    """Drop narration sentences containing numbers that are not visible in the scene."""
    from backend.intelligence.chunking import split_sentences
    from backend.intelligence.text import number_supported, numbers_in

    ev = numbers_in(evidence)
    return " ".join(s for s in split_sentences(text) if all(number_supported(n, ev) for n in numbers_in(s)))


@register_adapter
class VideoAdapter(DocumentAdapter):
    extensions = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
    format_name = "video"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        from backend.rendering.video.ffmpeg import find_ffmpeg, media_duration
        from backend.vision.describe import describe_frame, pick_vision_model, unload
        from backend.vision.keyframes import detect_scenes, extract_keyframes

        if not find_ffmpeg():
            raise ExtractionError("FFmpeg is required to analyse videos.")
        try:
            duration = media_duration(find_ffmpeg(), path)
        except Exception as exc:
            raise ExtractionError("The video could not be read. It may be corrupted or use an unsupported codec.") from exc
        report("Detecting scenes in the video")
        scenes = detect_scenes(path)
        extract_keyframes(path, scenes, work_dir / "figures")
        out = ExtractedDocument(document_id=document_id, filename=path.name, format="video", page_count=len(scenes),
                                metadata={"duration": round(duration, 2)})
        model = pick_vision_model()
        details: list[dict] = []
        prev = ""
        for sc in scenes:
            d = {"index": sc.index, "start": sc.start, "end": sc.end, "duration": sc.duration,
                 "frame": f"figures/scene_{sc.index:02d}.png" if sc.frame else "", "description": "", "visible_text": "", "screen": ""}
            if model and sc.frame:
                report(f"Understanding scene {sc.index} of {len(scenes)} ({fmt_ts(sc.start)}) with {model}")
                try:
                    fd = describe_frame(model, sc.frame, prev)
                    d.update(description=fd.description.strip(), visible_text=fd.visible_text.strip(), screen=fd.screen.strip(),
                             action=fd.action.strip())
                    prev = fd.description
                except Exception as exc:
                    out.warnings.append(f"Scene {sc.index} could not be described ({type(exc).__name__}).")
            details.append(d)
        if model:
            unload(model)  # free VRAM before the text model / rendering
        else:
            out.warnings.append("No local vision model is installed, so scenes were not described. "
                                "Install one (e.g. `ollama pull qwen2.5vl:3b`) for automatic demo narration.")
        described = [d for d in details if d["description"]]
        report("Writing the scene-by-scene narration")
        title, narr = write_narration(described) if described else ("", {})
        for d in details:
            text = narr.get(d["index"], "")
            d["narration"] = _numbers_ok(text, f"{d['description']} {d['visible_text']}") if text else ""
        out.metadata.update({"scenes": details, "vision_model": model or "", "demo_title": title})
        out.title = title or Path(path.name).stem.replace("_", " ")

        # ---- blocks: overview + scene-by-scene walkthrough (+ keyframes as figures)
        out.blocks.append(Block(type=ContentType.heading, text="Demo overview", page=1, level=1))
        screens = list(dict.fromkeys(d["screen"] for d in described if d["screen"]))
        out.blocks.append(Block(type=ContentType.paragraph, page=1, text=(
            f"The demo video runs for {fmt_ts(duration)} and walks through {len(scenes)} scenes."
            + (f" Screens shown include: {', '.join(screens[:8])}." if screens else ""))))
        out.blocks.append(Block(type=ContentType.heading, text="Demo walkthrough", page=1, level=1))
        for d in details:
            k = d["index"]
            screen = " ".join(d["screen"].split())[:40].strip(" .:")
            out.blocks.append(Block(type=ContentType.heading, page=k, level=2,
                                    text=f"Scene {k} · {screen + ' · ' if screen else ''}{fmt_ts(d['start'])}-{fmt_ts(d['end'])}"))
            if d["description"]:
                # "Screen: what happens" lets slides name each step after the screen it shows
                text = (f"{screen[:1].upper()}{screen[1:]}: " if screen else "") + d["description"] \
                    + (f" Visible text: {d['visible_text']}." if d["visible_text"] else "")
                out.blocks.append(Block(type=ContentType.paragraph, text=text, page=k))
            if d["frame"]:
                out.blocks.append(Block(type=ContentType.figure, text=f"Frame at {fmt_ts(d['start'] + d['duration'] * 0.45)}",
                                        page=k, figure_index=k, image_path=d["frame"]))
        log.info("Video analysed", scenes=len(scenes), described=len(described), vision=bool(model))
        return out

