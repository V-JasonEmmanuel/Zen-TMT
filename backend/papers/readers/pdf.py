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
                weight: dict[float, int] = {}
                for s in spans:  # the size carrying most of the text (not the most spans)
                    if s["text"].strip():
                        weight[round(s["size"], 1)] = weight.get(round(s["size"], 1), 0) + len(s["text"].strip())
                main = max(weight, key=weight.get) if weight else spans[0]["size"]
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


JUNK = re.compile(r"^\s*(?:a?1{6,}\s*)+$|^\s*check\s+for\s+updates\s*$|"
                  r"^\s*(?:https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/\S+\.[gt]\d{3}\s*$", re.I)  # per-figure/table DOI lines (PLOS)
MATH_SPAN = re.compile(r"CMMI|CMSY|CMEX|TeX_CM|Math|Euclid|Symbol|PI_chars|jsMath|MTExtra|MTSY|MTMI|STIX|Cambria\s*Math|MSAM|MSBM|rsfs|wasy|Mathematica", re.I)
SIDEBAR_LABEL = re.compile(r"^\s*(citation|editor|received|accepted|published|copyright|data availability( statement)?|funding|"
                           r"competing interests|conflicts? of interest|peer review history|open access|ethics statement|"
                           r"author contributions|abbreviations|academic editor|reviewed by|edited by|correspondence|"
                           r"specialty section|article history|keywords?)\b\s*:?", re.I)


def _strip_junk(pages: list[PageInfo]) -> None:
    """Hidden text in publisher badges ('a1111111111', 'Check for updates') and margin line numbers."""
    for p in pages:
        p.lines = [l for l in p.lines if not JUNK.match(l.text)]
        for l in p.lines:
            l.spans = [s for s in l.spans if not re.fullmatch(r"\s*a?1{8,}\s*", s["text"])]
        p.lines = [l for l in p.lines if l.text.strip()]


def _vector_bullets(doc, pages: list[PageInfo]) -> None:
    """Designed documents often draw list bullets as small filled circles instead of a bullet character:
    give those lines a text bullet so they are read as list items."""
    for pno, p in enumerate(pages):
        try:
            dots = [d["rect"] for d in doc[pno].get_drawings() if d.get("fill") and 1.5 <= d["rect"].width <= 8 and
                    1.5 <= d["rect"].height <= 8 and any(it[0] == "c" for it in d["items"])]
        except Exception:
            continue
        for r in dots:
            cy = (r.y0 + r.y1) / 2
            ln = min((l for l in p.lines if l.y0 - 1 <= cy <= l.y1 + 1 and 0 < l.x0 - r.x1 < 26 and l.spans),
                     key=lambda l: l.x0 - r.x1, default=None)
            if ln is not None and not BULLET.match(ln.text):
                s0 = dict(ln.spans[0])
                s0["text"] = "• "
                s0["bbox"] = (r.x0, s0["bbox"][1], r.x1, s0["bbox"][3])
                ln.spans.insert(0, s0)
                ln.x0 = r.x0


def _label_start(l) -> bool:
    """A line that starts with a run-in label in bold/medium type ("Clarity: what matters...")."""
    s = next((x for x in l.spans if x["text"].strip()), None)
    if not s:
        return False
    strong = bool(s["flags"] & 16) or bool(re.search(r"bold|medium|semibold|black|heavy", s["font"], re.I))
    return strong and bool(re.match(r"^\s*[A-Z][\w &/'’-]{0,30}:", l.text))


def _is_math_span(s: dict) -> bool:
    t = s["text"]
    return bool(MATH_SPAN.search(s["font"])) or any(ch == "�" or 0xE000 <= ord(ch) <= 0xF8FF for ch in t)


