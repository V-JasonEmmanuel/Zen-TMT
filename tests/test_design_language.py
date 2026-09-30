"""Zensar Experience design language (from Zensar's LinkedIn posts) and the no-blank-slides guarantee."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from backend.schemas import Claim, ContentPlan, ContentContract, Slide, Step

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def xtheme():
    """The real Zensar brand (official tokens + social.json) copied into the test brand store."""
    from backend.branding.brand_profile import BrandStore
    from backend.branding.presets import apply_preset
    from backend.branding.theme import build_theme

    store = BrandStore()
    d = store.dir("zensar_x")
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(ROOT / "brands" / "zensar", d)
    b = json.loads((d / "brand.json").read_text(encoding="utf-8"))
    b["id"] = "zensar_x"
    (d / "brand.json").write_text(json.dumps(b), encoding="utf-8")
    return apply_preset(build_theme(store.load("zensar_x"), store), "zensar_experience")


def test_social_tokens_are_measured_and_sourced():
    spec = json.loads((ROOT / "brands" / "zensar" / "social.json").read_text(encoding="utf-8"))
    assert spec["sources"] and all(s.startswith("https://www.linkedin.com/") for s in spec["sources"])
    for role, v in spec["colors"].items():
        assert role.startswith("li_") and v["hex"].startswith("#") and len(v["hex"]) == 7 and v["where"]


def test_experience_theme(xtheme):
    t = xtheme
    assert t.design == "experience"
    assert t.c("li_mustard") == "#E3C473" and t.c("li_teal") == "#86C7C2" and t.c("li_sage") == "#9BB795"
    assert t.logo_position == "top_right" and t.footer_text == "An RPG Company"
    assert t.c("primary") == "#10005D"  # official tokens are untouched


def _plan(slides):
    return ContentPlan(contract=ContentContract(), slides=slides, title="Demo")


def test_experience_slides_have_the_language(xtheme):
    from backend.rendering.layouts import RenderContext, build_slide_scene

    slides = [Slide(slide_number=1, layout="cover", title="InvoiceFlow", subtitle="Client briefing"),
              Slide(slide_number=2, layout="key_findings", title="Highlights", topic="results",
                    key_points=[Claim(text="Processing time fell to 42 seconds.", status="structural")])]
    ctx = RenderContext(_plan(slides))
    cover = build_slide_scene(slides[0], xtheme, ctx)
    names = {getattr(e, "name", "") for e in cover.elements}
    assert {"background_art", "li_sage", "li_quarter", "li_triangle", "li_square", "logo"} <= names
    content = build_slide_scene(slides[1], xtheme, ctx)
    names = {getattr(e, "name", "") for e in content.elements}
    assert {"section_label", "title", "li_quarter", "logo"} <= names


def _ink(img, bg) -> float:
    a = np.asarray(img.convert("RGB")).astype(int)
    b = np.array(bg, int)
    h = a.shape[0]
    body = a[int(h * 0.25):int(h * 0.85)]  # content area, below the title
    return float((np.abs(body - b).sum(axis=2) > 40).mean())


@pytest.mark.parametrize("layout", ["key_findings", "executive_summary", "two_column", "three_column", "process", "workflow",
                                    "timeline", "architecture", "kpi", "chart", "table", "quote", "text_image", "comparison",
                                    "research_methodology", "research_results", "conclusion"])
def test_no_blank_slide_for_any_layout(xtheme, layout):
    """A slide whose content was lost (e.g. dropped as unverifiable) still renders visible content."""
    from backend.branding.theme import hex_to_rgb
    from backend.rendering.images.raster import RasterRenderer
    from backend.rendering.layouts import RenderContext, build_slide_scene

    empty = Slide(slide_number=3, layout=layout, title="Empty slide", topic="results",
                  narration="The pilot processed invoices end to end. Approval became automatic below the threshold.")
    bare = Slide(slide_number=4, layout=layout, title="Nothing at all", topic="results")
    ctx = RenderContext(_plan([empty, bare]))
    rr = RasterRenderer(640)
    for s in (empty, bare):
        scene = build_slide_scene(s, xtheme, ctx)
        img = rr.render(scene)
        assert _ink(img, hex_to_rgb(scene.background)) > 0.004, f"{layout}: slide {s.slide_number} renders blank"


def test_planner_prunes_empty_slides():
    from backend.planning.content_planner import prune_empty

    slides = [Slide(slide_number=1, layout="cover", title="T"),
              Slide(slide_number=2, layout="key_findings", title="Empty"),
              Slide(slide_number=3, layout="process", title="Flow", steps=[Step(title="A", description="a"), Step(title="B", description="b")]),
              Slide(slide_number=4, layout="references", title="Sources")]
    kept = prune_empty(slides)
    assert [s.title for s in kept] == ["T", "Flow", "Sources"]
    assert [s.slide_number for s in kept] == [1, 2, 3]


def test_brand_cards_and_transition_use_the_language(xtheme):
    from PIL import Image

    from backend.rendering.experience import brand_card
    from backend.rendering.video.motion import slide_frames, transition_frame

    for kind in ("intro", "outro"):
        g = slide_frames(brand_card(xtheme, kind), xtheme, 480, 12, "subtle", "none", None)
        frames = []
        try:
            while True:
                frames.append(next(g))
        except StopIteration as stop:
            final = stop.value
        assert 0 < len(frames) / 12 < 2.6  # the build fits the intro/outro slot
        a = np.asarray(final.convert("RGB")).astype(int)
        assert a.std() > 20  # gradient/wave + shapes + wordmark, never a flat frame
    black, white = Image.new("RGB", (320, 180), "black"), Image.new("RGB", (320, 180), "white")
    mid = np.asarray(transition_frame("zensar_grid", black, white, 0.5, xtheme)).reshape(-1, 3)
    colours = {tuple(c) for c in mid[:: 97]}
    assert (0xE3, 0xC4, 0x73) in colours or (0x86, 0xC7, 0xC2) in colours  # mustard / teal tiles


def test_docx_embedded_figures_are_extracted(tmp_path):
    """Diagrams pasted into Word documents become figures the planner can place on slides."""
    import sys

    sys.path.insert(0, str(ROOT / "samples"))
    from make_showcase import architecture_png, showcase_docx

    from backend.ingestion.base import get_adapter

    doc = showcase_docx(tmp_path / "s.docx", architecture_png(tmp_path / "fig.png"))
    out = get_adapter(doc).extract(doc, "doc_fig", tmp_path / "work")
    figs = [b for b in out.blocks if b.type.value == "figure"]
    assert len(figs) == 1 and (tmp_path / "work" / figs[0].image_path).exists()
    assert sum(1 for b in out.blocks if b.type.value == "table") == 2


def test_repo_graph_only_for_repository_slides():
    """With a document and a repository in one project, the document's architecture slide must not
    get the code's dependency diagram (and a repository slide must)."""
    from backend.planning.visual_planner import attach_visual
    from backend.schemas import DocumentChunk

    ch = {
        "d1": DocumentChunk(id="d1", document_id="doc", index=0, page=1, page_end=1, text="Upload Service sends invoices to the Rules Engine."),
        "d2": DocumentChunk(id="d2", document_id="doc", index=1, page=1, page_end=1, text="The ERP Connector exports invoices."),
        "r1": DocumentChunk(id="r1", document_id="repo", index=0, page=1, page_end=1, text="The api module imports planning."),
    }
    graph = {"repo": {"nodes": [{"id": "api", "label": "api"}, {"id": "planning", "label": "planning"}],
                      "edges": [{"source": "api", "target": "planning"}]}}
    doc_slide = Slide(slide_number=2, layout="architecture", title="Architecture", candidate_chunks=["r1", "d1", "d2"],
                      key_points=[Claim(text="Upload Service sends invoices.", sources=["d1"]),
                                  Claim(text="ERP Connector exports invoices.", sources=["d2"])])
    out = attach_visual(doc_slide, ch, None, graph)
    assert not out.visual or "api" not in {n.label for n in out.visual.nodes}
    repo_slide = Slide(slide_number=3, layout="architecture", title="Code", candidate_chunks=["r1"],
                       key_points=[Claim(text="The api module imports planning.", sources=["r1"])])
    out = attach_visual(repo_slide, ch, None, graph)
    assert out.visual and {n.label for n in out.visual.nodes} == {"api", "planning"}


