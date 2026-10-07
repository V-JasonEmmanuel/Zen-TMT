"""Builds a Paper from the flat element stream every reader produces.

Readers only report what they see (headings, paragraphs, figures, tables, equations, lists and
the lines of the front matter and of the reference list). This module decides what is the title,
authors, affiliations, abstract and keywords; builds the numbered section tree; recognises the
special sections publishers treat separately (acknowledgements, funding, competing interests, data
availability, author contributions, ethics, appendices); and reads the reference list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from backend.papers.model import Author, Block, Inline, Paper, Section, plain

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
         "XII": 12, "XIII": 13, "XIV": 14, "XV": 15}
SPECIAL = [
    ("acknowledgements", r"acknowledg(e)?ments?"),
    ("funding", r"funding(\s+(information|sources?|statement))?"),
    ("competing", r"(declaration\s+of\s+)?(competing|conflicts?)\s+(of\s+)?interests?|conflict\s+of\s+interest\s+statement"),
    ("data", r"(data|code)(\s+and\s+(code|materials?))?\s+availability(\s+statement)?|availability\s+of\s+data(\s+and\s+materials?)?"),
    ("contributions", r"(credit\s+)?author(ship)?\s+contributions?(\s+statement)?|author\s+contribution"),
    ("ethics", r"ethic(s|al)(\s+(approval|statement|declarations?))?(\s+and\s+consent.*)?|consent\s+(to|for)\s+(participate|publication)"),
    ("declarations", r"declarations?|statements?\s+and\s+declarations"),
    ("appendix", r"appendi(x|ces)(\s+[A-Z0-9]+)?(\b.*)?"),
]
REFS_HEAD = re.compile(r"^(references?|bibliography|literature\s+cited|works\s+cited|reference\s+list)\s*$", re.I)
ABSTRACT = re.compile(r"^\s*(abstract|summary)\s*[.:—–-]?\s*", re.I)
KEYWORDS = re.compile(r"^\s*(key\s*words?|index\s+terms|keywords?)\s*[.:—–-]+\s*|^\s*(key\s*words?|index\s+terms)\s+", re.I)
HIGHLIGHTS = re.compile(r"^\s*highlights\s*$", re.I)


@dataclass
class Elem:
    kind: str  # heading | para | list | figure | table | equation | code | quote
    runs: list[Inline] = field(default_factory=list)
    level: int = 0  # heading level hint from the reader (0 = unknown)
    items: list[list[Inline]] = field(default_factory=list)
    ordered: bool = False
    block: Optional[Block] = None  # prepared block (figures, tables, equations)

    @property
    def text(self) -> str:
        return plain(self.runs).strip()


def heading_info(text: str) -> tuple[str, int, str]:
    """('2.1 Method', ...) -> ('Method', level, '2.1'). Level 0 = numbering gives no level."""
    t = text.strip()
    m = re.match(r"^(\d+(?:\.\d+){0,3})\.?\s+(?=\S)(.*)$", t)
    if m and len(m.group(2)) > 1:
        return m.group(2).strip(), m.group(1).count(".") + 1, m.group(1)
    m = re.match(r"^([IVX]{1,5})\.\s+(.*)$", t)
    if m and m.group(1) in ROMAN:
        return m.group(2).strip(), 1, m.group(1)
    m = re.match(r"^([A-H])\.\s+(.*)$", t)
    if m and len(m.group(2)) > 2:
        return m.group(2).strip(), 2, m.group(1)
    m = re.match(r"^(\d)\)\s+(.*)$", t)
    if m:
        return m.group(2).strip(), 3, m.group(1)
    return t, 0, ""


def special_kind(title: str) -> str:
    t = re.sub(r"^(\d+(\.\d+)*|[IVX]+|[A-Z])[.)]?\s+", "", title.strip()).strip(" .:").lower()
    for kind, pat in SPECIAL:
        if re.fullmatch(pat, t):
            return kind
    return "body"


def tidy_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip(" .:")
    if t.isupper() and len(t) > 3:  # IEEE / ACM headings are set in capitals - store them in title case
        small = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "via", "with"}
        words = t.lower().split()
        t = " ".join(w if (i and w in small) else (w[:1].upper() + w[1:]) for i, w in enumerate(words))
        t = re.sub(r"\b(Ai|Ml|Nlp|Llm|Api|Iot|Gpu|Cpu|Cnn|Rnn|Lstm|Bert|Gpt|Sql|Ui|Ux|Erp|Pdf|Hci)\b", lambda m: m.group(1).upper(), t)
    return t


def build(elems: list[Elem], *, title: str = "", front: Optional[list[str]] = None, ref_lines: Optional[list[tuple[str, float]]] = None,
          source_format: str = "", source_name: str = "") -> Paper:
    """front = lines between title and abstract (authors/affiliations) if the reader separated them."""
    p = Paper(title=title.strip(), source_format=source_format, source_name=source_name)
    i = 0
    front_lines = list(front or [])
    # ---- front matter: everything before the abstract / first heading that is not yet assigned
    while i < len(elems) and not p.abstract:
        e = elems[i]
        txt = e.text
        if e.kind == "heading" and re.fullmatch(r"(abstract|summary)\s*[.:]?", txt, re.I):
            i += 1
            parts = []
            while i < len(elems) and elems[i].kind == "para" and not KEYWORDS.match(elems[i].text):
                parts += elems[i].runs + [Inline(t=" ")]
                i += 1
            p.abstract = _strip(parts)
            break
        if e.kind == "para" and ABSTRACT.match(txt) and len(txt) > 60:
            p.abstract = _drop_prefix(e.runs, ABSTRACT)
            i += 1
            break
        if e.kind == "heading" and heading_info(txt)[1] and not front_lines:
            break  # body starts without an abstract
        if e.kind in ("para", "heading"):
            if not p.title and e.kind == "heading":
                p.title = txt
            else:
                front_lines.append(txt)
        i += 1
        if i > 40:
            break
    if not p.abstract and i >= len(elems):
        i = 0  # no abstract found: treat everything as body
        front_lines = list(front or [])
    # keywords (paragraph right after the abstract, or anywhere in the first elements)
    for j in range(i, min(i + 4, len(elems))):
        if elems[j].kind == "para" and KEYWORDS.match(elems[j].text):
            kw = KEYWORDS.sub("", elems[j].text, count=1)
            p.keywords = [k.strip(" .") for k in re.split(r"\s*[;,·•|]\s*|\s+\\sep\s+", kw) if k.strip(" .")]
            del elems[j]
            break
    authors_from_front(p, front_lines)

    # ---- body
    cur: Optional[Section] = None
    body = elems[i:]
    in_highlights = False
    for e in body:
        if e.kind == "heading":
            raw = e.text
            if REFS_HEAD.match(re.sub(r"^(\d+|[IVX]+)\.?\s+", "", raw)):
                break
            if HIGHLIGHTS.match(raw):
                in_highlights = True
                continue
            in_highlights = False
            name, lvl, num = heading_info(raw)
            level = lvl or e.level or 1
            cur = Section(title=tidy_title(name), level=min(3, max(1, level)), source_number=num, kind=special_kind(raw))
            p.sections.append(cur)
            continue
        if in_highlights:
            for it in (e.items or [e.runs]):
                t = plain(it).strip(" •-")
                if t:
                    p.highlights.append(t)
            continue
        if e.kind == "para" and KEYWORDS.match(e.text) and not p.keywords:
            kw = KEYWORDS.sub("", e.text, count=1)
            p.keywords = [k.strip(" .") for k in re.split(r"\s*[;,·•]\s*", kw) if k.strip(" .")]
            continue
        if cur is None:
            cur = Section(title="Introduction" if not p.sections else "", level=1)
            p.sections.append(cur)
        blk = e.block or Block(kind=e.kind if e.kind in ("para", "list", "code", "quote", "equation") else "para",
                               runs=e.runs, items=e.items, ordered=e.ordered)
        cur.blocks.append(blk)
    # headings with no content and no subsections are kept (structure), empty untitled leading section dropped
    p.sections = [s for s in p.sections if s.title or s.blocks]
    _infer_levels(p)
    return p


def normalize(p: Paper) -> None:
    """Remove the source format's typographic conventions so the target format's apply:
    whole-paragraph bold/italic (e.g. IEEE's bold abstract) and all-caps captions."""

    def plain_style(runs: list[Inline]) -> list[Inline]:
        texts = [r for r in runs if r.t.strip() and not r.cite and not r.math and not r.xref]
        if not texts:
            return runs
        if all(r.b for r in texts):
            for r in runs:
                r.b = False
        if all(r.i for r in texts) and sum(len(r.t) for r in texts) > 80:
            for r in runs:
                r.i = False
        return runs

    p.abstract = plain_style(p.abstract)
    for b in p.all_blocks():
        if b.kind == "para":
            plain_style(b.runs)
        if b.caption:
            plain_style(b.caption)
            txt = "".join(r.t for r in b.caption if not r.cite)
            letters = [c for c in txt if c.isalpha()]
            if len(letters) > 8 and all(c.isupper() for c in letters):
                first = True
                for r in b.caption:
                    if r.t and not r.cite:
                        words = []
                        for w in re.split(r"(\s+)", r.t):
                            if w.strip() and re.fullmatch(r"[A-Z]{2,5}\d*|[A-Z]+\d+[A-Z\d]*", w.strip(",.;:()")) and len(w) <= 5:
                                words.append(w)  # likely an acronym (CNN, F1, IoT) - keep
                            else:
                                words.append(w.lower())
                        r.t = "".join(words)
                        if first and r.t.strip():
                            i = len(r.t) - len(r.t.lstrip())
                            r.t = r.t[:i] + r.t[i:i + 1].upper() + r.t[i + 1:]
                            first = False


def _infer_levels(p: Paper) -> None:
    """If the source had no numbering, levels come from the readers' size hints; normalise to start at 1."""
    if p.sections and min(s.level for s in p.sections) > 1:
        d = min(s.level for s in p.sections) - 1
        for s in p.sections:
            s.level -= d


def _strip(runs: list[Inline]) -> list[Inline]:
    while runs and not runs[-1].cite and not runs[-1].t.strip():
        runs = runs[:-1]
    return runs


def _drop_prefix(runs: list[Inline], pat: re.Pattern) -> list[Inline]:
    """Remove a label like 'Abstract—' even when it spans several runs (italic label + bold text)."""
    out = [r.model_copy() for r in runs]
    full = "".join(r.t if not (r.cite or r.math) else "\x00" for r in out)
    m = pat.match(full)
    n = m.end() if m else 0
    for r in out:
        if n <= 0:
            break
        if r.cite or r.math:
            break
        cut = min(n, len(r.t))
        r.t = r.t[cut:]
        n -= cut
    return [r for r in out if r.t or r.cite or r.math]


# ------------------------------------------------------------------ authors and affiliations
AFFIL_CUES = re.compile(r"\b(universit|institut|college|school|department|dept\.|faculty|laborator|lab\b|centre|center|"
                        r"academy|hospital|inc\.|ltd|gmbh|corporation|corp\.|research|technologies|polytechnic|campus|"
                        r"street|road|india|usa|china|germany|uk\b|france|japan|canada|australia)", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
MARK = r"(?:\d{1,2}|[*†‡§¶#a-h])"


def authors_from_front(p: Paper, lines: list[str]) -> None:
    if not lines:
        return
    aff_lines, name_lines, emails = [], [], []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        found = EMAIL.findall(s)
        if found and len(EMAIL.sub("", s).strip(" ,;:{}()<>Email-mail")) < 6:
            emails += found
            continue
        if re.match(rf"^\s*{MARK}\s*[A-Z]", s) and AFFIL_CUES.search(s) or AFFIL_CUES.search(s) and not _looks_like_names(s):
            aff_lines.append(s)
            emails += found
        elif _looks_like_names(s):
            name_lines.append(s)
        elif aff_lines or len(s.split()) > 12:
            aff_lines.append(s)
        else:
            name_lines.append(s)
    # affiliations: "1 Dept..., Univ...," with leading markers
    marks: dict[str, int] = {}
    for s in aff_lines:
        m = re.match(rf"^\s*({MARK})\s*(.+)$", s)
        text = EMAIL.sub("", m.group(2) if m else s).strip(" ,;")
        if not text:
            continue
        if not m and p.affiliations and not re.match(r"^[A-Z]", text):
            p.affiliations[-1] += " " + text  # continuation line
            continue
        p.affiliations.append(text)
        if m:
            marks[m.group(1)] = len(p.affiliations) - 1
    joined = " , ".join(name_lines)
    joined = re.sub(r"\s+and\s+|\s*&\s*", ", ", joined)
    for raw in [x.strip() for x in joined.split(",") if x.strip()]:
        m = re.match(rf"^(.*?[a-zà-ÿ.])\s*((?:{MARK}\s*,?\s*)+)$", raw)
        name, sup = (m.group(1), m.group(2)) if m else (raw, "")
        name = re.sub(r"[*†‡§¶]+$", "", name).strip(" ,")
        if not re.search(r"[A-Za-z]", name) or len(name.split()) > 6:
            continue
        a = Author(name=name, corresponding="*" in raw)
        for mk in re.findall(MARK, sup):
            if mk in marks:
                a.affiliations.append(marks[mk])
        if not a.affiliations and len(p.affiliations) == 1:
            a.affiliations = [0]
        p.authors.append(a)
    for e in emails:  # attach emails to authors by name similarity
        local = re.sub(r"[^a-z]", "", e.split("@")[0].lower())
        best = next((a for a in p.authors if not a.email and any(part.lower()[:4] in local for part in a.name.split() if len(part) > 2)), None)
        if best:
            best.email = e
        elif p.authors and not p.authors[0].email:
            p.authors[0].email = e


def _looks_like_names(s: str) -> bool:
    t = re.sub(rf"(?<=[a-z]){MARK}+", "", s)
    t = re.sub(r"[*†‡§¶]", "", t)
    parts = [x.strip() for x in re.split(r",|\band\b|&", t) if x.strip()]
    if not parts:
        return False
    ok = sum(1 for x in parts if re.fullmatch(r"(?:[A-ZÀ-Ý][\w'’\-]*\.?\s+){1,3}[A-ZÀ-Ý][\w'’\-]+", x) or
             re.fullmatch(r"[A-ZÀ-Ý][\w'’\-]+\s+(?:[A-Z]\.\s*)+[A-ZÀ-Ý][\w'’\-]+", x))
    return ok >= max(1, int(len(parts) * 0.6)) and not AFFIL_CUES.search(t)
