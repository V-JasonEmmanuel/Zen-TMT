"""Paper model: one structured representation of a scholarly paper, independent of any format.

Every reader (PDF, DOCX, LaTeX, Markdown/text) produces a Paper; every writer (LaTeX, DOCX, PDF,
BibTeX) consumes one. The paper's wording is carried verbatim - conversion changes structure,
numbering, citation and reference style, never the author's text.

Inline text is a list of Inline runs: plain text with simple formatting, a citation group
(reference keys) or inline math (LaTeX source).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Inline(BaseModel):
    t: str = ""  # text
    b: bool = False
    i: bool = False
    sup: bool = False
    sub: bool = False
    cite: list[str] = Field(default_factory=list)  # reference keys (a citation group)
    math: str = ""  # inline math, LaTeX source (from LaTeX/DOCX sources)
    raw_cite: str = ""  # the citation as written in the source, e.g. "[3-5]"
    xref: str = ""  # cross reference to a figure/table/equation block label ("fig1", "tab2", "eq3"); t = source text
    img: str = ""  # inline math cropped from a PDF (fonts without text mapping) - path relative to the paper folder
    img_w: float = 0.0  # points
    img_h: float = 0.0


class Block(BaseModel):
    kind: Literal["para", "list", "equation", "figure", "table", "code", "quote"] = "para"
    runs: list[Inline] = Field(default_factory=list)  # para / quote / equation text
    items: list[list[Inline]] = Field(default_factory=list)  # list items
    ordered: bool = False
    # equations
    latex: str = ""  # LaTeX source when known (LaTeX/DOCX sources)
    number: str = ""  # equation number as in the source, e.g. "3"
    # figures / tables / equation images
    image: str = ""  # path relative to the paper folder
    caption: list[Inline] = Field(default_factory=list)
    label: str = ""  # "fig1", "tab2", "eq3" - used for cross references
    rows: list[list[str]] = Field(default_factory=list)  # table cells (header first)
    omml: str = ""  # DOCX equation XML (kept for Word output)
    width_frac: float = 0.0  # figure/table width as a fraction of the source column/page (0 = full width)
    note: str = ""  # conversion note for the report


class Section(BaseModel):
    title: str
    level: int = 1  # 1 = section, 2 = subsection, 3 = subsubsection
    blocks: list[Block] = Field(default_factory=list)
    kind: Literal["body", "acknowledgements", "declarations", "appendix", "funding", "data", "contributions",
                  "competing", "ethics"] = "body"
    source_number: str = ""  # numbering as found in the source ("2.1", "IV", "A")


class Author(BaseModel):
    name: str
    affiliations: list[int] = Field(default_factory=list)  # indexes into Paper.affiliations
    email: str = ""
    orcid: str = ""
    corresponding: bool = False


class Reference(BaseModel):
    key: str  # citation key (stable, BibTeX-safe)
    raw: str  # the reference exactly as written in the source
    csl: dict[str, Any] = Field(default_factory=dict)  # CSL-JSON item (parsed fields)
    status: Literal["parsed", "partial", "raw"] = "raw"  # raw = rendered verbatim (could not be parsed)
    method: str = ""  # rules | llm | bibtex | user
    source_label: str = ""  # "[12]" / "12." in the source list
    cited: bool = False


class Paper(BaseModel):
    title: str = ""
    subtitle: str = ""
    authors: list[Author] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    abstract: list[Inline] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)  # Elsevier highlights, if the source has them
    source_format: str = ""  # pdf | docx | latex | markdown | text
    source_citation_style: str = ""  # numeric | author-year | latex
    source_name: str = ""
    warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def all_blocks(self):
        for s in self.sections:
            yield from s.blocks

    def ref(self, key: str) -> Optional[Reference]:
        return next((r for r in self.references if r.key == key), None)


def plain(runs: list[Inline]) -> str:
    """Text of a run list (citations shown as written in the source, math as LaTeX)."""
    out = []
    for r in runs:
        if r.cite:
            out.append(r.raw_cite or "[" + ",".join(r.cite) + "]")
        elif r.math:
            out.append(f"${r.math}$")
        else:
            out.append(r.t)
    return "".join(out)


def text_runs(text: str) -> list[Inline]:
    return [Inline(t=text)] if text else []
