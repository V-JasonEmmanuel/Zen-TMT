"""Brand document templates, learned from a reference PDF.

A template records what the reference actually uses - page size, the page designs it is made of (cover,
card pages, text pages, image pages, conclusion, back cover), their colours (sampled from the rendered
page), geometry (columns, cards, rules, footer), text styles and the brand artwork (logo lockups,
patterns, decorative shapes) as vector paths that are replayed exactly. Nothing here is invented: every
value is measured from the reference; what the reference does not show stays empty.

Coordinates are PDF points with the origin at the TOP-left of the page (as measured).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

PageKind = Literal["cover", "intro", "body", "image", "conclusion", "back"]


class TextStyle(BaseModel):
    family: str = ""  # font family in the reference (e.g. "Graphik")
    weight: int = 400  # 300 light, 400 regular, 500 medium, 600 semibold, 700 bold
    size: float = 10.0
    leading: float = 0.0  # line spacing (pt); 0 = 1.2 x size
    color: str = "#000000"
    space_after: float = 0.0  # extra space after a paragraph


class Shape(BaseModel):
    """One vector path from the reference (replayed as-is)."""
    items: list[list] = Field(default_factory=list)  # ["l", x1,y1,x2,y2] | ["c", x1,y1,c1x,c1y,c2x,c2y,x2,y2] | ["re", x0,y0,x1,y1]
    fill: Optional[str] = None
    fill_opacity: float = 1.0
    stroke: Optional[str] = None
    width: float = 0.0
    even_odd: bool = False
    close: bool = False
    bbox: list[float] = Field(default_factory=list)


class Artwork(BaseModel):
    """A cluster of shapes that belong together (logo lockup, pattern, label marker)."""
    role: str = ""  # logo | tagline | pattern | marker | decoration
    bbox: list[float] = Field(default_factory=list)
    shapes: list[Shape] = Field(default_factory=list)


class Card(BaseModel):
    box: list[float]
    color: str
    radius: float = 0.0
    pad_x: float = 24.0
    pad_top: float = 40.0
    pad_bottom: float = 30.0
    dash_color: str = ""
    text_color: str = "#FFFFFF"
    divider_color: str = ""
    divider_width: float = 0.25
    separator_rules: bool = False  # paragraphs separated by thin rules (conclusion card)


class Photo(BaseModel):
    box: list[float]  # visible image area on the page
    fade_from: float = 0.0  # y where the image starts fading into the page colour (0 = no fade)
    fade_to: float = 0.0


class Footer(BaseModel):
    pattern: str = ""  # "© Zensar Technologies, {year}  |  Page {page}"
    style: TextStyle = Field(default_factory=TextStyle)
    x1: float = 0.0  # right edge (right aligned)
    baseline: float = 0.0
    align: str = "right"


class PageDesign(BaseModel):
    kind: PageKind
    source_page: int  # 1-based page of the reference
    background: str = "#FFFFFF"
    decorations: list[Shape] = Field(default_factory=list)  # big background shapes, colours sampled
    artwork: list[Artwork] = Field(default_factory=list)
    photo: Optional[Photo] = None
    card: Optional[Card] = None
    text_color: str = "#000000"
    heading_color: str = "#000000"
    columns: list[list[float]] = Field(default_factory=list)  # [[x0, x1], [x0, x1]]
    divider: Optional[dict] = None  # {"x":, "color":, "width":}
    rule_color: str = ""
    rule_width: float = 0.25
    content_top: float = 0.0
    content_bottom: float = 0.0
    top_rule: Optional[float] = None  # y of a full-width rule above the text (image pages)
    bottom_rule: Optional[float] = None  # y of the full-width rule below the text
    footer: Optional[Footer] = None
    bullet: Optional[dict] = None  # {"size":, "color":, "indent":}


class CoverDesign(BaseModel):
    title: TextStyle = Field(default_factory=TextStyle)
    title_box: list[float] = Field(default_factory=list)  # x0, y_top, x1, y_bottom of the title block
    label: TextStyle = Field(default_factory=TextStyle)
    label_text: str = ""  # e.g. "White Paper"
    label_pos: list[float] = Field(default_factory=list)  # x0, y_top of the label text
    marker: Optional[Artwork] = None  # the small shape before the label


class BackDesign(BaseModel):
    author_label: str = ""  # "Authored by"
    author_label_style: TextStyle = Field(default_factory=TextStyle)
    author_name_style: TextStyle = Field(default_factory=TextStyle)
    author_detail_style: TextStyle = Field(default_factory=TextStyle)
    author_pos: list[float] = Field(default_factory=list)  # x0, y_top
    boilerplate: list[str] = Field(default_factory=list)
    boilerplate_style: TextStyle = Field(default_factory=TextStyle)
    boilerplate_box: list[float] = Field(default_factory=list)  # x0, y_top, x1, y_bottom


class ImageStyle(BaseModel):
    prompt_style: str = ""  # appended to every image prompt (derived from the reference photos)
    negative: str = ""
    lab_mean: list[float] = Field(default_factory=list)  # colour statistics of the reference photos (CIELAB)
    lab_std: list[float] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)


class DocTemplate(BaseModel):
    id: str
    name: str
    brand_id: str = ""
    source_file: str = ""
    created_at: str = ""
    page_w: float = 595.28
    page_h: float = 841.89
    fonts_seen: list[str] = Field(default_factory=list)  # e.g. ["Graphik-Light", "Graphik-Medium"]
    font_fallback: str = ""  # installed family used when the reference family is not installed
    accent: str = ""
    dash: dict = Field(default_factory=dict)  # {"w":, "h":, "gap":, "after":}
    styles: dict[str, TextStyle] = Field(default_factory=dict)  # h1, body, card_body, list ...
    pages: dict[str, PageDesign] = Field(default_factory=dict)  # kind -> design
    cover: CoverDesign = Field(default_factory=CoverDesign)
    back: BackDesign = Field(default_factory=BackDesign)
    image_style: ImageStyle = Field(default_factory=ImageStyle)
    notes: list[str] = Field(default_factory=list)