def _sidebar(pages: list[PageInfo], body: float) -> list[tuple[str, str]]:
    """Journal first pages often carry a narrow metadata column (citation, editor, dates, licence,
    funding, competing interests). It is not body text: take it out and return (label, text) items."""
    items: list[tuple[str, str]] = []
    for p in pages[:2]:
        main = [l for l in p.lines if abs(l.size - body) < 0.8 and len(l.text) > 40]
        if len(main) < 5:
            continue
        bx = statistics.median(l.x0 for l in main)
        side = [l for l in p.lines if l.x1 < bx - 4 and l.x1 < p.w * 0.42 and l.size < body - 0.4]
        if len(side) < 4 or bx < p.w * 0.25:
            continue
        ids = {id(l) for l in side}
        p.lines = [l for l in p.lines if id(l) not in ids]
        side.sort(key=lambda l: (l.y0, l.x0))
        cur_label, cur, prev = "", [], None
        for l in side:
            t = l.text.strip()
            m = SIDEBAR_LABEL.match(t)
            first_bold = bool(l.spans) and bool((l.spans[0]["flags"] & 16) or re.search(r"bold", l.spans[0]["font"], re.I))
            gap = (l.y0 - prev.y1) if prev else 0
            labelled = bool(m) and (first_bold or bool(re.match(SIDEBAR_LABEL.pattern + r"\s*$", t, re.I)) or t[m.end() - 1:m.end()] == ":")
            if labelled or gap > l.h * 1.2:
                if cur:
                    items.append((cur_label, _join_lines(cur)))
                cur_label = m.group(1).strip().title() if labelled else ""
                cur = [t[m.end():].strip()] if labelled else [t]
            else:
                cur.append(t)
            prev = l
        if cur:
            items.append((cur_label, _join_lines(cur)))
    return [(a, b) for a, b in items if b or a]


def _join_lines(parts: list[str]) -> str:
    out = ""
    for p in parts:
        if not p:
            continue
        if out.endswith("-") and p[:1].islower() and _dehyphen(out, p):
            out = out[:-1] + p
        elif re.search(r"[A-Za-z0-9]-$", out) and p[:1].isalnum():
            out = out + p  # "DE-AC05-" + "00OR22725", "Just-" + "In-Time"
        else:
            out = (out + " " + p).strip()
    from backend.papers.references import join_urls

    return join_urls(re.sub(r"\s+", " ", out))


