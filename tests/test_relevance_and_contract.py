"""Instruction understanding + relevance ranking + exclusions."""
from backend.intelligence.relevance import rank_chunks
from backend.planning.content_contract import parse_instruction, parse_instruction_rules
from backend.schemas import ContentType, SectionType


def test_rules_parse_count_audience_focus_exclude():
    c = parse_instruction_rules("Create a 10-slide technical presentation for a senior client audience. Focus on architecture, "
                                "methodology and results. Do not include detailed implementation code.")
    assert c.slide_count == 10
    assert c.audience == "senior_client"
    assert c.purpose == "technical_presentation"
    assert c.include == ["architecture", "methodology", "results"]
    assert c.exclude == ["implementation_code"]


def test_rules_word_numbers_and_detail():
    c = parse_instruction_rules("Make a brief eight-slide executive briefing on the key findings for the board, without references.")
    assert c.slide_count == 8
    assert c.audience == "executive"
    assert c.detail_level == "low"
    assert "references" in c.exclude
    assert "findings" in c.include


def test_llm_merge_keeps_explicit_facts(fake_llm):
    llm = fake_llm([{"audience": "technical", "purpose": "training", "slide_count": 25, "tone": "casual",
                     "include": ["security"], "exclude": ["costs"], "detail_level": "high", "notes": ""}])
    c = parse_instruction("Create 6 slides for a senior client audience focusing on results.", llm)
    assert c.slide_count == 6  # stated in the instruction -> rules win over the model
    assert c.audience == "senior_client"
    assert "results" in c.include and "security" in c.include and "costs" in c.exclude
    assert c.parse_method == "rules+llm"


def test_llm_failure_falls_back_to_rules(fake_llm):
    c = parse_instruction("Create 5 slides about methodology.", fake_llm(["not json", "still not json"]))
    assert c.slide_count == 5 and c.parse_method == "rules"


def test_relevance_prefers_requested_sections(extracted, embedder):
    _, _, chunks = extracted
    c = parse_instruction_rules("Create a presentation focusing on methodology.")
    res = rank_chunks(c, chunks, embedder.encode([x.text for x in chunks]), embedder)
    cm = {x.id: x for x in chunks}
    top = [cm[s.chunk_id] for s in res.ranked()[:2]]
    assert any(t.section_type == SectionType.methodology for t in top)
    meth = [s for s in res.scored if cm[s.chunk_id].section_type == SectionType.methodology]
    other = [s for s in res.scored if cm[s.chunk_id].section_type == SectionType.background]
    assert max(s.score for s in meth) > max(s.score for s in other)


def test_excluded_section_by_heading(tmp_path, embedder):
    """A 'Risks' heading has no canonical type, but excluding risks must still drop it."""
    from backend.extraction.structure import analyze_structure
    from backend.ingestion import get_adapter
    from backend.intelligence.chunking import chunk_document

    p = tmp_path / "ops.md"
    p.write_text("# Ops Review\n\n## Results\n\nResolution time fell from 26 to 9 hours.\n\n"
                 "## Risks\n\nTwo regions still use legacy forms, which limits routing accuracy.\n\n"
                 "## Recommendations\n\nExtend the portal to the remaining regions.\n", encoding="utf-8")
    doc = get_adapter(p).extract(p, "ops", tmp_path)
    chunks = chunk_document(doc, analyze_structure(doc))
    c = parse_instruction_rules("Create 5 slides on results and recommendations. Do not include the risks section.")
    assert "risks" in c.exclude
    res = rank_chunks(c, chunks, embedder.encode([x.text for x in chunks]), embedder)
    cm = {x.id: x for x in chunks}
    assert all(cm[s.chunk_id].section != "Risks" for s in res.ranked())
    assert any(s.excluded and cm[s.chunk_id].section == "Risks" for s in res.scored)


def test_excluded_sections_are_filtered(extracted, embedder):
    _, _, chunks = extracted
    c = parse_instruction_rules("Focus on results. Do not include implementation code.")
    res = rank_chunks(c, chunks, embedder.encode([x.text for x in chunks]), embedder)
    cm = {x.id: x for x in chunks}
    kept = {cm[s.chunk_id].content_type for s in res.ranked()}
    assert ContentType.code not in kept
    assert all(cm[s.chunk_id].section_type != SectionType.references for s in res.ranked())
    excluded = [s for s in res.scored if s.excluded]
    assert excluded and all(s.reason for s in excluded)
