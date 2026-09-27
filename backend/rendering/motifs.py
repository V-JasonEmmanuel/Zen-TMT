"""Zensar shape library - the modular shape language derived from the Z motif
(circle + square + triangle) and the modular grid described in Zensar's brand announcement.

Every primitive takes its colour from theme roles. Compositions are placed on a ModularGrid
and follow curated patterns: shapes express hierarchy, grouping and section separation and are
never scattered randomly. All shapes carry an `anim` tag so the video engine can "build" them.
"""
from __future__ import annotations

from typing import Optional

from backend.branding.theme import Theme
from backend.rendering.grid import ModularGrid, Rect
from backend.rendering.scene import Line, Shape

Corner = str


# ------------------------------------------------------------------ primitives
def ZensarSquare(t: Theme, r: Rect, role: str = "secondary", **kw) -> Shape:
    return Shape("rect", *r, fill=t.c(role), name="zensar_square", anim=kw.pop("anim", "motif"), **kw)


def ZensarCircle(t: Theme, r: Rect, role: str = "primary", **kw) -> Shape:
    x, y, w, h = r
    d = min(w, h)
    return Shape("ellipse", x + (w - d) / 2, y + (h - d) / 2, d, d, fill=t.c(role), name="zensar_circle",
                 anim=kw.pop("anim", "motif"), **kw)


def ZensarTriangle(t: Theme, r: Rect, role: str = "surface_alt", corner: Corner = "bl", **kw) -> Shape:
    return Shape("right_triangle", *r, fill=t.c(role), corner=corner, name="zensar_triangle", anim=kw.pop("anim", "motif"), **kw)  # type: ignore[arg-type]


def ZensarQuarterCircle(t: Theme, r: Rect, role: str = "primary", corner: Corner = "bl", **kw) -> Shape:
    return Shape("quarter_circle", *r, fill=t.c(role), corner=corner, name="zensar_quarter", anim=kw.pop("anim", "motif"), **kw)  # type: ignore[arg-type]


def ZensarDiamond(t: Theme, r: Rect, role: str = "secondary", **kw) -> Shape:
    return Shape("diamond", *r, fill=t.c(role), name="zensar_diamond", anim=kw.pop("anim", "motif"), **kw)


def ZensarConnector(t: Theme, x1, y1, x2, y2, role: str = "secondary", width_pt: float = 1.0, arrow: bool = False) -> Line:
    return Line(x1, y1, x2, y2, t.c(role), width_pt, arrow_end=arrow, name="zensar_connector", anim="motif")


def ZensarFrame(t: Theme, r: Rect, role: str = "secondary", width_pt: float = 1.5) -> Shape:
    return Shape("rect", *r, fill=None, line=t.c(role), line_pt=width_pt, name="zensar_frame", anim="motif")


def ZensarAccent(t: Theme, x: float, y: float, size: float = 0.14, role: str = "accent") -> Shape:
    """Small square marker (section tags, list markers)."""
    return Shape("rect", x, y, size, size, fill=t.c(role), name="zensar_accent", anim="chrome")


# ------------------------------------------------------------------ compositions
# Curated module patterns on a square grid. Each entry: (row, col, kind, role, corner/None, rspan, cspan)
# Colour roles: P primary, S secondary, A accent, T* tints. Patterns echo the Z motif: a square, a
# quarter-circle and a triangle meeting on a diagonal, surrounded by lighter tint modules.
PATTERNS: dict[str, list[tuple]] = {
    "cover": [
        (0, 2, "square", "tint_0", None, 1, 1),
        (1, 1, "quarter", "secondary", "br", 1, 1),
        (1, 2, "square", "primary", None, 1, 1),
        (2, 0, "triangle", "tint_1", "tr", 1, 1),
        (2, 1, "square", "tint_0", None, 1, 1),
        (2, 2, "triangle", "secondary", "tl", 1, 1),
        (3, 1, "quarter", "accent", "tr", 1, 1),
        (3, 2, "square", "tint_2", None, 1, 1),
    ],
    "divider": [
        (0, 1, "triangle", "secondary", "br", 1, 1),
        (1, 0, "quarter", "tint_0", "tr", 1, 1),
        (1, 1, "square", "secondary", None, 1, 1),
        (2, 1, "quarter", "accent", "tl", 1, 1),
        (2, 0, "square", "tint_1", None, 1, 1),
    ],
    "corner": [
        (0, 1, "triangle", "tint_0", "br", 1, 1),
        (1, 0, "quarter", "secondary", "tr", 1, 1),
        (1, 1, "square", "primary", None, 1, 1),
    ],
    "panel": [
        (0, 0, "quarter", "secondary", "br", 1, 1),
        (1, 1, "triangle", "tint_0", "tl", 1, 1),
    ],
}


