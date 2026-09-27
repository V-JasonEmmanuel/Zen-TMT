"""Document structure analysis: sections, canonical section types, title.

Nothing is assumed: sections are only typed when their heading (or the opening words
of an un-headed document) matches known patterns; everything else is `other`.
"""
from __future__ import annotations

import re

from backend.schemas import ContentType, DocumentStructure, ExtractedDocument, Section, SectionType

# ordered: first match wins
SECTION_PATTERNS: list[tuple[SectionType, re.Pattern]] = [
    (SectionType.abstract, re.compile(r"\babstract\b|\bsummary of (the )?paper\b", re.I)),
    (SectionType.executive_summary, re.compile(r"executive summary|key takeaways|at a glance|overview of findings", re.I)),
    (SectionType.acknowledgements, re.compile(r"acknowledg", re.I)),
    (SectionType.references, re.compile(r"^(references|bibliography|works cited|citations|literature cited)\b", re.I)),
    (SectionType.appendix, re.compile(r"^(appendix|appendices|annex|supplementary)", re.I)),
    (SectionType.related_work, re.compile(r"related work|literature review|prior work|state of the art", re.I)),
    (SectionType.introduction, re.compile(r"introduction|^overview$|^purpose\b|^scope\b", re.I)),
    (SectionType.background, re.compile(r"background|motivation|problem statement|context|preliminar", re.I)),
    (SectionType.architecture, re.compile(r"architecture|system design|framework|design overview|solution design|components", re.I)),
    (SectionType.methodology, re.compile(r"method|approach|materials|procedure|research design|data collection|proposed (model|system|solution)|technique", re.I)),
    (SectionType.implementation, re.compile(r"implementation|deployment|setup|code|algorithm", re.I)),
    (SectionType.experiments, re.compile(r"experiment|evaluation|benchmark|test(ing)? setup|dataset|case stud", re.I)),
    (SectionType.results, re.compile(r"result|finding|performance|outcome|analysis|metrics|impact", re.I)),
    (SectionType.discussion, re.compile(r"discussion|limitation|threats to validity|implication|lessons", re.I)),
    (SectionType.recommendations, re.compile(r"recommendation|next steps|future work|roadmap|way forward|proposal", re.I)),
    (SectionType.conclusion, re.compile(r"conclusion|concluding|summary|closing remarks", re.I)),
]

_NUM_PREFIX = re.compile(r"^((\d+(\.\d+)*)|[IVX]+|[A-Z])[.):]?\s+")


def classify_heading(title: str) -> SectionType:
    t = _NUM_PREFIX.sub("", title.strip()).strip()
    for st, pat in SECTION_PATTERNS:
        if pat.search(t):
            return st
    return SectionType.other


def analyze_structure(doc: ExtractedDocument) -> DocumentStructure:
    sections: list[Section] = []
    current: Section | None = None
    parent_type = SectionType.other
    title = doc.title

    def new_section(title_text: str, level: int, page: int) -> Section:
        nonlocal parent_type
        st = classify_heading(title_text)
        # sub-sections inherit the canonical type of their parent when they have none
        if level > 1 and st == SectionType.other:
            st = parent_type
        if level <= 1:
            parent_type = st
        return Section(id=f"S{len(sections) + 1}", title=title_text, level=level, section_type=st,
                       page_start=page, page_end=page)

    for i, b in enumerate(doc.blocks):
        if b.type == ContentType.heading:
            if b.text.strip() == title.strip() and not sections:
                continue  # the document title is not a section
            current = new_section(b.text, max(1, b.level or 1), b.page)
            sections.append(current)
            continue
        if current is None:
            # content before the first heading: abstract-like opener or preamble
            first_words = b.text[:40].lower()
            st_title = "Abstract" if first_words.startswith("abstract") else "Introduction" if len(doc.blocks) > 3 else "Content"
            current = new_section(st_title, 1, b.page)
            if b.page == 1 and st_title == "Introduction":
                current.section_type = SectionType.other
                current.title = "Opening"
            sections.append(current)
        current.block_indexes.append(i)
        current.page_end = max(current.page_end, b.page)

    # everything after a references heading at top level is references (unless a new canonical section starts)
    in_refs = False
    for s in sections:
        if s.section_type == SectionType.references:
            in_refs = True
        elif s.level <= 1 and s.section_type not in (SectionType.other,):
            in_refs = s.section_type == SectionType.references
        elif in_refs and s.section_type == SectionType.other:
            s.section_type = SectionType.references

    sections = [s for s in sections if s.block_indexes or s.level <= 2]
    detected = []
    for s in sections:
        if s.section_type not in detected and s.section_type != SectionType.other:
            detected.append(s.section_type)
    return DocumentStructure(
        title=title,
        sections=sections,
        detected_types=detected,
        table_count=sum(1 for b in doc.blocks if b.type == ContentType.table),
        figure_count=sum(1 for b in doc.blocks if b.type == ContentType.figure),
    )