def _inline_math(doc, pages: list[PageInfo], fig_dir: Path, counters: dict) -> int:
    """Inline math set in fonts without a usable text mapping is cropped from the page as a small image
    (exact appearance). PDFs often split one formula over several text "lines" (stacked limits, super/
    subscripts, an operand starting under a big operator): those pieces are reassembled first."""
    import fitz

    def words_of(l: Line) -> bool:
        return any(not _is_math_span(s) and re.search(r"[a-z]{3,}", s["text"]) for s in l.spans if not s.get("img"))

    def group_rect(l: Line, a: int, b: int) -> "fitz.Rect":
        spans = l.spans
        r = fitz.Rect(spans[a]["bbox"])
        for s in spans[a:b + 1]:
            r |= fitz.Rect(s["bbox"])
        lead = len(spans[a]["text"]) - len(spans[a]["text"].lstrip())
        if lead:  # start at the first glyph, not the leading space (avoids slivers of the previous letter)
            r.x0 = min(r.x1 - 1, r.x0 + lead * spans[a]["size"] * 0.25)
        # vertical extent from the glyphs around the baseline, never the whole PDF line (which can overlap
        # the line above when it carries super/subscripts)
        sz = max(l.size, tsize)  # a line set mostly in small math type still sits on a text baseline
        base = max((s["origin"][1] for s in spans[a:b + 1] if s["size"] >= sz * 0.85), default=spans[a]["origin"][1])
        r.y0 = max(r.y0, base - sz * 1.05)
        r.y1 = min(max(r.y1, base + sz * 0.25), base + sz * 0.6)
        return r

    def mathish(s: dict, l: Line) -> bool:
        return _mathish(s, l) or (s["size"] < tsize * 0.85 and bool(s["text"].strip()))

    made = 0
    tsize = 10.0
    for pno, p in enumerate(pages):
        page = doc[pno]
        groups: list[list] = []  # [line, a, b, rect, dropped]
        word_lines = [l for l in p.lines if words_of(l)]
        tsize = statistics.median([l.size for l in word_lines]) if word_lines else 10.0
        # short lines in a smaller font are pieces of formulas (fraction numerators/denominators, limits,
        # super/subscripts) even when they contain words ("precision x recall" over "precision + recall")
        small = [l for l in p.lines if len(l.text.strip()) <= 60 and l.x1 - l.x0 < 220 and
                 max((s["size"] for s in l.spans if s["text"].strip()), default=99) < tsize * 0.85]
        small_ids = {id(l) for l in small}
        text_lines = [l for l in word_lines if id(l) not in small_ids]
        # 1) math inside text lines
        for l in text_lines:
            spans = l.spans
            i = 0
            while i < len(spans):
                if not _is_math_span(spans[i]):
                    i += 1
                    continue
                a = i
                while a > 0 and mathish(spans[a - 1], l) and not _is_math_span(spans[a - 1]) and                         (len(spans[a - 1]["text"].strip()) <= 3 or spans[a - 1]["size"] < tsize * 0.85):
                    a -= 1  # a preceding short italic variable ("PR" in PR(i)), a small-type operand
                b = i
                while b + 1 < len(spans) and (_is_math_span(spans[b + 1]) or mathish(spans[b + 1], l)):
                    b += 1
                while b > i and not _is_math_span(spans[b]) and re.fullmatch(r"[\s,.;:]*", spans[b]["text"]):
                    b -= 1  # trailing sentence punctuation stays text
                groups.append([l, a, b, group_rect(l, a, b), False])
                i = b + 1
        if not groups and not text_lines:
            continue
        # 2) math-only lines on the same visual row as text are pieces of that sentence; small ones are
        #    super/subscript fragments of a neighbouring formula; the rest are display equations (left alone)
        others = [l for l in p.lines if id(l) not in small_ids and not words_of(l) and l.text.strip() and
                  any(_is_math_span(s) for s in l.spans) and
                  (len(l.text.strip()) <= 60 or all(_is_math_span(s) for s in l.spans))]  # long radical bars
        for l in others:
            c = (l.y0 + l.y1) / 2
            if any(abs(c - (t.y0 + t.y1) / 2) < max(t.size, 6) * 0.6 for t in text_lines):
                b = len(l.spans) - 1
                while b > 0 and not _is_math_span(l.spans[b]) and re.fullmatch(r"[\s,.;:]*", l.spans[b]["text"]):
                    b -= 1  # trailing sentence punctuation stays text
                groups.append([l, 0, b, group_rect(l, 0, b), False])
        if not groups:
            continue
        # 3) small pieces join the formula they overlap or directly follow (repeat: a numerator attached first
        #    widens the formula so its denominator then overlaps too)
        pending = [l for l in small if not l.used]
        for _ in range(3):
            left = []
            for fl in pending:
                fr = fitz.Rect(fl.x0, fl.y0, fl.x1, fl.y1)
                best, best_score = None, -1e9
                for g in groups:
                    r = g[3]
                    if g[4] or not (r.y0 - fl.size * 1.3 < (fr.y0 + fr.y1) / 2 < r.y1 + fl.size * 1.3):
                        continue
                    ov = min(fr.x1, r.x1 + 2) - max(fr.x0, r.x0 - 2)
                    if ov > -5 and (ov > 0 or fr.x0 >= r.x1 - 2) and ov > best_score:
                        best, best_score = g, ov
                if best is not None:
                    best[3] = best[3] | fr
                    fl.used = True
                    fl.inside = True
                else:
                    left.append(fl)
            if len(left) == len(pending):
                break
            pending = left
        # 4) pieces of one formula that continue each other on the same row merge into one image
        groups.sort(key=lambda g: (round((g[3].y0 + g[3].y1) / 2), g[3].x0))
        for i, g1 in enumerate(groups):
            if g1[4]:
                continue
            for g2 in groups:
                if g2 is g1 or g2[4] or g2[0] is g1[0]:
                    continue
                r1, r2 = g1[3], g2[3]
                ov = min(r1.y1, r2.y1) - max(r1.y0, r2.y0)
                if ov > 0.3 * min(r1.height, r2.height) and r1.x0 < r2.x0 < r1.x1 + 3:  # continues or sits under it
                    g1[3] = r1 | r2
                    g2[4] = True
        # punctuation drawn inside a formula's box (the comma after a radical) is already in its image
        for l in p.lines:
            if not l.used and re.fullmatch(r"[\s,.;:]+", l.text) and any(
                    not g[4] and g[0] is not l and g[3].x0 <= (l.x0 + l.x1) / 2 <= g[3].x1 and g[3].y0 <= (l.y0 + l.y1) / 2 <= g[3].y1
                    for g in groups):
                l.used = True
        # 5) render; replace spans by image spans (right to left keeps indexes valid)
        by_line: dict[int, list] = {}
        for g in groups:
            by_line.setdefault(id(g[0]), []).append(g)
        for gl in by_line.values():
            l = gl[0][0]
            for _, a, b, r, dropped in sorted(gl, key=lambda g: -g[1]):
                if dropped:  # merged into the image of the formula's first part
                    l.spans = l.spans[:a] + l.spans[b + 1:]
                    continue
                clip = fitz.Rect(r.x0 - 0.5, r.y0 - 0.5, r.x1 + 0.5, r.y1 + 0.5)
                counters["inline"] = counters.get("inline", 0) + 1
                name = f"inline_{counters['inline']:03d}.png"
                page.get_pixmap(clip=clip, matrix=fitz.Matrix(4, 4), alpha=False).save(str(fig_dir / name))
                lead = " " if l.spans[a]["text"].startswith(" ") else ""
                img = {"text": "", "img": f"figures/{name}", "w": clip.width, "h": clip.height, "font": "img", "flags": 0,
                       "size": l.size, "bbox": tuple(clip), "origin": (clip.x0, clip.y1), "lead": lead,
                       "src": "".join(s["text"] for s in l.spans[a:b + 1])}
                l.spans = l.spans[:a] + [img] + l.spans[b + 1:]
                made += 1
            if all(s.get("img") or not s["text"].strip(" ,.;:") for s in l.spans):
                l.size = max(l.size, tsize)  # now an image on a text row: no longer "small type"
        p.lines = [l for l in p.lines if l.spans]
    return made


