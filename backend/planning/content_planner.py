"""Content planning: relevant chunks -> verified, source-mapped ContentPlan.

1. Outline (deterministic): slide slots from the contract, topic relevance mass and
   document structure; each slot receives a small set of candidate chunks.
2. Writing (per slide): the local LLM writes concise content from ONLY that slot's
   passages, citing them; without an LLM an extractive writer selects source sentences.
3. Verification: every statement is checked against its sources (see verification.py).
Each slide can be regenerated independently from its stored candidate chunks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from pydantic import BaseModel, Field

from backend.intelligence.chunking import split_sentences
from backend.intelligence.relevance import TOPICS, RelevanceResult
from backend.intelligence.text import NUMBER, numbers_in, shorten
from backend.intelligence.verification import Verifier
from backend.llm.base import LLMProvider, LLMUnavailable
from backend.llm.prompts import load_prompt, system_prompt
from backend.llm.structured_output import StructuredOutputError, generate_structured
from backend.planning.slide_planner import SPECS, apply_fallback, enforce_limits, layout_guidance
from backend.planning.visual_planner import attach_visual, chart_from_table, table_from_chunk
from backend.schemas import (
    KPI, Claim, Column, ContentContract, ContentPlan, ContentType, DocumentChunk, SectionType, Slide,
    SourceReference, Step,
)
from backend.utils.logging import get_logger

log = get_logger(__name__)
WORKFLOW_CUES = re.compile(r"\b(workflow|pipeline|data flow|walkthrough)\b", re.I)
SEQUENCE_CUES = re.compile(r"\b(first|second|then|next|finally|step|stage|phase|subsequently|afterwards)\b", re.I)
COMPARE_CUES = re.compile(r"\b(compared (to|with)|versus|vs\.?|baseline|traditional|conventional|outperform)", re.I)
TIME_CUES = re.compile(r"\b(19|20)\d{2}\b|\bQ[1-4]\b|\b(week|month|quarter|phase) \d", re.I)


class PlanningError(Exception):
    pass


# ------------------------------------------------------------------ LLM draft schema
class DraftPoint(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)


class DraftStep(BaseModel):
    title: str
    description: str = ""
    sources: list[str] = Field(default_factory=list)


class DraftKPI(BaseModel):
    value: str
    label: str
    sources: list[str] = Field(default_factory=list)


class DraftColumn(BaseModel):
    heading: str
    points: list[DraftPoint] = Field(default_factory=list)


class SlideDraft(BaseModel):
    title: str
    subtitle: str = ""
    points: list[DraftPoint] = Field(default_factory=list)
    columns: list[DraftColumn] = Field(default_factory=list)
    steps: list[DraftStep] = Field(default_factory=list)
    kpis: list[DraftKPI] = Field(default_factory=list)
    quote: Optional[DraftPoint] = None
    narration: str = ""


# ------------------------------------------------------------------ context
@dataclass
class PlanningContext:
    document_id: str
    document_name: str
    doc_title: str
    chunks: list[DocumentChunk]
    contract: ContentContract
    relevance: RelevanceResult
    embedder: object
    verifier: Verifier
    llm: Optional[LLMProvider] = None
    drop_unverified: bool = False
    doc_graphs: dict = field(default_factory=dict)  # document_id -> architecture graph (code repos)
    chunk_map: dict[str, DocumentChunk] = field(init=False)

    def __post_init__(self):
        self.chunk_map = {c.id: c for c in self.chunks}


@dataclass
class Slot:
    layout: str
    topic: str = ""
    title_hint: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    table_chunk: Optional[str] = None


def clean_heading(title: str) -> str:
    t = re.sub(r"^((\d+(\.\d+)*)|[IVX]+|[A-Z])[.):]?\s+", "", title.strip())
    return t[:1].upper() + t[1:] if t else t


def topic_label(topic: str) -> str:
    return topic.replace("_", " ").title().replace("And", "and")


# ------------------------------------------------------------------ outline
def build_outline(ctx: PlanningContext) -> tuple[list[Slot], list[str]]:
    n = ctx.contract.slide_count
    ranked = ctx.relevance.ranked()
    if not ranked:
        raise PlanningError("No relevant content was found in the document for this instruction.")
    cm = ctx.chunk_map

    front: list[Slot] = []
    tail: list[Slot] = []
    if n == 1:
        return [Slot("executive_summary", "overview", "Executive Summary", _summary_chunks(ctx))], []
    front.append(Slot("cover"))
    if n == 2 or n >= 5:
        front.append(Slot("executive_summary", "overview", "Executive Summary", _summary_chunks(ctx)))
    if n >= 4 or n == 3:
        tail.append(Slot("conclusion", "conclusion", "Conclusion", _conclusion_chunks(ctx)))
    if n >= 7:
        tail.append(Slot("references", "sources", "Sources"))
    body_n = max(0, n - len(front) - len(tail))

    topics = ctx.relevance.topics
    by_topic: dict[str, list] = {t: [s for s in ranked if s.topic == t] for t in topics}
    mass = {t: sum(s.score for s in by_topic[t][:6]) for t in topics}
    active = [t for t in topics if by_topic[t]]
    missing = [t for t in topics if not by_topic[t]]
    warnings = [f"No content matching '{topic_label(t)}' was found in the document." for t in missing]
    if len(active) > body_n:
        keep = set(sorted(active, key=lambda t: -mass[t])[:body_n])
        active = [t for t in active if t in keep]

    # allocate slots: one each, remainder by relevance mass, capped by available material
    alloc = {t: 1 for t in active}
    remaining = body_n - len(active)
    cap = {t: max(1, len(by_topic[t]) // 2) for t in active}
    while remaining > 0 and active:
        cands = [t for t in active if alloc[t] < cap[t]]
        if not cands:
            break
        t = max(cands, key=lambda t: mass[t] / (alloc[t] + 1))
        alloc[t] += 1
        remaining -= 1
    if remaining > 0:
        warnings.append(f"The document only contained enough relevant material for {n - remaining} slides.")

    body: list[Slot] = []
    for t in active:
        k = alloc[t]
        scored = by_topic[t]
        tables = [s for s in scored if cm[s.chunk_id].content_type == ContentType.table and cm[s.chunk_id].table]
        chartable = [s for s in tables if chart_from_table(cm[s.chunk_id])]
        text_pool = [s for s in scored if cm[s.chunk_id].content_type not in (ContentType.table, ContentType.code)]
        text_pool = sorted(text_pool[: max(4, 4 * k)], key=lambda s: cm[s.chunk_id].index)
        table_slot = None
        wants_data = TOPICS.get(t, {}).get("tables") or t in ("results", "findings", "experiments", "benefits")
        if (chartable or tables) and (k >= 2 or (wants_data and len(text_pool) < 3)):
            best = (chartable or tables)[0]
            table_slot = best.chunk_id
            k_text = k - 1
        else:
            k_text = k
        groups = _split(text_pool, k_text) if k_text > 0 else []
        pref = TOPICS.get(t, {}).get("sections", [])
        for gi, group in enumerate(groups):
            # lead with the chunk that best represents the topic (it names the slide)
            ranked_group = sorted(group, key=lambda s: -s.score)
            lead = next((s for s in ranked_group if cm[s.chunk_id].section_type in pref), ranked_group[0])
            ids = [lead.chunk_id] + [s.chunk_id for s in group if s is not lead]
            layout = _choose_layout(t, [cm[i] for i in ids], gi, body)
            hint = clean_heading(cm[ids[0]].section) if ids else topic_label(t)
            body.append(Slot(layout, t, hint, ids))
        if table_slot:
            tchunk = cm[table_slot]
            related = [s.chunk_id for s in scored if cm[s.chunk_id].section == tchunk.section and s.chunk_id != table_slot][:2]
            layout = "chart" if chart_from_table(tchunk) else "table"
            body.append(Slot(layout, t, clean_heading(tchunk.section), [table_slot, *related], table_chunk=table_slot))

    slots = front + body + tail
    log.info("Slide outline created", slides=len(slots), topics=len(active))
    return slots, warnings


def dedupe_titles(slides: list[Slide]) -> None:
    """Two slides must not share a title (e.g. 'Overview' twice): retitle the later one from its content."""
    seen: set[str] = set()
    for s in slides:
        key = s.title.strip().lower()
        if key in seen and s.layout not in ("cover", "references"):
            if s.columns:
                s.title = " & ".join(c.heading for c in s.columns[:2])
            elif s.steps:
                s.title = "How it works"
            elif s.topic and topic_label(s.topic).lower() not in key:
                s.title = f"{s.title}: {topic_label(s.topic)}"
            else:
                s.title = f"{s.title} (continued)"
            key = s.title.strip().lower()
        seen.add(key)


def _split(items: list, k: int) -> list[list]:
    if k <= 0 or not items:
        return []
    k = min(k, len(items))
    size = int(np.ceil(len(items) / k))
    return [items[i * size:(i + 1) * size] for i in range(k) if items[i * size:(i + 1) * size]]


def _choose_layout(topic: str, chunks: list[DocumentChunk], index: int, previous: list[Slot]) -> str:
    text = " ".join(c.text for c in chunks)
    nums = [n for n in numbers_in(text) if "%" in n or "." in n or len(n.rstrip("%")) >= 2]
    has_figure = any(c.image_path for c in chunks)
    sections = {c.section for c in chunks}
    demo = any(c.section.startswith("Scene ") or c.section == "Demo walkthrough" for c in chunks)
    if topic == "architecture":
        layout = "architecture" if index == 0 else "two_column"
    elif topic == "workflow" or (topic == "methodology" and (demo or WORKFLOW_CUES.search(text))):
        layout = "workflow" if index == 0 else ("image_text" if has_figure else "process")
    elif topic in ("methodology", "experiments"):
        layout = "research_methodology" if index == 0 else ("process" if SEQUENCE_CUES.search(text) else "two_column")
    elif topic in ("results", "findings", "benefits", "business_impact"):
        layout = "kpi" if len(nums) >= 4 and index == 0 else ("research_results" if len(nums) >= 2 else "key_findings")
    elif topic == "timeline" or len(TIME_CUES.findall(text)) >= 3:
        layout = "timeline"
    elif topic in ("recommendations", "future_work"):
        layout = "process" if SEQUENCE_CUES.search(text) else "three_column"
    elif COMPARE_CUES.search(text) and len(chunks) >= 2:
        layout = "comparison"
    elif has_figure:
        layout = "image_text"
    elif len(sections) >= 2:
        layout = "two_column"
    else:
        layout = "key_findings"
    recent = [s.layout for s in previous[-2:]]
    if len(recent) == 2 and all(r == layout for r in recent):
        layout = "two_column" if layout != "two_column" else "key_findings"
    return layout


def _summary_chunks(ctx: PlanningContext) -> list[str]:
    ranked = ctx.relevance.ranked()
    cm = ctx.chunk_map
    ids = [s.chunk_id for s in ranked if cm[s.chunk_id].section_type in (SectionType.abstract, SectionType.executive_summary)][:2]
    for t in ctx.relevance.topics:
        ids += [s.chunk_id for s in ranked if s.topic == t and cm[s.chunk_id].content_type == ContentType.paragraph][:1]
    ids += [s.chunk_id for s in ranked[:4]]
    return [i for i in dict.fromkeys(ids) if cm[i].content_type == ContentType.paragraph][:6]


def _conclusion_chunks(ctx: PlanningContext) -> list[str]:
    ranked = ctx.relevance.ranked()
    cm = ctx.chunk_map
    ids = [s.chunk_id for s in ranked if cm[s.chunk_id].section_type in (SectionType.conclusion, SectionType.recommendations)][:3]
    ids += [s.chunk_id for s in ranked if s.topic in ("results", "findings")][:2]
    if len(ids) < 2:
        ids += [s.chunk_id for s in ranked[:4]]
    return [i for i in dict.fromkeys(ids) if cm[i].content_type != ContentType.table][:5]


# ------------------------------------------------------------------ writing
def _sources_block(chunks: list[DocumentChunk], budget: int = 4200) -> tuple[str, dict[str, str]]:
    labels, parts, used = {}, [], 0
    per = max(500, budget // max(1, len(chunks)))
    for i, c in enumerate(chunks):
        label = f"S{i + 1}"
        labels[label] = c.id
        body = c.text if c.content_type != ContentType.table else "TABLE:\n" + c.text
        body = body[:per]
        parts.append(f"[{label}] (section: {clean_heading(c.section)}, page {c.page})\n{body}")
        used += len(body)
        if used > budget:
            break
    return "\n\n".join(parts), labels


def _map_ids(ids: list[str], labels: dict[str, str]) -> list[str]:
    out = []
    for s in ids:
        key = str(s).strip().strip("[]").upper()
        if not key.startswith("S"):
            key = f"S{key}"
        if key in labels:
            out.append(labels[key])
    return list(dict.fromkeys(out))


def llm_write(ctx: PlanningContext, slide: Slide, guidance: str = "", temperature: Optional[float] = None) -> Optional[SlideDraft]:
    if ctx.llm is None:
        return None
    chunks = [ctx.chunk_map[c] for c in slide.candidate_chunks if c in ctx.chunk_map]
    if not chunks:
        return None
    src_text, labels = _sources_block(chunks)
    c = ctx.contract
    instruction = c.raw_instruction + (f"\nAdditional guidance for this slide: {guidance}" if guidance else "")
    prompt = load_prompt("slide_writer").render(
        slide_number=slide.slide_number, slide_count=c.slide_count, deck_title=ctx.doc_title,
        audience=c.audience.replace("_", " "), tone=c.tone, detail_level=c.detail_level,
        instruction=instruction, topic=slide.topic or slide.title, layout=slide.layout,
        layout_guidance=layout_guidance(slide.layout), sources=src_text, max_words=SPECS[slide.layout].max_words,
        exclude=", ".join(c.exclude) or "nothing specified",
    )
    try:
        draft = generate_structured(ctx.llm, prompt, SlideDraft, system=system_prompt(), retries=1, max_tokens=900)
    except (LLMUnavailable, StructuredOutputError) as exc:
        log.warning("LLM slide writing failed; using extractive writer", slide=slide.slide_number, reason=type(exc).__name__)
        return None
    # translate S-labels to chunk ids
    for p in draft.points:
        p.sources = _map_ids(p.sources, labels)
    for col in draft.columns:
        for p in col.points:
            p.sources = _map_ids(p.sources, labels)
    for s in draft.steps:
        s.sources = _map_ids(s.sources, labels)
    for k in draft.kpis:
        k.sources = _map_ids(k.sources, labels)
    if draft.quote:
        draft.quote.sources = _map_ids(draft.quote.sources, labels)
    draft.narration = re.sub(r"\[?S\d+\]?", "", draft.narration).strip()
    return draft


CITATION = re.compile(r"\s*[\[(]\s*S\d+(?:\s*[,;/&]\s*S?\d+)*\s*[\])]")


def _strip_citations(d: SlideDraft) -> None:
    """Source labels belong in `sources`, never in visible text ('... 68%. [S1, S2]')."""
    clean = lambda t: CITATION.sub("", t or "").strip()  # noqa: E731
    d.title, d.subtitle = clean(d.title), clean(d.subtitle)
    for p in d.points:
        p.text = clean(p.text)
    for c in d.columns:
        c.heading = clean(c.heading)
        for p in c.points:
            p.text = clean(p.text)
    for s in d.steps:
        s.title, s.description = clean(s.title), clean(s.description)
    for k in d.kpis:
        k.value, k.label = clean(k.value), clean(k.label)
    if d.quote:
        d.quote.text = clean(d.quote.text)


def apply_draft(slide: Slide, d: SlideDraft) -> Slide:
    _strip_citations(d)
    slide.title = d.title.strip() or slide.title
    if d.subtitle:
        slide.subtitle = d.subtitle.strip()
    slide.key_points = [Claim(text=p.text.strip(), sources=p.sources) for p in d.points if p.text.strip()]
    slide.columns = [Column(heading=c.heading.strip(), points=[Claim(text=p.text.strip(), sources=p.sources) for p in c.points if p.text.strip()])
                     for c in d.columns if c.heading.strip()]
    steps = []
    for i, s in enumerate(d.steps):
        title, desc = s.title.strip(), s.description.strip()
        if not title and not desc:
            continue
        if not desc and len(title.split()) > 5:  # small models sometimes put the whole step in the title
            title, desc = f"Step {i + 1}", title
        steps.append(Step(title=title or f"Step {i + 1}", description=desc, sources=s.sources))
    slide.steps = steps
    slide.kpis = [KPI(value=k.value.strip(), label=k.label.strip(), sources=k.sources) for k in d.kpis if k.value.strip()]
    slide.quote = Claim(text=d.quote.text.strip().strip('"'), sources=d.quote.sources) if d.quote and d.quote.text.strip() else None
    slide.narration = d.narration.strip()
    return slide


class ExtractiveWriter:
    """No-LLM writer: selects and trims real source sentences (never paraphrases facts)."""

    def __init__(self, ctx: PlanningContext):
        self.ctx = ctx

    def sentences(self, slide: Slide) -> list[tuple[str, str]]:
        out = []
        for cid in slide.candidate_chunks:
            ch = self.ctx.chunk_map.get(cid)
            if not ch or ch.content_type in (ContentType.table, ContentType.figure, ContentType.code, ContentType.caption):
                continue
            for s in split_sentences(ch.text.replace("\n- ", "\n").replace("\n", " ")):
                s = s.strip("- ").strip()
                if re.match(r"^(table|figure|fig\.)\s*\d", s, re.I):
                    continue
                if 30 <= len(s) <= 320 and not re.match(r"^(and|but|or|however|this|these|it)\b", s, re.I):
                    out.append((s, cid))
        return out

    def select(self, slide: Slide, k: int, prefer_numbers: bool = False) -> list[tuple[str, str]]:
        sents = self.sentences(slide)
        if not sents:
            return []
        emb = self.ctx.embedder
        q = f"{slide.topic.replace('_', ' ')} {slide.title} {self.ctx.contract.raw_instruction}"
        vecs = emb.encode([s for s, _ in sents])
        qv = emb.encode([q])[0]
        base = vecs @ qv
        if prefer_numbers:
            base = base + np.array([0.15 if numbers_in(s) else 0.0 for s, _ in sents])
        chosen: list[int] = []
        while len(chosen) < min(k, len(sents)):  # maximal marginal relevance for diversity
            best, best_score = None, -9.0
            for i in range(len(sents)):
                if i in chosen:
                    continue
                redundancy = max((float(vecs[i] @ vecs[j]) for j in chosen), default=0.0)
                score = 0.7 * float(base[i]) - 0.3 * redundancy
                if score > best_score:
                    best, best_score = i, score
            chosen.append(best)
        return [sents[i] for i in chosen]

    def write(self, slide: Slide) -> Slide:
        lay = slide.layout
        spec = SPECS[lay]
        if not slide.title:
            first = self.ctx.chunk_map.get(slide.candidate_chunks[0]) if slide.candidate_chunks else None
            slide.title = clean_heading(first.section) if first else topic_label(slide.topic)
            if slide.title.startswith("Scene "):  # demo video scene headings are not slide titles
                slide.title = "Demo walkthrough" if lay in ("workflow", "process") else "What the demo shows"
        if lay in ("two_column", "three_column", "comparison"):
            ncols = 3 if lay == "three_column" else 2
            by_sec: dict[str, list[str]] = {}
            for cid in slide.candidate_chunks:
                ch = self.ctx.chunk_map.get(cid)
                if ch:
                    by_sec.setdefault(clean_heading(ch.section), []).append(cid)
            if len(by_sec) >= ncols:
                cols = []
                for heading, ids in list(by_sec.items())[:ncols]:
                    sub = Slide(slide_number=0, layout="key_findings", topic=slide.topic, title=heading, candidate_chunks=ids)
                    picks = self.select(sub, 2 if ncols == 3 else 3)
                    cols.append(Column(heading=heading, points=[Claim(text=s, sources=[c]) for s, c in picks]))
                slide.columns = cols
            else:
                slide.layout = "key_findings"
                return self.write(slide)
        elif lay in ("process", "workflow", "timeline", "research_methodology"):
            picks = self._ordered(self.select(slide, 5))
            steps = []
            for i, (s, cid) in enumerate(picks):
                m = re.match(r"^([A-Z][\w /&-]{2,40}?)(?::| - | – )\s*(.+)$", s)
                if m:
                    steps.append(Step(title=m.group(1), description=m.group(2), sources=[cid]))
                elif lay == "timeline" and (tm := TIME_CUES.search(s)):
                    steps.append(Step(title=tm.group(0), description=s, sources=[cid]))
                else:
                    steps.append(Step(title=f"Step {i + 1}" if lay != "timeline" else f"Phase {i + 1}", description=s, sources=[cid]))
            slide.steps = steps
        elif lay in ("kpi", "research_results"):
            picks = self.select(slide, 8, prefer_numbers=True)
            kpis, rest = [], []
            for s, cid in picks:
                m = kpi_number(s)
                if m and len(kpis) < 3:
                    label = shorten((s[:m.start()] + s[m.end():]).strip(" ,.;:"), 8)
                    kpis.append(KPI(value=m.group(0).strip(), label=label, sources=[cid]))
                else:
                    rest.append((s, cid))
            slide.kpis = kpis
            slide.key_points = [Claim(text=s, sources=[c]) for s, c in rest[:2 if lay == "kpi" else 3]]
        elif lay == "quote":
            picks = self.select(slide, 1)
            slide.quote = Claim(text=picks[0][0], sources=[picks[0][1]]) if picks else None
        elif lay == "architecture":
            slide.key_points = [Claim(text=s, sources=[c]) for s, c in self.select(slide, 3)]
        else:
            slide.key_points = [Claim(text=s, sources=[c]) for s, c in self.select(slide, spec.max_items, prefer_numbers=lay in ("chart", "table"))]
        full = [s for s, _ in self.select(slide, 3)]
        slide.narration = " ".join(full)
        return slide

    def _ordered(self, picks: list[tuple[str, str]]) -> list[tuple[str, str]]:
        order = {cid: self.ctx.chunk_map[cid].index for _, cid in picks}
        return sorted(picks, key=lambda p: (order[p[1]], self.ctx.chunk_map[p[1]].text.find(p[0])))


# ------------------------------------------------------------------ planner
class ContentPlanner:
    def __init__(self, ctx: PlanningContext):
        self.ctx = ctx
        self.extractive = ExtractiveWriter(ctx)

    def subtitle(self) -> str:
        c = self.ctx.contract
        purpose = c.purpose.replace("_", " ").strip().capitalize() if c.purpose != "presentation" else "Presentation"
        focus = [topic_label(t) for t in self.ctx.relevance.topics[:3]] if c.include else []
        return f"{purpose} · {' & '.join(focus)}" if focus else purpose

    def build(self, on_progress: Optional[Callable[[int, int], None]] = None) -> ContentPlan:
        slots, warnings = build_outline(self.ctx)
        slides: list[Slide] = []
        for i, slot in enumerate(slots, start=1):
            slide = Slide(slide_number=i, layout=slot.layout, topic=slot.topic, title="" if slot.layout not in ("executive_summary", "conclusion") else slot.title_hint,
                          candidate_chunks=slot.chunk_ids)
            slides.append(self.write_slide(slide, slot.table_chunk))
            if on_progress:
                on_progress(i, len(slots))
        self.finalize_references(slides)
        dedupe_titles(slides)
        plan = ContentPlan(title=self.ctx.doc_title, subtitle=self.subtitle(), contract=self.ctx.contract, slides=slides,
                           warnings=warnings)
        log.info("Content plan created", slides=len(slides),
                 needs_review=sum(1 for s in slides if s.needs_review))
        return plan

    def write_slide(self, slide: Slide, table_chunk: Optional[str] = None, guidance: str = "",
                    temperature: Optional[float] = None) -> Slide:
        ctx = self.ctx
        if slide.layout == "cover":
            slide.title = shorten(ctx.doc_title, 14)
            slide.subtitle = self.subtitle()
            slide.narration = f"{slide.title}. {slide.subtitle.replace('·', '-')}."
            return slide
        if slide.layout == "references":
            slide.title = slide.title or "Sources"
            return slide
        if table_chunk is None:
            table_chunk = next((c for c in slide.candidate_chunks if c in ctx.chunk_map and ctx.chunk_map[c].table), None) \
                if slide.layout in ("chart", "table", "research_results") else None
        if table_chunk and table_chunk in ctx.chunk_map:
            tch = ctx.chunk_map[table_chunk]
            slide.chart = chart_from_table(tch) if slide.layout in ("chart", "research_results") else None
            slide.table = table_from_chunk(tch) if slide.layout == "table" or (slide.layout == "chart" and not slide.chart) else None
            if slide.layout == "chart" and not slide.chart:
                slide.layout = "table"
        keep_title = slide.title
        draft = llm_write(ctx, slide, guidance, temperature)
        if draft is not None:
            apply_draft(slide, draft)
            if slide.layout in ("executive_summary", "conclusion") and keep_title and len(slide.title.split()) > 8:
                slide.title = keep_title
            slide.speaker_notes = ""
        else:
            slide.key_points, slide.columns, slide.steps, slide.kpis, slide.quote = [], [], [], [], None
            self.extractive.write(slide)
        slide = enforce_limits(slide)
        slide = ctx.verifier.verify_slide(slide, drop_unverified=ctx.drop_unverified)
        slide = apply_fallback(slide)
        slide = attach_visual(slide, ctx.chunk_map, ctx.llm, ctx.doc_graphs)
        if not slide.narration:
            slide.narration = ". ".join(p.text.rstrip(".…") for p in slide.key_points[:3])
        slide.sources = self.slide_sources(slide)
        return slide

    def slide_sources(self, slide: Slide) -> list[SourceReference]:
        ids: list[str] = []
        for p in slide.key_points:
            ids += p.sources
        for c in slide.columns:
            for p in c.points:
                ids += p.sources
        for s in slide.steps:
            ids += s.sources
        for k in slide.kpis:
            ids += k.sources
        if slide.quote:
            ids += slide.quote.sources
        if slide.chart:
            ids.append(slide.chart.source)
        if slide.table:
            ids.append(slide.table.source)
        if slide.visual:
            ids += slide.visual.sources
        return [self.ctx.chunk_map[i].ref() for i in dict.fromkeys(ids) if i in self.ctx.chunk_map]

    def finalize_references(self, slides: list[Slide]) -> None:
        for ref_slide in (s for s in slides if s.layout == "references"):
            seen: dict[str, SourceReference] = {}
            for s in slides:
                if s is ref_slide:
                    continue
                for r in s.sources:
                    key = f"{r.section}|{r.page}"
                    seen.setdefault(key, r)
            refs = sorted(seen.values(), key=lambda r: (r.page or 0))
            ref_slide.key_points = [Claim(text=_ref_line(r), sources=[r.chunk_id], confidence=1.0, status="structural")
                                    for r in refs[:14]]
            ref_slide.sources = refs
            ref_slide.narration = "The content in this presentation is drawn directly from the source document, with page and section references for every slide."

    def regenerate_slide(self, slide: Slide, layout: Optional[str] = None, guidance: str = "") -> Slide:
        new = Slide(slide_number=slide.slide_number, layout=layout or slide.layout, topic=slide.topic,
                    title=slide.title if slide.layout in ("executive_summary", "conclusion", "references") else "",
                    candidate_chunks=slide.candidate_chunks, accent_role=slide.accent_role)
        table_chunk = (slide.chart.source if slide.chart else slide.table.source if slide.table else None)
        return self.write_slide(new, table_chunk, guidance, temperature=0.5)


def kpi_number(sentence: str) -> Optional[re.Match]:
    """Pick the most metric-like number in a sentence: percentages, then decimals, then
    3+ digit values. Years and citation markers like [2] are never KPIs."""
    cands = []
    for m in NUMBER.finditer(sentence):
        tok = m.group(0)
        bare = tok.replace(",", "").rstrip("%")
        before = sentence[max(0, m.start() - 1):m.start()]
        if before == "[" or re.fullmatch(r"(19|20)\d{2}", bare):
            continue
        rank = 0 if tok.endswith("%") else 1 if "." in bare else 2 if len(bare) >= 3 else 9
        if rank < 9:
            cands.append((rank, m.start(), m))
    # a sentence with several metrics ("from 71.4% to 84.9%") cannot be reduced to one KPI safely
    return cands[0][2] if len(cands) == 1 else None


def _ref_line(r: SourceReference) -> str:
    parts = [clean_heading(r.section) or "Document"]
    if r.page:
        parts.append(f"p. {r.page}" if not r.page_end or r.page_end == r.page else f"pp. {r.page}–{r.page_end}")
    if r.table:
        parts.append(f"Table {r.table}")
    if r.figure:
        parts.append(f"Figure {r.figure}")
    return " · ".join(parts)
