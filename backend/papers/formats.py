"""Target formats: the rules of each publisher template, as data.

Each profile drives all writers: the LaTeX document class + bibliography style (the authoritative
submission format), the Word layout, the PDF preview, the citation/reference style (official CSL
style files in ./styles), heading numbering, caption conventions and the publisher's checks
(abstract length, keyword count, required statements).
Sources: the publishers' author guidelines and their LaTeX templates (sn-jnl, llncs, elsarticle,
IEEEtran, acmart) and the APA Publication Manual, 7th ed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

MM = 1 / 25.4  # inches per mm


@dataclass
class Format:
    id: str
    name: str
    publisher: str
    description: str
    # citations / references
    csl: str  # style file in backend/papers/styles
    csl_author_year: Optional[str] = None  # alternative author-year style, if the publisher offers one
    latex_class: str = "article"
    latex_options: str = ""
    bst: str = "plain"  # BibTeX style for the LaTeX project
    bst_author_year: Optional[str] = None
    natbib: bool = False
    # page
    page: str = "A4"  # A4 | Letter
    margins_in: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)  # top, right, bottom, left
    columns: int = 1
    column_gap_in: float = 0.25
    font: str = "Times New Roman"
    body_pt: float = 10.0
    line_spacing: float = 1.0
    para_indent_in: float = 0.15
    justify: bool = True
    # front matter
    title_pt: float = 14.0
    title_bold: bool = True
    title_align: str = "center"
    abstract_label: str = "Abstract"
    abstract_runin: bool = False  # "Abstract—text" (IEEE) vs a heading + paragraph
    abstract_label_style: str = "bold"  # bold | bold-italic | italic | heading
    keywords_label: str = "Keywords"
    keywords_sep: str = ", "
    # headings
    numbering: str = "arabic"  # arabic (1, 1.1) | roman (I., A.) | none
    h1_case: str = "title"  # title | upper | smallcaps
    h1_align: str = "left"
    h1_pt: float = 12.0
    h2_italic: bool = False
    h2_pt: float = 10.0
    references_title: str = "References"
    # captions
    fig_label: str = "Fig."
    fig_sep: str = " "  # between number and caption text, e.g. "Fig. 1 " vs "Fig. 1. "
    fig_number_suffix: str = ""
    table_label: str = "Table"
    table_roman: bool = False  # IEEE: TABLE I
    table_caption_above: bool = True
    fig_caption_above: bool = False  # APA: "Figure 1" + title above the figure
    caption_newline: bool = False  # APA: label on its own line, title in italics below it
    title_page: bool = False  # APA manuscript: title page, abstract page, then the text
    caption_pt: float = 9.0
    ref_pt: float = 9.0
    # publisher rules
    abstract_words: tuple[int, int] = (150, 250)
    keywords_count: tuple[int, int] = (4, 6)
    required: list[str] = field(default_factory=list)  # required statements (section kinds)
    notes: list[str] = field(default_factory=list)


FORMATS: dict[str, Format] = {f.id: f for f in [
    Format(
        id="springer_nature", name="Springer Nature journal", publisher="Springer Nature",
        description="Springer Nature journal article (sn-jnl template): single column, numbered sections, "
                    "Springer Basic references, Declarations section.",
        csl="springer-basic-brackets", csl_author_year="springer-basic-author-date",
        latex_class="sn-jnl", latex_options="pdflatex,sn-basic", bst="sn-basic", bst_author_year="sn-basic",
        natbib=True, page="A4", margins_in=(1.0, 1.1, 1.0, 1.1), body_pt=10.5, line_spacing=1.15, title_pt=17,
        title_align="left", h1_pt=12, h2_pt=10.5, fig_label="Fig.", fig_sep=" ", table_label="Table",
        abstract_words=(150, 250), keywords_count=(4, 6),
        required=["funding", "competing", "ethics", "data", "contributions"],
        notes=["Springer Nature asks for a 'Declarations' section (funding, competing interests, ethics approval, "
               "consent, data/code availability, author contributions)."]),
    Format(
        id="springer_lncs", name="Springer LNCS (proceedings)", publisher="Springer",
        description="Lecture Notes in Computer Science conference paper (llncs class): 12.2 x 19.3 cm text "
                    "block, 10 pt, 'Keywords: a · b', splncs04 references.",
        csl="springer-lecture-notes-in-computer-science", latex_class="llncs", latex_options="runningheads",
        bst="splncs04", page="A4", margins_in=(52 * MM, 44 * MM, 52 * MM, 44 * MM), body_pt=10, title_pt=14,
        abstract_label="Abstract.", abstract_runin=True, abstract_label_style="bold",
        keywords_label="Keywords:", keywords_sep=" · ", h1_pt=12, h2_pt=10, fig_label="Fig.",
        fig_number_suffix=".", table_label="Table", caption_pt=9, ref_pt=9,
        abstract_words=(150, 250), keywords_count=(3, 6), required=[],
        notes=["LNCS papers are limited by page count (typically 12-16 pages incl. references); check the CFP."]),
    Format(
        id="elsevier", name="Elsevier journal (elsarticle)", publisher="Elsevier",
        description="Elsevier journal article (elsarticle preprint): single column, numbered sections, "
                    "Elsevier numeric references (or Harvard), highlights and declarations.",
        csl="elsevier-with-titles", csl_author_year="elsevier-harvard", latex_class="elsarticle",
        latex_options="preprint,12pt", bst="elsarticle-num", bst_author_year="elsarticle-harv", natbib=True,
        page="A4", margins_in=(1.0, 1.0, 1.0, 1.0), body_pt=12, line_spacing=1.5, title_pt=17,
        abstract_label="Abstract", h1_pt=12, h2_pt=12, h2_italic=True, fig_label="Fig.", fig_number_suffix=".",
        table_label="Table", abstract_words=(100, 250), keywords_count=(1, 7),
        required=["competing", "contributions", "data"],
        notes=["Elsevier journals ask for 3-5 Highlights (max. 85 characters each) as a separate file.",
               "A 'Declaration of competing interest' and a CRediT authorship statement are required."]),
    Format(
        id="ieee", name="IEEE conference / journal", publisher="IEEE",
        description="IEEEtran: two columns, Roman-numbered small-caps section headings, 'Abstract—' and "
                    "'Index Terms—', TABLE I captions above tables, IEEE references.",
        csl="ieee", latex_class="IEEEtran", latex_options="conference", bst="IEEEtran", page="Letter",
        margins_in=(0.75, 0.625, 1.0, 0.625), columns=2, column_gap_in=0.25, body_pt=10, title_pt=24,
        title_bold=False, abstract_label="Abstract", abstract_runin=True, abstract_label_style="bold-italic",
        keywords_label="Index Terms", keywords_sep=", ", numbering="roman", h1_case="smallcaps", h1_align="center",
        h1_pt=10, h2_italic=True, h2_pt=10, references_title="References", fig_label="Fig.", fig_number_suffix=".",
        table_label="TABLE", table_roman=True, caption_pt=8, ref_pt=8, para_indent_in=0.14,
        abstract_words=(150, 250), keywords_count=(3, 8), required=[]),
    Format(
        id="acm", name="ACM conference (acmart sigconf)", publisher="ACM",
        description="ACM proceedings (acmart, sigconf): two columns, upper-case numbered headings, CCS concepts "
                    "and keywords, ACM reference format.",
        csl="association-for-computing-machinery", latex_class="acmart", latex_options="sigconf",
        bst="ACM-Reference-Format", natbib=True, page="Letter", margins_in=(0.75, 0.75, 0.75, 0.75), columns=2,
        column_gap_in=0.33, body_pt=9, title_pt=14.4, abstract_label="ABSTRACT", abstract_label_style="heading",
        keywords_label="KEYWORDS", h1_case="upper", h1_pt=10, h2_pt=10, fig_label="Figure", fig_number_suffix=":",
        table_label="Table", fig_sep=" ", caption_pt=8, ref_pt=7.5, abstract_words=(100, 250),
        keywords_count=(3, 8), required=[],
        notes=["ACM asks for CCS Concepts (from the ACM Computing Classification System) - add them in the LaTeX file."]),
    Format(
        id="apa7", name="APA 7th edition manuscript", publisher="APA",
        description="APA 7 professional manuscript: 12 pt Times New Roman, double spacing, unnumbered APA "
                    "heading levels, author-date citations, hanging-indent references.",
        csl="apa", latex_class="apa7", latex_options="man,12pt", bst="apa", natbib=False, page="Letter",
        margins_in=(1.0, 1.0, 1.0, 1.0), body_pt=12, line_spacing=2.0, para_indent_in=0.5, justify=False,
        title_pt=12, abstract_label="Abstract", abstract_label_style="heading", keywords_label="Keywords",
        numbering="none", h1_align="center", h1_pt=12, h2_pt=12, fig_label="Figure", fig_sep="", table_label="Table",
        fig_caption_above=True, caption_newline=True, title_page=True,
        caption_pt=12, ref_pt=12, abstract_words=(150, 250), keywords_count=(3, 5), required=[]),
]}


def gallery() -> list[dict]:
    out = []
    for f in FORMATS.values():
        out.append({"id": f.id, "name": f.name, "publisher": f.publisher, "description": f.description,
                    "columns": f.columns, "page": f.page, "latex_class": f.latex_class,
                    "citation_styles": ["numeric", "author-year"] if f.csl_author_year else
                    (["author-year"] if f.id == "apa7" else ["numeric"]),
                    "notes": f.notes})
    return out


def csl_for(f: Format, style: str = "") -> str:
    if style == "author-year" and f.csl_author_year:
        return f.csl_author_year
    return f.csl


def author_year(f: Format, style: str = "") -> bool:
    return f.id == "apa7" or (style == "author-year" and f.csl_author_year is not None)