def _mathish(s: dict, l: Line) -> bool:
    t = s["text"]
    if _is_math_span(s):
        return True
    if not t.strip():
        return True
    if s["size"] < l.size * 0.85:  # sub/superscripts
        return True
    if (s["flags"] & 2 or re.search(r"italic|-it\b|oblique", s["font"], re.I)) and len(t.strip()) <= 4:
        return True
    return bool(re.fullmatch(r"\s*[()\[\]{}=+\-/|,;:<>^_0-9.]{1,4}\s*", t))


def _columns(p: PageInfo) -> None:
    mid = p.w / 2
    # only real text lines count (figure labels such as 'Alice', 'File A' are short and would fake columns)
    text_lines = [ln for ln in p.lines if len(ln.text.strip()) >= 30 and ln.x1 - ln.x0 > p.w * 0.25]
    left = [ln for ln in text_lines if ln.x1 <= mid + p.w * 0.03 and ln.x1 - ln.x0 < p.w * 0.5]
    right = [ln for ln in text_lines if ln.x0 >= mid - p.w * 0.03 and ln.x1 - ln.x0 < p.w * 0.5]
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


def _rows(lines: list[Line]) -> list[Line]:
    """Visual rows top to bottom, each read left to right. Lines on one baseline with different heights
    (a run-in heading set as its own line, text next to a tall formula) belong to the same row."""
    out: list[Line] = []
    row: list[Line] = []
    rc = rh = 0.0
    for l in sorted(lines, key=lambda l: ((l.y0 + l.y1) / 2, l.x0)):
        c, h = (l.y0 + l.y1) / 2, max(1.0, min(l.h, l.size * 1.4))
        if row and abs(c - rc) < min(rh, h) * 0.45:
            row.append(l)
        else:
            out += sorted(row, key=lambda x: x.x0)
            row, rc, rh = [l], c, h
    return out + sorted(row, key=lambda x: x.x0)


def _ordered(p: PageInfo, extra_full: list[tuple[float, float]] = ()) -> list[Line]:
    """Reading order: bands separated by full-width items; inside a band, left column then right."""
    if not p.two_col:
        return _rows(p.lines)
    fulls = sorted([l for l in p.lines if l.col == 0], key=lambda l: l.y0)
    seps = sorted([l.y0 for l in fulls] + [a for a, _ in extra_full])
    out: list[Line] = []
    rest = [l for l in p.lines if l.col != 0]
    prev = -1.0
    for sep in seps + [p.h + 1]:
        band = [l for l in rest if prev <= l.y0 < sep]
        out += _rows([l for l in band if l.col == 1])
        out += _rows([l for l in band if l.col == 2])
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
                    rows = _table_rows(p, cand[1])
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


