"""Compose a brand document (PDF) from document content and a learned template.

Page sequence (each page design comes from the reference):
    cover -> intro (opening section in the card, next section below it) -> text pages, with image pages
    where the document's sections get a generated image -> conclusion card -> back cover

Text flows through two-column pages with ReportLab paragraphs. Colours that depend on the page (text,
headings, rules on dark vs light pages) are drawn with sentinel colours that are mapped to the page's
measured colours while that page is drawn, so a paragraph can flow from a dark page onto a light one.
"""
from __future__ import annotations

import html
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfgen import textobject
from reportlab.platypus import Flowable, Image, Paragraph, Table, TableStyle

from backend.branddocs.content import DocContent, DocSection
from backend.branddocs.fonts import FontSet
from backend.branddocs.model import DocTemplate, PageDesign, Shape, TextStyle
from backend.papers.model import Block, Inline

# ------------------------------------------------------------------ page-dependent colours
SENT = {"text": "#010203", "head": "#010204", "rule": "#010205"}
_tl = threading.local()
_orig_fill = textobject._PDFColorSetter.setFillColor
_orig_stroke = textobject._PDFColorSetter.setStrokeColor


def _key(c) -> str:
    try:
        return colors.toColor(c).hexval().lower()
    except Exception:
        return ""


def _mapped(c):
    m = getattr(_tl, "map", None)
    if m:
        k = _key(c)
        if k in m:
            return m[k]
    return c


def _set_fill(self, aColor, alpha=None):
    return _orig_fill(self, _mapped(aColor), alpha)


def _set_stroke(self, aColor, alpha=None):
    return _orig_stroke(self, _mapped(aColor), alpha)


textobject._PDFColorSetter.setFillColor = _set_fill
textobject._PDFColorSetter.setStrokeColor = _set_stroke


def _page_colours(d: PageDesign) -> dict:
    return {"0x" + SENT["text"][1:]: colors.HexColor(d.text_color), "0x" + SENT["head"][1:]: colors.HexColor(d.heading_color),
            "0x" + SENT["rule"][1:]: colors.HexColor(d.rule_color or d.text_color)}


def _hex(h: str, default="#000000"):
    return colors.HexColor(h or default)


# ------------------------------------------------------------------ flowables
class Dash(Flowable):
    def __init__(self, w, h, color, space_before=0.0, space_after=0.0):
        super().__init__()
        self.dw, self.dh, self.color = w, h, color
        self.spaceBefore, self.spaceAfter = space_before, space_after

    def wrap(self, aw, ah):
        return self.dw, self.dh

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.dw, self.dh, stroke=0, fill=1)


class HeadingBlock(Flowable):
    """Heading paragraph with the brand dash under its last line (kept with the following text)."""
    keep_next = True

    def __init__(self, para: Paragraph, dash: Optional[dict], dash_color, space_after: float):
        super().__init__()
        self.para, self.dash, self.dash_color = para, dash, dash_color
        self.spaceAfter = space_after
        self.spaceBefore = 0

    def wrap(self, aw, ah):
        self.pw, self.ph = self.para.wrap(aw, 10 ** 6)
        st = self.para.style
        n = max(1, len(getattr(self.para, "blPara").lines))
        self.last_base = st.fontSize + (n - 1) * st.leading  # from the top
        extra = (self.dash["gap"] + self.dash["h"] - (self.ph - self.last_base)) if self.dash else 0
        self.height = self.ph + max(0, extra)
        self.width = aw
        return aw, self.height

    def split(self, aw, ah):
        return []

    def draw(self):
        self.para.drawOn(self.canv, 0, self.height - self.ph)
        if self.dash:
            y = self.height - self.last_base - self.dash["gap"] - self.dash["h"]
            self.canv.setFillColor(self.dash_color)
            self.canv.rect(0, y, self.dash["w"], self.dash["h"], stroke=0, fill=1)


class SectionRule(Flowable):
    """Thin rule between two sections in the same column (dropped at the top of a column)."""

    def __init__(self, width: float, space_before: float, space_after: float):
        super().__init__()
        self.lw = width
        self.spaceBefore, self.spaceAfter = space_before, space_after

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.lw

    def draw(self):
        self.canv.setStrokeColor(_hex(SENT["rule"]))
        self.canv.setLineWidth(self.lw)
        self.canv.line(0, 0, self.width, 0)


