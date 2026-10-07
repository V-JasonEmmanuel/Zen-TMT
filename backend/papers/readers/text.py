"""Raw content: Markdown, plain text, or text pasted into the app.

Markdown structure is used directly (# headings, lists, tables, $$ equations $$, inline $math$).
Plain text is structured from the paper's own conventions: the first line is the title, numbered
or short capitalised lines are headings ("2. Related Work", "III. METHOD", "Conclusion"),
"Abstract" / "Keywords" / "References" are recognised, blank lines separate paragraphs.
"""
from __future__ import annotations

import re
from pathlib import Path

from backend.papers.model import Block, Inline
from backend.papers.structure import REFS_HEAD, Elem, heading_info, special_kind

KNOWN = re.compile(r"^(abstract|introduction|background|related\s+work|literature\s+review|methods?|methodology|materials\s+and\s+methods|"
                   r"approach|experiments?|experimental\s+(setup|results)|evaluation|results(\s+and\s+discussion)?|discussion|"
                   r"conclusions?(\s+and\s+future\s+work)?|future\s+work|limitations|acknowledg(e)?ments?|appendix.*|references|"
                   r"bibliography|system\s+(design|architecture)|architecture|implementation|case\s+study|problem\s+statement|"
                   r"preliminaries|proposed\s+(method|approach|system)|dataset|data|analysis)\s*[.:]?$", re.I)


def _inline_md(s: str) -> list[Inline]:
    out: list[Inline] = []
    for tok in re.split(r"(\$[^$\n]+\$|\*\*[^*]+\*\*|\*[^*\n]+\*|_[^_\n]+_)", s):
        if not tok:
            continue
        if tok.startswith("$") and tok.endswith("$") and len(tok) > 2:
            out.append(Inline(math=tok.strip("$")))
        elif tok.startswith("**") and tok.endswith("**"):
            out.append(Inline(t=tok[2:-2], b=True))
        elif (tok.startswith("*") and tok.endswith("*")) or (tok.startswith("_") and tok.endswith("_") and len(tok) > 2):
            out.append(Inline(t=tok[1:-1], i=True))
        else:
            out.append(Inline(t=tok))
    return out


def _cols(line: str) -> list[str]:
    """Cells of a plain-text table row (columns separated by 2+ spaces, tabs or pipes)."""
    s = line.strip()
    if not s or len(s) > 220:
        return []
    if "|" in s:
        cells = [c.strip() for c in s.strip("|").split("|")]
    else:
        cells = [c.strip() for c in re.split(r"\s{2,}|\t", s)]
    cells = [c for c in cells if c]
    return cells if len(cells) >= 2 and all(len(c) < 80 for c in cells) else []


def _is_heading(line: str, nxt_blank: bool) -> bool:
    t = line.strip()
    if not t or len(t) > 100 or t.endswith((",", ";")):
        return False
    name, lvl, _ = heading_info(t)
    if lvl and len(name.split()) <= 12 and not name.endswith(".") and name[:1].isupper():
        return True
    if KNOWN.match(t):
        return True
    if t.isupper() and 3 < len(t) < 70 and len(t.split()) <= 10:
        return True
    return special_kind(t) != "body" and len(t.split()) <= 6


