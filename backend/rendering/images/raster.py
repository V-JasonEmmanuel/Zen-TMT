"""Raster backend (Pillow): Scene -> PNG/JPG. Used for previews, standalone visuals, PDF and video frames."""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from backend.branding.fonts import get_font, text_width_pt
from backend.branding.theme import hex_to_rgb
from backend.rendering.charts import chart_png
from backend.rendering.scene import LINE_HEIGHT, Chart, Line, Para, Picture, Scene, Shape, Table, TextBox, fit_text

SS = 2  # supersampling factor for anti-aliased shapes


class RasterRenderer:
    def __init__(self, width_px: int = 1920):
        self.width_px = width_px

    def render(self, scene: Scene) -> Image.Image:
        s = self.width_px * SS / scene.width  # px per inch at supersampled size
        W, H = round(scene.width * s), round(scene.height * s)
        img = Image.new("RGB", (W, H), hex_to_rgb(scene.background))
        draw = ImageDraw.Draw(img)
        for el in scene.elements:
            if isinstance(el, Shape):
                if el.opacity < 0.999:
                    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    self._shape(ImageDraw.Draw(layer), el, s)
                    alpha = layer.getchannel("A").point(lambda a: int(a * max(0.0, el.opacity)))
                    layer.putalpha(alpha)
                    img.paste(layer, (0, 0), layer)
                    draw = ImageDraw.Draw(img)
                else:
                    self._shape(draw, el, s)
            elif isinstance(el, Line):
                self._line(draw, el, s)
            elif isinstance(el, TextBox):
                self._text(draw, el, s)
            elif isinstance(el, Picture):
                self._picture(img, el, s)
            elif isinstance(el, Table):
                self._table(draw, el, s)
            elif isinstance(el, Chart):
                self._chart(img, el, s)
        return img.resize((self.width_px, round(self.width_px * scene.height / scene.width)), Image.LANCZOS)

    def save(self, scene: Scene, path: Path, fmt: str = "PNG") -> Path:
        img = self.render(scene)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt.upper() in ("JPG", "JPEG"):
            img.save(path, "JPEG", quality=92, optimize=True)
        else:
            img.save(path, "PNG", optimize=True)
        return path

    # -------------------------------------------------------------- elements
    @staticmethod
    def _shape(draw: ImageDraw.ImageDraw, sh: Shape, s: float) -> None:
        x0, y0, x1, y1 = sh.x * s, sh.y * s, (sh.x + sh.w) * s, (sh.y + sh.h) * s
        fill = hex_to_rgb(sh.fill) if sh.fill else None
        outline = hex_to_rgb(sh.line) if sh.line and sh.line_pt else None
        lw = max(1, round(sh.line_pt / 72 * s)) if outline else 0
        if sh.rotation % 360 == 0 and sh.kind in ("rect", "round_rect", "ellipse", "pill"):
            if sh.kind == "rect":
                draw.rectangle((x0, y0, x1, y1), fill=fill, outline=outline, width=lw)
            elif sh.kind in ("round_rect", "pill"):
                r = (y1 - y0) / 2 if sh.kind == "pill" else max(0, sh.radius * s)
                draw.rounded_rectangle((x0, y0, x1, y1), radius=min(r, (x1 - x0) / 2, (y1 - y0) / 2), fill=fill, outline=outline, width=lw)
            else:
                draw.ellipse((x0, y0, x1, y1), fill=fill, outline=outline, width=lw)
        else:
            draw.polygon(shape_polygon(sh, s), fill=fill, outline=outline, width=lw)

    @staticmethod
    def _line(draw, ln: Line, s: float) -> None:
        col = hex_to_rgb(ln.color)
        w = max(1, round(ln.width_pt / 72 * s))
        x1, y1, x2, y2 = ln.x1 * s, ln.y1 * s, ln.x2 * s, ln.y2 * s
        if ln.arrow_end:
            ang = math.atan2(y2 - y1, x2 - x1)
            L = w * 4.5
            x2b, y2b = x2 - L * 0.8 * math.cos(ang), y2 - L * 0.8 * math.sin(ang)
            draw.line((x1, y1, x2b, y2b), fill=col, width=w)
            pts = [(x2, y2), (x2 - L * math.cos(ang - 0.45), y2 - L * math.sin(ang - 0.45)),
                   (x2 - L * math.cos(ang + 0.45), y2 - L * math.sin(ang + 0.45))]
            draw.polygon(pts, fill=col)
        else:
            draw.line((x1, y1, x2, y2), fill=col, width=w)

    @staticmethod
    def _text(draw, tb: TextBox, s: float) -> None:
        if not tb.fitted_size:
            fit_text(tb)
        size = tb.fitted_size
        px = lambda pt: pt / 72 * s  # noqa: E731
        total = tb.content_h * s
        y = tb.y * s
        if tb.valign == "middle":
            y += (tb.h * s - total) / 2
        elif tb.valign == "bottom":
            y += tb.h * s - total
        for i, p in enumerate(tb.paras):
            ps = size * p.size_scale
            bold = p.bold if p.bold is not None else tb.bold
            font = get_font(tb.font, bold, round(px(ps)))
            color = hex_to_rgb(p.color or tb.color)
            indent = px(ps * 1.3) if p.bullet else 0
            lh = px(ps * LINE_HEIGHT)
            asc = px(ps) * 0.93  # baseline offset within the line box
            for j, line in enumerate(p.lines):
                lw = font.getlength(line)
                avail = tb.w * s - indent
                if tb.align == "center":
                    x = tb.x * s + indent + (avail - lw) / 2
                elif tb.align == "right":
                    x = tb.x * s + tb.w * s - lw
                else:
                    x = tb.x * s + indent
                if j == 0 and p.bullet:
                    bfont = get_font(tb.font, True, round(px(ps)))
                    draw.text((tb.x * s, y + asc + (lh - px(ps) * LINE_HEIGHT) / 2), p.bullet, font=bfont,
                              fill=hex_to_rgb(tb.bullet_color or tb.color), anchor="ls")
                draw.text((x, y + asc + (lh - px(ps) * LINE_HEIGHT) / 2), line, font=font, fill=color, anchor="ls")
                y += lh
            if i < len(tb.paras) - 1:
                y += px(ps * p.space_after)

    @staticmethod
    def _picture(img: Image.Image, pic: Picture, s: float) -> None:
        try:
            src = Image.open(pic.path).convert("RGBA")
        except Exception:
            return
        bw, bh = pic.w * s, pic.h * s
        if pic.fit == "cover":  # centre-crop to the box aspect, then scale to fill it exactly
            src = ImageOps.fit(src, (max(1, round(bw)), max(1, round(bh))), Image.LANCZOS)
            img.paste(src, (round(pic.x * s), round(pic.y * s)), src)
            return
        r = min(bw / src.width, bh / src.height)
        nw, nh = max(1, round(src.width * r)), max(1, round(src.height * r))
        src = src.resize((nw, nh), Image.LANCZOS)
        ox, oy = round(pic.x * s + (bw - nw) / 2), round(pic.y * s + (bh - nh) / 2)
        img.paste(src, (ox, oy), src)

    def _table(self, draw, tb: Table, s: float) -> None:
        for cell in table_cells(tb):
            kind, x, y, w, h, fill, box = cell
            if fill:
                draw.rectangle((x * s, y * s, (x + w) * s, (y + h) * s), fill=hex_to_rgb(fill))
            if tb.border:
                draw.line((x * s, (y + h) * s, (x + w) * s, (y + h) * s), fill=hex_to_rgb(tb.border), width=max(1, round(s / 72)))
            self._text(draw, box, s)

    @staticmethod
    def _chart(img: Image.Image, ch: Chart, s: float) -> None:
        png = chart_png(ch, round(ch.w * s), round(ch.h * s))
        chart = Image.open(io.BytesIO(png)).convert("RGBA")
        img.paste(chart, (round(ch.x * s), round(ch.y * s)), chart)


