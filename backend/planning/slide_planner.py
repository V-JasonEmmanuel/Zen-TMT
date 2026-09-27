"""Semantic layout rules: what each layout needs, content limits, and safe fallbacks.

The AI/planner chooses a *semantic* layout; the rendering engine decides positions.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.intelligence.text import shorten
from backend.schemas import LAYOUTS, Slide


@dataclass(frozen=True)
class LayoutSpec:
    fields: tuple[str, ...]  # content fields the writer should fill
    min_items: int = 0
    max_items: int = 5
    max_words: int = 18
    guidance: str = ""
    fallback: str = "key_findings"


SPECS: dict[str, LayoutSpec] = {
    "cover": LayoutSpec(("title", "subtitle"), guidance="Title slide: title and a one-line subtitle only."),
    "section_divider": LayoutSpec(("title", "subtitle"), guidance="Section divider: short title and optional subtitle."),
    "executive_summary": LayoutSpec(("points",), 3, 5, 20, "Fill 'points' with 3-5 of the most important takeaways."),
    "two_column": LayoutSpec(("columns",), 2, 2, 16, "Fill 'columns' with exactly 2 columns, each with a heading and 2-3 points."),
    "three_column": LayoutSpec(("columns",), 3, 3, 14, "Fill 'columns' with exactly 3 columns, each with a heading and 1-3 points."),
    "text_image": LayoutSpec(("points",), 2, 4, 18, "Fill 'points' with 2-4 points that accompany a figure."),
    "image_text": LayoutSpec(("points",), 2, 4, 18, "Fill 'points' with 2-4 points that accompany a figure."),
    "process": LayoutSpec(("steps",), 3, 6, 14, "Fill 'steps' with 3-6 sequential steps (title of 2-4 words + short description), in order."),
    "workflow": LayoutSpec(("steps",), 3, 6, 14, "Fill 'steps' with 3-6 workflow stages in order (title of 2-4 words + short description)."),
    "timeline": LayoutSpec(("steps",), 3, 6, 12, "Fill 'steps' with 3-6 dated milestones in order; put the date/phase in 'title'."),
    "research_methodology": LayoutSpec(("steps", "points"), 3, 5, 14, "Fill 'steps' with 3-5 methodology stages in order, and 'points' with up to 2 key design choices."),
    "architecture": LayoutSpec(("points",), 2, 4, 16, "Fill 'points' with 2-4 statements explaining the main components and how they interact."),
    "comparison": LayoutSpec(("columns",), 2, 2, 14, "Fill 'columns' with exactly 2 columns comparing two things (e.g. before vs after, baseline vs proposed), 2-4 points each."),
    "kpi": LayoutSpec(("kpis", "points"), 2, 4, 10, "Fill 'kpis' with 2-4 headline metrics: 'value' = the exact number from the source (with unit), 'label' = what it measures (max 6 words)."),
    "research_results": LayoutSpec(("kpis", "points"), 1, 4, 16, "Fill 'kpis' with up to 3 headline metrics copied exactly, and 'points' with 2-3 result statements."),
    "chart": LayoutSpec(("points",), 1, 3, 16, "A chart built from the source table is shown. Fill 'points' with 1-3 takeaways from that table."),
    "table": LayoutSpec(("points",), 0, 2, 16, "A table from the source is shown. Fill 'points' with up to 2 takeaways."),
    "key_findings": LayoutSpec(("points",), 2, 4, 18, "Fill 'points' with 2-4 key findings, most important first."),
    "quote": LayoutSpec(("quote",), 1, 1, 30, "Fill 'quote' with one short, impactful sentence copied (nearly) verbatim from the sources."),
    "conclusion": LayoutSpec(("points",), 2, 4, 18, "Fill 'points' with 2-4 concluding takeaways or next steps."),
    "references": LayoutSpec((), guidance="Generated automatically from the sources used."),
}
assert set(SPECS) == set(LAYOUTS)


def layout_guidance(layout: str) -> str:
    return SPECS[layout].guidance


def validate_layout(layout: str) -> str:
    return layout if layout in SPECS else "key_findings"


def enforce_limits(slide: Slide) -> Slide:
    """Keep slides readable: cap item counts and words, and fall back when a layout lacks content."""
    spec = SPECS[slide.layout]
    mw = spec.max_words
    slide.title = shorten(slide.title, 12)
    slide.subtitle = shorten(slide.subtitle, 20)
    cap = spec.max_items if "points" in spec.fields and spec.fields[0] == "points" else 3
    slide.key_points = slide.key_points[:cap]
    for p in slide.key_points:
        p.text = shorten(p.text, mw)
    ncols = 3 if slide.layout == "three_column" else 2
    slide.columns = slide.columns[:ncols]
    for c in slide.columns:
        c.heading = shorten(c.heading, 5)
        c.points = c.points[:4 if ncols == 2 else 3]
        for p in c.points:
            p.text = shorten(p.text, mw)
    slide.steps = slide.steps[:6]
    for s in slide.steps:
        s.title = shorten(s.title, 5)
        s.description = shorten(s.description, mw)
    slide.kpis = slide.kpis[:4]
    for k in slide.kpis:
        k.value = k.value.strip()[:14]
        k.label = shorten(k.label, 8)
    if slide.quote:
        slide.quote.text = shorten(slide.quote.text, 35)
    if slide.kpis and slide.key_points:  # don't repeat KPI values as bullets
        from backend.intelligence.text import numbers_in

        kpi_nums = set().union(*(numbers_in(k.value) for k in slide.kpis))
        slide.key_points = [p for p in slide.key_points if not (numbers_in(p.text) and numbers_in(p.text) <= kpi_nums)]
    return apply_fallback(slide)


def has_content(slide: Slide) -> bool:
    lay = slide.layout
    if lay in ("cover", "section_divider", "references"):
        return True
    if lay in ("two_column", "comparison"):
        return len([c for c in slide.columns if c.points]) >= 2
    if lay == "three_column":
        return len([c for c in slide.columns if c.points]) >= 3
    if lay in ("process", "workflow", "timeline", "research_methodology"):
        return len(slide.steps) >= 2
    if lay == "kpi":
        return len(slide.kpis) >= 2
    if lay == "research_results":
        return bool(slide.kpis or slide.key_points or slide.chart)
    if lay == "chart":
        return slide.chart is not None
    if lay == "table":
        return slide.table is not None
    if lay == "quote":
        return slide.quote is not None
    if lay == "architecture":
        return bool(slide.visual and slide.visual.nodes) or bool(slide.key_points)
    if lay in ("text_image", "image_text"):
        return bool(slide.key_points)
    return bool(slide.key_points)


def apply_fallback(slide: Slide) -> Slide:
    """If the chosen layout cannot be filled, convert the content to a layout that can show it."""
    if has_content(slide):
        return slide
    from backend.schemas import Claim

    original = slide.layout
    points = list(slide.key_points)
    for c in slide.columns:
        points += c.points
    for s in slide.steps:
        points.append(Claim(text=f"{s.title}: {s.description}".strip(": "), sources=s.sources, confidence=s.confidence, status=s.status))
    for k in slide.kpis:
        points.append(Claim(text=f"{k.value} – {k.label.rstrip('…').rstrip()}", sources=k.sources, confidence=k.confidence, status=k.status))
    if slide.quote:
        points.append(slide.quote)
    slide.key_points, slide.columns, slide.steps, slide.kpis, slide.quote = points[:5], [], [], [], None
    slide.layout = "key_findings" if len(points) <= 4 else "executive_summary"
    if not points:
        slide.warnings.append("No verifiable content was found for this slide.")
    elif original != slide.layout:
        slide.warnings.append(f"Layout changed from '{original}' to '{slide.layout}' to fit the available content.")
    return slide
