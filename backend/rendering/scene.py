"""Renderer-independent scene graph.

The layout engine converts (Slide + Theme) into a Scene of positioned primitives in inches.
Three backends draw the *same* scene: PPTX (editable), raster PNG/JPG (previews, PDF, video)
and SVG. Text is fitted once here, so every output shares font sizes and line breaks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Union

from backend.branding.fonts import wrap_text
from backend.schemas import ChartData

LINE_HEIGHT = 1.2  # multiple of font size (matches PowerPoint single spacing)


@dataclass
class Para:
    text: str
    bullet: Optional[str] = None  # e.g. "•", "1."
    bold: Optional[bool] = None
    color: Optional[str] = None
    size_scale: float = 1.0
    space_after: float = 0.35  # multiple of font size
    lines: list[str] = field(default_factory=list)  # filled by fit_text


@dataclass
class TextBox:
    x: float
    y: float
    w: float
    h: float
    paras: list[Para]
    font: str
    size: float
    color: str
    bold: bool = False
    italic: bool = False
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    min_size: float = 9.0
    bullet_color: Optional[str] = None
    name: str = ""
    anim: str = ""
    fitted_size: float = 0.0
    overflow: bool = False
    content_h: float = 0.0  # height used by fitted text (in)

    @property
    def bullet_indent(self) -> float:
        return (self.fitted_size or self.size) * 1.3 / 72


ShapeKind = Literal["rect", "round_rect", "ellipse", "chevron", "pentagon", "right_arrow", "triangle",
                    "right_triangle", "quarter_circle", "diamond", "pill"]


@dataclass
class Shape:
    kind: ShapeKind
    x: float
    y: float
    w: float
    h: float
    fill: Optional[str] = None
    line: Optional[str] = None
    line_pt: float = 0.0
    radius: float = 0.0  # inches, round_rect only
    name: str = ""
    rotation: float = 0.0  # degrees clockwise about the centre
    opacity: float = 1.0
    corner: Literal["tl", "tr", "bl", "br"] = "bl"  # right-angle corner (right_triangle) / circle centre (quarter_circle)
    anim: str = ""  # motion group tag used by the video engine (e.g. "motif", "build:2")


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    color: str
    width_pt: float = 1.5
    arrow_end: bool = False
    dash: bool = False
    name: str = ""
    anim: str = ""


@dataclass
class Picture:
    x: float
    y: float
    w: float
    h: float
    path: str
    fit: Literal["contain", "cover"] = "contain"
    name: str = ""
    anim: str = ""


@dataclass
class Table:
    x: float
    y: float
    w: float
    h: float
    headers: list[str]
    rows: list[list[str]]
    font: str
    size: float
    header_fill: str
    header_color: str
    text_color: str
    band_fill: Optional[str]
    border: Optional[str]
    name: str = ""
    anim: str = ""


@dataclass
class Chart:
    x: float
    y: float
    w: float
    h: float
    data: ChartData
    palette: list[str]
    font: str
    text_color: str
    grid_color: str
    gridlines: bool = False
    data_labels: bool = True
    name: str = ""
    anim: str = ""


Element = Union[TextBox, Shape, Line, Picture, Table, Chart]


@dataclass
class Scene:
    width: float
    height: float
    background: str
    elements: list[Element] = field(default_factory=list)
    notes: str = ""
    name: str = ""
    use_template_background: bool = False

    def add(self, *els: Element) -> None:
        self.elements.extend(els)


def fit_text(box: TextBox) -> TextBox:
    """Choose the largest size <= box.size that fits; wrap lines; truncate as a last resort."""
    width_pt = box.w * 72
    height_pt = box.h * 72
    size = box.size
    while True:
        total = 0.0
        for i, p in enumerate(box.paras):
            s = size * p.size_scale
            indent = s * 1.3 if p.bullet else 0.0
            p.lines = wrap_text(p.text, box.font, bool(p.bold if p.bold is not None else box.bold), s, max(10.0, width_pt - indent))
            total += len(p.lines) * s * LINE_HEIGHT
            if i < len(box.paras) - 1:
                total += s * p.space_after
        if total <= height_pt or size <= box.min_size:
            break
        size = max(box.min_size, size - (2 if size > 20 else 1))
    box.fitted_size = size
    box.content_h = total / 72
    if total > height_pt + 0.5:
        box.overflow = True
        _truncate(box, height_pt)
    return box


def _truncate(box: TextBox, height_pt: float) -> None:
    used = 0.0
    keep: list[Para] = []
    for p in box.paras:
        s = box.fitted_size * p.size_scale
        lh = s * LINE_HEIGHT
        avail = int((height_pt - used) // lh)
        if avail <= 0:
            break
        if len(p.lines) > avail:
            p.lines = p.lines[:avail]
            p.lines[-1] = p.lines[-1].rstrip(" .,;:") + "…"
            p.text = " ".join(p.lines)
            keep.append(p)
            break
        keep.append(p)
        used += len(p.lines) * lh + s * p.space_after
    box.paras = keep
    box.content_h = min(box.h, used / 72)