def _module(t: Theme, kind: str, cell: Rect, role: str, corner: Optional[str], anim: str) -> Shape:
    if kind == "square":
        return ZensarSquare(t, cell, role, anim=anim)
    if kind == "quarter":
        return ZensarQuarterCircle(t, cell, role, corner or "bl", anim=anim)
    if kind == "triangle":
        return ZensarTriangle(t, cell, role, corner or "bl", anim=anim)
    if kind == "circle":
        return ZensarCircle(t, cell, role, anim=anim)
    return ZensarDiamond(t, cell, role, anim=anim)


def ZensarModule(t: Theme, region: Rect, pattern: str = "cover", cols: int = 3, gutter: float = 0.0,
                 anim_prefix: str = "motif") -> list[Shape]:
    """A composition of primitives on a square modular grid, following a curated pattern."""
    grid = ModularGrid.square(region, cols, gutter)
    out = []
    for i, (r, c, kind, role, corner, rs, cs) in enumerate(PATTERNS[pattern]):
        if r >= grid.rows or c >= grid.cols:
            continue
        out.append(_module(t, kind, grid.cell(r, c, rs, cs), role, corner, f"{anim_prefix}:{i}"))
    return out


def ZensarGrid(t: Theme, region: Rect, module: str = "3x3", role: str = "border", width_pt: float = 0.5) -> list[Line]:
    """Visible hairline grid (used sparingly: title compositions, video transitions)."""
    g = ModularGrid.module(region, module)
    x, y, w, h = region
    lines = [Line(x + c * g.cell_w, y, x + c * g.cell_w, y + h, t.c(role), width_pt, name="zensar_grid", anim="motif")
             for c in range(1, g.cols)]
    lines += [Line(x, y + r * g.cell_h, x + w, y + r * g.cell_h, t.c(role), width_pt, name="zensar_grid", anim="motif")
              for r in range(1, g.rows)]
    return lines


def section_tag(t: Theme, text: str, right: float, y: float) -> list:
    """Coloured square marker + section label, right aligned (as on Zensar report pages)."""
    from backend.rendering.components import text as tb

    label = (text or "").strip()
    if not label:
        return []
    w = 3.2
    box = tb(t, right - w, y, w, 0.3, label, role="text_secondary", size=t.sizes["caption"] + 1, font="caption",
             align="right", valign="middle", min_size=7, name="section_tag")
    box.anim = "chrome"
    from backend.branding.fonts import text_width_pt

    tw = text_width_pt(label, box.font, False, box.fitted_size) / 72
    return [ZensarAccent(t, right - tw - 0.24, y + 0.15 - 0.06, 0.12, "accent"), box]


def corner_motif(t: Theme, size: float = 0.9) -> list[Shape]:
    """Small 2x2 cluster anchored to the bottom-right corner of a content slide."""
    region = (t.slide_w - size, t.slide_h - size, size, size)
    return ZensarModule(t, region, "corner", cols=2)


def cover_composition(t: Theme, region: Rect) -> list:
    x, y, w, h = region
    shapes: list = []
    if t.shapes and t.shapes.line_role:  # thin diagonal rule behind the modules (as on the report cover)
        shapes.append(ZensarConnector(t, x - w * 0.35, y + h, x + w, y - 0.2, t.shapes.line_role, 0.75))
    return shapes + ZensarModule(t, region, "cover", cols=3)


__all__ = ["ZensarSquare", "ZensarCircle", "ZensarTriangle", "ZensarQuarterCircle", "ZensarDiamond", "ZensarConnector",
           "ZensarFrame", "ZensarAccent", "ZensarModule", "ZensarGrid", "section_tag", "corner_motif", "cover_composition"]
