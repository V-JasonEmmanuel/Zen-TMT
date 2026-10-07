"""Conversion report: the publisher's checks plus content fidelity (nothing lost or invented)."""
from __future__ import annotations

import re
from collections import Counter

from backend.papers.formats import Format
from backend.papers.model import Paper, plain
from backend.papers.writers.common import arrange, statement_title


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z]{3,}|\d+(?:[.,]\d+)?", s.lower())


def fidelity(paper: Paper, raw_text: str) -> dict:
    """Share of the source's words that are present in the converted paper (body, captions, front, refs)."""
    parts = [paper.title, plain(paper.abstract), " ".join(paper.keywords), " ".join(a.name for a in paper.authors),
             " ".join(a.email for a in paper.authors), " ".join(paper.affiliations), " ".join(paper.highlights),
             " ".join(paper.meta.get("footnotes", []))]
    for s in paper.sections:
        parts += [s.title, s.source_number]  # source numbering is replaced by the target's
        for b in s.blocks:
            parts += [plain(b.runs), plain(b.caption), " ".join(plain(i) for i in b.items), " ".join(" ".join(r) for r in b.rows), b.latex]
    parts += [r.raw for r in paper.references]
    parts += list((paper.meta.get("article_info") or {}).values()) + list(paper.meta.get("author_notes") or [])
    have = Counter(_words(" ".join(parts)))
    joined = " ".join(parts).lower()
    # words the source broke across lines ("pro-\ntion") are compared as the whole word
    raw_text = re.sub(r"([A-Za-z]+)-[ \t]*\n\s*([a-z]+)",
                      lambda m: m.group(1) + ("-" if f"{m.group(1)}-{m.group(2)}".lower() in joined else "") + m.group(2), raw_text)
    from backend.papers.references import join_urls

    raw_text = join_urls(raw_text)  # DOIs/URLs broken over lines are whole in the output
    raw_text = re.sub(r"(?<=[a-z])ID(?=[\d☯*†‡§,\s]|$)", "", raw_text, flags=re.M)  # ORCID icon read as 'ID'
    # structural labels are replaced by the target format's own (they are not content)
    labels = {"abstract", "keywords", "keyword", "index", "terms", "references", "bibliography", "fig", "figure", "table",
              "tab", "eq", "eqs", "equation", "email", "mail", "summary", "acknowledgment", "acknowledgments", "acknowledgements",
              "iii", "vii", "viii", "xii", "xiii"}
    src = Counter(w for w in _words(raw_text) if w not in labels)
    have.update({w: n for w, n in src.items() if w in labels})
    if not src:
        return {"coverage": 1.0, "missing_sample": []}
    kept = sum(min(n, have.get(w, 0)) for w, n in src.items())
    total = sum(src.values())
    missing = [w for w, n in src.most_common() if have.get(w, 0) == 0][:15]
    return {"coverage": round(kept / total, 4), "missing_sample": missing}