class ListItem(Flowable):
    def __init__(self, para: Paragraph, indent: float, bullet_size: float, number: str = "", show=True):
        super().__init__()
        self.para, self.indent, self.bs, self.number, self.show = para, indent, bullet_size, number, show
        self.spaceBefore = 0
        self.spaceAfter = para.style.spaceAfter

    def wrap(self, aw, ah):
        self.aw = aw
        w, self.ph = self.para.wrap(aw - self.indent, ah)
        return aw, self.ph

    def split(self, aw, ah):
        parts = self.para.split(aw - self.indent, ah)
        if len(parts) < 2:
            return []
        return [ListItem(parts[0], self.indent, self.bs, self.number, self.show),
                ListItem(parts[1], self.indent, self.bs, self.number, False)]

    def draw(self):
        st = self.para.style
        base = self.ph - st.fontSize
        if self.show:
            if self.number:
                self.canv.setFont(st.fontName, st.fontSize)
                self.canv.setFillColor(st.textColor)
                self.canv.drawString(0, base, self.number)
            else:
                self.canv.setFillColor(st.textColor)
                r = self.bs / 2
                self.canv.circle(r, base + st.fontSize * 0.33, r, stroke=0, fill=1)
        self.para.drawOn(self.canv, self.indent, 0)


class Figure(Flowable):
    def __init__(self, path: Path, caption: Optional[Paragraph], max_h: float):
        super().__init__()
        self.path, self.caption, self.max_h = path, caption, max_h
        with PILImage.open(path) as im:
            self.iw, self.ih = im.size
        self.spaceBefore, self.spaceAfter = 6, 12

    def wrap(self, aw, ah):
        w = aw
        h = w * self.ih / self.iw
        if h > self.max_h:
            h = self.max_h
            w = h * self.iw / self.ih
        ch = self.caption.wrap(aw, 10 ** 6)[1] + 4 if self.caption else 0
        if h + ch > ah and ah > 0.45 * (h + ch) and ah - ch > 60:  # shrink a little rather than leave a gap
            h = ah - ch
            w = h * self.iw / self.ih
        self.dw, self.dh, self.ch, self.aw = w, h, ch, aw
        return aw, h + ch

    def split(self, aw, ah):
        return []

    def draw(self):
        self.canv.drawImage(str(self.path), (self.aw - self.dw) / 2, self.ch, self.dw, self.dh, preserveAspectRatio=True, mask="auto")
        if self.caption:
            self.caption.drawOn(self.canv, 0, 0)


