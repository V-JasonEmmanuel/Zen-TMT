"""Developer smoke test: ingest -> structure -> chunks -> contract -> relevance -> plan (no rendering).

    python scripts/smoke_pipeline.py <file> "<instruction>" [--llm]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.extraction.structure import analyze_structure  # noqa: E402
from backend.ingestion import get_adapter  # noqa: E402
from backend.intelligence.chunking import chunk_document  # noqa: E402
from backend.intelligence.embeddings import get_embedder  # noqa: E402
from backend.intelligence.relevance import rank_chunks  # noqa: E402
from backend.intelligence.verification import Verifier  # noqa: E402
from backend.planning.content_contract import parse_instruction  # noqa: E402
from backend.planning.content_planner import ContentPlanner, PlanningContext  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("instruction")
ap.add_argument("--llm", action="store_true")
a = ap.parse_args()

t0 = time.time()
path = Path(a.file)
work = Path(tempfile.mkdtemp())
doc = get_adapter(path).extract(path, "doc1", work)
st = analyze_structure(doc)
chunks = chunk_document(doc, st)
print(f"blocks={len(doc.blocks)} sections={[(s.title, s.section_type.value) for s in st.sections]} chunks={len(chunks)}")
llm = None
if a.llm:
    from backend.llm import get_llm

    llm = get_llm()
contract = parse_instruction(a.instruction, llm, [s.title for s in st.sections])
print("contract:", contract.model_dump(exclude={"raw_instruction"}))
emb = get_embedder()
vecs = emb.encode([c.text for c in chunks])
rel = rank_chunks(contract, chunks, vecs, emb)
cm = {c.id: c for c in chunks}
for s in rel.ranked(include_excluded=True)[:40]:
    c = cm[s.chunk_id]
    print(f"  {s.score:.2f} {'X' if s.excluded else ' '} [{s.topic:14}] {c.section[:22]:22} {c.content_type.value:9} {c.text[:60]!r} {s.reason}")
ctx = PlanningContext("doc1", path.name, doc.title, chunks, contract, rel, emb, Verifier(cm, emb), llm)
plan = ContentPlanner(ctx).build(lambda i, n: print(f"  slide {i}/{n} {time.time() - t0:.0f}s"))
for s in plan.slides:
    print(f"\n#{s.slide_number} [{s.layout}] {s.title} | {s.subtitle}")
    for p in s.key_points:
        print(f"   - ({p.status} {p.confidence:.2f}) {p.text}")
    for c in s.columns:
        print(f"   [{c.heading}] " + " / ".join(f"({p.status[:4]}) {p.text}" for p in c.points))
    for st_ in s.steps:
        print(f"   > ({st_.status[:4]}) {st_.title}: {st_.description}")
    for k in s.kpis:
        print(f"   # ({k.status[:4]}) {k.value} - {k.label}")
    if s.chart:
        print(f"   chart: {s.chart.categories} {[x.name for x in s.chart.series]}")
    if s.visual:
        print(f"   visual: {s.visual.kind} nodes={[n.label for n in s.visual.nodes]}")
    print(f"   sources: {[r.label for r in s.sources][:4]}  warnings={s.warnings}")
print(f"\nplan warnings: {plan.warnings}  total {time.time() - t0:.1f}s")
