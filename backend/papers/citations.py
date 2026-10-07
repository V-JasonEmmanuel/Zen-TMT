"""In-text citations: find them in the paper's text and link them to reference entries.

Handles numeric ([1], [1, 4], [2-5], superscript numbers), author-year parenthetical
((Smith et al., 2020; Lee & Park 2019a)) and narrative (Smith and Jones (2019)) citations.
Each recognised citation becomes an Inline with `cite` = reference keys, so writers can re-render
it in the target style. Anything that cannot be resolved is left as written and reported.
"""
from __future__ import annotations

import re
import unicodedata

from backend.papers.model import Inline, Paper, Reference

NUM_GROUP = re.compile(r"\[(\s*\d{1,4}(?:\s*[-–—,]\s*\d{1,4})*\s*)\]")
NUM_RANGE = re.compile(r"\[(\d{1,4})\]\s*[-–—]\s*\[(\d{1,4})\]")
PAREN = re.compile(r"\(([^()]{2,400}?\b(?:19|20)\d{2}[a-z]?(?:[^()]{0,200}?))\)")
NARRATIVE = re.compile(r"\b([A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+(?:et\s+al\.?|(?:and|&)\s+[A-Z][A-Za-zÀ-ÿ'’\-]+))?)\s+\(((?:19|20)\d{2}[a-z]?)\)")
PART = re.compile(r"([A-Z][A-Za-zÀ-ÿ'’\-]+(?:[^,;0-9]*?))[,\s]+((?:19|20)\d{2})([a-z])?")


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _expand(spec: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", spec.strip()):
        m = re.match(r"(\d+)\s*[-–—]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 50:
                out += list(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


class Linker:
    def __init__(self, refs: list[Reference]):
        self.refs = refs
        self.by_label: dict[int, str] = {}
        for i, r in enumerate(refs, start=1):
            m = re.search(r"\d+", r.source_label or "")
            self.by_label[int(m.group()) if m else i] = r.key
        self.by_author: dict[tuple[str, str], list[Reference]] = {}
        for r in refs:
            fam = ""
            if r.csl.get("author"):
                a = r.csl["author"][0]
                fam = a.get("family") or a.get("literal") or ""
            if not fam:
                fam = (r.raw.split(",")[0].split()[0] if r.raw.split() else "")
            year = str((r.csl.get("issued") or {}).get("date-parts", [[""]])[0][0] or "")
            if not year and (m := re.search(r"(?:19|20)\d{2}", r.raw)):
                year = m.group()
            self.by_author.setdefault((_n(fam), year), []).append(r)
        self.unresolved: list[str] = []

    def numeric(self, nums: list[int]) -> list[str]:
        keys = [self.by_label.get(n) for n in nums]
        return [k for k in keys if k] if all(keys) else []

    def author_year(self, name: str, year: str, suffix: str = "") -> str:
        fam = _n(re.split(r"\s+(?:et\s+al\b|and\b|&)", name.strip())[0].strip(" ,"))
        cands = self.by_author.get((fam, year), [])
        if not cands:  # surname with particles / hyphens: match on the last word
            last = fam.split()[-1] if fam.split() else fam
            cands = [r for (f, y), rs in self.by_author.items() if y == year and (f.endswith(last) or last.endswith(f)) for r in rs]
        if len(cands) > 1 and suffix:
            idx = ord(suffix) - 97
            withsuf = [r for r in cands if r.csl.get("year-suffix") == suffix]
            cands = withsuf or (cands[idx:idx + 1] if idx < len(cands) else cands)
        return cands[0].key if cands else ""


def link_runs(runs: list[Inline], linker: Linker, style: str) -> list[Inline]:
    out: list[Inline] = []
    for r in runs:
        if r.cite or r.math or not r.t:
            out.append(r)
            continue
        if r.sup and style == "numeric" and re.fullmatch(r"\s*\d{1,3}(?:\s*[-–,]\s*\d{1,3})*\s*", r.t):
            keys = linker.numeric(_expand(r.t))  # superscript (Vancouver) citations
            if keys:
                out.append(Inline(cite=keys, raw_cite=r.t))
                continue
        out += _split_text(r, linker, style)
    return out


def _split_text(r: Inline, linker: Linker, style: str) -> list[Inline]:
    text = r.t
    spans: list[tuple[int, int, list[str], str, str]] = []  # start, end, keys, raw, prefix kept as text
    if style in ("numeric", "unknown"):
        ranged: list[tuple[int, int]] = []
        for m in NUM_RANGE.finditer(text):  # IEEE: [1]–[3] = references 1 to 3
            a, b = int(m.group(1)), int(m.group(2))
            keys = linker.numeric(list(range(a, b + 1))) if 0 < b - a <= 50 else []
            if keys:
                spans.append((m.start(), m.end(), keys, m.group(0), ""))
                ranged.append((m.start(), m.end()))
        for m in NUM_GROUP.finditer(text):
            if any(a <= m.start() < b for a, b in ranged):
                continue
            nums = _expand(m.group(1))
            if nums and max(nums) > max(len(linker.refs), 1) * 1.5 + 5:
                continue  # values in brackets ("[10, 100, 1000]"), not citations
            keys = linker.numeric(nums) if nums else []
            if keys:
                spans.append((m.start(), m.end(), keys, m.group(0), ""))
            elif nums:
                linker.unresolved.append(m.group(0))
    if style in ("author-year", "unknown"):
        taken: list[tuple[int, int]] = []
        for m in PAREN.finditer(text):
            keys = []
            ok = True
            for part in re.split(r";", m.group(1)):
                pm = PART.search(part)
                if not pm:
                    ok = False
                    break
                k = linker.author_year(pm.group(1), pm.group(2), pm.group(3) or "")
                if not k:
                    ok = False
                    break
                keys.append(k)
            if ok and keys:
                spans.append((m.start(), m.end(), keys, m.group(0), ""))
                taken.append((m.start(), m.end()))
            elif re.search(r"\b[A-Z][a-z]+.{0,40}\b(?:19|20)\d{2}", m.group(1)):
                linker.unresolved.append(m.group(0))
        for m in NARRATIVE.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            k = linker.author_year(m.group(1), m.group(2)[:4], m.group(2)[4:])
            if k:  # keep the author names as text; the year part becomes the citation
                ys = m.start(2) - 1
                spans.append((ys, m.end(), [k], m.group(0)[ys - m.start():], "narrative"))
    spans.sort()
    out: list[Inline] = []
    pos = 0
    for a, b, keys, raw, kind in spans:
        if a < pos:
            continue
        if a > pos:
            out.append(r.model_copy(update={"t": text[pos:a]}))
        out.append(Inline(cite=keys, raw_cite=raw, t="narrative" if kind else ""))
        pos = b
    if pos < len(text):
        out.append(r.model_copy(update={"t": text[pos:]}))
    return out or [r]


def detect_style(texts: list[str]) -> str:
    joined = " ".join(texts)
    num = len(NUM_GROUP.findall(joined))
    ay = len(PAREN.findall(joined)) + len(NARRATIVE.findall(joined))
    if num == 0 and ay == 0:
        return "unknown"
    return "numeric" if num >= ay else "author-year"


def link_paper(paper: Paper) -> list[str]:
    """Link every citation in the paper; mark cited references; return warnings."""
    if paper.source_citation_style == "latex":
        return []
    linker = Linker(paper.references)
    style = paper.source_citation_style or "unknown"
    for b in paper.all_blocks():
        b.runs = link_runs(b.runs, linker, style)
        b.items = [link_runs(it, linker, style) for it in b.items]
        b.caption = link_runs(b.caption, linker, style)
    paper.abstract = link_runs(paper.abstract, linker, style)
    cited = {k for b in paper.all_blocks() for r in (*b.runs, *b.caption, *[x for it in b.items for x in it]) for k in r.cite}
    cited |= {k for r in paper.abstract for k in r.cite}
    for ref in paper.references:
        ref.cited = ref.key in cited
    warnings = []
    if linker.unresolved:
        uniq = list(dict.fromkeys(linker.unresolved))
        warnings.append(f"{len(uniq)} citation(s) could not be matched to a reference and were kept as written: "
                        + ", ".join(uniq[:8]) + ("…" if len(uniq) > 8 else ""))
    uncited = [r for r in paper.references if not r.cited]
    if uncited and paper.references:
        warnings.append(f"{len(uncited)} reference(s) are never cited in the text: "
                        + ", ".join(r.source_label or r.key for r in uncited[:8]))
    return warnings