def _table_rows(p: PageInfo, table) -> list[list[str]]:
    """Cell texts rebuilt from the page's text lines (line breaks inside a cell become spaces, broken words
    are rejoined). A table whose cells hold math set in symbol fonts returns [] and is kept as an image."""
    rows = []
    for row in table.rows:
        out = []
        for bb in row.cells:
            if bb is None:
                out.append("")
                continue
            x0, y0, x1, y1 = bb
            parts = []
            for l in sorted(p.lines, key=lambda l: (l.y0, l.x0)):
                spans = [s for s in l.spans if x0 - 1 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= x1 + 1 and
                         y0 - 1 <= (s["bbox"][1] + s["bbox"][3]) / 2 <= y1 + 1]
                if not spans:
                    continue
                if any(s.get("img") or _is_math_span(s) or re.search("[\u00bc\u00f0\u00de\u00fe]", s["text"]) for s in spans):
                    return []
                parts.append("".join(s["text"] for s in spans).strip())
            out.append(_join_lines(parts))
        rows.append(out)
    return [r for r in rows if any(r)]


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
    fonts = " ".join(s["font"] for s in l.spans if not s.get("img"))
    if any(s.get("img") for s in l.spans):
        return False  # a text line carrying inline math images
    mathy = MATH_FONT.search(fonts) is not None or sum(c in MATH_CHARS for c in t) >= 2 or \
        (numbered and "=" in t and len(t) < 120 and not t.rstrip()[:-4].rstrip().endswith("."))
    words = re.findall(r"\b[a-z]{3,}\b", "".join(s["text"] for s in l.spans if not _is_math_span(s)))
    sentence = len(words) >= 4 or (bool(re.search(r"[a-z]{4,}\s+[a-z]{3,}\s+[a-z]{3,}", t)) and not numbered)
    return (centred or numbered) and mathy and not sentence


# ------------------------------------------------------------------ runs
_VOCAB: dict[str, int] = {}


def _dehyphen(prefix_text: str, next_text: str) -> bool:
    """True if a line-final hyphen should be removed (word broken by typesetting) rather than kept
    (a real compound such as 'just-in-time'), judged from how the words appear elsewhere in the paper."""
    m1 = re.search(r"([A-Za-z]+)-$", prefix_text)
    m2 = re.match(r"([A-Za-z]+(?:-[A-Za-z]+)*)", next_text.lstrip())
    if not m1 or not m2:
        return True
    a, b = m1.group(1).lower(), m2.group(1).lower()
    if _VOCAB.get(f"{a}-{b}", 0) > 0 or "-" in b and _VOCAB.get(f"{a}-{b.split('-')[0]}", 0) > 0:
        return False
    if _VOCAB.get(a + b.split("-")[0], 0) > 0:
        return True
    if "-" not in b and len(b) >= 4 and any(k.endswith("-" + b) for k in _VOCAB):
        return False  # 'finer-' + 'grained' when the paper also writes 'coarser-grained'
    if "-" not in b and len(a) >= 4 and len(b) >= 4 and _VOCAB.get(a, 0) > 1 and _VOCAB.get(b, 0) > 1:
        return False  # two real words (seen elsewhere, not only as these fragments), never written joined
    return "-" not in b  # 'in-time' after 'just-' is a compound; plain fragments are joined


