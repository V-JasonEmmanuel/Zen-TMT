"""PDF papers (PyMuPDF): layout-aware reading of scholarly PDFs.

  lines      text lines with font size / bold / italic / superscript flags and positions
  cleanup    running headers, footers and page numbers repeated across pages are removed
  order      two-column pages are read column by column; full-width items (title, wide
             figures/tables) split the page into bands so reading order follows the layout
  graphics   figures (raster images and vector drawings) and tables are located from their
             captions ("Fig. 3", "Table II") and cropped from the page at high resolution;
             ruled tables are also extracted as cells; their text is removed from the body flow
  equations  display equations (math fonts / centred lines with "(n)") are cropped as images
             (PDF keeps no equation source) and flagged for review in the report
  text       lines are merged into paragraphs (hyphenation repaired), headings recognised
             from numbering, size and weight, and the reference list handed over separately
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from backend.papers.model import Block, Inline
from backend.papers.structure import REFS_HEAD, Elem, heading_info, special_kind

CAPTION = re.compile(r"^\s*(fig\.?|figure|table)\s*([0-9]+|[IVXL]+)\s*[.:|—–-]?\s*", re.I)
MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|CMR\d+.*Math|Math|Symbol|STIX|Cambria\s*Math|MSAM|MSBM|rsfs|Euclid|MTMI|MTSY|TeX", re.I)
MATH_CHARS = set("=∑∏∫√≤≥≠≈±×÷∂∇∈∉∀∃∞αβγδεθλμπσφωΩΔΣΦΨ→←↔⇒⇔^_·‖")
BULLET = re.compile(r"^\s*(?:[•◦▪●‣–—-]|\(?[a-z0-9]{1,2}\))\s+")


@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    spans: list[dict]
    size: float
    bold: bool
    italic: bool
    fonts: str
    col: int = 0  # 0 full width, 1 left, 2 right
    used: bool = False
    inside: bool = False  # text drawn inside a figure/table graphic
    eqnum: str = ""  # equation number set in its own text line on the equation's baseline

    @property
    def text(self) -> str:
        return "".join(s["text"] for s in self.spans)

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class PageInfo:
    w: float
    h: float
    two_col: bool = False
    lines: list[Line] = field(default_factory=list)


def _lines(doc) -> list[PageInfo]:
    pages = []
    for pno, page in enumerate(doc):
        info = PageInfo(page.rect.width, page.rect.height)
        d = page.get_text("dict", flags=0)
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"].strip() or s["text"] == " "]
                if not spans or not "".join(s["text"] for s in spans).strip():
                    continue
                if abs(ln["dir"][1]) > 0.2:  # rotated text (arXiv side stamps, watermarks)
                    continue
                sizes = [s["size"] for s in spans if s["text"].strip()]
                main = max(sizes, key=sizes.count) if sizes else spans[0]["size"]
                bold = all((s["flags"] & 16) or re.search(r"bold|black|semibold|heavy", s["font"], re.I) for s in spans if s["text"].strip())
                italic = all((s["flags"] & 2) or re.search(r"italic|oblique", s["font"], re.I) for s in spans if s["text"].strip())
                x0, y0, x1, y1 = ln["bbox"]
                info.lines.append(Line(pno, x0, y0, x1, y1, spans, round(main, 1), bold, italic,
                                       " ".join(s["font"] for s in spans)))
        pages.append(info)
    return pages


def _remove_running(pages: list[PageInfo]) -> None:
    """Drop headers/footers that repeat on several pages, and bare page numbers."""
    from collections import Counter

    def key(t: str) -> str:
        return re.sub(r"\d+", "#", t.strip().lower())

    cnt: Counter = Counter()
    for p in pages:
        for ln in p.lines:
            if ln.y1 < p.h * 0.09 or ln.y0 > p.h * 0.91:
                cnt[key(ln.text)] += 1
    rep = {k for k, v in cnt.items() if v >= max(2, len(pages) // 3)}
    for p in pages:
        p.lines = [ln for ln in p.lines if not (
            (ln.y1 < p.h * 0.09 or ln.y0 > p.h * 0.91) and (key(ln.text) in rep or re.fullmatch(r"\s*[-–]?\s*\d{1,4}\s*[-–]?\s*", ln.text)))]


def _columns(p: PageInfo) -> None:
    mid = p.w / 2
    left = [ln for ln in p.lines if ln.x1 <= mid + p.w * 0.03 and ln.x1 - ln.x0 < p.w * 0.5]
    right = [ln for ln in p.lines if ln.x0 >= mid - p.w * 0.03 and ln.x1 - ln.x0 < p.w * 0.5]
    p.two_col = len(left) >= 6 and len(right) >= 6
    for ln in p.lines:
        if not p.two_col:
            ln.col = 0
        elif ln.x1 <= mid + p.w * 0.03:
            ln.col = 1
        elif ln.x0 >= mid - p.w * 0.03:
            ln.col = 2
        else:
            ln.col = 0


def _ordered(p: PageInfo, extra_full: list[tuple[float, float]] = ()) -> list[Line]:
    """Reading order: bands separated by full-width items; inside a band, left column then right."""
    if not p.two_col:
        return sorted(p.lines, key=lambda l: (round(l.y0 / 2), l.x0))
    fulls = sorted([l for l in p.lines if l.col == 0], key=lambda l: l.y0)
    seps = sorted([l.y0 for l in fulls] + [a for a, _ in extra_full])
    out: list[Line] = []
    rest = [l for l in p.lines if l.col != 0]
    prev = -1.0
    for sep in seps + [p.h + 1]:
        band = [l for l in rest if prev <= l.y0 < sep]
        out += sorted([l for l in band if l.col == 1], key=lambda l: (l.y0, l.x0))
        out += sorted([l for l in band if l.col == 2], key=lambda l: (l.y0, l.x0))
        out += sorted([l for l in fulls if abs(l.y0 - sep) < 0.01], key=lambda l: l.x0)
        prev = sep
    seen, res = set(), []
    for l in out:
        if id(l) not in seen:
            seen.add(id(l))
            res.append(l)
    return res


def _col_bounds(p: PageInfo, col: int) -> tuple[float, float]:
    xs = [l for l in p.lines if l.col == col] or p.lines
    return min(l.x0 for l in xs), max(l.x1 for l in xs)


# ------------------------------------------------------------------ graphics
def _graphics(page, p: PageInfo, body_size: float, out_dir: Path, counters: dict, rel_prefix: str) -> list[tuple[float, Elem, Line]]:
    """Figures and tables on one page, anchored at their captions. Returns (y, Elem, caption line)."""
    import fitz

    results = []
    caps = [l for l in p.lines if CAPTION.match(l.text) and (l.bold or re.match(r"^\s*(fig|table)", l.text, re.I))
            and not l.used and len(l.text) < 400]
    # only captions that start a line block (not "as shown in Fig. 3" mid-sentence lines)
    caps = [c for c in caps if re.match(r"^\s*(fig\.?|figure|table)\s*([0-9]+|[IVXL]+)\s*([.:|—–-]|$)", c.text, re.I) or c.bold]
    if not caps:
        return []
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    rects = []
    for img in page.get_image_info():
        r = fitz.Rect(img["bbox"])
        if r.width > 40 and r.height > 30:
            rects.append(r)
    try:
        for cl in page.cluster_drawings(x_tolerance=6, y_tolerance=6):
            if cl.width > 60 and cl.height > 40:
                rects.append(cl)
    except Exception:
        pass
    taken_tables = set()
    for cap in sorted(caps, key=lambda c: c.y0):
        is_table = cap.text.strip().lower().startswith("table")
        # caption continuation lines (same column, directly below, same size)
        cap_lines = [cap]
        nxt = sorted([l for l in p.lines if l.col == cap.col and l.y0 > cap.y0 and not l.used], key=lambda l: l.y0)
        for l in nxt:
            if l.y0 - cap_lines[-1].y1 < cap.h * 0.8 and abs(l.size - cap.size) < 0.6 and not CAPTION.match(l.text):
                cap_lines.append(l)
            else:
                break
        cx0, cx1 = (cap.x0, cap.x1) if cap.col == 0 else _col_bounds(p, cap.col)
        if cap.col == 0 or (cap.x1 - cap.x0) > p.w * 0.6:
            cx0, cx1 = min(cx0, p.w * 0.06), max(cx1, p.w * 0.94)
        cap_top, cap_bot = cap.y0, cap_lines[-1].y1
        region = None
        rows: list[list[str]] = []
        if is_table:
            below = [(i, t) for i, t in enumerate(tables) if i not in taken_tables and t.bbox[1] >= cap_top - 2 and t.bbox[0] < cx1 and t.bbox[2] > cx0]
            above = [(i, t) for i, t in enumerate(tables) if i not in taken_tables and t.bbox[3] <= cap_top + 2 and t.bbox[0] < cx1 and t.bbox[2] > cx0]
            cand = min(below, key=lambda it: it[1].bbox[1] - cap_bot, default=None) or max(above, key=lambda it: it[1].bbox[3], default=None)
            if cand and abs((cand[1].bbox[1] if cand in below else cap_top - cand[1].bbox[3]) - (cap_bot if cand in below else 0)) < 120:
                taken_tables.add(cand[0])
                region = fitz.Rect(cand[1].bbox)
                try:
                    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in cand[1].extract()]
                    rows = [r for r in rows if any(r)]
                except Exception:
                    rows = []
            if region is None:  # unruled table: lines below the caption up to the next paragraph gap
                ys = [l for l in sorted(p.lines, key=lambda l: l.y0) if l.y0 >= cap_bot - 1 and l.x0 >= cx0 - 2 and l.x1 <= cx1 + 2 and not l.used and l not in cap_lines]
                last = cap_bot
                for l in ys:
                    if l.y0 - last > max(14, body_size * 2.2) or (len(l.text) > 90 and l.text.rstrip().endswith(".")):
                        break
                    last = l.y1
                if last - cap_bot > body_size * 2:
                    region = fitz.Rect(cx0, cap_bot + 1, cx1, last + 2)
        else:
            # graphic objects above the caption (figures carry the caption below), nearest first
            cands = [r for r in rects if r.y1 <= cap_top + 4 and r.x0 < cx1 and r.x1 > cx0 and cap_top - r.y1 < p.h * 0.5]
            if cands:
                nearest = max(cands, key=lambda r: r.y1)
                region = fitz.Rect(nearest)
                for r in cands:  # sub-figures side by side / stacked within the same span
                    if r is not nearest and r.y1 > region.y0 - 30 and r.y0 < region.y1 + 30:
                        region |= r
            else:
                # no graphic objects found: everything between the previous text above and the caption
                prev = [l for l in p.lines if l.y1 <= cap_top - 1 and l.x0 < cx1 and l.x1 > cx0 and l.col in (cap.col, 0) and
                        len(l.text) > 60 and l.size >= body_size - 0.6]
                top = max((l.y1 for l in prev), default=p.h * 0.08)
                if cap_top - top > 40:
                    region = fitz.Rect(cx0, top + 2, cx1, cap_top - 2)
        if region is None or region.height < 12:
            continue
        region = region & page.rect
        # text inside the graphic (axis labels, table cells) is not body text
        for l in p.lines:
            r = fitz.Rect(l.x0, l.y0, l.x1, l.y1)
            if r.intersects(region) and (r & region).get_area() > 0.5 * r.get_area():
                l.used = True
                l.inside = not (is_table and rows)  # table cells extracted as text stay part of the content
        for l in cap_lines:
            l.used = True
        kind = "table" if is_table else "figure"
        counters[kind] = counters.get(kind, 0) + 1
        n = counters[kind]
        name = f"{kind}_{n:02d}.png"
        pix = page.get_pixmap(clip=region, matrix=fitz.Matrix(3, 3), alpha=False)
        pix.save(str(out_dir / name))
        caption_text = " ".join(l.text.strip() for l in cap_lines)
        caption_text = CAPTION.sub("", caption_text, count=1).strip()
        blk = Block(kind=kind, image=f"{rel_prefix}{name}", caption=[Inline(t=caption_text)], label=f"{'tab' if is_table else 'fig'}{n}",
                    rows=rows if is_table and _good_table(rows) else [])
        if is_table and not blk.rows:
            blk.note = "Table kept as an image (its cells could not be read reliably)."
        results.append((min(region.y0, cap_top), Elem(kind=kind, block=blk), cap))
    return results


def _good_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2 or len(rows[0]) < 2:
        return False
    filled = sum(1 for r in rows for c in r if c)
    return filled >= 0.6 * sum(len(r) for r in rows)


# ------------------------------------------------------------------ equations
def _is_equation(l: Line, colx: tuple[float, float], body: float) -> bool:
    t = l.text.strip()
    if not t or len(t) > 160:
        return False
    w = colx[1] - colx[0]
    centred = abs(((l.x0 + l.x1) / 2) - (colx[0] + colx[1]) / 2) < w * 0.18 and (l.x1 - l.x0) < w * 0.85
    numbered = bool(re.search(r"\(\s*\d{1,3}[a-z]?\s*\)\s*$", t))
    mathy = MATH_FONT.search(l.fonts) is not None or sum(c in MATH_CHARS for c in t) >= 2 or \
        (numbered and "=" in t and len(t) < 120 and not t.rstrip()[:-4].rstrip().endswith("."))
    sentence = bool(re.search(r"[a-z]{4,}\s+[a-z]{3,}\s+[a-z]{3,}", t)) and not numbered
    return (centred or numbered) and mathy and not sentence


# ------------------------------------------------------------------ runs
def _runs(lines: list[Line], body_size: float) -> list[Inline]:
    runs: list[Inline] = []
    for k, l in enumerate(lines):
        for s in l.spans:
            t = s["text"]
            if not t:
                continue
            sup = bool(s["flags"] & 1) or (s["size"] < body_size * 0.8 and s["origin"][1] < l.y1 - l.h * 0.35 and t.strip() != "")
            r = Inline(t=t, b=bool(s["flags"] & 16) or bool(re.search(r"bold", s["font"], re.I)),
                       i=bool(s["flags"] & 2) or bool(re.search(r"italic|oblique", s["font"], re.I)), sup=sup and len(t.strip()) <= 12)
            if runs and (runs[-1].b, runs[-1].i, runs[-1].sup) == (r.b, r.i, r.sup) and not runs[-1].cite:
                runs[-1].t += r.t
            else:
                runs.append(r)
        if k < len(lines) - 1 and runs:
            last = runs[-1]
            nxt = lines[k + 1].text.lstrip()
            if last.t.endswith("-") and nxt[:1].islower() and not last.t.endswith(" -"):
                last.t = last.t[:-1]  # hyphenation at the line end
            elif not last.t.endswith((" ", "/")):
                last.t += " "
    for r in runs:
        r.t = re.sub(r"[ \t]{2,}", " ", r.t.replace("­", ""))
    if runs:
        runs[0].t = runs[0].t.lstrip()
        runs[-1].t = runs[-1].t.rstrip()
    return [r for r in runs if r.t]


# ------------------------------------------------------------------ main
def read(path: Path, work_dir: Path) -> dict:
    import fitz

    doc = fitz.open(str(path))
    if doc.needs_pass:
        raise ValueError("The PDF is password-protected.")
    fig_dir = work_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    pages = _lines(doc)
    if sum(len(p.lines) for p in pages) < 20:
        raise ValueError("The PDF contains almost no text (it may be a scanned image). Use a PDF with selectable text.")
    _remove_running(pages)
    sizes = [l.size for p in pages for l in p.lines for _ in range(max(1, len(l.text) // 10))]
    body = statistics.mode([round(s * 2) / 2 for s in sizes])
    for p in pages:
        _columns(p)

    counters: dict[str, int] = {}
    stream: list[tuple[int, float, object]] = []  # (page, order index, Line | Elem)
    notes: list[str] = []
    for pno, (page, p) in enumerate(zip(doc, pages)):
        graphics = _graphics(page, p, body, fig_dir, counters, "figures/")
        order = _ordered(p)
        placed = set()
        for idx, l in enumerate(order):
            for y, el, cap in graphics:
                if id(el) not in placed and l is cap:
                    stream.append((pno, idx - 0.5, el))
                    placed.add(id(el))
            if not l.used:
                stream.append((pno, idx, l))
        for y, el, cap in graphics:
            if id(el) not in placed:
                stream.append((pno, len(order), el))
    # footnotes: a block of small text at the bottom of a column, visually separated from the text above
    foot: list[Line] = []
    for p in pages:
        for col in {l.col for l in p.lines}:
            cl = sorted([l for l in p.lines if l.col == col and not l.used], key=lambda l: l.y0)
            k = len(cl)
            while k > 0 and cl[k - 1].size < body - 1.2 and cl[k - 1].y0 > p.h * 0.7:
                k -= 1
            if k < len(cl) and k > 0 and cl[k].y0 - cl[k - 1].y1 > max(cl[k].h, cl[k - 1].h) * 1.4:
                if not any(REFS_HEAD.match(l.text.strip()) for l in cl[:k]) and not re.match(r"^\s*\[\d+\]", cl[k].text):
                    foot += cl[k:]
    foot_ids = {id(x) for x in foot}
    footnotes = [x.text.strip() for x in foot]

    # ---- title (page 1, largest text in the upper part)
    first = [x for pg, _, x in stream if pg == 0 and isinstance(x, Line) and x.y0 < pages[0].h * 0.45]
    title_lines: list[Line] = []
    if first:
        big = max(l.size for l in first)
        if big >= body + 2:
            cand = [l for l in first if abs(l.size - big) < 0.6]
            title_lines = [l for l in cand if l.y0 - cand[0].y0 < big * 4.5]
    title = " ".join(l.text.strip() for l in title_lines)
    tids = {id(l) for l in title_lines}

    # ---- group lines into paragraphs / headings
    elems: list[Elem] = []
    front: list[str] = []
    refs: list[tuple[str, float]] = []
    in_refs = False
    after_refs: list[Elem] = []
    seen_abstract = False
    seen_heading = False
    buf: list[Line] = []
    heading_sizes = sorted({l.size for _, _, l in stream if isinstance(l, Line) and l.size > body + 0.4}, reverse=True)

    def flush():
        nonlocal buf
        if not buf:
            return
        lines = buf
        buf = []
        text = " ".join(l.text.strip() for l in lines).strip()
        if not text:
            return
        if in_refs:
            return
        colx = (min(l.x0 for l in lines), max(l.x1 for l in lines))
        if all(_is_equation(l, _col_bounds(pages[l.page], l.col) if l.col else (pages[l.page].w * 0.08, pages[l.page].w * 0.92), body) for l in lines) and len(lines) <= 6:
            elems.append(_equation(doc, lines, fig_dir, counters))
            return
        m = BULLET.match(text)
        if m and len(lines) <= 8:
            r = _runs(lines, body)
            if r:
                r[0].t = BULLET.sub("", r[0].t, count=1)
            if elems and elems[-1].kind == "list":
                elems[-1].items.append(r)
            else:
                elems.append(Elem(kind="list", items=[r], ordered=bool(re.match(r"^\s*\(?\d", text))))
            return
        elems.append(Elem(kind="para", runs=_runs(lines, body)))

    for pno, _, x in stream:
        if isinstance(x, Elem):
            flush()
            (after_refs if in_refs else elems).append(x)
            continue
        l: Line = x
        if id(l) in tids or id(l) in foot_ids:
            continue
        t = l.text.strip()
        name, lvl, num = heading_info(t)
        short = len(t) < 110 and len(t.split()) <= 14
        # front matter: page-1 lines between the title and the abstract / first section heading
        if not seen_abstract and not seen_heading and pno == 0 and not in_refs:
            starts_body = re.match(r"^\s*(abstract|summary|key\s*words?|index\s+terms)\b", t, re.I) or \
                (lvl and short and (l.bold or t.isupper() or l.size > body + 0.3) and not re.search(r"[,@]", t)) or \
                bool(REFS_HEAD.match(t))
            if not starts_body:
                front.append(t)
                continue
        is_heading = short and not t.endswith((",", ";")) and (
            (lvl and (l.bold or l.italic or l.size > body + 0.3 or (t.isupper() and len(t) > 3)) and not re.search(r"\.\s+\w", name)) or
            (l.bold and l.size >= body - 0.2 and not t.endswith(".") and len(t.split()) <= 10 and not CAPTION.match(t) and (not buf or buf[-1].text.rstrip().endswith((".", ":")) or l.size > body + 0.3)) or
            (l.size > body + 0.9 and not t.endswith(".")) or
            bool(REFS_HEAD.match(re.sub(r"^(\d+|[IVX]+)\.?\s+", "", t))) or
            (t.isupper() and 3 < len(t) < 60 and special_kind(t) != "body"))
        if in_refs:
            if is_heading and (special_kind(t) == "appendix" or re.match(r"^(appendix|supplementary)", t, re.I)):
                in_refs = False
            else:
                colx0 = _col_bounds(pages[l.page], l.col)[0] if l.col else min(ll.x0 for ll in pages[l.page].lines)
                refs.append((t, round(l.x0 - colx0, 1)))
                continue
        if is_heading and not re.fullmatch(r"(abstract|summary)\b.*", t, re.I) or (re.fullmatch(r"(abstract|summary)\s*[.:]?", t, re.I)):
            flush()
            if REFS_HEAD.match(re.sub(r"^(\d+|[IVX]+)\.?\s+", "", t)):
                in_refs = True
                continue
            level = lvl or (heading_sizes.index(l.size) + 1 if l.size in heading_sizes else 2 if l.bold and l.size <= body + 0.2 else 1)
            elems.append(Elem(kind="heading", runs=[Inline(t=t)], level=min(3, level)))
            seen_heading = True
            if re.fullmatch(r"(abstract|summary)\s*[.:]?", t, re.I):
                seen_abstract = True
            continue
        if not in_refs and re.fullmatch(r"\(\s*\d{1,3}[a-z]?\s*\)", t):
            # an equation number in its own text line, on the baseline of the equation it numbers
            tgt = buf[-1] if buf else None
            if tgt and tgt.page == l.page and abs((tgt.y0 + tgt.y1) / 2 - (l.y0 + l.y1) / 2) < max(tgt.h, l.h) * 0.8:
                tgt.eqnum = t.strip("() ")
                continue
            if elems and elems[-1].kind == "equation" and not elems[-1].block.number:
                elems[-1].block.number = t.strip("() ")
                continue
        if re.match(r"^\s*(abstract|summary)\b", t, re.I):
            seen_abstract = True
        if re.match(r"^\s*(key\s*words?|index\s+terms)\b", t, re.I):
            flush()
        if buf:
            prev = buf[-1]
            gap = l.y0 - prev.y1
            ends = prev.text.rstrip().endswith((".", ":", "?", "!"))
            indent = l.x0 - (_col_bounds(pages[l.page], l.col)[0] if l.col else min(ll.x0 for ll in pages[l.page].lines)) > body * 0.6
            if l.page != prev.page or (l.col != prev.col and l.y0 < prev.y0 - prev.h):
                new_para = ends and (indent or gap > 0)  # page / column break: continue the paragraph unless it ended
            elif l.col != prev.col:
                new_para = gap > max(prev.h, l.h) * 0.5  # from a full-width block into a column (or back)
            else:
                new_para = gap > max(prev.h, l.h) * 0.75 or gap < -prev.h * 2 or (indent and ends and l.x0 - prev.x0 > body * 0.6)
            new_para = new_para or bool(BULLET.match(t)) or abs(l.size - prev.size) > 1.2 or (l.bold != prev.bold and len(t) < 60 and ends) or \
                (_is_equation(l, _col_bounds(pages[l.page], l.col) if l.col else (pages[l.page].w * 0.08, pages[l.page].w * 0.92), body) !=
                 _is_equation(prev, _col_bounds(pages[prev.page], prev.col) if prev.col else (pages[prev.page].w * 0.08, pages[prev.page].w * 0.92), body))
            if new_para:
                flush()
        buf.append(l)
    flush()
    elems += after_refs
    # merge paragraphs split by a column/page break mid-sentence
    merged: list[Elem] = []
    for e in elems:
        if merged and e.kind == "para" and merged[-1].kind == "para" and merged[-1].runs and e.runs:
            prev_t = merged[-1].text
            if prev_t and not prev_t.rstrip().endswith((".", ":", "?", "!", "”", "\"")) and e.text[:1].islower():
                last = merged[-1].runs[-1]
                if last.t.endswith("-"):
                    last.t = last.t[:-1]
                elif not last.t.endswith(" "):
                    last.t += " "
                merged[-1].runs += e.runs
                continue
        merged.append(e)
    if any(b.kind == "equation" for e in merged if (b := e.block)):
        notes.append("Display equations were recovered from the PDF as images (a PDF does not contain their source). "
                      "Check them, or upload the LaTeX/Word source for fully editable equations.")
    raw_text = "\n".join(l.text for p in pages for l in p.lines if not l.inside)
    return {"elems": merged, "title": title, "front": front, "refs": refs, "raw_text": raw_text,
            "footnotes": footnotes, "notes": notes, "pages": len(doc)}


def _equation(doc, lines: list[Line], fig_dir: Path, counters: dict) -> Elem:
    import fitz

    page = doc[lines[0].page]
    r = fitz.Rect(min(l.x0 for l in lines) - 2, min(l.y0 for l in lines) - 2, max(l.x1 for l in lines) + 2, max(l.y1 for l in lines) + 2)
    text = " ".join(l.text.strip() for l in lines)
    m = re.search(r"\(\s*(\d{1,3}[a-z]?)\s*\)\s*$", text)
    num = m.group(1) if m else next((l.eqnum for l in lines if l.eqnum), "")
    # crop without the equation number (it is re-numbered by the target format)
    if m:
        num_span = next((s for l in lines for s in l.spans if re.fullmatch(r"\s*\(\s*\d{1,3}[a-z]?\s*\)\s*", s["text"])), None)
        if num_span:
            r.x1 = min(r.x1, num_span["bbox"][0] - 1)
    counters["equation"] = counters.get("equation", 0) + 1
    n = counters["equation"]
    name = f"equation_{n:02d}.png"
    page.get_pixmap(clip=r, matrix=fitz.Matrix(4, 4), alpha=False).save(str(fig_dir / name))
    eq_text = re.sub(r"\(\s*\d{1,3}[a-z]?\s*\)\s*$", "", text).strip()
    return Elem(kind="equation", block=Block(kind="equation", runs=[Inline(t=eq_text)], number=num, image=f"figures/{name}",
                                             label=f"eq{num or n}", note="Equation recovered from the PDF as an image."))
