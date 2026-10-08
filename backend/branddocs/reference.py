"""Learn a brand document template from a reference PDF (offline).

The reference is read with PyMuPDF: text spans give the type scale and page geometry, vector drawings give
cards, rules, heading dashes, bullets and the brand artwork (replayed later as exact vectors), and the page
rendered to pixels gives the colours as they really appear (blend modes and transparency included).
Each page is classified into one of the page designs a document is built from:

    cover  - full-bleed image, large title, document label (e.g. "White Paper"), logo lockups
    intro  - first page with a coloured card holding the opening section
    body   - two-column text page
    image  - page with a photo across the top that fades into the page colour
    conclusion - card page that closes the document
    back   - back cover: author block, brand pattern/logo, company boilerplate
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from backend.branddocs.model import (Artwork, BackDesign, Card, CoverDesign, DocTemplate, Footer, ImageStyle, PageDesign,
                                     Photo, Shape, TextStyle)

WEIGHTS = [("thin", 100), ("hairline", 100), ("extralight", 200), ("ultralight", 200), ("light", 300), ("book", 400),
           ("regular", 400), ("roman", 400), ("normal", 400), ("medium", 500), ("semibold", 600), ("demibold", 600),
           ("demi", 600), ("extrabold", 800), ("ultrabold", 800), ("bold", 700), ("black", 900), ("heavy", 900)]
FOOTER_PAGE = re.compile(r"\bpage\s*\d+\b|^\s*\d+\s*$", re.I)


def hexc(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(round(max(0, min(255, v)))) for v in rgb[:3])


def _hex_from_fitz(c) -> Optional[str]:
    return hexc([v * 255 for v in c]) if c else None


def font_family_weight(font: str, flags: int = 0) -> tuple[str, int]:
    """'OAIYWV+Graphik-Medium' -> ('Graphik', 500); 'Arial-BoldMT' -> ('Arial', 700)."""
    name = font.split("+", 1)[-1]
    fam, _, style = name.partition("-")
    if not style and "," in name:
        fam, _, style = name.partition(",")
    s = re.sub(r"(MT|PS|Std|Pro|LT|OT|It(alic)?|Oblique)$", "", style.replace(" ", "")).lower()
    weight = 400
    for key, w in WEIGHTS:
        if key in s:
            weight = w
            break
    else:
        if flags & 16:
            weight = 700
    fam = re.sub(r"(MT|PS|Std)$", "", fam).strip() or name
    return fam, weight


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    family: str
    weight: int
    color: str
    baseline: float
    spans: list = field(default_factory=list)


@dataclass
class PageData:
    no: int
    w: float
    h: float
    lines: list[Line]
    drawings: list[dict]
    images: list[dict]
    pix: np.ndarray  # rendered page, 1 px = 1 pt


def _read(doc) -> list[PageData]:
    import fitz

    out = []
    for p in doc:
        lines = []
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                main = max(spans, key=lambda s: len(s["text"]))
                fam, wt = font_family_weight(main["font"], main["flags"])
                text = "".join(s["text"] for s in l["spans"]).strip()
                x0, y0, x1, y1 = l["bbox"]
                lines.append(Line(text, x0, y0, x1, y1, round(main["size"], 2), fam, wt, hexc(fitz.sRGB_to_rgb(main["color"])),
                                  main["origin"][1], spans))
        pix = p.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()
        out.append(PageData(p.number + 1, p.rect.width, p.rect.height, lines, p.get_drawings(), p.get_image_info(xrefs=True), arr))
    return out


# ------------------------------------------------------------------ shapes
def _shape(d: dict) -> Shape:
    items = []
    for it in d["items"]:
        op = it[0]
        if op == "l":
            items.append(["l", it[1].x, it[1].y, it[2].x, it[2].y])
        elif op == "c":
            items.append(["c", it[1].x, it[1].y, it[2].x, it[2].y, it[3].x, it[3].y, it[4].x, it[4].y])
        elif op == "re":
            r = it[1]
            items.append(["re", r.x0, r.y0, r.x1, r.y1])
        elif op == "qu":
            q = it[1]
            items.append(["l", q.ul.x, q.ul.y, q.ur.x, q.ur.y])
            items.append(["l", q.ur.x, q.ur.y, q.lr.x, q.lr.y])
            items.append(["l", q.lr.x, q.lr.y, q.ll.x, q.ll.y])
            items.append(["l", q.ll.x, q.ll.y, q.ul.x, q.ul.y])
    r = d["rect"]
    return Shape(items=items, fill=_hex_from_fitz(d.get("fill")), fill_opacity=float(d.get("fill_opacity") or 1.0),
                 stroke=_hex_from_fitz(d.get("color")) if d.get("type") in ("s", "fs") else None,
                 width=float(d.get("width") or 0.0), even_odd=bool(d.get("even_odd")), close=bool(d.get("closePath")),
                 bbox=[r.x0, r.y0, r.x1, r.y1])


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inside(inner, outer, tol=2.0) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def _shape_mask(s: Shape, w: float, h: float) -> np.ndarray:
    """Pixels covered by one shape (rendered alone), 1 px = 1 pt."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    sh = page.new_shape()
    for it in s.items:
        if it[0] == "l":
            sh.draw_line((it[1], it[2]), (it[3], it[4]))
        elif it[0] == "c":
            sh.draw_bezier((it[1], it[2]), (it[3], it[4]), (it[5], it[6]), (it[7], it[8]))
        elif it[0] == "re":
            sh.draw_rect(fitz.Rect(it[1:5]))
    sh.finish(fill=(0, 0, 0), color=None, even_odd=s.even_odd, closePath=True)
    sh.commit()
    pix = page.get_pixmap(alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    return arr < 128


def _sample(pd: PageData, mask: np.ndarray, exclude: list) -> Optional[str]:
    m = mask.copy()
    H, W = m.shape
    for r in exclude:
        x0, y0, x1, y1 = (max(0, int(r[0]) - 2), max(0, int(r[1]) - 2), min(W, int(r[2]) + 3), min(H, int(r[3]) + 3))
        m[y0:y1, x0:x1] = False
    pix = pd.pix[: m.shape[0], : m.shape[1]][m[: pd.pix.shape[0], : pd.pix.shape[1]]]
    if len(pix) < 20:
        return None
    return hexc(np.median(pix, axis=0))


def _prefer_exact(sampled: Optional[str], declared: Optional[str]) -> Optional[str]:
    """Rendering rounds colours by a level or two: keep the exact declared colour unless the page really looks
    different (blend modes / transparency)."""
    if not sampled or not declared:
        return sampled or declared
    a = [int(sampled[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(declared[i:i + 2], 16) for i in (1, 3, 5)]
    return declared.upper() if max(abs(x - y) for x, y in zip(a, b)) <= 3 else sampled


def _cluster(shapes: list[Shape], gap: float = 10.0) -> list[list[Shape]]:
    groups: list[list[Shape]] = []
    boxes: list[list[float]] = []
    for s in shapes:
        b = s.bbox
        hit = [i for i, g in enumerate(boxes) if b[0] <= g[2] + gap and b[2] >= g[0] - gap and b[1] <= g[3] + gap and b[3] >= g[1] - gap]
        if not hit:
            groups.append([s])
            boxes.append(list(b))
            continue
        k = hit[0]
        for j in sorted(hit[1:], reverse=True):
            groups[k] += groups.pop(j)
            g = boxes.pop(j)
            boxes[k] = [min(boxes[k][0], g[0]), min(boxes[k][1], g[1]), max(boxes[k][2], g[2]), max(boxes[k][3], g[3])]
        groups[k].append(s)
        boxes[k] = [min(boxes[k][0], b[0]), min(boxes[k][1], b[1]), max(boxes[k][2], b[2]), max(boxes[k][3], b[3])]
    return groups


def _bbox(shapes: list[Shape]) -> list[float]:
    return [min(s.bbox[0] for s in shapes), min(s.bbox[1] for s in shapes), max(s.bbox[2] for s in shapes), max(s.bbox[3] for s in shapes)]


# ------------------------------------------------------------------ per page
@dataclass
class Parts:
    bg: str = "#FFFFFF"
    cards: list[tuple[Shape, list[float]]] = field(default_factory=list)
    decorations: list[Shape] = field(default_factory=list)
    dashes: list[Shape] = field(default_factory=list)
    bullets: list[Shape] = field(default_factory=list)
    vrules: list[Shape] = field(default_factory=list)
    hrules: list[Shape] = field(default_factory=list)
    artwork: list[Artwork] = field(default_factory=list)
    photo: Optional[Photo] = None


def _parts(pd: PageData) -> Parts:
    P = Parts()
    page_area = pd.w * pd.h
    shapes = [(_shape(d), d) for d in pd.drawings]
    text_boxes = [[l.x0, l.y0, l.x1, l.y1] for l in pd.lines]
    rest: list[Shape] = []
    bg_shape = None
    for s, d in shapes:
        b = s.bbox
        a = _area(b)
        w, h = b[2] - b[0], b[3] - b[1]
        if s.fill and a >= 0.95 * page_area:
            bg_shape = s
            continue
        if s.stroke and not s.fill and all(it[0] == "l" for it in s.items) and len(s.items) == 1 and s.width <= 1.2:
            (P.vrules if w < 1.5 else P.hrules if h < 1.5 else rest).append(s)
            continue
        if s.fill and h <= 6.5 and 12 <= w <= 70 and all(it[0] == "re" for it in s.items):
            P.dashes.append(s)
            continue
        if s.fill and w <= 8 and h <= 8 and any(it[0] == "c" for it in s.items) and any(
                abs(t[1] - b[1]) < 6 and t[0] > b[2] for t in text_boxes):
            P.bullets.append(s)
            continue
        if s.fill and a >= 0.04 * page_area:
            lines_in = [t for t in text_boxes if _inside(t, b)]
            ops = [it[0] for it in s.items]
            rect_like = all(o == "re" for o in ops) or (ops.count("c") == 4 and ops.count("l") <= 4)  # (rounded) rectangle
            if len(lines_in) >= 3 and w >= pd.w * 0.5 and rect_like:
                P.cards.append((s, b))
            else:
                P.decorations.append(s)
            continue
        rest.append(s)
    # visible photos (an image can be placed but clipped away entirely): judge only the pixels not covered
    # by text, cards or big shapes
    covered = np.zeros(pd.pix.shape[:2], dtype=bool)
    for bb in text_boxes + [s.bbox for s in P.decorations] + [b for _, b in P.cards]:
        covered[max(0, int(bb[1]) - 2):int(bb[3]) + 3, max(0, int(bb[0]) - 2):int(bb[2]) + 3] = True
    for im in pd.images:
        r = [max(0, im["bbox"][0]), max(0, im["bbox"][1]), min(pd.w, im["bbox"][2]), min(pd.h, im["bbox"][3])]
        if _area(r) < 0.12 * page_area:
            continue
        sl = (slice(int(r[1]), int(r[3])), slice(int(r[0]), int(r[2])))
        free = ~covered[sl]
        reg = pd.pix[sl].astype(float).mean(axis=2)[free]
        if reg.size < 0.3 * free.size or reg.std() < 14:
            continue
        P.photo = Photo(box=r)
    # colours as rendered
    excl_text = text_boxes
    card_boxes = [b for _, b in P.cards]
    if bg_shape is not None:
        mask = np.ones(pd.pix.shape[:2], dtype=bool)
        for s in P.decorations + [c for c, _ in P.cards]:
            b = s.bbox
            mask[max(0, int(b[1]) - 2):int(b[3]) + 3, max(0, int(b[0]) - 2):int(b[2]) + 3] = False
        if P.photo:
            b = P.photo.box
            mask[int(b[1]):int(b[3]), int(b[0]):int(b[2])] = False
        P.bg = _prefer_exact(_sample(pd, mask, excl_text), bg_shape.fill) or "#FFFFFF"
    else:
        P.bg = hexc(np.median(pd.pix.reshape(-1, 3), axis=0))
    for s in P.decorations:
        s.fill = _prefer_exact(_sample(pd, _shape_mask(s, pd.w, pd.h), excl_text + card_boxes + ([P.photo.box] if P.photo else [])), s.fill)
        s.fill_opacity = 1.0
    for c, b in P.cards:
        c.fill = _prefer_exact(_sample(pd, _shape_mask(c, pd.w, pd.h), excl_text), c.fill)
    for g in _cluster(rest):
        bb = _bbox(g)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        role = "pattern" if _area(bb) >= 0.03 * page_area else "logo" if w >= 3 * h and h <= 60 else "marker" if w <= 24 and h <= 24 else "artwork"
        P.artwork.append(Artwork(role=role, bbox=bb, shapes=g))
    return P


def _photo_fade(pd: PageData, P: Parts) -> None:
    """Where a top photo fades into the page colour (row medians ignore text on top of it)."""
    if not P.photo:
        return
    x0, y0, x1, y1 = (int(v) for v in P.photo.box)
    bg = np.array([int(P.bg[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    reg = pd.pix[y0:y1, x0:x1].astype(float)
    d = np.median(np.abs(reg - bg).sum(axis=2), axis=1)
    if d.max() < 20:
        return
    flat = np.where(d < 0.08 * d.max())[0]
    # the last row from which the rest of the image is plain page colour
    end = y1
    for y in range(len(d) - 1, -1, -1):
        if d[y] >= 0.08 * d.max():
            end = y0 + y + 1
            break
    strong = np.where(d >= 0.6 * d.max())[0]
    start = y0 + int(strong.max()) if len(strong) else y0
    if end < y1 - 8 and len(flat):
        P.photo.box = [P.photo.box[0], P.photo.box[1], P.photo.box[2], float(end)]
        P.photo.fade_from = float(min(start, end))
        P.photo.fade_to = float(end)


def _style(lines: list[Line]) -> TextStyle:
    c = Counter((l.family, l.weight, l.size, l.color) for l in lines for _ in range(max(1, len(l.text) // 8)))
    (fam, wt, size, color), _ = c.most_common(1)[0]
    same = sorted([l for l in lines if l.size == size and l.family == fam], key=lambda l: (round(l.x0), l.y0))
    # a real line step is at least the type size (pieces of one line, or super/subscripts, are not)
    gaps = [b.baseline - a.baseline for a, b in zip(same, same[1:]) if abs(a.x0 - b.x0) < 3 and size * 0.95 <= b.baseline - a.baseline < size * 2.2]
    leading = round(statistics.median(gaps), 2) if gaps else round(size * 1.25, 2)
    return TextStyle(family=fam, weight=wt, size=size, leading=leading, color=color)


def _para_space(lines: list[Line], st: TextStyle) -> float:
    same = sorted([l for l in lines if l.size == st.size], key=lambda l: (round(l.x0), l.y0))
    gaps = [b.baseline - a.baseline - st.leading for a, b in zip(same, same[1:])
            if abs(a.x0 - b.x0) < 3 and st.leading * 1.3 < b.baseline - a.baseline < st.leading * 3]
    return round(statistics.median(gaps), 2) if gaps else round(st.leading * 0.6, 2)


def _columns(pd: PageData, body: TextStyle, vrules: list[Shape], region=None) -> tuple[list[list[float]], Optional[dict]]:
    ls = [l for l in pd.lines if abs(l.size - body.size) < 0.6 and (region is None or _inside([l.x0, l.y0, l.x1, l.y1], region))]
    xs = Counter(round(l.x0 / 4) * 4 for l in ls)
    starts = sorted(x for x, n in xs.items() if n >= 3)
    merged: list[float] = []
    for x in starts:
        if not merged or x - merged[-1] > 40:
            merged.append(x)
    div = None
    vr = [v for v in vrules if (v.bbox[3] - v.bbox[1]) > 80 and (region is None or _inside(v.bbox, region))]
    if vr:
        v = max(vr, key=lambda v: v.bbox[3] - v.bbox[1])
        div = {"x": round((v.bbox[0] + v.bbox[2]) / 2, 2), "color": v.stroke or "#000000", "width": v.width or 0.25,
               "y0": v.bbox[1], "y1": v.bbox[3]}
    left = min(merged) if merged else 36.0
    right = (region[2] - (left - region[0])) if region else pd.w - left

    def end_of(x0: float, limit: float) -> float:
        ends = sorted(l.x1 for l in ls if abs(l.x0 - x0) < 6 and l.x1 <= limit + 2)
        return ends[int(len(ends) * 0.9)] if ends else limit
    if len(merged) >= 2 and div:
        x2 = min(x for x in merged if x > div["x"]) if any(x > div["x"] for x in merged) else merged[1]
        gap = x2 - div["x"]
        return [[left, div["x"] - gap], [x2, right]], div
    if len(merged) >= 2:
        x2 = merged[1]
        c1 = min(end_of(left, x2 - 8), x2 - 14)
        gut = x2 - c1
        return [[left, c1], [x2, max(end_of(x2, right), min(right, x2 + (c1 - left)))]], div
    return [[left, right]], div


def _footer(pd: PageData, body: TextStyle) -> Optional[Footer]:
    cand = [l for l in pd.lines if l.size < body.size - 0.5 and FOOTER_PAGE.search(l.text) and l.y0 > pd.h * 0.85]
    if not cand:
        return None
    l = max(cand, key=lambda l: l.y0)
    pat = re.sub(r"(?i)(page\s*)\d+", r"\1{page}", l.text)
    if pat == l.text:
        pat = re.sub(r"\d+", "{page}", l.text)
    pat = re.sub(r"\b(19|20)\d{2}\b", "{year}", pat)
    pat = re.sub(r"\s{2,}", "  ", pat)
    centre = (l.x0 + l.x1) / 2
    align = "center" if abs(centre - pd.w / 2) < 20 else "right" if centre > pd.w / 2 else "left"
    return Footer(pattern=pat, style=TextStyle(family=l.family, weight=l.weight, size=l.size, color=l.color),
                  x1=l.x1 if align == "right" else l.x0 if align == "left" else centre, baseline=l.baseline, align=align)


def _design(kind, pd: PageData, P: Parts, body: TextStyle, heading: Optional[TextStyle]) -> PageDesign:
    d = PageDesign(kind=kind, source_page=pd.no, background=P.bg, decorations=P.decorations,
                   artwork=[a for a in P.artwork if a.role != "marker" or kind != "cover"], photo=P.photo)
    body_lines = [l for l in pd.lines if abs(l.size - body.size) < 0.6]
    head_lines = [l for l in pd.lines if heading and abs(l.size - heading.size) < 0.6]
    card_box = None
    if P.cards:
        c, b = max(P.cards, key=lambda cb: _area(cb[1]))
        card_box = b
        inner = [l for l in pd.lines if _inside([l.x0, l.y0, l.x1, l.y1], b)]
        radius = 0.0
        cs = [it for it in c.items if it[0] == "c"]
        if cs:
            it = cs[0]
            radius = round(max(abs(it[7] - it[1]), abs(it[8] - it[2])), 2)
        dash = next((s for s in P.dashes if _inside(s.bbox, b)), None)
        vdiv = [v for v in P.vrules if _inside(v.bbox, b)]
        seps = [r for r in P.hrules if _inside(r.bbox, b)]
        inner_body = [l for l in inner if not heading or abs(l.size - heading.size) >= 0.6]
        d.card = Card(box=b, color=c.fill or "#000000", radius=radius,
                      pad_x=round(min(l.x0 for l in inner) - b[0], 2) if inner else 24,
                      pad_top=round(min(l.y0 for l in inner) - b[1], 2) if inner else 40,
                      pad_bottom=round(b[3] - max(l.y1 for l in inner), 2) if inner else 30,
                      dash_color=dash.fill if dash else "", text_color=(inner_body or inner)[0].color if inner else "#FFFFFF",
                      divider_color=vdiv[0].stroke if vdiv else "", divider_width=vdiv[0].width if vdiv else 0.25,
                      separator_rules=bool(seps),
                      columns=2 if (vdiv or len({round(l.x0 / 20) for l in inner_body if l.x1 - l.x0 > 40}) >= 2 and
                                    max((l.x1 - l.x0 for l in inner_body), default=0) < (b[2] - b[0]) * 0.6) else 1)
    outside = [l for l in body_lines if not card_box or not _inside([l.x0, l.y0, l.x1, l.y1], card_box)]
    if outside:
        d.text_color = Counter(l.color for l in outside).most_common(1)[0][0]
    elif body_lines:
        d.text_color = body_lines[0].color
    ho = [l for l in head_lines if not card_box or not _inside([l.x0, l.y0, l.x1, l.y1], card_box)]
    d.heading_color = ho[0].color if ho else d.text_color
    region = None
    if card_box:  # columns of the text below/after the card
        region = [0, card_box[3], pd.w, pd.h]
    vr_out = [v for v in P.vrules if not card_box or not _inside(v.bbox, card_box)]
    cols, div = _columns(pd, body, vr_out, region)
    if len([l for l in outside]) < 3 and card_box:
        cols, div = _columns(pd, body, [v for v in P.vrules if _inside(v.bbox, card_box)], card_box)
    d.columns, d.divider = cols, div
    full = [r for r in P.hrules if (r.bbox[2] - r.bbox[0]) > pd.w * 0.7]
    col_rules = [r for r in P.hrules if r not in full and not (card_box and _inside(r.bbox, card_box))]
    rules = full + col_rules
    if rules:
        d.rule_color = Counter(r.stroke for r in rules).most_common(1)[0][0] or ""
        d.rule_width = rules[0].width or 0.25
    elif div:
        d.rule_color, d.rule_width = div["color"], div["width"]
    texts = [l for l in pd.lines if l.size >= body.size - 0.6 and (not card_box or not _inside([l.x0, l.y0, l.x1, l.y1], card_box))
             and not FOOTER_PAGE.search(l.text)]
    if texts:
        top_text = min(l.y0 for l in texts)
        bot_text = max(l.y1 for l in texts)
        above = [r for r in full if r.bbox[1] < top_text]
        below = [r for r in full if r.bbox[1] > bot_text]
        d.top_rule = max(r.bbox[1] for r in above) if above and P.photo else None
        d.bottom_rule = min(r.bbox[1] for r in below) if below else None
        d.content_top = round(min([top_text] + ([div["y0"]] if div else [])), 2)
        d.content_bottom = round(max([bot_text] + ([div["y1"]] if div else [])), 2)
    if P.bullets:
        bl = P.bullets[0]
        line = min((l for l in pd.lines if abs(l.y0 - bl.bbox[1]) < 8 and l.x0 > bl.bbox[2]), key=lambda l: l.x0, default=None)
        d.bullet = {"size": round(bl.bbox[2] - bl.bbox[0], 2), "color": bl.fill or d.text_color,
                    "indent": round((line.x0 - bl.bbox[0]) if line else 17, 2)}
    d.footer = _footer(pd, body)
    return d


# ------------------------------------------------------------------ colour statistics of photos
def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _hue_name(rgb) -> str:
    import colorsys

    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    if s < 0.15:
        return "black" if l < 0.15 else "white" if l > 0.85 else "grey"
    deg = h * 360
    for lim, name in [(15, "red"), (40, "orange"), (65, "yellow"), (150, "green"), (195, "teal"), (225, "blue"), (255, "indigo"),
                      (290, "violet"), (330, "magenta"), (361, "red")]:
        if deg < lim:
            return name
    return "red"


def image_style(photos: list[np.ndarray]) -> ImageStyle:
    from PIL import Image

    if not photos:
        return ImageStyle(prompt_style="professional, clean, minimal composition, soft natural light, corporate photography",
                          negative=NEGATIVE)
    px = np.concatenate([p.reshape(-1, 3) for p in photos]).astype(float)
    lab = _rgb_to_lab(px)
    img = Image.fromarray(np.concatenate([p.reshape(-1, 3) for p in photos])[None, :, :].astype(np.uint8))
    q = img.quantize(6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:18]
    counts = sorted(q.getcolors(), reverse=True)
    colours = [tuple(pal[i * 3:i * 3 + 3]) for _, i in counts]
    names = []
    for c in colours:
        n = _hue_name(c)
        if n not in names and n not in ("grey",):
            names.append(n)
    L = float(lab[:, 0].mean())
    chroma = float(np.hypot(lab[:, 1], lab[:, 2]).mean())
    light = "dark, low-key, dramatic lighting" if L < 35 else "bright, high-key lighting" if L > 65 else "balanced lighting"
    tone = " and ".join(n for n in names if n not in ("black", "white")[:2])[:60] or "neutral"
    vivid = "glowing highlights, saturated colour" if chroma > 30 else "muted colour"
    style = (f"cinematic concept art, {light}, {tone} tones, {vivid}, minimal composition, clean, professional corporate imagery, "
             "high detail, sharp focus")
    return ImageStyle(prompt_style=style, negative=NEGATIVE, lab_mean=[round(float(v), 3) for v in lab.mean(axis=0)],
                      lab_std=[round(float(v), 3) for v in lab.std(axis=0)], palette=[hexc(c) for c in colours])


NEGATIVE = ("text, letters, words, typography, caption, watermark, signature, logo, brand name, blurry, lowres, jpeg artifacts, "
            "deformed, disfigured, extra limbs, extra fingers, bad anatomy, cropped face, cartoon, nsfw, nudity, gore, violence")


# ------------------------------------------------------------------ main
def analyze(pdf: Path, tid: str, name: str, brand_id: str = "") -> DocTemplate:
    import fitz

    doc = fitz.open(str(pdf))
    if doc.needs_pass:
        raise ValueError("The reference PDF is password-protected.")
    pages = _read(doc)
    if not pages or not any(p.lines for p in pages):
        raise ValueError("The reference PDF has no selectable text, so its type and layout cannot be measured.")
    W, H = pages[0].w, pages[0].h
    t = DocTemplate(id=tid, name=name, brand_id=brand_id, source_file=pdf.name, page_w=W, page_h=H)
    all_lines = [l for p in pages for l in p.lines]
    t.fonts_seen = sorted({f"{l.family}-{l.weight}" for l in all_lines})
    textish = [l for l in all_lines if 7.5 <= l.size <= 14]
    body = _style(textish or all_lines)
    body.space_after = _para_space(all_lines, body)
    t.styles["body"] = body
    sizes = sorted({l.size for l in all_lines})
    cover_max = max((l.size for l in pages[0].lines), default=0)
    head_lines = [l for p in pages[1:] for l in p.lines if body.size * 1.6 <= l.size < max(cover_max, body.size * 1.6 + 0.1) - 0.1]
    if not head_lines:
        head_lines = [l for p in pages for l in p.lines if l.size >= body.size * 1.6]
    heading = _style(head_lines) if head_lines else None
    if heading:
        t.styles["h1"] = heading
    # emphasised body (conclusion card) and run-in labels
    emph = [l for l in all_lines if l.weight >= 500 and body.size < l.size < body.size * 1.5 and len(l.text) > 25]
    if emph:
        t.styles["emphasis"] = _style(emph)
    labels = [s for l in all_lines for s in l.spans if abs(s["size"] - body.size) < 0.3 and font_family_weight(s["font"])[1] >= 500]
    if labels:
        fam, wt = font_family_weight(labels[0]["font"])
        t.styles["label"] = TextStyle(family=fam, weight=wt, size=body.size, leading=body.leading,
                                      color=hexc(fitz.sRGB_to_rgb(Counter(s["color"] for s in labels).most_common(1)[0][0])))
    parts = [_parts(p) for p in pages]
    for p, P in zip(pages, parts):
        _photo_fade(p, P)
    # accent + heading dash
    dashes = [d for P in parts for d in P.dashes]
    if dashes:
        t.accent = Counter(d.fill for d in dashes).most_common(1)[0][0] or ""
        d0 = next(d for d in dashes if d.fill == t.accent)
        gap, after = [], []
        for p, P in zip(pages, parts):
            for d in P.dashes:
                above = [l for l in p.lines if l.y1 <= d.bbox[1] + 1 and abs(l.x0 - d.bbox[0]) < 6 and heading and abs(l.size - heading.size) < 0.6]
                below = [l for l in p.lines if l.y0 >= d.bbox[3] - 1 and abs(l.x0 - d.bbox[0]) < 8]
                if above:
                    gap.append(d.bbox[1] - max(above, key=lambda l: l.y1).baseline)
                if below:
                    after.append(min(below, key=lambda l: l.y0).baseline - body.size * 0.8 - d.bbox[3])
        t.dash = {"w": round(d0.bbox[2] - d0.bbox[0], 2), "h": round(d0.bbox[3] - d0.bbox[1], 2),
                  "gap": round(statistics.median(gap), 2) if gap else 12.0, "after": round(statistics.median(after), 2) if after else 14.0}
    # classify pages
    kinds: dict[int, str] = {}
    if parts[0].photo or cover_max >= body.size * 2.5:
        kinds[0] = "cover"
    last = len(pages) - 1
    if last > 0 and not any(FOOTER_PAGE.search(l.text) and l.size < body.size for l in pages[last].lines):
        kinds[last] = "back"
    def headed_card(i: int) -> bool:  # a panel that holds a section (heading inside), not a table box
        if not heading:
            return False
        return any(_inside([l.x0, l.y0, l.x1, l.y1], b) and abs(l.size - heading.size) < 0.6
                   for _, b in parts[i].cards for l in pages[i].lines)
    card_pages = [i for i, P in enumerate(parts) if P.cards and i not in kinds and headed_card(i)]
    if card_pages:
        kinds[card_pages[0]] = "intro"
        if len(card_pages) > 1:
            kinds[card_pages[-1]] = "conclusion"
        elif card_pages[0] > len(pages) / 2:
            kinds[card_pages[0]] = "conclusion"
    for i, P in enumerate(parts):
        if i not in kinds and P.photo:
            kinds[i] = "image"
            break
    rest = [i for i in range(len(pages)) if i not in kinds]
    plain = [i for i in rest if not parts[i].cards] or rest  # a text page without panels
    if plain:
        kinds[max(plain, key=lambda i: sum(len(l.text) for l in pages[i].lines))] = "body"
    for i, k in sorted(kinds.items()):
        t.pages[k] = _design(k, pages[i], parts[i], body, heading)
    if "body" not in t.pages:
        t.notes.append("The reference has no plain text page; text pages reuse the intro page design without its card.")
    # cover
    if "cover" in t.pages:
        p, P = pages[0], parts[0]
        big = [l for l in p.lines if abs(l.size - cover_max) < 0.6]
        if big:
            st = _style(big)
            st.leading = round(statistics.median([b.baseline - a.baseline for a, b in zip(big, big[1:])]), 2) if len(big) > 1 else round(cover_max * 1.05, 2)
            t.cover.title = st
            t.cover.title_box = [min(l.x0 for l in big), min(l.y0 for l in big), max(max(l.x1 for l in big), p.w - 36), max(l.y1 for l in big)]
            below = sorted([l for l in p.lines if l.y0 >= t.cover.title_box[3] - 2 and l.size < cover_max], key=lambda l: l.y0)
            if below:
                # the document label ("White paper"): the line with the small marker shape before it, else a short line
                def marker_for(l):
                    return [a for a in P.artwork if a.role == "marker" and abs((a.bbox[1] + a.bbox[3]) / 2 - (l.y0 + l.y1) / 2) < l.size
                            and a.bbox[2] <= l.x0 + 2 and l.x0 - a.bbox[2] < 30]
                marked = [l for l in below if marker_for(l)]
                short = [l for l in below if len(l.text.split()) <= 3]
                lab = (marked or short or below)[0]
                t.cover.label = TextStyle(family=lab.family, weight=lab.weight, size=lab.size, color=lab.color)
                t.cover.label_text = lab.text
                t.cover.label_pos = [lab.x0, lab.y0]
                mk = marker_for(lab)
                t.cover.marker = mk[0] if mk else None
    # back cover
    if "back" in t.pages:
        p = pages[last]
        ls = sorted(p.lines, key=lambda l: l.y0)
        blocks: list[list[Line]] = []
        for l in ls:
            if blocks and l.y0 - blocks[-1][-1].y1 < l.size * 1.6 and abs(l.size - blocks[-1][-1].size) < 2:
                blocks[-1].append(l)
            else:
                blocks.append([l])
        if blocks and len(blocks[0]) >= 2 and len(blocks[0][0].text.split()) <= 3 and blocks[0][0].y0 < p.h * 0.4:
            b0 = blocks[0]
            t.back.author_label = b0[0].text
            t.back.author_label_style = TextStyle(family=b0[0].family, weight=b0[0].weight, size=b0[0].size, color=b0[0].color)
            nm = max(b0[1:], key=lambda l: l.weight)
            t.back.author_name_style = TextStyle(family=nm.family, weight=nm.weight, size=nm.size, color=nm.color,
                                                 leading=round(b0[2].baseline - b0[1].baseline, 2) if len(b0) > 2 else nm.size * 1.3)
            det = [l for l in b0[1:] if l is not nm] or [nm]
            t.back.author_detail_style = TextStyle(family=det[0].family, weight=det[0].weight, size=det[0].size, color=det[0].color,
                                                   leading=t.back.author_name_style.leading)
            t.back.author_pos = [b0[0].x0, b0[0].y0]
        small = [l for l in ls if l.size < body.size + 0.5 and l.y0 > p.h * 0.5]
        if small:
            paras: list[list[Line]] = []
            for l in small:
                if paras and l.y0 - paras[-1][-1].y1 < l.size * 0.9:
                    paras[-1].append(l)
                else:
                    paras.append([l])
            from backend.papers.readers.pdf import _join_lines

            t.back.boilerplate = [_join_lines([x.text for x in para]) for para in paras]
            st = _style(small)
            st.space_after = _para_space(small, st)
            t.back.boilerplate_style = st
            t.back.boilerplate_box = [min(l.x0 for l in small), min(l.y0 for l in small), max(l.x1 for l in small), max(l.y1 for l in small)]
    # photos -> image style
    photos = []
    for i, P in enumerate(parts):
        if P.photo:
            b = P.photo.box
            reg = pages[i].pix[int(b[1]):int(b[3]), int(b[0]):int(b[2])]
            if reg.size:
                photos.append(reg[::2, ::2])
    t.image_style = image_style(photos)
    missing = [k for k in ("cover", "intro", "body", "image", "conclusion", "back") if k not in t.pages]
    if missing:
        t.notes.append("Page designs not present in the reference (they fall back to the text page design): " + ", ".join(missing))
    return t
