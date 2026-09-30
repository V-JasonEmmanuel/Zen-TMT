"""Theme = concrete design tokens resolved from a BrandProfile.

Unset brand values are replaced by NEUTRAL (greyscale / system-font) fallbacks. Each
substitution is listed in `Theme.fallbacks` and surfaced in the UI, so the output never
silently pretends to be on-brand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.branding.brand_profile import BrandProfile, BrandStore, ShapeSystem, VideoStyle
from backend.branding.fonts import has_family

NEUTRAL = {
    "primary": "#262626", "secondary": "#595959", "accent": "#7F7F7F", "background": "#FFFFFF",
    "surface": "#F2F2F2", "text_primary": "#1A1A1A", "text_secondary": "#595959",
}
NEUTRAL_FONT = "Arial"
SYSTEM_STATUS = {"success": "#1E8E3E", "warning": "#B26A00", "error": "#C5221F"}  # UI status only, not brand colours
DEFAULT_SIZES = {"title": 28.0, "cover_title": 40.0, "subtitle": 18.0, "heading": 18.0, "body": 16.0, "caption": 9.0, "kpi": 40.0}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(h: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@dataclass
class Theme:
    brand_id: str
    brand_name: str
    colors: dict[str, str]
    palette: list[str]
    heading_font: str
    body_font: str
    caption_font: str
    heading_bold: bool
    title_color_role: str
    sizes: dict[str, float]
    slide_w: float = 13.333
    slide_h: float = 7.5
    margin_x: float = 0.6
    margin_y: float = 0.45
    gutter: float = 0.35
    title_align: str = "left"
    content_top: float = 1.55
    footer_h: float = 0.45
    cover_style: str = "light"
    card_fill_role: str = "surface"
    card_border_role: Optional[str] = None
    card_radius: float = 0.08
    card_border_pt: float = 0.0
    accent_bar: bool = True
    accent_bar_role: str = "accent"
    bullet_style: str = "dot"
    bullet_color_role: str = "accent"
    shape_style: str = "rounded"
    chart_gridlines: bool = False
    chart_data_labels: bool = True
    table_header_fill_role: str = "primary"
    table_header_text_role: str = "on_primary"
    table_band_fill_role: Optional[str] = "surface"
    table_border_role: Optional[str] = "surface"
    image_radius: float = 0.0
    logo_path: Optional[Path] = None
    logo_dark_path: Optional[Path] = None
    logo_position: str = "top_right"
    logo_width: float = 1.3
    logo_show_on: str = "all"
    footer_text: str = ""
    show_page_numbers: bool = True
    show_sources: bool = True
    template_path: Optional[Path] = None
    template_blank_layout: Optional[str] = None
    fallbacks: list[str] = field(default_factory=list)
    # --- extended design system
    tints: list[str] = field(default_factory=list)
    subtitle_role: str = "text_secondary"
    kpi_font: str = ""
    logo_min_width: float = 0.6
    shapes: Optional[ShapeSystem] = None
    grid_module: str = "3x3"
    video_style: Optional[VideoStyle] = None
    font_substitutions: dict[str, str] = field(default_factory=dict)  # brand font -> font actually used everywhere
    design: str = ""  # "experience" = Zensar LinkedIn design language (backend/branding/social.py)
    section_label_roles: list[str] = field(default_factory=list)

    @property
    def motifs_on(self) -> bool:
        return bool(self.shapes and self.shapes.enabled and self.shapes.motifs and self.shapes.density != "none")

    def c(self, role: Optional[str]) -> str:
        """Colour for a role name. Supports derived 'on_<role>' contrast colours."""
        if not role:
            return self.colors["text_primary"]
        if role.startswith("on_"):
            base = self.c(role[3:])
            dark, light = self.colors["text_primary"], "#FFFFFF"
            return light if contrast(base, light) >= contrast(base, dark) else dark
        if role.startswith("tint_"):
            i = int(role[5:]) if role[5:].isdigit() else 0
            return self.tints[i % len(self.tints)] if self.tints else self.colors["surface_alt"]
        if role.startswith("#"):
            return role  # explicit colour chosen by a user in the shape editor (validated upstream)
        return self.colors.get(role) or self.colors["text_primary"]

    @property
    def is_branded(self) -> bool:
        return not any(f.startswith("colors.primary") or f.startswith("typography.heading") for f in self.fallbacks)


def build_theme(brand: BrandProfile, store: Optional[BrandStore] = None) -> Theme:
    store = store or BrandStore()
    fb: list[str] = []
    colors = {}
    for role, neutral in NEUTRAL.items():
        v = getattr(brand.colors, role)
        if v is None:
            fb.append(f"colors.{role}")
            v = neutral
        colors[role] = v
    # optional roles resolve to brand roles (never to invented colours); status colours are system UI colours
    derived = {"accent_2": "accent", "accent_3": "accent_2", "highlight": "accent", "surface_alt": "surface",
               "border": "surface_alt"}
    for role, base in derived.items():
        colors[role] = getattr(brand.colors, role) or colors[base]
    for role, system in SYSTEM_STATUS.items():
        colors[role] = getattr(brand.colors, role) or system
    palette = [c for c in brand.colors.palette]
    roles = brand.components.chart_palette_roles or ["primary", "secondary", "accent", "text_secondary"]
    for r in roles:
        col = colors.get(r)
        if col and col not in palette:
            palette.append(col)

    substitutions: dict[str, str] = {}
    fallback_family = brand.typography.fallback_family or NEUTRAL_FONT

    def font(spec_family: Optional[str], key: str) -> str:
        if not spec_family:
            fb.append(f"typography.{key}.family")
            return fallback_family
        if not has_family(spec_family):
            # consistent substitution in EVERY output (PPTX, images, PDF, video) - shown to the user
            substitutions[spec_family] = fallback_family
            return fallback_family
        return spec_family

    heading = font(brand.typography.heading.family, "heading")
    body = font(brand.typography.body.family, "body")
    caption = font(brand.typography.caption.family, "caption") if brand.typography.caption.family else body
    kpi = font(brand.typography.kpi.family, "kpi") if brand.typography.kpi.family else heading
    sizes = dict(DEFAULT_SIZES)
    sizes.update({k: float(v) for k, v in brand.typography.sizes.items() if v})

    L, C = brand.layout, brand.components
    d = store.dir(brand.id)

    def asset(rel: Optional[str], sub: str) -> Optional[Path]:
        if not rel:
            return None
        p = d / sub / rel
        return p if p.exists() else None

    t = Theme(
        brand_id=brand.id, brand_name=brand.name, colors=colors, palette=palette,
        heading_font=heading, body_font=body, caption_font=caption,
        heading_bold=brand.typography.heading.bold if brand.typography.heading.bold is not None else True,
        title_color_role=brand.typography.heading.color_role or "text_primary", sizes=sizes,
        fallbacks=fb,
    )
    for attr, val in (("slide_w", L.slide_width_in), ("slide_h", L.slide_height_in), ("margin_x", L.margin_x_in),
                      ("margin_y", L.margin_y_in), ("gutter", L.gutter_in), ("title_align", L.title_align),
                      ("content_top", L.content_top_in), ("footer_h", L.footer_height_in), ("cover_style", L.cover_style),
                      ("card_fill_role", C.card_fill_role), ("card_border_role", C.card_border_role),
                      ("card_radius", C.card_radius_in), ("card_border_pt", C.card_border_pt), ("accent_bar", C.accent_bar),
                      ("accent_bar_role", C.accent_bar_role), ("bullet_style", C.bullet_style),
                      ("bullet_color_role", C.bullet_color_role), ("shape_style", C.shape_style),
                      ("chart_gridlines", C.chart_gridlines), ("chart_data_labels", C.chart_data_labels),
                      ("table_header_fill_role", C.table_header_fill_role), ("table_header_text_role", C.table_header_text_role),
                      ("table_band_fill_role", C.table_band_fill_role), ("table_border_role", C.table_border_role),
                      ("image_radius", C.image_radius_in)):
        if val is not None:
            setattr(t, attr, val)
    if t.shape_style == "square":
        t.card_radius = 0.0
    # scale default geometry for non-16:9 or smaller slide sizes
    if L.slide_width_in and not L.margin_x_in:
        t.margin_x = round(0.045 * t.slide_w, 3)
    if L.slide_height_in and not L.content_top_in:
        t.content_top = round(0.207 * t.slide_h, 3)
        t.margin_y = round(0.06 * t.slide_h, 3)
    t.tints = list(brand.colors.tints)
    t.subtitle_role = brand.typography.subtitle_color_role or "text_secondary"
    t.kpi_font = kpi
    t.font_substitutions = substitutions
    t.shapes = brand.shapes
    t.grid_module = brand.grid.module
    t.video_style = brand.video_style
    t.logo_min_width = brand.logo.min_width_in or 0.6
    t.logo_path = asset(brand.logo.file, "assets")
    t.logo_dark_path = asset(brand.logo.file_on_dark, "assets")
    t.logo_position = brand.logo.position
    t.logo_width = brand.logo.width_in or round(t.slide_w * 0.1, 2)
    t.logo_show_on = brand.logo.show_on
    t.footer_text = brand.footer.text
    t.show_page_numbers = brand.footer.show_page_numbers
    t.show_sources = brand.footer.show_sources
    if brand.template.file and brand.template.use_as_base:
        t.template_path = asset(brand.template.file, "references")
        t.template_blank_layout = brand.template.blank_layout
    return t


def load_theme(brand_id: str) -> Theme:
    store = BrandStore()
    return build_theme(store.load(brand_id), store)
