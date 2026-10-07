"""Word papers (python-docx): styles, inline formatting, figures, tables, native equations.

Paragraph styles (Title, Heading 1-3, Caption, List ...) give the structure directly. Word
equations are kept twice: as LaTeX (converted from OMML) for LaTeX/PDF output and as the original
OMML for Word output, so they stay editable everywhere.
"""
from __future__ import annotations

import copy
import io
import re
from pathlib import Path

from lxml import etree

from backend.papers.model import Block, Inline
from backend.papers.readers import omml
from backend.papers.structure import REFS_HEAD, Elem

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CAPTION = re.compile(r"^\s*(fig\.?|figure|table)\s*([0-9]+|[IVX]+)\s*[.:|—–-]?\s*", re.I)


def _runs_of(p) -> list[Inline]:
    """Inline runs incl. inline equations, in document order."""
    out: list[Inline] = []
    for child in p._p.iterchildren():
        tag = etree.QName(child).localname
        if tag == "r":
            t = "".join(x.text or "" for x in child.iter(f"{{{W}}}t"))
            if not t:
                if child.find(f"{{{W}}}tab") is not None:
                    t = " "
                else:
                    continue
            rpr = child.find(f"{{{W}}}rPr")
            def on(name):  # noqa: E306
                e = rpr.find(f"{{{W}}}{name}") if rpr is not None else None
                return e is not None and e.get(f"{{{W}}}val", "true") not in ("0", "false")
            va = rpr.find(f"{{{W}}}vertAlign") if rpr is not None else None
            v = va.get(f"{{{W}}}val") if va is not None else ""
            r = Inline(t=t, b=on("b"), i=on("i"), sup=v == "superscript", sub=v == "subscript")
            if out and (out[-1].b, out[-1].i, out[-1].sup, out[-1].sub) == (r.b, r.i, r.sup, r.sub) and not out[-1].math and not out[-1].cite:
                out[-1].t += t
            else:
                out.append(r)
        elif tag == "hyperlink":
            t = "".join(x.text or "" for x in child.iter(f"{{{W}}}t"))
            if t:
                out.append(Inline(t=t))
        elif tag == "oMath":
            out.append(Inline(math=omml.to_latex(child)))
    return out


