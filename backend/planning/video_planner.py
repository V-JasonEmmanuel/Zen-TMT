"""Video storyboard planning: per-slide timing from narration length or reading time."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.schemas import ContentPlan, Slide

TRANSITION = 0.6  # crossfade seconds
LEAD_IN = 0.5  # narration starts after the transition settles
TAIL = 0.9  # pause after narration before the next transition


@dataclass
class Scene:
    slide_number: int
    narration: str
    audio_seconds: float = 0.0
    duration: float = 0.0  # visible seconds including the outgoing transition
    start: float = 0.0  # when the slide is fully on screen
    subtitles: list[tuple[float, float, str]] = field(default_factory=list)


def reading_seconds(slide: Slide) -> float:
    words = len(slide.title.split()) + len(slide.subtitle.split())
    words += sum(len(p.text.split()) for p in slide.key_points)
    words += sum(len(p.text.split()) for c in slide.columns for p in c.points)
    words += sum(len((s.title + " " + s.description).split()) for s in slide.steps)
    words += sum(len((k.value + " " + k.label).split()) for k in slide.kpis)
    if slide.layout == "cover":
        return 5.0
    return max(5.0, min(14.0, 2.5 + words / 3.2))


def plan_storyboard(plan: ContentPlan, audio: dict[int, float] | None = None) -> list[Scene]:
    audio = audio or {}
    scenes: list[Scene] = []
    t = 0.0
    for s in plan.slides:
        a = audio.get(s.slide_number, 0.0)
        dur = max(4.0, LEAD_IN + a + TAIL + TRANSITION) if a else reading_seconds(s) + TRANSITION
        sc = Scene(s.slide_number, s.narration, a, round(dur, 3), round(t, 3))
        scenes.append(sc)
        t += dur - TRANSITION
    return scenes


def build_subtitles(scenes: list[Scene]) -> None:
    """Split each scene's narration into sentence cues spread across its audio by length."""
    from backend.intelligence.chunking import split_sentences

    for sc in scenes:
        if not sc.narration or not sc.audio_seconds:
            continue
        sents = split_sentences(sc.narration) or [sc.narration]
        total_chars = sum(len(x) for x in sents) or 1
        t0 = sc.start + LEAD_IN
        for sent in sents:
            d = sc.audio_seconds * len(sent) / total_chars
            sc.subtitles.append((round(t0, 3), round(t0 + d, 3), sent))
            t0 += d


def _ts(sec: float, sep: str) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s % 1) * 1000)):03d}"


def to_srt(scenes: list[Scene]) -> str:
    cues = [c for sc in scenes for c in sc.subtitles]
    return "\n".join(f"{i}\n{_ts(a, ',')} --> {_ts(b, ',')}\n{txt}\n" for i, (a, b, txt) in enumerate(cues, 1))


def to_vtt(scenes: list[Scene]) -> str:
    cues = [c for sc in scenes for c in sc.subtitles]
    return "WEBVTT\n\n" + "\n".join(f"{_ts(a, '.')} --> {_ts(b, '.')}\n{txt}\n" for a, b, txt in cues)