def _runs(lines: list[Line], body_size: float) -> list[Inline]:
    runs: list[Inline] = []
    for k, l in enumerate(lines):
        full = [s for s in l.spans if not s.get("img") and s["text"].strip() and s["size"] >= max(l.size, body_size) * 0.88]
        base = statistics.median(s["origin"][1] for s in full) if full else None
        for s in l.spans:
            if s.get("img"):
                if s.get("lead") and runs and not runs[-1].t.endswith(" ") and not runs[-1].img:
                    runs[-1].t += " "
                runs.append(Inline(img=s["img"], img_w=round(s["w"], 2), img_h=round(s["h"], 2)))
                continue
            t = s["text"]
            if not t:
                continue
            # superscripts are set smaller than the text (the PDF flag alone misfires next to tall formulas)
            smaller = s["size"] < max(l.size, body_size) * 0.88
            sup = smaller and (bool(s["flags"] & 1) or (s["origin"][1] < l.y1 - l.h * 0.35 and t.strip() != ""))
            # subscripts: smaller and set below the line's baseline ("c" + "i", "tau" + "0")
            sub = smaller and not sup and base is not None and s["origin"][1] > base + s["size"] * 0.12 and \
                0 < len(t.strip()) <= 12 and not re.search(r"[a-z]{4,}", t)
            r = Inline(t=t, b=bool(s["flags"] & 16) or bool(re.search(r"bold|medium|semibold|demibold|heavy|black", s["font"], re.I)),
                       i=bool(s["flags"] & 2) or bool(re.search(r"italic|oblique", s["font"], re.I)), sup=sup and len(t.strip()) <= 12,
                       sub=sub)
            if runs and (runs[-1].b, runs[-1].i, runs[-1].sup, runs[-1].sub) == (r.b, r.i, r.sup, r.sub) and not runs[-1].cite and not runs[-1].img:
                runs[-1].t += r.t
            else:
                runs.append(r)
        if k < len(lines) - 1 and runs:
            last = runs[-1]
            nxt = lines[k + 1].text.lstrip()
            if not last.img and re.search(r"[A-Za-z0-9]-\s+$", last.t):
                last.t = last.t.rstrip()  # "quanti- " (trailing space span) is still a line-end hyphen
            if last.img:
                if not re.match(r"[.,;:)\]]", nxt):
                    runs.append(Inline(t=" "))
            elif re.search(r"[A-Za-z0-9]-$", last.t) and nxt[:1].isalnum():
                if nxt[:1].islower() and _dehyphen(last.t, nxt):
                    last.t = last.t[:-1]  # word broken across lines
                # else: a real compound ('just-in-time', 'Just-In-Time') - keep the hyphen, no space
            elif not last.t.endswith((" ", "/")) and not (re.search(r"(?:https?://|\b10\.)\S*\.$", last.t) and nxt[:1].isdigit()):
                last.t += " "
    from backend.papers.references import fix_diacritics

    for r in runs:
        r.t = fix_diacritics(re.sub(r"[ \t]{2,}", " ", r.t.replace("­", "")))
    if runs:
        runs[0].t = runs[0].t.lstrip()
        runs[-1].t = runs[-1].t.rstrip()
    return [r for r in runs if r.t or r.img]


