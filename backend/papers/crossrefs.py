"""Cross references in the text ("Table II", "Fig. 3", "Figure 3", "Eq. (2)") become live references,
so each format prints its own convention ("Table 2", "TABLE II" -> "Table~\\ref{tab2}") and numbering."""
from __future__ import annotations

import re

from backend.papers.model import Inline, Paper

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
PAT = re.compile(r"\b(?:(Fig(?:ure)?s?\.?|FIG(?:URE)?\.?)|(Tables?|TABLES?|Tab\.)|(Eqs?\.|Equations?))\s*~?\s*"
                 r"(\(\s*(?:\d{1,3}|[IVX]{1,5})[a-z]?\s*\)|(?:\d{1,3}|[IVX]{1,5})[a-z]?)(?![\w.]\d)(?!\w)")


def link(paper: Paper) -> int:
    figs = [b.label for b in paper.all_blocks() if b.kind == "figure"]
    tabs = [b.label for b in paper.all_blocks() if b.kind == "table"]
    eqs = {}
    k = 0
    for b in paper.all_blocks():
        if b.kind == "equation":
            k += 1
            eqs[b.number or str(k)] = b.label
    count = 0

    def resolve(m: re.Match) -> str:
        num = m.group(4).strip("() ")
        n = ROMAN.get(num) if num in ROMAN else int(re.match(r"\d+", num).group()) if re.match(r"\d+", num) else None
        if m.group(1) and n and n <= len(figs):
            return figs[n - 1]
        if m.group(2) and n and n <= len(tabs):
            return tabs[n - 1]
        if m.group(3):
            return eqs.get(num, "")
        return ""

    def fix(runs: list[Inline]) -> list[Inline]:
        nonlocal count
        out: list[Inline] = []
        for r in runs:
            if r.cite or r.math or r.xref or not r.t:
                out.append(r)
                continue
            pos = 0
            for m in PAT.finditer(r.t):
                lab = resolve(m)
                if not lab:
                    continue
                if m.start() > pos:
                    out.append(r.model_copy(update={"t": r.t[pos:m.start()]}))
                out.append(Inline(t=m.group(0), xref=lab, b=r.b, i=r.i))
                count += 1
                pos = m.end()
            if pos < len(r.t):
                out.append(r.model_copy(update={"t": r.t[pos:]}))
        return out

    for s in paper.sections:
        for b in s.blocks:
            b.runs = fix(b.runs)
            b.items = [fix(i) for i in b.items]
    return count


def render(fmt, lay, label: str, original: str) -> str:
    """Printed form of a cross reference in the target format (Word/PDF)."""
    from backend.papers.writers.common import roman

    kind = label[:3]
    n = lay.by_label.get(label)
    if n is None:
        return original
    plural = bool(re.match(r"\w+s\b", original.split()[0])) if original.split() else False
    if kind == "fig":
        word = fmt.fig_label.rstrip(".") + ("." if fmt.fig_label.endswith(".") else "")
        return f"{word[:-1] + 's.' if plural and word.endswith('.') else word + ('s' if plural else '')} {n}"
    if kind == "tab":
        num = roman(n) if fmt.table_roman else str(n)
        return f"Table{'s' if plural else ''} {num}"
    return f"{'Eqs.' if plural else 'Eq.'} ({n})" if fmt.id != "apa7" else f"Equation {n}"
