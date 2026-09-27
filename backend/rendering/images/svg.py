"""SVG backend: Scene -> standalone SVG (vector shapes/text; charts and photos embedded)."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from xml.sax.saxutils import escape

from backend.rendering.charts import chart_svg
from backend.rendering.images.raster import shape_polygon, table_cells
from backend.rendering.scene import LINE_HEIGHT, Chart, Line, Picture, Scene, Shape, Table, TextBox, fit_text

PX_PER_IN = 144  # 13.333in -> 1920px


def _attr(v: str) -> str:
    return escape(v, {'"': "&quot;"})


class SVGRenderer:
    def render(self, scene: Scene) -> str:
        s = PX_PER_IN
        W, H = scene.width * s, scene.height * s
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
               f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
               f'<path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
               f'<rect width="100%" height="100%" fill="{scene.background}"/>']
        for el in scene.elements:
            if isinstance(el, Shape):
                out.append(self._shape(el, s))
            elif isinstance(el, Line):
                marker = ' marker-end="url(#arrow)"' if el.arrow_end else ""
                out.append(f'<line x1="{el.x1 * s:.1f}" y1="{el.y1 * s:.1f}" x2="{el.x2 * s:.1f}" y2="{el.y2 * s:.1f}" '
                           f'stroke="{el.color}" stroke-width="{el.width_pt / 72 * s:.1f}"{marker}/>')
            elif isinstance(el, TextBox):
                out.append(self._text(el, s))
            elif isinstance(el, Picture):
                out.append(self._picture(el, s))
            elif isinstance(el, Table):
                for _, x, y, w, h, fill, box in table_cells(el):
                    if fill:
                        out.append(f'<rect x="{x * s:.1f}" y="{y * s:.1f}" width="{w * s:.1f}" height="{h * s:.1f}" fill="{fill}"/>')
                    if el.border:
                        out.append(f'<line x1="{x * s:.1f}" y1="{(y + h) * s:.1f}" x2="{(x + w) * s:.1f}" y2="{(y + h) * s:.1f}" stroke="{el.border}"/>')
                    out.append(self._text(box, s))
            elif isinstance(el, Chart):
                data = base64.b64encode(chart_svg(el, el.w, el.h)).decode()
                out.append(f'<image x="{el.x * s:.1f}" y="{el.y * s:.1f}" width="{el.w * s:.1f}" height="{el.h * s:.1f}" '
                           f'href="data:image/svg+xml;base64,{data}"/>')
        out.append("</svg>")
        return "\n".join(out)

    def save(self, scene: Scene, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(scene), encoding="utf-8")
        return path

    @staticmethod
    def _shape(sh: Shape, s: float) -> str:
        fill = sh.fill or "none"
        stroke = f' stroke="{sh.line}" stroke-width="{sh.line_pt / 72 * s:.1f}"' if sh.line and sh.line_pt else ""
        if sh.opacity < 0.999:
            stroke += f' opacity="{sh.opacity:.2f}"'
        if sh.rotation % 360 or sh.kind not in ("rect", "round_rect", "ellipse"):
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in shape_polygon(sh, s))
            return f'<polygon points="{pts}" fill="{fill}"{stroke}/>'
        if sh.kind in ("rect", "round_rect"):
            r = f' rx="{sh.radius * s:.1f}"' if sh.kind == "round_rect" else ""
            return f'<rect x="{sh.x * s:.1f}" y="{sh.y * s:.1f}" width="{sh.w * s:.1f}" height="{sh.h * s:.1f}"{r} fill="{fill}"{stroke}/>'
        if sh.kind == "ellipse":
            return (f'<ellipse cx="{(sh.x + sh.w / 2) * s:.1f}" cy="{(sh.y + sh.h / 2) * s:.1f}" rx="{sh.w / 2 * s:.1f}" '
                    f'ry="{sh.h / 2 * s:.1f}" fill="{fill}"{stroke}/>')
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in shape_polygon(sh, s))
        return f'<polygon points="{pts}" fill="{fill}"{stroke}/>'

    @staticmethod
    def _text(tb: TextBox, s: float) -> str:
        if not tb.fitted_size:
            fit_text(tb)
        px = lambda pt: pt / 72 * s  # noqa: E731
        total = tb.content_h * s
        y = tb.y * s
        if tb.valign == "middle":
            y += (tb.h * s - total) / 2
        elif tb.valign == "bottom":
            y += tb.h * s - total
        anchor = {"left": "start", "center": "middle", "right": "end"}[tb.align]
        fam = _attr(f"'{tb.font}', Arial, Helvetica, sans-serif")
        parts = [f'<g font-family="{fam}">']
        for i, p in enumerate(tb.paras):
            ps = tb.fitted_size * p.size_scale
            bold = p.bold if p.bold is not None else tb.bold
            indent = px(ps * 1.3) if p.bullet else 0
            lh = px(ps * LINE_HEIGHT)
            for j, line in enumerate(p.lines):
                base = y + px(ps) * 0.93
                if tb.align == "center":
                    x = tb.x * s + indent + (tb.w * s - indent) / 2
                elif tb.align == "right":
                    x = (tb.x + tb.w) * s
                else:
                    x = tb.x * s + indent
                if j == 0 and p.bullet:
                    parts.append(f'<text x="{tb.x * s:.1f}" y="{base:.1f}" font-size="{px(ps):.1f}" font-weight="bold" '
                                 f'fill="{tb.bullet_color or tb.color}">{escape(p.bullet)}</text>')
                style = ' font-style="italic"' if tb.italic else ""
                parts.append(f'<text x="{x:.1f}" y="{base:.1f}" font-size="{px(ps):.1f}" text-anchor="{anchor}" '
                             f'font-weight="{"bold" if bold else "normal"}"{style} fill="{p.color or tb.color}">{escape(line)}</text>')
                y += lh
            if i < len(tb.paras) - 1:
                y += px(ps * p.space_after)
        parts.append("</g>")
        return "".join(parts)

    @staticmethod
    def _picture(pic: Picture, s: float) -> str:
        p = Path(pic.path)
        if not p.exists():
            return ""
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        data = base64.b64encode(p.read_bytes()).decode()
        return (f'<image x="{pic.x * s:.1f}" y="{pic.y * s:.1f}" width="{pic.w * s:.1f}" height="{pic.h * s:.1f}" '
                f'preserveAspectRatio="xMidYMid {"slice" if pic.fit == "cover" else "meet"}" '
                f'style="overflow:hidden" href="data:{mime};base64,{data}"/>')