def shape_polygon(sh: Shape, s: float = 1.0) -> list[tuple[float, float]]:
    """Outline polygon for every shape kind (in pixels when s = px/in), rotated about the centre.
    Shared by the raster and SVG backends and by the PPTX freeform builder, so all outputs match."""
    x0, y0, w, h = sh.x * s, sh.y * s, sh.w * s, sh.h * s
    tip = min(h * 0.35, w * 0.25)
    k = sh.kind
    if k == "chevron":
        pts = [(x0, y0), (x0 + w - tip, y0), (x0 + w, y0 + h / 2), (x0 + w - tip, y0 + h), (x0, y0 + h), (x0 + tip, y0 + h / 2)]
    elif k == "pentagon":
        pts = [(x0, y0), (x0 + w - tip, y0), (x0 + w, y0 + h / 2), (x0 + w - tip, y0 + h), (x0, y0 + h)]
    elif k == "triangle":
        pts = [(x0 + w / 2, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    elif k == "right_arrow":
        pts = [(x0, y0 + h * 0.3), (x0 + w - tip, y0 + h * 0.3), (x0 + w - tip, y0), (x0 + w, y0 + h / 2),
               (x0 + w - tip, y0 + h), (x0 + w - tip, y0 + h * 0.7), (x0, y0 + h * 0.7)]
    elif k == "diamond":
        pts = [(x0 + w / 2, y0), (x0 + w, y0 + h / 2), (x0 + w / 2, y0 + h), (x0, y0 + h / 2)]
    elif k == "right_triangle":
        corners = {"tl": (x0, y0), "tr": (x0 + w, y0), "bl": (x0, y0 + h), "br": (x0 + w, y0 + h)}
        right = corners[sh.corner]
        others = [p for c, p in corners.items() if c != sh.corner and c != {"tl": "br", "br": "tl", "tr": "bl", "bl": "tr"}[sh.corner]]
        pts = [right, *others]
    elif k == "quarter_circle":
        cx, cy = {"tl": (x0, y0), "tr": (x0 + w, y0), "bl": (x0, y0 + h), "br": (x0 + w, y0 + h)}[sh.corner]
        start = {"tl": 0, "tr": 90, "br": 180, "bl": 270}[sh.corner]  # degrees, y down
        n = 24
        pts = [(cx, cy)] + [(cx + w * math.cos(math.radians(start + 90 * i / n)), cy + h * math.sin(math.radians(start + 90 * i / n)))
                            for i in range(n + 1)]
    elif k == "ellipse":
        pts = [(x0 + w / 2 + w / 2 * math.cos(2 * math.pi * i / 72), y0 + h / 2 + h / 2 * math.sin(2 * math.pi * i / 72)) for i in range(72)]
    elif k in ("round_rect", "pill"):
        r = min(h / 2 if k == "pill" else sh.radius * s, w / 2, h / 2)
        pts = []
        for cx, cy, a0 in ((x0 + w - r, y0 + r, 270), (x0 + w - r, y0 + h - r, 0), (x0 + r, y0 + h - r, 90), (x0 + r, y0 + r, 180)):
            pts += [(cx + r * math.cos(math.radians(a0 + 90 * i / 8)), cy + r * math.sin(math.radians(a0 + 90 * i / 8))) for i in range(9)]
    else:
        pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    if sh.rotation % 360:
        a = math.radians(sh.rotation)
        cx, cy = x0 + w / 2, y0 + h / 2
        pts = [(cx + (px - cx) * math.cos(a) - (py - cy) * math.sin(a), cy + (px - cx) * math.sin(a) + (py - cy) * math.cos(a))
               for px, py in pts]
    return pts


def table_cells(tb: Table):
    """Shared table geometry: (kind, x, y, w, h, fill, fitted TextBox) per cell."""
    ncols = max(len(tb.headers), max((len(r) for r in tb.rows), default=0))
    headers = (tb.headers + [""] * ncols)[:ncols]
    rows = [(r + [""] * ncols)[:ncols] for r in tb.rows]
    weights = []
    for j in range(ncols):
        longest = max([len(headers[j])] + [len(r[j]) for r in rows]) or 1
        weights.append(min(max(longest, 6), 40))
    total = sum(weights)
    widths = [tb.w * wt / total for wt in weights]
    rh = tb.h / (len(rows) + 1)

    def is_num(v: str) -> bool:
        return bool(v) and v.replace(".", "").replace(",", "").replace("%", "").replace("-", "").strip().isdigit()

    numeric_col = [bool(rows) and sum(is_num(r[j]) for r in rows) >= max(1, len(rows) * 0.6) for j in range(ncols)]
    out = []
    y = tb.y
    for i, row in enumerate([headers] + rows):
        x = tb.x
        header = i == 0
        fill = tb.header_fill if header else (tb.band_fill if tb.band_fill and i % 2 == 0 else None)
        for j, val in enumerate(row):
            right = numeric_col[j] and (header or is_num(val))
            box = TextBox(x + 0.1, y + 0.04, widths[j] - 0.2, rh - 0.08, [Para(val)], tb.font, tb.size,
                          tb.header_color if header else tb.text_color, bold=header,
                          align="right" if right else "left", valign="middle", min_size=7)
            fit_text(box)
            out.append(("header" if header else "cell", x, y, widths[j], rh, fill, box))
            x += widths[j]
        y += rh
    return out


def measure(text: str, font: str, bold: bool, size: float) -> float:
    return text_width_pt(text, font, bold, size)