def read_text(text: str, name: str = "pasted text") -> dict:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    md = bool(re.search(r"^#{1,6}\s", text, re.M))
    lines = text.split("\n")
    elems: list[Elem] = []
    refs: list[tuple[str, float]] = []
    front: list[str] = []
    title = ""
    in_refs = False
    seen_abstract = False
    para: list[str] = []
    i = 0

    def flush():
        nonlocal para
        if para:
            s = " ".join(x.strip() for x in para).strip()
            s = re.sub(r"(\w)- (\w)", r"\1\2", s) if not md else s
            if s:
                elems.append(Elem(kind="para", runs=_inline_md(s) if md else [Inline(t=s)]))
        para = []

    def title_set() -> bool:
        return bool(title)

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        nxt_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        if in_refs:
            if s:
                if md and re.match(r"^#{1,6}\s", s):
                    in_refs = False
                    continue
                refs.append((re.sub(r"^\s*[-*]\s+", "", s), float(len(ln) - len(ln.lstrip()))))
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if md:
            m = re.match(r"^(#{1,6})\s+(.*)$", s)
            if m:
                flush()
                h = m.group(2).strip()
                if len(m.group(1)) == 1 and not title:
                    title = h
                elif REFS_HEAD.match(h):
                    in_refs = True
                else:
                    elems.append(Elem(kind="heading", runs=[Inline(t=h)], level=max(1, len(m.group(1)) - 1)))
                i += 1
                continue
            if s.startswith("$$"):
                flush()
                buf = [s[2:]]
                while not buf[-1].rstrip().endswith("$$") and i + 1 < len(lines):
                    i += 1
                    buf.append(lines[i])
                latex = " ".join(buf).strip().removesuffix("$$").strip()
                elems.append(Elem(kind="equation", block=Block(kind="equation", latex=latex)))
                i += 1
                continue
            if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
                flush()
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    if not re.match(r"^\|?\s*:?-{2,}", lines[i].strip()):
                        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                    i += 1
                cap = []
                if elems and elems[-1].kind == "para" and re.match(r"^table\s+\d", elems[-1].text, re.I):
                    cap = [Inline(t=re.sub(r"^table\s+\d+\s*[.:]?\s*", "", elems.pop().text, flags=re.I))]
                elems.append(Elem(kind="table", block=Block(kind="table", rows=rows, caption=cap)))
                continue
        cols = _cols(ln)
        nxt = next((x for x in lines[i + 1:i + 3] if x.strip()), "")  # rows may be separated by blank lines
        if not md and len(cols) >= 2 and len(s) < 220 and len(_cols(nxt)) == len(cols):
            flush()
            rows = []
            while i < len(lines):
                if len(_cols(lines[i])) == len(cols):
                    rows.append(_cols(lines[i]))
                    i += 1
                elif not lines[i].strip() and i + 1 < len(lines) and len(_cols(lines[i + 1])) == len(cols):
                    i += 1
                else:
                    break
            cap = []
            if elems and elems[-1].kind == "para" and re.match(r"^table\s+\w+", elems[-1].text, re.I):
                cap = [Inline(t=re.sub(r"^table\s+\w+\s*[.:]?\s*", "", elems.pop().text, flags=re.I))]
            elems.append(Elem(kind="table", block=Block(kind="table", rows=rows, caption=cap)))
            continue
        if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", ln) and not (not md and heading_info(s)[1] and len(s) < 80 and nxt_blank):
            flush()
            item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", ln)
            runs = _inline_md(item) if md else [Inline(t=item.strip())]
            if elems and elems[-1].kind == "list":
                elems[-1].items.append(runs)
            else:
                elems.append(Elem(kind="list", items=[runs], ordered=bool(re.match(r"^\s*\d", ln))))
            i += 1
            continue
        if not md and not title:
            title = s
            i += 1
            continue
        if not md and _is_heading(s, nxt_blank) and (nxt_blank or not para):
            flush()
            if REFS_HEAD.match(s):
                in_refs = True
                i += 1
                continue
            if re.fullmatch(r"(abstract|summary)\s*[.:]?", s, re.I):
                seen_abstract = True
            elems.append(Elem(kind="heading", runs=[Inline(t=s)]))
            i += 1
            continue
        if not seen_abstract and not any(e.kind == "heading" for e in elems) and not para and \
                not re.match(r"^(abstract|summary)\b", s, re.I) and not elems and title:
            front.append(s)
            i += 1
            continue
        if re.match(r"^(abstract|summary)\b", s, re.I):
            seen_abstract = True
        para.append(s)
        i += 1
    flush()
    return {"elems": elems, "title": title, "front": front, "refs": refs, "raw_text": text, "footnotes": [], "notes": [],
            "pages": 0, "source_name": name}


def read(path: Path, work_dir: Path) -> dict:
    return read_text(path.read_text(encoding="utf-8", errors="ignore"), path.name)