def report(paper: Paper, fmt: Format, raw_text: str, math_as_text: int = 0, extra: list[str] | None = None) -> dict:
    checks: list[dict] = []

    def add(level: str, title: str, detail: str = ""):
        checks.append({"level": level, "title": title, "detail": detail})

    lay = arrange(paper, fmt)
    words = len(plain(paper.abstract).split())
    lo, hi = fmt.abstract_words
    if not paper.abstract:
        add("error", "No abstract found", f"{fmt.name} requires an abstract of {lo}-{hi} words.")
    elif not lo <= words <= hi:
        add("warning", f"Abstract has {words} words", f"{fmt.name} expects {lo}-{hi} words.")
    else:
        add("ok", f"Abstract: {words} words", f"Within the {lo}-{hi} word range.")
    klo, khi = fmt.keywords_count
    if not paper.keywords:
        add("warning", "No keywords found", f"{fmt.name} expects {klo}-{khi} keywords.")
    elif not klo <= len(paper.keywords) <= khi:
        add("warning", f"{len(paper.keywords)} keywords", f"{fmt.name} expects {klo}-{khi}.")
    else:
        add("ok", f"{len(paper.keywords)} keywords")
    if not paper.title:
        add("error", "No title found")
    if not paper.authors:
        add("warning", "No authors recognised", "Add the authors and affiliations in the Structure tab.")
    else:
        add("ok", f"{len(paper.authors)} author(s), {len(paper.affiliations)} affiliation(s)")
    nsec = sum(1 for n in lay.body if n.section.level == 1)
    add("ok" if nsec else "warning", f"{nsec} numbered sections" if fmt.numbering != "none" else f"{nsec} sections")
    refs = paper.references
    if refs:
        parsed = sum(1 for r in refs if r.status == "parsed")
        partial = [r for r in refs if r.status == "partial"]
        raw = [r for r in refs if r.status == "raw"]
        add("ok" if not raw and not partial else "warning",
            f"References: {parsed} of {len(refs)} fully formatted in the {fmt.publisher} style",
            ("; ".join(filter(None, [f"{len(partial)} partly parsed (check them)" if partial else "",
                                     f"{len(raw)} kept as written - edit them in the References tab" if raw else ""]))))
        uncited = [r for r in refs if not r.cited]
        if uncited:
            add("warning", f"{len(uncited)} reference(s) never cited in the text", ", ".join(r.source_label or r.key for r in uncited[:10]))
        llm = sum(1 for r in refs if r.method == "llm")
        if llm:
            add("info", f"{llm} reference(s) read with the local AI", "Every field was checked to appear verbatim in the original reference.")
    else:
        add("warning", "No reference list found")
    figs = [b for b in paper.all_blocks() if b.kind == "figure"]
    tabs = [b for b in paper.all_blocks() if b.kind == "table"]
    nocap = [b for b in figs + tabs if not b.caption]
    add("ok" if not nocap else "warning", f"{len(figs)} figure(s), {len(tabs)} table(s)",
        f"{len(nocap)} without a caption" if nocap else "All captioned and renumbered in the target style.")
    img_tabs = [b for b in tabs if not b.rows]
    if img_tabs:
        add("warning", f"{len(img_tabs)} table(s) kept as images", "Their cells could not be read reliably from the source.")
    eq_img = [b for b in paper.all_blocks() if b.kind == "equation" and not b.latex and not b.omml]
    if eq_img:
        add("warning", f"{len(eq_img)} equation(s) recovered as images", "PDF sources do not contain equation source; retype them for the final submission (marked TODO in main.tex).")
    if math_as_text:
        add("info", f"{math_as_text} math expression(s) shown as text in Word/PDF", "The LaTeX version keeps them exact.")
    for k in lay.missing:
        add("warning", f"Missing: {statement_title(fmt, k)}", "A placeholder was added; please complete it.")
    if fmt.id == "elsevier" and not paper.highlights:
        add("warning", "No highlights", "Elsevier asks for 3-5 highlights (max. 85 characters each).")
    for n in fmt.notes:
        add("info", n)
    for w in paper.warnings + (extra or []):
        add("warning", w)
    fid = fidelity(paper, raw_text)
    lvl = "ok" if fid["coverage"] >= 0.97 else "warning" if fid["coverage"] >= 0.9 else "error"
    add(lvl, f"Content preserved: {fid['coverage'] * 100:.1f}% of the source text",
        "The paper's own wording is carried over unchanged." + (f" Words not found in the conversion: {', '.join(fid['missing_sample'][:10])}" if fid["coverage"] < 0.99 and fid["missing_sample"] else ""))
    return {"format": fmt.id, "checks": checks, "fidelity": fid,
            "summary": {k: sum(1 for c in checks if c["level"] == k) for k in ("ok", "info", "warning", "error")}}


def markdown(rep: dict, fmt: Format, title: str) -> str:
    icon = {"ok": "✓", "info": "i", "warning": "!", "error": "✗"}
    lines = [f"# Conversion report - {fmt.name}", "", f"Paper: {title}", ""]
    for c in rep["checks"]:
        lines.append(f"- [{icon[c['level']]}] **{c['title']}**" + (f" - {c['detail']}" if c["detail"] else ""))
    return "\n".join(lines) + "\n"
