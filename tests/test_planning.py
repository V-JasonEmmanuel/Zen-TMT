"""Content planning, schema validation, repair/retry and hallucination control."""
import json

import pytest
from pydantic import ValidationError

from backend.intelligence.verification import Verifier
from backend.llm.structured_output import StructuredOutputError, extract_json, generate_structured
from backend.planning.content_planner import SlideDraft
from backend.schemas import LAYOUTS, ContentPlan, Slide
from tests.conftest import build_plan


def test_extract_json_handles_fences_and_chatter():
    assert json.loads(extract_json('Sure! ```json\n{"a": 1}\n``` done')) == {"a": 1}
    assert json.loads(extract_json('prefix {"a": {"b": "}"}} suffix')) == {"a": {"b": "}"}}
    assert extract_json("no json here") is None


def test_repair_retry_then_valid(fake_llm):
    llm = fake_llm(['{"title": 5, "points": "oops"', '{"title": "Results", "points": [{"text": "x", "sources": ["S1"]}]}'])
    draft = generate_structured(llm, "write", SlideDraft, retries=1)
    assert draft.title == "Results" and len(llm.prompts) == 2
    assert "previous answer was invalid" in llm.prompts[1]


def test_invalid_output_raises_after_retries(fake_llm):
    with pytest.raises(StructuredOutputError):
        generate_structured(fake_llm(["{}", "{}", "{}"]), "write", SlideDraft, retries=2)


def test_unsupported_layout_and_missing_fields_rejected():
    with pytest.raises(ValidationError):
        Slide(slide_number=1, layout="hologram")
    with pytest.raises(ValidationError):
        ContentPlan.model_validate({"slides": []})  # contract missing


def test_extractive_plan_is_grounded(extractive_plan, extracted):
    _, _, chunks = extracted
    cm = {c.id: c for c in chunks}
    plan = extractive_plan
    assert 3 <= len(plan.slides) <= 10
    assert plan.slides[0].layout == "cover" and plan.slides[-1].layout == "references"
    for s in plan.slides:
        assert s.layout in LAYOUTS
        items = [*s.key_points, *s.steps, *s.kpis, *(p for c in s.columns for p in c.points)]
        for it in items:
            if it.status == "structural":
                continue
            assert it.sources, f"slide {s.slide_number}: unsourced statement"
            assert all(src in cm for src in it.sources)
            assert it.status != "unsupported"
        # excluded material never reaches a slide
        for r in s.sources:
            assert cm[r.chunk_id].content_type.value != "code"
            assert cm[r.chunk_id].section_type.value != "references"
    chart = next(s for s in plan.slides if s.chart)
    assert chart.chart.categories[0] == "Fixed window + BM25"
    assert [x.name for x in chart.chart.series] == ["Accuracy (%)", "Recall@10 (%)"]  # ms column not mixed in
    assert chart.chart.series[0].values == [71.4, 76.8, 79.5, 84.9]


def test_fabricated_numbers_are_removed(extracted, embedder, fake_llm):
    """The LLM invents '97%' - verification must drop it, keep grounded statements."""

    def respond(prompt, schema):
        if "Convert the user's instruction" in prompt:
            return {"audience": "senior_client", "include": ["results"], "exclude": []}
        if "SOURCE PASSAGES" in prompt and "extract the" not in prompt:
            return {"title": "Results", "points": [
                {"text": "Section-aware chunking with hybrid retrieval achieved 84.9% accuracy.", "sources": ["S1"]},
                {"text": "Customer satisfaction rose to 97% after deployment.", "sources": ["S1"]},
            ], "kpis": [{"value": "84.9%", "label": "Best accuracy", "sources": ["S1"]},
                        {"value": "12x", "label": "Faster onboarding", "sources": ["S1"]}],
                "steps": [], "columns": [], "narration": "Accuracy reached 84.9%. Satisfaction reached 97%."}
        return {"nodes": [], "edges": []}

    plan, _ = build_plan(extracted, embedder, "Create 5 slides focusing on results.", llm=fake_llm(fn=respond))
    texts = [p.text for s in plan.slides for p in s.key_points] + [k.value for s in plan.slides for k in s.kpis]
    narr = " ".join(s.narration for s in plan.slides)
    assert not any("97%" in t for t in texts) and "97%" not in narr
    assert not any(t == "12x" for t in texts)
    assert any("84.9%" in t for t in texts)
    assert any(w.startswith("Removed") for s in plan.slides for w in s.warnings)


def test_rows_with_different_units_are_not_charted():
    from backend.planning.visual_planner import chart_from_table
    from backend.schemas import ContentType, DocumentChunk

    def chunk(rows):
        return DocumentChunk(id="t", document_id="d", index=0, page=1, page_end=1, content_type=ContentType.table, text="t", table=rows)

    mixed = [["Metric", "Q2", "Q3"], ["Resolution time (hours)", "26", "9"], ["First-contact resolution (%)", "41", "68"],
             ["Backlog (tickets)", "1,240", "310"]]
    assert chart_from_table(chunk(mixed)) is None
    same = [["Region", "Q2 (%)", "Q3 (%)"], ["North", "41", "68"], ["South", "39", "61"], ["West", "44", "70"]]
    c = chart_from_table(chunk(same))
    assert c is not None and c.unit == "%" and c.series[1].values == [68.0, 61.0, 70.0]


def test_citation_labels_never_visible():
    from backend.planning.content_planner import apply_draft

    d = SlideDraft(title="Results [S1]", points=[{"text": "FCR rose from 41% to 68%. [S1, S2]", "sources": ["S1"]},
                                                 {"text": "Backlog fell (S2)", "sources": ["S2"]}])
    s = apply_draft(Slide(slide_number=2, layout="key_findings"), d)
    assert s.title == "Results"
    assert [p.text for p in s.key_points] == ["FCR rose from 41% to 68%.", "Backlog fell"]


def test_verifier_scores(extracted, embedder):
    _, _, chunks = extracted
    cm = {c.id: c for c in chunks}
    v = Verifier(cm, embedder)
    res = next(c for c in chunks if "84.9%" in c.text and c.section.endswith("Results"))
    good = v.verify("Hybrid retrieval with section-aware chunking reached 84.9% accuracy.", [res.id], [])
    assert good.status in ("verified", "needs_review") and good.sources[0] == res.id
    bad = v.verify("Accuracy reached 99.9%.", [res.id], [])
    assert bad.status == "unsupported"
    regrounded = v.verify("The re-ranker added 45 ms of latency.", [], [c.id for c in chunks])
    assert regrounded.sources and regrounded.status != "unsupported"