def read(path: Path, work_dir: Path) -> dict:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    fig_dir = work_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    elems: list[Elem] = []
    refs: list[tuple[str, float]] = []
    front: list[str] = []
    title = ""
    in_refs = False
    seen_body = False
    counters = {"figure": 0, "table": 0, "equation": 0}
    pending_caption: list[Inline] | None = None
    raw: list[str] = []
    ref_n = 0

    for child in d.element.body.iterchildren():
        tag = etree.QName(child).localname
        if tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells = []
                prev = None
                for c in r.cells:
                    if prev is not None and c._tc is prev:
                        continue  # merged cell repeats
                    cells.append(re.sub(r"\s+", " ", c.text).strip())
                    prev = c._tc
                rows.append(cells)
            raw += [" ".join(r) for r in rows]
            counters["table"] += 1
            blk = Block(kind="table", rows=rows, label=f"tab{counters['table']}")
            if elems and elems[-1].kind == "para" and CAPTION.match(elems[-1].text) and elems[-1].text.lower().startswith("table"):
                blk.caption = _strip_label(elems.pop().runs)
            elems.append(Elem(kind="table", block=blk))
            continue
        if tag != "p":
            continue
        p = Paragraph(child, d)
        style = (p.style.name if p.style is not None else "").lower()
        text = p.text.strip()
        maths = child.findall(f"{{{omml.M}}}oMathPara")
        blips = child.xpath(".//a:blip/@r:embed")
        raw.append(text)
        if in_refs:
            if text:
                numbered = p._p.pPr is not None and p._p.pPr.numPr is not None
                if numbered:
                    ref_n += 1
                refs.append(((f"[{ref_n}] " if numbered else "") + text, 0.0))
            continue
        if maths:  # display equation
            for mp in maths:
                counters["equation"] += 1
                latex = omml.to_latex(mp)
                num = re.search(r"\((\d{1,3}[a-z]?)\)\s*$", text)
                elems.append(Elem(kind="equation", block=Block(kind="equation", latex=latex, omml=etree.tostring(mp).decode(),
                                                               runs=[Inline(t=omml.to_text(mp))], number=num.group(1) if num else "",
                                                               label=f"eq{counters['equation']}")))
            continue
        if blips:
            for rid in blips:
                try:
                    part = d.part.related_parts[rid]
                    from PIL import Image

                    with Image.open(io.BytesIO(part.blob)) as im:
                        if min(im.size) < 60:
                            continue
                        counters["figure"] += 1
                        name = f"figure_{counters['figure']:02d}.png"
                        im.convert("RGB").save(fig_dir / name)
                    elems.append(Elem(kind="figure", block=Block(kind="figure", image=f"figures/{name}", label=f"fig{counters['figure']}")))
                except Exception:
                    continue
            if not text:
                continue
        if not text and not p.runs:
            continue
        if not text:
            continue
        if style == "title" or (not title and not seen_body and style.startswith("heading") is False and _is_title_like(p)):
            if not title:
                title = text
                continue
        m = re.match(r"heading\s*(\d)", style)
        if style == "caption" or (CAPTION.match(text) and len(text) < 400 and (style == "caption" or _bold_start(p))):
            runs = _strip_label(_runs_of(p))
            # attach to the previous figure (captions below figures) or hold for the next table
            target = next((e for e in reversed(elems[-2:]) if e.kind in ("figure", "table") and not e.block.caption), None)
            if text.lower().startswith(("fig", "figure")) and target is not None and target.kind == "figure":
                target.block.caption = runs
            elif text.lower().startswith("table"):
                elems.append(Elem(kind="para", runs=_runs_of(p)))  # picked up by the next table
            elif target is not None:
                target.block.caption = runs
            continue
        if m or (REFS_HEAD.match(text) and len(text) < 40):
            if REFS_HEAD.match(text):
                in_refs = True
                continue
            seen_body = True
            elems.append(Elem(kind="heading", runs=[Inline(t=text)], level=int(m.group(1)) if m else 1))
            continue
        is_list = "list" in style or (p._p.pPr is not None and p._p.pPr.numPr is not None)
        if is_list:
            runs = _runs_of(p)
            if elems and elems[-1].kind == "list":
                elems[-1].items.append(runs)
            else:
                elems.append(Elem(kind="list", items=[runs], ordered="number" in style))
            continue
        if not seen_body and not re.match(r"^\s*(abstract|summary)\b", text, re.I) and not elems:
            if style in ("subtitle",):
                front.append(text)
                continue
            front.append(text)
            continue
        if re.match(r"^\s*(abstract|summary)\b", text, re.I):
            seen_body = True
        kind = "quote" if "quote" in style else "code" if "code" in style or "source" in style else "para"
        elems.append(Elem(kind="para" if kind == "para" else kind, runs=_runs_of(p)))
    cp = d.core_properties
    return {"elems": elems, "title": title or (cp.title or ""), "front": front, "refs": refs, "raw_text": "\n".join(raw),
            "footnotes": [], "notes": [], "pages": 0}


def _is_title_like(p) -> bool:
    sizes = [r.font.size.pt for r in p.runs if r.font.size]
    return bool(sizes) and max(sizes) >= 16


def _bold_start(p) -> bool:
    return bool(p.runs) and bool(p.runs[0].bold)


def _strip_label(runs: list[Inline]) -> list[Inline]:
    out = [r.model_copy() for r in runs]
    for r in out:
        if r.t.strip():
            r.t = CAPTION.sub("", r.t, count=1)
            break
    return [r for r in out if r.t or r.math or r.cite]
