"""User-supplied narration scripts -> per-clip narration text.

Supported formats (plain text / markdown / .docx text):
  * explicit markers:  "## Slide 3", "[Slide 3]", "Slide 3:" or "---" separators between sections
  * no markers:        sentences are distributed across the narrated clips in order,
                       proportionally to each clip's share of the generated narration length
"""
from __future__ import annotations

import re

from backend.intelligence.chunking import split_sentences

MARKER = re.compile(r"^\s*(?:#{1,6}\s*|\[)?\s*(?:slide|scene|clip)\s*(\d{1,3})\s*[\]:.)-]?\s*(.*)$", re.I)


def parse_script(text: str) -> tuple[dict[int, str], list[str]]:
    """Return ({number: text} for marked sections, [unmarked sections in order])."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return {}, []
    marked: dict[int, str] = {}
    current, buf = None, []
    lines = text.split("\n")
    has_markers = any(MARKER.match(l) for l in lines)
    if has_markers:
        for line in lines:
            m = MARKER.match(line)
            if m:
                if current is not None:
                    marked[current] = " ".join(buf).strip()
                current, buf = int(m.group(1)), [m.group(2)] if m.group(2) else []
            elif current is not None:
                buf.append(line.strip())
        if current is not None:
            marked[current] = " ".join(buf).strip()
        return {k: v for k, v in marked.items() if v}, []
    sections = [s.strip() for s in re.split(r"\n\s*-{3,}\s*\n", text) if s.strip()]
    return {}, [" ".join(s.split()) for s in sections]


def distribute(script: str, clip_keys: list[int], weights: list[float]) -> dict[int, str]:
    """Map a script onto clips. clip_keys are slide numbers (or clip indexes) in order."""
    marked, sections = parse_script(script)
    if marked:
        return {k: v for k, v in marked.items() if k in clip_keys}
    if not clip_keys:
        return {}
    if len(sections) == len(clip_keys):
        return dict(zip(clip_keys, sections))
    sentences = split_sentences(" ".join(sections))
    if not sentences:
        return {}
    total_w = sum(weights) or len(clip_keys)
    weights = [w or 1.0 for w in weights] if sum(weights) else [1.0] * len(clip_keys)
    out: dict[int, list[str]] = {k: [] for k in clip_keys}
    total_chars = sum(len(s) for s in sentences)
    acc, i = 0.0, 0
    bounds, run = [], 0.0
    for w in weights:
        run += w / total_w
        bounds.append(run)
    for s in sentences:
        pos = (acc + len(s) / 2) / total_chars
        while i < len(clip_keys) - 1 and pos > bounds[i]:
            i += 1
        out[clip_keys[i]].append(s)
        acc += len(s)
    return {k: " ".join(v) for k, v in out.items() if v}