# ------------------------------------------------------------------ main
def read(path: Path, work_dir: Path, general: bool = False) -> dict:
    """general=True: any document (no paper front matter; the title is the largest text on page 1)."""
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
    _strip_junk(pages)
    if general:
        _vector_bullets(doc, pages)
    from collections import Counter

    vocab: Counter = Counter()
    for p in pages:
        for l in p.lines:
            vocab.update(w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*(?!-)\b", l.text.rstrip("-")))
    _VOCAB.clear()
    _VOCAB.update(vocab)
    sizes = [l.size for p in pages for l in p.lines for _ in range(max(1, len(l.text) // 10))]
    body = statistics.mode([round(s * 2) / 2 for s in sizes])
    sidebar = _sidebar(pages, body)
    for p in pages:
        _columns(p)
    counters: dict[str, int] = {}
    n_inline = _inline_math(doc, pages, fig_dir, counters)
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
    first = [x for pg, _, x in stream if pg == 0 and isinstance(x, Line) and (general or x.y0 < pages[0].h * 0.45)]
    title_lines: list[Line] = []
    if first:
        big = max(l.size for l in first)
        if big >= body + 2:
            cand = [l for l in first if abs(l.size - big) < 0.6]
            title_lines = [l for l in cand if l.y0 - cand[0].y0 < big * 4.5]
    title = ""
    for l in title_lines:
        t = l.text.strip()
        if title.endswith("-") and t[:1].islower():
            title = title[:-1] + t if _dehyphen(title, t) else title + t
        else:
            title = (title + " " + t).strip()
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
        if not text and not any(sp.get("img") for l in lines for sp in l.spans):
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
        if not general and not seen_abstract and not seen_heading and pno == 0 and not in_refs:
            starts_body = re.match(r"^\s*(abstract|summary|key\s*words?|index\s+terms)\b", t, re.I) or \
                (lvl and short and (l.bold or t.isupper() or l.size > body + 0.3) and not re.search(r"[,@]", t)) or \
                bool(REFS_HEAD.match(t))
            if not starts_body:
                front.append(t)
                continue
        # run-in heading: "3.1.2 One-mode projection. We projected ..." - bold lead-in, then the paragraph
        last_head = next((e.text for e in reversed(elems) if e.kind == "heading"), "")
        if not in_refs and seen_heading and len(l.spans) >= 2 and special_kind(last_head) == "body":
            k = 0
            while k < len(l.spans) and not l.spans[k].get("img") and \
                    ((l.spans[k]["flags"] & 16) or re.search(r"bold|black|semibold", l.spans[k]["font"], re.I) or not l.spans[k]["text"].strip()):
                k += 1
            lead = "".join(s["text"] for s in l.spans[:k]).strip()
            rest = l.spans[k:]
            if lead and rest and re.search(r"[A-Za-z]", "".join(s["text"] for s in rest)) and len(lead) < 90:
                ln_, lv_, nu_ = heading_info(lead.rstrip(".:"))
                para_start = not buf or buf[-1].text.rstrip().endswith((".", ":", "?", "!"))
                if para_start and (lv_ or (len(lead.split()) <= 6 and lead.endswith((".", ":")) and lead[:1].isupper())):
                    flush()
                    elems.append(Elem(kind="heading", runs=[Inline(t=lead.rstrip(".:").strip())], level=min(3, lv_ or 3)))
                    rx0 = rest[0]["bbox"][0] if "bbox" in rest[0] else l.x0
                    l = Line(l.page, rx0, l.y0, l.x1, l.y1, rest, l.size, False, l.italic, l.fonts, l.col)
                    t = l.text.strip()
                    name, lvl, num = heading_info(t)
                    short = False
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
            ends = prev.text.rstrip().rstrip("”’\"')").endswith((".", ":", "?", "!"))  # also after a closing quote
            indent = l.x0 - (_col_bounds(pages[l.page], l.col)[0] if l.col else min(ll.x0 for ll in pages[l.page].lines)) > body * 0.6
            if l.page != prev.page or (l.col != prev.col and l.y0 < prev.y0 - prev.h):
                new_para = ends and (indent or gap > 0)  # page / column break: continue the paragraph unless it ended
            elif l.col != prev.col:
                new_para = gap > max(prev.h, l.h) * 0.5  # from a full-width block into a column (or back)
            else:
                new_para = gap > max(prev.h, l.h) * 0.75 or gap < -prev.h * 2 or (indent and ends and l.x0 - prev.x0 > body * 0.6)
            new_para = new_para or bool(BULLET.match(t)) or (general and _label_start(l)) or abs(l.size - prev.size) > 1.2 or (l.bold != prev.bold and len(t) < 60 and ends) or \
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
        if merged and e.kind == "para" and e.runs:
            # the paragraph this one continues: the previous paragraph, possibly with figures/tables that the
            # layout placed at the page/column break in between (those move after the joined paragraph)
            k = len(merged) - 1
            while k >= 0 and merged[k].kind in ("figure", "table") and len(merged) - k <= 3:
                k -= 1
            host = merged[k] if k >= 0 and merged[k].kind == "para" and merged[k].runs else None
            prev_t = host.text if host else ""
            first = next((r.t for r in e.runs if r.t.strip()), "")
            if host and prev_t and not prev_t.rstrip().endswith((".", ":", "?", "!", "”", "\"")) and \
                    (first[:1].islower() or (not first and e.runs[0].img)):
                last = host.runs[-1]
                if last.t.endswith("-") and first[:1].islower() and _dehyphen(last.t, first):
                    last.t = last.t[:-1]
                elif not last.t.endswith((" ", "-")):
                    last.t += " "
                host.runs += e.runs
                continue
        merged.append(e)
    if any(b.kind == "equation" for e in merged if (b := e.block)):
        notes.append("Display equations were recovered from the PDF as images (a PDF does not contain their source). "
                      "Check them, or upload the LaTeX/Word source for fully editable equations.")
    # source text for the fidelity check: body text only (no figure-internal labels, no math glyphs)
    raw_text = "\n".join("".join(s["text"] for s in l.spans if not s.get("img") and not _is_math_span(s))
                         for p in pages for l in p.lines if not l.inside)
    raw_text += "\n" + "\n".join(t for _, t in sidebar)
    if n_inline:
        notes.append(f"{n_inline} inline math expression(s) were carried over as images cut from the PDF "
                     "(its math fonts have no usable text). Upload the LaTeX/Word source for editable math.")
    return {"elems": merged, "title": title, "front": front, "refs": refs, "raw_text": raw_text,
            "footnotes": footnotes, "notes": notes, "pages": len(doc), "sidebar": sidebar}


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