def test_transition_never_reveals_an_empty_slide(xtheme):
    """The incoming slide builds under the transition: by the end of it the slide already shows content."""
    from PIL import Image

    from backend.rendering.layouts import RenderContext, build_slide_scene
    from backend.rendering.video.motion import TRANSITION_SECONDS, build_layers, compose, slide_frames

    s = Slide(slide_number=2, layout="key_findings", title="Highlights", topic="results",
              key_points=[Claim(text="Processing time fell to 42 seconds.", status="structural"),
                          Claim(text="86% of invoices approve automatically.", status="structural")])
    scene = build_slide_scene(s, xtheme, RenderContext(_plan([s])))
    prev = Image.new("RGB", (480, 270), (16, 0, 93))
    fps = 20
    g = slide_frames(scene, xtheme, 480, fps, "subtle", "zensar_grid", prev)
    frames = []
    try:
        while True:
            frames.append(next(g))
    except StopIteration as stop:
        final = stop.value
    n_tr = int(round(TRANSITION_SECONDS["zensar_grid"] * fps))
    end_of_transition = np.asarray(frames[n_tr - 1], float)
    base, layers, _ = build_layers(scene, 480, "subtle")
    empty = np.asarray(compose(base, layers, 0.0, 0.25), float)
    fin = np.asarray(final, float)
    assert np.abs(end_of_transition - fin).mean() < np.abs(empty - fin).mean() * 0.8
