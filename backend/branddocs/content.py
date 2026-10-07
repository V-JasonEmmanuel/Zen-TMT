"""Read the uploaded document (PDF, Word, Markdown, text) into the content of a brand document.

The Research Papers readers do the low-level reading (text order, columns, headings by type size or Word
style, lists, figures, tables, inline formatting, broken words, page furniture). This module turns their
elements into document sections for *any* document - not only papers: no front-matter/author parsing,
headings that a designer set over several lines are joined, and runs of large/bold lines that are really
sentences become emphasised paragraphs. The wording is kept exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.papers.model import Block, Inline

CONCLUSION = re.compile(r"^\s*(\d+(\.\d+)*\.?\s*)?(conclusions?|concluding remarks|summary|in summary|final thoughts|closing thoughts|"
                        r"the verdict|key takeaways|takeaways|wrap[- ]?up|the bottom line|in closing)\b", re.I)
AUTHOR_LABEL = re.compile(r"^\s*(authored by|written by|prepared by|authors?)\s*:?\s*$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
REFS = re.compile(r"^\s*(\d+\.?\s*)?(references|bibliography|works cited|sources)\s*$", re.I)


@dataclass
class DocSection:
    title: str
    level: int = 1
    blocks: list[Block] = field(default_factory=list)
    kind: str = "body"

    @property
    def text(self) -> str:
        out = []
        for b in self.blocks:
            out.append("".join(r.t for r in b.runs))
            out += ["".join(r.t for r in it) for it in b.items]
        return " ".join(out)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class DocAuthor:
    name: str
    detail: list[str] = field(default_factory=list)  # role / organisation lines
    email: str = ""


@dataclass
class DocContent:
    title: str
    sections: list[DocSection]
    conclusion: Optional[DocSection] = None
    authors: list[DocAuthor] = field(default_factory=list)
    base_dir: Path = Path(".")  # figures are relative to this folder
    notes: list[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def words(self) -> int:
        return sum(s.words for s in self.sections) + (self.conclusion.words if self.conclusion else 0)

    def all_text(self) -> str:
        parts = [self.title] + [s.title + " " + s.text for s in self.sections]
        if self.conclusion:
            parts.append(self.conclusion.title + " " + self.conclusion.text)
        return "\n".join(parts)


def _clean_runs(runs: list[Inline]) -> list[Inline]:
    """Citations, cross references and math print as written in the source."""
    out = []
    for r in runs:
        if r.cite and not r.t.strip():
            out.append(Inline(t=r.raw_cite or "", b=r.b, i=r.i))
        elif r.math and not r.t:
            out.append(Inline(t=r.math, i=True))
        else:
            out.append(r.model_copy())
    return out


def _sentences_to_paras(lines: list[str]) -> list[str]:
    """Lines of a block set in large/bold type -> paragraphs (a line ending a sentence before a capital starts one)."""
    paras: list[str] = []
    cur = ""
    for ln in lines:
        ln = ln.strip()
        if cur and re.search(r"[.!?]['\"”’)]*$", cur) and ln[:1].isupper():
            paras.append(cur)
            cur = ln
        else:
            from backend.papers.readers.pdf import _join_lines

            cur = _join_lines([cur, ln]) if cur else ln
    if cur:
        paras.append(cur)
    return paras


ROLE_WORDS = {"head", "practice", "director", "manager", "lead", "senior", "chief", "vice", "president", "officer", "engineer",
              "architect", "consultant", "analyst", "partner", "principal", "specialist", "scientist", "professor", "vp", "ceo",
              "cto", "cio", "coo", "cfo", "founder", "associate", "assistant", "global", "group", "executive", "evp", "svp", "avp"}


def _author_lines(runs: list[Inline]) -> list[str]:
    """'Daniel Gomez Practice Head, DE&A - Core daniel.gomez@zensar.com' -> name, role, e-mail."""
    text = "".join(r.t for r in runs).strip()
    email = EMAIL.search(text)
    rest = (text[:email.start()] + text[email.end():]).strip() if email else text
    bold = runs[0].t.strip() if runs and runs[0].b and len(runs[0].t.split()) <= 4 else ""
    if bold and rest.startswith(bold):
        name, role = bold, rest[len(bold):].strip(" ,")
    else:
        words = rest.split()
        k = 2
        while k < min(4, len(words)) and words[k][:1].isupper() and words[k].lower().strip(",") not in ROLE_WORDS:
            k += 1
        name, role = " ".join(words[:k]), " ".join(words[k:]).strip(" ,")
    return [x for x in (name, role, email.group(0) if email else "") if x]


def _join_broken(blocks: list[Block]) -> list[Block]:
    """Paragraphs the reader split mid-sentence (lines of a designed card) are joined again."""
    out: list[Block] = []
    for b in blocks:
        if out and b.kind == "para" and out[-1].kind == "para" and b.runs and out[-1].runs:
            prev = "".join(r.t for r in out[-1].runs).rstrip()
            nxt = "".join(r.t for r in b.runs).lstrip()
            if prev and nxt and not re.search(r"[.!?:;”\"’)]$", prev) and (nxt[:1].islower() or len(nxt.split()) <= 3):
                out[-1].runs[-1].t = out[-1].runs[-1].t.rstrip() + " "
                out[-1].runs += b.runs
                continue
        out.append(b)
    return out


def build(elems: list, title: str, filename: str, drop_texts: list[str] = ()) -> DocContent:
    from backend.papers.structure import heading_info

    drop = {re.sub(r"\W+", " ", t).strip().lower() for t in drop_texts if t}
    # 1) join headings a designer broke over several lines; sentence-like runs of heading lines are emphasised text
    merged: list = []
    i = 0
    while i < len(elems):
        e = elems[i]
        if e.kind != "heading":
            merged.append(e)
            i += 1
            continue
        group = [e]
        while i + len(group) < len(elems):
            n = elems[i + len(group)]
            if n.kind != "heading" or heading_info(n.text)[2] or heading_info(group[0].text)[2] or (n.level or 0) != (e.level or 0):
                break
            if AUTHOR_LABEL.match(n.text) or AUTHOR_LABEL.match(group[-1].text):
                break
            group.append(n)
        texts = [g.text for g in group]
        words = sum(len(t.split()) for t in texts)
        if len(group) > 1 and (words > 16 or (len(group) >= 4)):
            from backend.papers.structure import Elem

            for para in _sentences_to_paras(texts):
                merged.append(Elem(kind="para", runs=[Inline(t=para, b=True)]))
        elif len(group) > 1:
            from backend.papers.readers.pdf import _join_lines
            from backend.papers.structure import Elem

            merged.append(Elem(kind="heading", runs=[Inline(t=_join_lines(texts))], level=e.level))
        else:
            merged.append(e)
        i += len(group)
    # 2) sections
    sections: list[DocSection] = []
    cur = DocSection(title="", level=1)
    authors: list[DocAuthor] = []
    author_mode = False
    levels = sorted({e.level for e in merged if e.kind == "heading" and e.level})
    for e in merged:
        txt = e.text if e.kind in ("heading", "para", "quote") else ""
        if txt and re.sub(r"\W+", " ", txt).strip().lower() in drop:
            continue
        if e.kind == "heading" and AUTHOR_LABEL.match(txt):
            author_mode = True
            continue
        if author_mode:
            lines = [txt] if txt else []
            if e.kind == "list":
                lines = ["".join(r.t for r in it) for it in e.items]
            elif e.kind in ("para", "heading") and len(txt.split()) > 4 and not txt.rstrip().endswith("."):
                lines = _author_lines(e.runs)  # name, role and e-mail joined into one line by the reader
            for ln in lines:
                if EMAIL.search(ln) and authors and not authors[-1].email and len(ln.split()) <= 3:
                    authors[-1].email = EMAIL.search(ln).group(0)
                elif not authors or (authors[-1].detail or authors[-1].email) and len(ln.split()) <= 4 and ln[:1].isupper() and not EMAIL.search(ln):
                    authors.append(DocAuthor(name=ln.strip()))
                elif len(ln.split()) <= 10:
                    authors[-1].detail.append(ln.strip())
                else:
                    author_mode = False
                    break
            if author_mode:
                continue
        if e.kind == "heading":
            name, lvl, num = heading_info(txt)
            level = lvl or (levels.index(e.level) + 1 if e.level in levels else 1)
            if cur.blocks or cur.title:
                sections.append(cur)
            cur = DocSection(title=txt, level=max(1, min(3, level)), kind="references" if REFS.match(txt) else "body")
            continue
        if e.block is not None:
            b = e.block.model_copy(deep=True)
        elif e.kind == "list":
            b = Block(kind="list", items=[_clean_runs(it) for it in e.items], ordered=e.ordered)
        else:
            b = Block(kind=e.kind if e.kind in ("para", "quote", "code", "equation") else "para", runs=_clean_runs(e.runs))
        b.runs = _clean_runs(b.runs)
        cur.blocks.append(b)
    if cur.blocks or cur.title:
        sections.append(cur)
    for s in sections:
        s.blocks = _join_broken(s.blocks)
    sections = [s for s in sections if s.blocks or s.title]
    # drop empty headings that only introduce the next heading of a lower level? keep: they are structure
    doc_title = (title or "").strip()
    if not doc_title and sections and not sections[0].title and sections[0].blocks:
        first = sections[0].blocks[0]
        t = "".join(r.t for r in first.runs).strip()
        if 0 < len(t.split()) <= 14:
            doc_title = t
            sections[0].blocks.pop(0)
    if not doc_title and sections and sections[0].title and sections[0].level == 1 and len(sections) > 1:
        doc_title = sections[0].title
        sections[0].title = ""
    doc_title = doc_title or Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    sections = [s for s in sections if s.blocks or s.title]
    # a short untitled lead (standfirst) opens the first titled section instead of standing alone
    if len(sections) > 1 and not sections[0].title and sections[0].words < 60 and sections[1].title:
        sections[1].blocks = sections[0].blocks + sections[1].blocks
        sections.pop(0)
    conclusion = None
    for s in reversed(sections):
        if s.level == 1 and s.kind == "body" and CONCLUSION.match(s.title):
            conclusion = s
            break
    if conclusion is None:  # a lone conclusion at a lower level (all headings the same size in the source)
        for s in reversed(sections):
            if s.kind == "body" and CONCLUSION.match(s.title):
                conclusion = s
                break
    if conclusion is not None:
        i = sections.index(conclusion)
        j = i + 1
        while j < len(sections) and sections[j].level > conclusion.level and sections[j].kind == "body":
            if sections[j].title:
                conclusion.blocks.append(Block(kind="para", runs=[Inline(t=sections[j].title, b=True)]))
            conclusion.blocks += sections[j].blocks
            j += 1
        del sections[i:j]
        conclusion.blocks = _join_broken(conclusion.blocks)
        if not conclusion.blocks:
            sections.insert(i, conclusion)
            conclusion = None
    # all-level-2/3 documents: the highest level used becomes level 1
    if sections:
        top = min(s.level for s in sections if s.title) if any(s.title for s in sections) else 1
        for s in sections:
            s.level = max(1, s.level - top + 1)
    return DocContent(title=doc_title, sections=sections, conclusion=conclusion, authors=authors)


def read(src: Path, work_dir: Path, kind: str, filename: str, drop_texts: list[str] = ()) -> DocContent:
    if kind == "pdf":
        from backend.papers.readers import pdf

        data = pdf.read(src, work_dir, general=True)
    else:
        from backend.papers.readers import read_any

        data = read_any(src, work_dir, kind)
    elems = list(data["elems"])
    if data.get("front"):  # readers that still separate a front block: it is ordinary text here
        from backend.papers.structure import Elem

        elems = [Elem(kind="para", runs=[Inline(t=t)]) for t in data["front"] if t.strip()] + elems
    if data.get("refs"):
        from backend.papers.structure import Elem

        elems.append(Elem(kind="heading", runs=[Inline(t="References")], level=0))
        elems.append(Elem(kind="list", items=[[Inline(t=t)] for t, _ in data["refs"]], ordered=False))
    doc = build(elems, data.get("title", ""), filename, drop_texts)
    doc.base_dir = work_dir
    doc.raw_text = data.get("raw_text", "")
    doc.notes += [n for n in data.get("notes", []) if "inline math" in n.lower()]
    if not doc.sections and not doc.conclusion:
        raise ValueError("No text could be read from the document.")
    return doc
