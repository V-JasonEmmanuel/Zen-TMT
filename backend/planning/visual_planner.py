"""Visual planning: which slides get which visual, built from verified content only.

Charts are derived deterministically from extracted tables (numbers are copied, never
generated). Architecture/workflow graphs come from the LLM when available (restricted to
named components in the sources) or from document structure otherwise.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from backend.llm.base import LLMProvider, LLMUnavailable
from backend.llm.prompts import load_prompt, system_prompt
from backend.llm.structured_output import StructuredOutputError, generate_structured
from backend.schemas import ChartData, ChartSeries, DocumentChunk, GraphEdge, GraphNode, Slide, TableData, Visual
from backend.utils.logging import get_logger

log = get_logger(__name__)
NUM_CELL = re.compile(r"^[-+]?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|x|ms|s|k|m|bn)?(?:\s*(?:±|\+/-|\()\s*[\d.]+\)?)?\s*$", re.I)


def parse_number(cell: str) -> Optional[tuple[float, str]]:
    m = NUM_CELL.match((cell or "").strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "")), (m.group(2) or "")
    except ValueError:
        return None


def column_unit(header: str, cell_unit: str) -> str:
    m = re.search(r"\(([^)]{1,12})\)\s*$|\[([^\]]{1,12})\]\s*$", header or "")
    unit = (m.group(1) or m.group(2)) if m else cell_unit
    return (unit or "").strip().lower()


def table_from_chunk(chunk: DocumentChunk, max_rows: int = 8, max_cols: int = 6) -> Optional[TableData]:
    rows = chunk.table or []
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [(r + [""] * width)[:width] for r in rows]
    headers, body = rows[0][:max_cols], [r[:max_cols] for r in rows[1:max_rows + 1]]
    caption = f"Table {chunk.table_index}" if chunk.table_index else "Table"
    return TableData(headers=headers, rows=body, caption=caption, source=chunk.id)


def chart_from_table(chunk: DocumentChunk) -> Optional[ChartData]:
    """Build a chart only when the table has a label column and >=1 mostly-numeric column."""
    rows = [r for r in (chunk.table or []) if any(c.strip() for c in r)]
    if len(rows) < 3:
        return None
    width = max(len(r) for r in rows)
    rows = [(r + [""] * width)[:width] for r in rows]
    header, body = rows[0], rows[1:]
    numeric_cols, units = [], {}
    for j in range(width):
        parsed = [parse_number(r[j]) for r in body]
        ok = [p for p in parsed if p]
        if len(ok) >= max(2, int(len(body) * 0.7)):
            numeric_cols.append(j)
            us = {p[1] for p in ok if p[1]}
            units[j] = us.pop() if len(us) == 1 else ""
    label_col = next((j for j in range(width) if j not in numeric_cols), None)
    if label_col is None or not numeric_cols:
        return None
    numeric_cols = [j for j in numeric_cols if j != label_col]
    # never mix units on one axis (e.g. "Accuracy (%)" with "Latency (ms)"): keep the largest same-unit group
    groups: dict[str, list[int]] = {}
    for j in numeric_cols:
        groups.setdefault(column_unit(header[j], units.get(j, "")), []).append(j)
    numeric_cols = max(groups.values(), key=len)[:3] if groups else []
    body = [r for r in body if r[label_col].strip() and all(parse_number(r[j]) for j in numeric_cols)][:8]
    if len(body) < 2 or not numeric_cols:
        return None
    # metrics-in-rows tables ("Resolution time (hours)", "FCR (%)", "Backlog (tickets)") would put
    # different units on one axis - show those as a table instead
    if len({column_unit(r[label_col], "") for r in body}) > 1:
        return None
    series = [ChartSeries(name=header[j] or f"Series {k + 1}", values=[parse_number(r[j])[0] for r in body])
              for k, j in enumerate(numeric_cols)]
    unit = units.get(numeric_cols[0], "") or ("%" if column_unit(header[numeric_cols[0]], "") == "%" else "")
    cats = [r[label_col][:28] for r in body]
    title = f"Table {chunk.table_index}" if chunk.table_index else ""
    return ChartData(chart_type="bar" if max(len(c) for c in cats) > 14 else "column", title=title,
                     categories=cats, series=series, unit=unit, source=chunk.id)


class GraphDraft(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


def architecture_graph(chunks: list[DocumentChunk], llm: Optional[LLMProvider], kind: str = "architecture") -> Visual:
    ids = [c.id for c in chunks]
    if llm is not None and chunks:
        try:
            sources = "\n\n".join(f"[S{i + 1}] {c.text[:900]}" for i, c in enumerate(chunks[:4]))
            p = load_prompt("visual_planner").render(kind=kind, sources=sources)
            g = generate_structured(llm, p, GraphDraft, system=system_prompt(), retries=1, max_tokens=600)
            evidence = " ".join(c.text.lower() for c in chunks)
            # keep only nodes whose label words actually appear in the sources
            nodes = [n for n in g.nodes if n.label and sum(w in evidence for w in re.findall(r"[a-z0-9]+", n.label.lower())) >= 1][:8]
            valid = {n.id for n in nodes}
            edges = [e for e in g.edges if e.source in valid and e.target in valid and e.source != e.target][:12]
            if len(nodes) >= 3:
                return Visual(kind="architecture" if kind == "architecture" else "workflow", nodes=nodes, edges=edges, sources=ids)
        except (LLMUnavailable, StructuredOutputError, KeyError) as exc:
            log.warning("Graph extraction via LLM unavailable", reason=type(exc).__name__)
    # deterministic fallback: list items / short lines in the sources become components
    labels: list[str] = []
    for c in chunks:
        for line in c.text.split("\n"):
            line = line.strip("-• ").strip()
            m = re.match(r"^([A-Z][A-Za-z0-9 /&-]{2,40}?)(?::| - | – )", line)
            if m:
                labels.append(m.group(1).strip())
            elif line.startswith(("- ",)) or (3 <= len(line.split()) <= 5 and not line.endswith(".")):
                labels.append(line[:40])
    labels = list(dict.fromkeys(labels))[:6]
    if len(labels) < 3:
        return Visual(kind="none")
    nodes = [GraphNode(id=f"n{i}", label=l) for i, l in enumerate(labels)]
    edges = [GraphEdge(source=f"n{i}", target=f"n{i + 1}") for i in range(len(nodes) - 1)]
    return Visual(kind="workflow", nodes=nodes, edges=edges, sources=ids)


def attach_visual(slide: Slide, chunks: dict[str, DocumentChunk], llm: Optional[LLMProvider],
                  graphs: Optional[dict] = None) -> Slide:
    """Decide the slide's visual from its layout and verified content."""
    lay = slide.layout
    if lay in ("process", "workflow", "research_methodology") and slide.steps:
        slide.visual = Visual(kind="process", title=slide.title, sources=[s for st in slide.steps for s in st.sources])
    elif lay == "timeline" and slide.steps:
        slide.visual = Visual(kind="timeline", title=slide.title, sources=[s for st in slide.steps for s in st.sources])
    elif lay in ("kpi", "research_results") and slide.kpis:
        slide.visual = Visual(kind="kpi_cards", title=slide.title, sources=[s for k in slide.kpis for s in k.sources])
    elif lay in ("chart", "research_results") and slide.chart:
        slide.visual = Visual(kind="chart", title=slide.chart.title or slide.title, chart=slide.chart, sources=[slide.chart.source])
    elif lay == "comparison" and len(slide.columns) == 2:
        slide.visual = Visual(kind="comparison", title=slide.title)
    elif lay == "architecture":
        if not (slide.visual and slide.visual.nodes) and graphs:
            # code repositories carry a dependency graph measured from real imports - prefer it
            doc_ids = [chunks[c].document_id for c in slide.candidate_chunks if c in chunks]
            g = next((graphs[d] for d in doc_ids if d in graphs and graphs[d].get("nodes")), None)
            if g and len(g["nodes"]) >= 2:
                slide.visual = Visual(kind="architecture", nodes=[GraphNode(**n) for n in g["nodes"]],
                                      edges=[GraphEdge(**e) for e in g["edges"]],
                                      sources=[c for c in slide.candidate_chunks if c in chunks][:4])
        if not (slide.visual and slide.visual.nodes):
            cands = [chunks[c] for c in slide.candidate_chunks if c in chunks][:4]
            v = architecture_graph(cands, llm, "architecture")
            slide.visual = v if v.kind != "none" else None
        if slide.visual:
            slide.visual.title = slide.title
    elif lay in ("text_image", "image_text"):
        fig = next((chunks[c] for c in slide.candidate_chunks if c in chunks and chunks[c].image_path), None)
        if fig and not (slide.visual and slide.visual.kind == "document_figure"):
            slide.visual = Visual(kind="document_figure", image_path=f"{fig.document_id}/{fig.image_path}", caption=fig.text[:120],
                                  title=slide.title, sources=[fig.id])
    elif lay == "table" and slide.table:
        slide.visual = Visual(kind="table", title=slide.title, sources=[slide.table.source])
    return slide
