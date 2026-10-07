"""Shared rules for all writers: section numbering, heading case, captions, statements."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.papers.formats import Format
from backend.papers.model import Block, Paper, Section

ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI",
         "XVII", "XVIII", "XIX", "XX"]
STATEMENT_TITLES = {
    "funding": "Funding", "competing": "Competing interests", "ethics": "Ethics approval and consent",
    "data": "Data availability", "contributions": "Author contributions",
}
ELSEVIER_TITLES = {"competing": "Declaration of competing interest", "contributions": "CRediT authorship contribution statement",
                   "data": "Data availability", "funding": "Funding", "ethics": "Ethics statement"}
PLACEHOLDER = "[To be completed by the authors.]"


def roman(n: int) -> str:
    return ROMAN[n] if n < len(ROMAN) else str(n)


@dataclass
class Numbered:
    section: Section
    number: str  # "2.1", "II", "B" - empty for unnumbered
    heading: str  # full heading text as printed


@dataclass
class Layout:
    """The paper arranged for a format: numbered body sections, special sections, figure/table numbers."""
    body: list[Numbered] = field(default_factory=list)
    acknowledgements: list[Section] = field(default_factory=list)
    statements: dict[str, Section] = field(default_factory=dict)  # kind -> section
    appendix: list[Numbered] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # required statements absent in the source
    fig_no: dict[int, int] = field(default_factory=dict)  # id(block) -> number
    tab_no: dict[int, int] = field(default_factory=dict)
    eq_no: dict[int, int] = field(default_factory=dict)
    by_label: dict[str, int] = field(default_factory=dict)  # block label -> number (cross references)


def heading_text(fmt: Format, title: str, number: str, level: int) -> str:
    t = title
    if level == 1 and fmt.h1_case == "upper":
        t = t.upper()
    if not number:
        return t
    if fmt.numbering == "roman":
        return f"{number}. {t}" if level == 1 else f"{number}. {t}" if level == 2 else f"{number}) {t}"
    return f"{number} {t}" if fmt.id != "elsevier" else f"{number}. {t}"


def arrange(paper: Paper, fmt: Format) -> Layout:
    lay = Layout()
    counters = [0, 0, 0]
    in_appendix = False
    for s in paper.sections:
        if s.kind == "acknowledgements":
            lay.acknowledgements.append(s)
            continue
        if s.kind in STATEMENT_TITLES:
            lay.statements[s.kind] = s
            continue
        if s.kind == "declarations":
            lay.statements.setdefault("declarations", s)
            continue
        if s.kind == "appendix" and not in_appendix:
            in_appendix = True
            counters = [0, 0, 0]  # appendices: A, A.1, B ...
        lvl = max(1, min(3, s.level))
        if fmt.numbering == "none":
            num = ""
        else:
            counters[lvl - 1] += 1
            for k in range(lvl, 3):
                counters[k] = 0
            if in_appendix:
                num = ".".join([chr(64 + max(1, counters[0]))] + [str(c) for c in counters[1:lvl]])
            elif fmt.numbering == "roman":
                num = roman(counters[0]) if lvl == 1 else chr(64 + counters[1]) if lvl == 2 else str(counters[2])
            else:
                num = ".".join(str(c) for c in counters[:lvl])
        n = Numbered(s, num, heading_text(fmt, s.title, num, lvl) if s.title else "")
        (lay.appendix if in_appendix else lay.body).append(n)
    f = t = e = 0
    for s in paper.sections:
        for b in s.blocks:
            if b.kind == "figure":
                f += 1
                lay.fig_no[id(b)] = f
                lay.by_label[b.label] = f
            elif b.kind == "table":
                t += 1
                lay.tab_no[id(b)] = t
                lay.by_label[b.label] = t
            elif b.kind == "equation":
                e += 1
                lay.eq_no[id(b)] = e
                lay.by_label[b.label] = e
    lay.missing = [k for k in fmt.required if k not in lay.statements]
    return lay


def caption_label(fmt: Format, b: Block, lay: Layout) -> str:
    if b.kind == "figure":
        return f"{fmt.fig_label} {lay.fig_no.get(id(b), '')}{fmt.fig_number_suffix}"
    n = lay.tab_no.get(id(b), 0)
    num = roman(n) if fmt.table_roman else str(n)
    return f"{fmt.table_label} {num}{fmt.fig_number_suffix if not fmt.table_roman else ''}"


def statement_title(fmt: Format, kind: str) -> str:
    return (ELSEVIER_TITLES if fmt.id == "elsevier" else STATEMENT_TITLES).get(kind, kind.title())


def ack_title(fmt: Format) -> str:
    return {"ieee": "Acknowledgment", "acm": "Acknowledgments"}.get(fmt.id, "Acknowledgements")
