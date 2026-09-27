"""Developer smoke test for rendering: builds an extractive plan and renders PPTX + PNG + SVG + visuals.

    python scripts/smoke_render.py tests/fixtures/sample_research.pdf <out_dir> [brand_id]
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.branding.brand_profile import BrandProfile, BrandStore, ensure_default_brands  # noqa: E402
from backend.branding.theme import build_theme  # noqa: E402
from backend.extraction.structure import analyze_structure  # noqa: E402
from backend.ingestion import get_adapter  # noqa: E402
from backend.intelligence.chunking import chunk_document  # noqa: E402
from backend.intelligence.embeddings import get_embedder  # noqa: E402
from backend.intelligence.relevance import rank_chunks  # noqa: E402
from backend.intelligence.verification import Verifier  # noqa: E402
from backend.planning.content_contract import parse_instruction  # noqa: E402
from backend.planning.content_planner import ContentPlanner, PlanningContext  # noqa: E402
from backend.rendering.images.raster import RasterRenderer  # noqa: E402
from backend.rendering.images.svg import SVGRenderer  # noqa: E402
from backend.rendering.layouts import RenderContext, build_slide_scene, build_visual_scene  # noqa: E402
from backend.rendering.ppt.generator import PPTXGenerator  # noqa: E402

src, out = Path(sys.argv[1]), Path(sys.argv[2])
brand_id = sys.argv[3] if len(sys.argv) > 3 else "zensar"
t0 = time.time()
work = Path(tempfile.mkdtemp())
doc = get_adapter(src).extract(src, "doc1", work)
chunks = chunk_document(doc, analyze_structure(doc))
contract = parse_instruction("Create a 10-slide technical presentation for a senior client audience. Focus on architecture, "
                             "methodology and results. Do not include detailed implementation code.")
emb = get_embedder()
rel = rank_chunks(contract, chunks, emb.encode([c.text for c in chunks]), emb)
cm = {c.id: c for c in chunks}
plan = ContentPlanner(PlanningContext("doc1", src.name, doc.title, chunks, contract, rel, emb, Verifier(cm, emb))).build()
print(f"plan {time.time() - t0:.1f}s")

ensure_default_brands()
theme = build_theme(BrandStore().load(brand_id))
print("fallbacks:", theme.fallbacks)
ctx = RenderContext(plan, work)
scenes = [build_slide_scene(s, theme, ctx) for s in plan.slides]
print(f"scenes {time.time() - t0:.1f}s")
PPTXGenerator(theme).build(scenes, out / "presentation.pptx", plan.title)
print(f"pptx {time.time() - t0:.1f}s")
rr = RasterRenderer(1920)
for sc in scenes:
    rr.save(sc, out / "slides" / f"{sc.name}.png")
print(f"png {time.time() - t0:.1f}s")
for s in plan.slides:
    v = build_visual_scene(s, theme, ctx)
    if v:
        rr.save(v, out / "images" / f"{v.name}.png")
        SVGRenderer().save(v, out / "images" / f"{v.name}.svg")
print(f"visuals {time.time() - t0:.1f}s")