class Marker(Flowable):
    """Zero-size marker: an image page may start here (section with a generated image)."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        pass


# ------------------------------------------------------------------ layout engine
@dataclass
class Placed:
    f: Flowable
    x: float
    top: float  # y from the top of the page
    w: float
    h: float


def fill(story: list, cols: list[tuple[float, float]], top: float, bottom: float, seen: Optional[list] = None,
         allow_stop: bool = True) -> tuple[list[Placed], list, list[float]]:
    """Place flowables into columns (top-origin coordinates). Returns placed items, the rest, column bottoms."""
    placed: list[Placed] = []
    bottoms: list[float] = []
    story = list(story)
    for ci, (x0, x1) in enumerate(cols):
        w = x1 - x0
        y = top
        first = True
        while story:
            f = story[0]
            if isinstance(f, Marker):
                if seen is not None:
                    # a section with an image: start it on the image page when less than half this page is left
                    left = (bottom - y) + (bottom - top) * (len(cols) - ci - 1)
                    if placed and allow_stop and left < 0.5 * (bottom - top) * len(cols):
                        bottoms.append(y)
                        return placed, story, bottoms + [top] * (len(cols) - len(bottoms))
                    seen.append(f.key)
                story.pop(0)
                continue
            if first and isinstance(f, SectionRule):
                story.pop(0)
                continue
            sb = 0 if first else f.getSpaceBefore()
            avail = bottom - y - sb
            if avail <= 4:
                break
            fw, fh = f.wrap(w, avail)
            need = fh
            if getattr(f, "keep_next", False) and len(story) > 1:
                nxt = story[1]
                nh = nxt.wrap(w, 10 ** 6)[1]
                lead = getattr(getattr(nxt, "style", None), "leading", 0) or getattr(getattr(getattr(nxt, "para", None), "style", None), "leading", 14)
                need += f.getSpaceAfter() + min(nh, lead * 3)
            if need <= avail + 0.01:
                placed.append(Placed(f, x0, y + sb, w, fh))
                y += sb + fh + f.getSpaceAfter()
                story.pop(0)
                first = False
                continue
            if getattr(f, "keep_next", False) and not first:
                break
            parts = f.split(w, avail) if avail > 20 else []
            if len(parts) >= 2:
                p0 = parts[0]
                h0 = p0.wrap(w, avail)[1]
                placed.append(Placed(p0, x0, y + sb, w, h0))
                y += sb + h0
                story[0:1] = parts[1:]
                break
            if first:  # does not fit even an empty column: place it anyway (never loop forever)
                placed.append(Placed(f, x0, y, w, min(fh, bottom - y)))
                y += fh
                story.pop(0)
                first = False
                continue
            break
        bottoms.append(y)
    return placed, story, bottoms


def balanced(story: list, cols: list[tuple[float, float]], top: float, max_bottom: float) -> tuple[list[Placed], list, list[float]]:
    """Fill the columns with the smallest height that takes the whole story (or all of max height)."""
    placed, rest, bottoms = fill(story, cols, top, max_bottom)
    if rest or len(cols) == 1:
        return placed, rest, bottoms
    lo, hi = 0.0, max_bottom - top
    best = (placed, rest, bottoms)
    for _ in range(14):
        mid = (lo + hi) / 2
        p, r, b = fill(story, cols, top, top + mid)
        if r:
            lo = mid
        else:
            hi = mid
            best = (p, r, b)
    return best


# ------------------------------------------------------------------ composer
@dataclass
class Composer:
    tpl: DocTemplate
    fonts: FontSet
    doc: DocContent
    images: dict  # key -> Path ("cover", "sec-<i>")
    label: str = ""
    year: int = field(default_factory=lambda: date.today().year)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        t = self.tpl
        self.W, self.H = t.page_w, t.page_h
        self.page_no = 0
        self.body_st = t.styles.get("body") or TextStyle(size=10, leading=14)
        self.h1_st = t.styles.get("h1") or TextStyle(size=22, weight=500, leading=26)
        self.dash = t.dash or None
        self.accent = _hex(t.accent or "#000000")
        self._families()
        self.st = self._styles()

    # ---------------- fonts and styles
    def _font(self, weight: int, italic=False) -> str:
        return self.fonts.get(weight, italic)

    def _families(self):
        done = set()
        for w in {self.body_st.weight, self.h1_st.weight, 400, 500}:
            n = self._font(w)
            if n in done or n.startswith("Helvetica"):
                continue
            done.add(n)
            b = self._font(max(500, w + 200))
            registerFontFamily(n, normal=n, bold=b, italic=self._font(w, True), boldItalic=self._font(max(500, w + 200), True))

    def _ps(self, name, st: TextStyle, color, **kw) -> ParagraphStyle:
        lead = st.leading or st.size * 1.25
        return ParagraphStyle(name, fontName=self._font(st.weight), fontSize=st.size, leading=lead, textColor=color,
                              alignment=TA_LEFT, spaceAfter=kw.pop("spaceAfter", st.space_after), **kw)

    def _styles(self) -> dict:
        b, h = self.body_st, self.h1_st
        text, head = _hex(SENT["text"]), _hex(SENT["head"])
        st = {"body": self._ps("body", b, text), "h1": self._ps("h1", h, head, spaceAfter=0)}
        h2 = TextStyle(family=h.family, weight=h.weight, size=round(max(b.size * 1.35, h.size * 0.6), 1))
        h2.leading = round(h2.size * 1.2, 1)
        st["h2"] = self._ps("h2", h2, head, spaceAfter=b.space_after * 0.5)
        h3 = TextStyle(family=h.family, weight=max(500, b.weight), size=b.size + 1)
        h3.leading = round(h3.size * 1.3, 1)
        st["h3"] = self._ps("h3", h3, head, spaceAfter=b.space_after * 0.3)
        small = TextStyle(family=b.family, weight=b.weight, size=round(b.size * 0.82, 2), leading=round(b.leading * 0.82, 2))
        st["caption"] = self._ps("caption", small, text, spaceAfter=0)
        st["refs"] = self._ps("refs", small, text, spaceAfter=small.size * 0.5)
        st["cell"] = self._ps("cell", small, text, spaceAfter=0)
        st["list"] = self._ps("list", b, text, spaceAfter=max(2.0, b.space_after * 0.25))
        return st

    def recolor(self, style: ParagraphStyle, color) -> ParagraphStyle:
        return ParagraphStyle(style.name + "_c", parent=style, textColor=color)

    # ---------------- markup
    def markup(self, runs: list[Inline], label_ok=True) -> str:
        out = []
        lab = self.tpl.styles.get("label")
        bp = self.body_st.size
        for k, r in enumerate(runs):
            if r.img:
                p = self.doc.base_dir / r.img
                if p.exists():
                    h = min(r.img_h, bp * 1.9)
                    w = r.img_w * h / r.img_h if r.img_h else h
                    out.append(f'<img src="{p.as_posix()}" width="{w:.1f}" height="{h:.1f}" valign="{-h * 0.28:.1f}"/>')
                continue
            t = html.escape(r.t, quote=False)
            if not t:
                continue
            if r.sup:
                t = f'<super rise="{bp * 0.35:.1f}" size="{bp * 0.7:.1f}">{t}</super>'
            if r.sub:
                t = f'<sub rise="{bp * 0.2:.1f}" size="{bp * 0.7:.1f}">{t}</sub>'
            if r.i:
                t = f"<i>{t}</i>"
            if r.b:
                # a run-in label ("Clarity: what matters") prints in the reference's label colour
                if label_ok and lab and k == 0 and r.t.strip().endswith(":") and len(r.t.split()) <= 4 and len(runs) > 1:
                    t = f'<font name="{self._font(lab.weight)}" color="{lab.color}">{t}</font>'
                else:
                    t = f"<b>{t}</b>"
            out.append(t)
        return "".join(out).strip() or "&nbsp;"

    # ---------------- story
    def heading(self, title: str, level: int, style_over: Optional[ParagraphStyle] = None, dash_color=None) -> Flowable:
        if level <= 1:
            st = style_over or self.st["h1"]
            sa = (self.dash or {}).get("after", 14) - self.body_st.size * 0.25
            return HeadingBlock(Paragraph(html.escape(title), st), self.dash, dash_color or self.accent, max(6, sa))
        st = self.st["h2" if level == 2 else "h3"]
        if style_over is not None:
            st = self.recolor(st, style_over.textColor)
        hb = HeadingBlock(Paragraph(html.escape(title), st), None, None, st.spaceAfter)
        return hb

    def blocks(self, blocks: list[Block], col_w: float, body: Optional[ParagraphStyle] = None, kind="body") -> list[Flowable]:
        out: list[Flowable] = []
        body = body or (self.st["refs"] if kind == "references" else self.st["body"])
        lst = self.recolor(self.st["list"], body.textColor) if body is not self.st["body"] else self.st["list"]
        if kind == "references":
            lst = body
        bul = self._bullet()
        for b in blocks:
            if b.kind in ("para", "quote", "code"):
                st = body if b.kind != "code" else ParagraphStyle("code", parent=body, fontName="Courier", fontSize=body.fontSize * 0.9)
                out.append(Paragraph(self.markup(b.runs), st))
            elif b.kind == "list":
                for n, it in enumerate(b.items):
                    num = f"{n + 1}." if b.ordered else ""
                    out.append(ListItem(Paragraph(self.markup(it), ParagraphStyle("li", parent=lst, spaceAfter=lst.spaceAfter)),
                                        bul["indent"], bul["size"], num))
                if out and isinstance(out[-1], ListItem):
                    out[-1].spaceAfter = body.spaceAfter
            elif b.kind in ("figure", "equation") and b.image:
                p = self.doc.base_dir / b.image
                if p.exists():
                    cap = Paragraph(self.markup(b.caption), self.st["caption"]) if b.caption else None
                    out.append(Figure(p, cap, self.H * (0.42 if b.kind == "figure" else 0.12)))
            elif b.kind == "equation":
                out.append(Paragraph(f"<i>{html.escape(b.latex or ''.join(r.t for r in b.runs))}</i>", body))
            elif b.kind == "table":
                tf = self.table(b, col_w)
                if tf is not None:
                    if b.caption:
                        out.append(Paragraph(self.markup(b.caption), self.st["caption"]))
                    out.append(tf)
                elif b.image and (self.doc.base_dir / b.image).exists():
                    cap = Paragraph(self.markup(b.caption), self.st["caption"]) if b.caption else None
                    out.append(Figure(self.doc.base_dir / b.image, cap, self.H * 0.5))
        return out

    def _bullet(self) -> dict:
        for k in ("body", "intro", "image"):
            d = self.tpl.pages.get(k)
            if d and d.bullet:
                return {"indent": d.bullet["indent"], "size": d.bullet["size"]}
        return {"indent": self.body_st.size * 1.6, "size": self.body_st.size * 0.45}

    def table(self, b: Block, col_w: float) -> Optional[Table]:
        rows = [r for r in b.rows if any(c.strip() for c in r)]
        if not rows:
            return None
        n = max(len(r) for r in rows)
        cell, head = self.st["cell"], ParagraphStyle("cellh", parent=self.st["cell"], fontName=self._font(500))
        data = [[Paragraph(html.escape(c), head if i == 0 else cell) for c in r + [""] * (n - len(r))] for i, r in enumerate(rows)]
        lens = [max(4, max(len(r[j]) if j < len(r) else 0 for r in rows)) for j in range(n)]
        tot = sum(min(x, 40) for x in lens)
        widths = [col_w * min(x, 40) / tot for x in lens]
        t = Table(data, colWidths=widths, repeatRows=1)
        rule = _hex(SENT["rule"])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
                               ("LINEBELOW", (0, 1), (-1, -1), 0.25, rule), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        t.spaceBefore, t.spaceAfter = 4, self.body_st.space_after
        return t

    def section_story(self, s: DocSection, col_w: float, first: bool) -> list[Flowable]:
        out: list[Flowable] = []
        if s.title:
            if not first and s.level <= 1:
                out.append(SectionRule(self.tpl.pages.get("body", PageDesign(kind="body", source_page=0)).rule_width or 0.25, 22, 34))
            out.append(self.heading(s.title, s.level))
        out += self.blocks(s.blocks, col_w, kind=s.kind)
        return out

    # ---------------- drawing helpers
    def Y(self, y: float) -> float:
        return self.H - y

    def shape(self, c, s: Shape):
        p = c.beginPath()
        cur = None
        for it in s.items:
            if it[0] == "re":
                x0, y0, x1, y1 = it[1:5]
                p.rect(x0, self.Y(y1), x1 - x0, y1 - y0)
                cur = None
                continue
            x, y = it[1], it[2]
            if cur is None or abs(cur[0] - x) > 0.01 or abs(cur[1] - y) > 0.01:
                p.moveTo(x, self.Y(y))
            if it[0] == "l":
                p.lineTo(it[3], self.Y(it[4]))
                cur = (it[3], it[4])
            else:
                p.curveTo(it[3], self.Y(it[4]), it[5], self.Y(it[6]), it[7], self.Y(it[8]))
                cur = (it[7], it[8])
        if s.fill:
            p.close()
        c.saveState()
        if s.fill:
            c.setFillColor(_hex(s.fill))
            if s.fill_opacity < 1:
                c.setFillAlpha(s.fill_opacity)
        if s.stroke:
            c.setStrokeColor(_hex(s.stroke))
            c.setLineWidth(s.width or 0.5)
        c.drawPath(p, fill=1 if s.fill else 0, stroke=1 if s.stroke else 0, fillMode=1 if s.even_odd else 0)
        c.restoreState()

    def paint(self, c, d: PageDesign, art=True):
        c.setFillColor(_hex(d.background))
        c.rect(0, 0, self.W, self.H, stroke=0, fill=1)
        for s in d.decorations:
            self.shape(c, s)
        if art:
            for a in d.artwork:
                for s in a.shapes:
                    self.shape(c, s)

    def photo(self, c, d: PageDesign, path: Path, box: list[float], fade_from=0.0, fade_to=0.0, shade_from=0.0, shade_to=0.0):
        """Image in a box (cover-fit) fading into the page colour at the bottom, like the reference."""
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        im = PILImage.open(path).convert("RGB")
        scale = max(bw / im.width, bh / im.height)
        nw, nh = int(im.width * scale * 2), int(im.height * scale * 2)  # 144 dpi
        im = im.resize((nw, nh), PILImage.LANCZOS)
        cx, cy = (nw - int(bw * 2)) // 2, int((nh - int(bh * 2)) * 0.35)
        im = im.crop((cx, cy, cx + int(bw * 2), cy + int(bh * 2)))
        if fade_to > fade_from > 0:
            import numpy as np

            a = np.asarray(im).astype(float)
            bg = np.array([int(d.background[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
            ys = (np.arange(a.shape[0]) / 2 + y0)
            t = np.clip((ys - fade_from) / max(1, fade_to - fade_from), 0, 1)[:, None, None]
            t = t * t * (3 - 2 * t)
            a = a * (1 - t) + bg * t
            im = PILImage.fromarray(a.astype("uint8"))
        if shade_to > shade_from > 0:
            # behind overlaid text (the cover title) the image is darkened just enough to be as dark as the
            # reference image is there (mean luminance about 0.2), fading in from above the text
            import numpy as np

            a = np.asarray(im).astype(float)
            bg = np.array([int(d.background[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
            ys = np.arange(a.shape[0]) / 2 + y0
            band = a[int((shade_to - y0) * 2):int((shade_to + 170 - y0) * 2)]  # where the text sits
            lum = float(np.percentile(band @ np.array([0.2126, 0.7152, 0.0722]), 90) / 255) if band.size else 0.0
            alpha = min(0.88, max(0.0, 1 - 0.3 / lum)) if lum > 0.3 else 0.0  # bright parts at most ~0.3
            if alpha > 0:
                t = np.clip((ys - shade_from) / max(1, shade_to - shade_from), 0, 1)[:, None, None]
                t = (t * t * (3 - 2 * t)) * alpha
                a = a * (1 - t) + bg * t
                im = PILImage.fromarray(a.astype("uint8"))
        tmp = path.with_name(path.stem + f"_p{self.page_no}.jpg")
        im.save(tmp, quality=90)
        c.drawImage(str(tmp), x0, self.Y(y1), bw, bh)

    def draw_placed(self, c, placed: list[Placed], d: Optional[PageDesign]):
        _tl.map = _page_colours(d) if d else None
        try:
            for p in placed:
                p.f.wrapOn(c, p.w, max(p.h, 1))
                p.f.drawOn(c, p.x, self.Y(p.top + p.h))
        finally:
            _tl.map = None

    def footer(self, c, d: PageDesign):
        f = d.footer or next((x.footer for x in self.tpl.pages.values() if x.footer), None)
        if not f or not f.pattern:
            return
        txt = f.pattern.replace("{year}", str(self.year)).replace("{page}", str(self.page_no))
        c.setFont(self._font(f.style.weight), f.style.size)
        col = f.style.color if d.footer else d.text_color
        c.setFillColor(_hex(col))
        y = self.Y(f.baseline)
        if f.align == "right":
            c.drawRightString(f.x1, y, txt)
        elif f.align == "center":
            c.drawCentredString(f.x1, y, txt)
        else:
            c.drawString(f.x1, y, txt)

    def hline(self, c, y, x0, x1, color, width):
        c.setStrokeColor(_hex(color))
        c.setLineWidth(width)
        c.line(x0, self.Y(y), x1, self.Y(y))

    def vline(self, c, x, y0, y1, color, width):
        c.setStrokeColor(_hex(color))
        c.setLineWidth(width)
        c.line(x, self.Y(y0), x, self.Y(y1))

    def new_page(self, c):
        if self.page_no:
            c.showPage()
        self.page_no += 1

    # ---------------- pages
    def cover(self, c):
        d = self.tpl.pages.get("cover")
        self.new_page(c)
        if not d:
            return
        c.setFillColor(_hex(d.background))
        c.rect(0, 0, self.W, self.H, stroke=0, fill=1)
        img = self.images.get("cover")
        if img:
            top = self.tpl.cover.title_box[1] if self.tpl.cover.title_box else self.H * 0.55
            self.photo(c, d, Path(img), [0, 0, self.W, self.H], shade_from=max(1.0, top - 170), shade_to=top - 20)
            self.used_images.add("cover")
        for a in d.artwork:
            for s in a.shapes:
                self.shape(c, s)
        cv = self.tpl.cover
        if cv.title_box:
            x0, ytop, x1, ybot = cv.title_box
            size, lead = cv.title.size, cv.title.leading or cv.title.size * 1.05
            for _ in range(8):
                st = ParagraphStyle("ct", fontName=self._font(cv.title.weight), fontSize=size, leading=lead, textColor=_hex(cv.title.color))
                p = Paragraph(html.escape(self.doc.title), st)
                w, h = p.wrap(x1 - x0, 10 ** 6)
                if len(p.blPara.lines) <= 4 or size < cv.title.size * 0.55:
                    break
                size *= 0.88
                lead *= 0.88
            p.drawOn(c, x0, self.Y(ybot + (lead - size) * 0.3))
        label = self.label if self.label is not None else cv.label_text
        if label and cv.label_pos:
            if cv.marker:
                for s in cv.marker.shapes:
                    self.shape(c, s)
            c.setFont(self._font(cv.label.weight), cv.label.size)
            c.setFillColor(_hex(cv.label.color))
            c.drawString(cv.label_pos[0], self.Y(cv.label_pos[1] + cv.label.size * 0.95), label)

    def card_page(self, c, d: PageDesign, sec: DocSection, conclusion=False) -> tuple[list, float]:
        """Draw the card holding a section. Returns (story that did not fit, y of the card bottom)."""
        cd = d.card
        x0, y0, x1, y1 = cd.box
        tc = _hex(cd.text_color)
        h1 = self.recolor(self.st["h1"], tc)
        inner_x0, inner_x1 = x0 + cd.pad_x, x1 - cd.pad_x
        mid = (x0 + x1) / 2
        gut = max(14.0, (self.tpl.pages.get(d.kind).columns[1][0] - d.divider["x"]) if (d.divider and len(d.columns) > 1) else 20.0)
        cols = [(inner_x0, mid - gut), (mid + gut, inner_x1)]
        top = y0 + cd.pad_top - (h1.fontSize * 0.22)
        head = [self.heading(sec.title, 1, h1, _hex(cd.dash_color or self.tpl.accent))] if sec.title else []
        placed_h: list[Placed] = []
        if head:
            ph, _, b = fill(head, [(inner_x0, inner_x1)], top, y1)
            placed_h, top = ph, b[0] + head[0].getSpaceAfter()
        if conclusion:
            em = self.tpl.styles.get("emphasis") or self.body_st
            size = em.size
            story = []
            for _ in range(6):
                st = ParagraphStyle("em", fontName=self._font(em.weight), fontSize=size, leading=(em.leading or em.size * 1.25) * size / em.size,
                                    textColor=tc, spaceAfter=0)
                story = []
                for k, b in enumerate(sec.blocks):
                    if k:
                        story.append(SectionRule(cd.divider_width if cd.separator_rules else 0.01, size * 1.3, size * 1.3))
                    story += self.blocks([b], cols[0][1] - cols[0][0], st)
                p, rest, bot = balanced(story, cols, top, y1 - cd.pad_bottom)
                if not rest or size <= self.body_st.size:
                    break
                size -= 0.5
        else:
            body = self.recolor(self.st["body"], tc)
            story = self.blocks(sec.blocks, cols[0][1] - cols[0][0], body)
            p, rest, bot = balanced(story, cols, top, y1 - cd.pad_bottom)
            if rest and d.content_bottom > y1:  # a little longer than the reference card: let the card grow
                p, rest, bot = balanced(story, cols, top, y1 - cd.pad_bottom + 0.35 * (d.content_bottom - y1))
        bottom = (max(bot) if p else top) + cd.pad_bottom
        if conclusion:  # the closing card keeps a generous size, but shrinks around a short conclusion
            bottom = max(bottom, y0 + 0.55 * (y1 - y0))
        c.setFillColor(_hex(cd.color))
        c.roundRect(x0, self.Y(bottom), x1 - x0, bottom - y0, cd.radius, stroke=0, fill=1)
        if cd.divider_color and p and len({q.x for q in p}) > 1:
            self.vline(c, mid, top, max(bot), cd.divider_color, cd.divider_width)
        mapping = {"0x" + SENT["rule"][1:]: _hex(cd.divider_color or cd.text_color), "0x" + SENT["text"][1:]: tc,
                   "0x" + SENT["head"][1:]: tc}
        _tl.map = mapping
        try:
            for q in placed_h + p:
                q.f.wrapOn(c, q.w, max(q.h, 1))
                q.f.drawOn(c, q.x, self.Y(q.top + q.h))
        finally:
            _tl.map = None
        return rest, bottom

    def intro(self, c, sections: list[DocSection]) -> list[DocSection]:
        d = self.tpl.pages.get("intro")
        if not d or not d.card or not sections:
            return sections
        self.new_page(c)
        self.paint(c, d)
        sec = sections[0]
        rest, card_bottom = self.card_page(c, d, sec)
        remaining = list(sections[1:])
        cols = [tuple(x) for x in d.columns] or [(36, self.W - 36)]
        gap = max(24.0, d.content_top - d.card.box[3]) if d.content_top > d.card.box[3] else 40.0
        top = card_bottom + gap
        bottom = d.content_bottom or (self.H - 80)
        story = list(rest)
        if story:  # the end of the opening section, below its card
            p, story, bots = balanced(story, cols, top, bottom)
            self.draw_placed(c, p, d)
            if d.divider and p and len({q.x for q in p}) > 1:
                self.vline(c, d.divider["x"], top, max(bots), d.divider["color"], d.divider["width"])
            top = (max(bots) if p else top) + gap * 0.8
        if not story and remaining:
            nxt = remaining.pop(0)
            col_w = cols[0][1] - cols[0][0]
            head = [self.heading(nxt.title, 1)] if nxt.title else []
            if head and bottom - top > 150:
                ph, _, b = fill(head, [(cols[0][0], cols[-1][1])], top, bottom)
                self.draw_placed(c, ph, d)
                top = b[0] + head[0].getSpaceAfter()
                story = self.blocks(nxt.blocks, col_w, kind=nxt.kind)
            else:
                remaining.insert(0, nxt)
        if story and bottom - top > 60:
            p, story, bots = balanced(story, cols, top, bottom)
            self.draw_placed(c, p, d)
            if d.divider and p and len({q.x for q in p}) > 1:
                self.vline(c, d.divider["x"], top, max(bots), d.divider["color"], d.divider["width"])
        if d.bottom_rule:
            self.hline(c, d.bottom_rule, cols[0][0], cols[-1][1], d.rule_color or d.text_color, d.rule_width)
        self.footer(c, d)
        self._carry = story
        return remaining

    def flow(self, c, story: list, image_keys: set[str]):
        body = self.tpl.pages.get("body") or self.tpl.pages.get("intro")
        img_d = self.tpl.pages.get("image")
        pending: Optional[str] = None
        last_image = False
        guard = 0
        while story and guard < 400:
            guard += 1
            while story and isinstance(story[0], Marker):
                if story[0].key in image_keys and img_d:
                    pending = story[0].key
                story.pop(0)
            if not story:
                break
            # never two image pages in a row: a waiting image goes on the page after the next text page
            use_img = pending is not None and img_d is not None and pending in self.images and not last_image
            last_image = use_img
            d = img_d if use_img else body
            self.new_page(c)
            self.paint(c, d)
            if use_img and d.photo:
                ph = d.photo
                self.photo(c, d, Path(self.images[pending]), ph.box, ph.fade_from, ph.fade_to)
                self.used_images.add(pending)
                if d.top_rule:
                    self.hline(c, d.top_rule, d.columns[0][0], d.columns[-1][1], d.rule_color or d.text_color, d.rule_width)
                pending = None
            cols = [tuple(x) for x in d.columns] or [(36, self.W - 36)]
            top = d.content_top or 72
            bottom = d.content_bottom or (self.H - 72)
            seen: list[str] = []
            placed, story, bots = fill(story, cols, top, bottom, seen, allow_stop=not use_img)
            # a section with an image started on this page: the next page is its image page
            for k in seen:
                if k in image_keys and img_d is not None:
                    pending = k
            self.draw_placed(c, placed, d)
            if d.divider and placed and len({p.x for p in placed}) > 1:
                y1 = max(p.top + p.h for p in placed)
                self.vline(c, d.divider["x"], max(top, d.divider.get("y0", top)) if d.kind == "image" else top, max(y1, top + 40),
                           d.divider["color"], d.divider["width"])
            if d.bottom_rule:
                self.hline(c, d.bottom_rule, cols[0][0], cols[-1][1], d.rule_color or d.text_color, d.rule_width)
            self.footer(c, d)

    def conclusion(self, c) -> bool:
        d = self.tpl.pages.get("conclusion")
        sec = self.doc.conclusion
        if not d or not d.card or not sec:
            return False
        self.new_page(c)
        self.paint(c, d)
        rest, _ = self.card_page(c, d, sec, conclusion=True)
        if rest:
            self.notes.append("The conclusion was longer than the closing card; its last part continues on the next page.")
            self._overflow = rest
        if d.bottom_rule:
            self.hline(c, d.bottom_rule, 36, self.W - 36, d.rule_color or "#FFFFFF", d.rule_width)
        self.footer(c, d)
        return True

    def back(self, c, authors: list):
        d = self.tpl.pages.get("back")
        if not d:
            return
        self.new_page(c)
        self.paint(c, d)
        bk = self.tpl.back
        if authors and bk.author_pos:
            x, y = bk.author_pos
            st = bk.author_label_style
            c.setFillColor(_hex(st.color))
            c.setFont(self._font(st.weight), st.size)
            y += st.size
            c.drawString(x, self.Y(y), bk.author_label or "Authored by")
            lead = bk.author_name_style.leading or bk.author_name_style.size * 1.3
            y += lead * 1.6
            for a in authors:
                for k, txt in enumerate([a.name] + list(a.detail) + ([a.email] if a.email else [])):
                    s = bk.author_name_style if k == 0 else bk.author_detail_style
                    c.setFillColor(_hex(s.color))
                    c.setFont(self._font(s.weight), s.size)
                    c.drawString(x, self.Y(y), txt[:90])
                    y += lead
                y += lead * 0.8
        if bk.boilerplate and bk.boilerplate_box:
            st = bk.boilerplate_style
            ps = ParagraphStyle("bp", fontName=self._font(st.weight), fontSize=st.size, leading=st.leading or st.size * 1.4,
                                textColor=_hex(st.color), spaceAfter=st.space_after or st.size)
            x0, y0, x1, _ = bk.boilerplate_box
            y = y0
            for t in bk.boilerplate:
                p = Paragraph(html.escape(t), ps)
                w, h = p.wrap(x1 - x0 + 2, 10 ** 6)
                p.drawOn(c, x0, self.Y(y + h))
                y += h + ps.spaceAfter

    # ---------------- build
    def build(self, out: Path, image_sections: dict[int, str]) -> dict:
        c = rl_canvas.Canvas(str(out), pagesize=(self.W, self.H))
        c.setTitle(self.doc.title)
        c.setAuthor(", ".join(a.name for a in self.doc.authors) or "")
        c.setCreator("Zensar Content Studio - brand documents (offline)")
        self._carry: list = []
        self._overflow: list = []
        self.used_images: set[str] = set()
        self.cover(c)
        sections = [s for s in self.doc.sections]
        # the body flow: sections after the intro page; markers where an image page may start
        first_idx = 0
        if self.tpl.pages.get("intro") and self.tpl.pages["intro"].card and sections:
            remaining = self.intro(c, sections)
            first_idx = len(sections) - len(remaining)
            sections = remaining
        body = self.tpl.pages.get("body") or self.tpl.pages.get("intro")
        col_w = (body.columns[0][1] - body.columns[0][0]) if body and body.columns else self.W - 72
        story: list = list(self._carry)
        for k, s in enumerate(sections):
            idx = first_idx + k
            if idx in image_sections:
                story.append(Marker(image_sections[idx]))
            story += self.section_story(s, col_w, first=(k == 0 and not story))
        if self.doc.conclusion and not self.tpl.pages.get("conclusion"):
            story += self.section_story(self.doc.conclusion, col_w, first=not story)
        self.flow(c, story, set(image_sections.values()))
        if self.conclusion(c) and self._overflow:
            self.flow(c, self._overflow, set())
        self.back(c, self.doc.authors)
        c.showPage()
        c.save()
        return {"pages": self.page_no, "notes": self.notes, "used_images": sorted(self.used_images)}
