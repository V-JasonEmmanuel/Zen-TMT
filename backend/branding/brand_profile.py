"""Brand profiles: stored as JSON files under brands/<id>/ and edited through the Brand Manager.

Every value is optional. Values are never invented: unset values stay null, and the theme
resolver substitutes clearly-labelled neutral fallbacks (reported to the user) at render time.
`provenance` records where each value came from (manual / pptx_template / reference_image).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.schemas import utcnow
from backend.utils.config import get_settings
from backend.utils.files import UnsafePathError, safe_join, sanitize_filename, slugify

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_ROLES = ("primary", "secondary", "accent", "background", "surface", "text_primary", "text_secondary")
EXTRA_COLOR_ROLES = ("accent_2", "accent_3", "highlight", "surface_alt", "border", "success", "warning", "error")
ALL_COLOR_ROLES = COLOR_ROLES + EXTRA_COLOR_ROLES
ProvenanceSource = Literal["manual", "pptx_template", "reference_image", "default",
                           "official_website", "official_annual_report", "official_press"]


def _hex(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    v = v.strip()
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    if not HEX.match(v):
        raise ValueError(f"'{v}' is not a #RRGGBB colour")
    return v.upper()


class Colors(BaseModel):
    primary: Optional[str] = None
    secondary: Optional[str] = None
    accent: Optional[str] = None
    background: Optional[str] = None
    surface: Optional[str] = None
    text_primary: Optional[str] = None
    text_secondary: Optional[str] = None
    accent_2: Optional[str] = None
    accent_3: Optional[str] = None
    highlight: Optional[str] = None
    surface_alt: Optional[str] = None
    border: Optional[str] = None
    success: Optional[str] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    palette: list[str] = Field(default_factory=list)  # chart series order / additional brand colours
    tints: list[str] = Field(default_factory=list)  # light brand tints for panels and shape fills

    @field_validator(*ALL_COLOR_ROLES, mode="before")
    @classmethod
    def _v(cls, v):
        return _hex(v)

    @field_validator("palette", "tints", mode="before")
    @classmethod
    def _p(cls, v):
        return [c for c in (_hex(x) for x in (v or [])) if c]


class FontSpec(BaseModel):
    family: Optional[str] = None
    bold: Optional[bool] = None
    color_role: Optional[str] = None
    weight: Optional[int] = None  # 300 light ... 700 bold (informational; renderers use regular/bold)


class Typography(BaseModel):
    heading: FontSpec = Field(default_factory=FontSpec)
    body: FontSpec = Field(default_factory=FontSpec)
    caption: FontSpec = Field(default_factory=FontSpec)
    kpi: FontSpec = Field(default_factory=FontSpec)
    subtitle_color_role: Optional[str] = None
    # used for ALL outputs when a brand font is not installed/licensed on this machine
    fallback_family: Optional[str] = None
    line_height: Optional[float] = None
    sizes: dict[str, Optional[float]] = Field(default_factory=dict)  # title, subtitle, heading, body, caption, kpi (pt)


class LayoutRules(BaseModel):
    slide_width_in: Optional[float] = None
    slide_height_in: Optional[float] = None
    margin_x_in: Optional[float] = None
    margin_y_in: Optional[float] = None
    gutter_in: Optional[float] = None
    title_align: Optional[Literal["left", "center"]] = None
    content_top_in: Optional[float] = None
    footer_height_in: Optional[float] = None
    cover_style: Optional[Literal["light", "solid_primary", "template"]] = None


class Components(BaseModel):
    card_fill_role: Optional[str] = None
    card_border_role: Optional[str] = None
    card_radius_in: Optional[float] = None
    card_border_pt: Optional[float] = None
    accent_bar: Optional[bool] = None
    accent_bar_role: Optional[str] = None
    bullet_style: Optional[Literal["dot", "square", "dash", "number"]] = None
    bullet_color_role: Optional[str] = None
    shape_style: Optional[Literal["rounded", "square"]] = None
    chart_palette_roles: list[str] = Field(default_factory=list)
    chart_gridlines: Optional[bool] = None
    chart_data_labels: Optional[bool] = None
    table_header_fill_role: Optional[str] = None
    table_header_text_role: Optional[str] = None
    table_band_fill_role: Optional[str] = None
    table_border_role: Optional[str] = None
    image_radius_in: Optional[float] = None


class LogoRules(BaseModel):
    file: Optional[str] = None  # primary logo for light backgrounds, relative to brand assets/
    file_on_dark: Optional[str] = None  # light/white logo for dark backgrounds
    file_mono: Optional[str] = None
    position: Literal["top_right", "top_left", "bottom_right", "bottom_left", "none"] = "top_right"
    width_in: Optional[float] = None
    min_width_in: Optional[float] = None
    clear_space_ratio: Optional[float] = None  # clear space as a fraction of logo height
    show_on: Literal["all", "cover", "content", "none"] = "all"
    sources: dict[str, str] = Field(default_factory=dict)  # variant -> where the asset came from


class ShapeSystem(BaseModel):
    """Modular shape language (e.g. Zensar's circle/square/triangle Z motif). Shapes are placed on a
    grid for hierarchy, grouping and section separation - never scattered at random."""

    enabled: bool = False
    motifs: list[Literal["circle", "square", "triangle", "quarter_circle", "diamond", "arc", "line"]] = Field(default_factory=list)
    density: Literal["none", "subtle", "expressive"] = "subtle"
    cover_composition: Literal["grid_cluster", "diagonal", "none"] = "grid_cluster"
    color_roles: list[str] = Field(default_factory=list)
    line_role: Optional[str] = None
    section_tag: bool = False  # small coloured marker + section name at top-right
    notes: str = ""


class GridSystem(BaseModel):
    columns: int = 12
    module: Literal["2x2", "3x3", "4x4", "6x6"] = "3x3"


class VideoStyle(BaseModel):
    transition: Literal["fade", "zensar_grid", "wipe", "slide"] = "fade"
    motion: Literal["none", "subtle", "standard"] = "subtle"
    intro: bool = False
    outro: bool = False
    build_animations: bool = True
    chart_animation: bool = True
    configured: bool = False


class VoiceStyle(BaseModel):
    engine: Optional[str] = None
    voice: Optional[str] = None
    speed: float = 1.0
    pause_ms: int = 350
    volume: float = 1.0
    pronunciations: dict[str, str] = Field(default_factory=dict)


class ImageSources(BaseModel):
    strategy: Literal["prefer_source", "prefer_library", "prefer_web", "prefer_generated", "auto"] = "auto"
    providers: list[str] = Field(default_factory=lambda: ["local", "brand_assets"])
    default_treatment: Literal["none", "tint", "duotone", "overlay", "desaturate"] = "none"
    min_width_px: int = 1200
    configured: bool = False


class ReferenceMeta(BaseModel):
    filename: str
    type: str = "image"
    source: str = "user_upload"
    source_url: str = ""
    date_added: str = Field(default_factory=utcnow)
    description: str = ""
    design_role: Literal["layout", "slide", "branding", "shapes", "diagram", "visual_style", "image_treatment", "other"] = "other"
    active: bool = True


class Footer(BaseModel):
    text: str = ""
    show_page_numbers: bool = True
    show_sources: bool = True


class TemplateRef(BaseModel):
    file: Optional[str] = None  # relative to brand references/
    use_as_base: bool = True
    blank_layout: Optional[str] = None


class Provenance(BaseModel):
    source: ProvenanceSource = "manual"
    confidence: float = 1.0
    note: str = ""
    url: str = ""


class BrandProfile(BaseModel):
    id: str
    name: str
    description: str = ""
    version: int = 1
    colors: Colors = Field(default_factory=Colors)
    typography: Typography = Field(default_factory=Typography)
    layout: LayoutRules = Field(default_factory=LayoutRules)
    components: Components = Field(default_factory=Components)
    logo: LogoRules = Field(default_factory=LogoRules)
    footer: Footer = Field(default_factory=Footer)
    template: TemplateRef = Field(default_factory=TemplateRef)
    shapes: ShapeSystem = Field(default_factory=ShapeSystem)
    grid: GridSystem = Field(default_factory=GridSystem)
    video_style: VideoStyle = Field(default_factory=VideoStyle)
    voice: VoiceStyle = Field(default_factory=VoiceStyle)
    image_sources: ImageSources = Field(default_factory=ImageSources)
    references: list[str] = Field(default_factory=list)  # reference image filenames
    reference_meta: dict[str, ReferenceMeta] = Field(default_factory=dict)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=utcnow)

    @property
    def status(self) -> str:
        core = [self.colors.primary, self.colors.text_primary, self.typography.heading.family, self.typography.body.family]
        if all(core):
            return "configured"
        if any(core) or self.template.file:
            return "partial"
        return "unconfigured"

    def missing(self) -> list[str]:
        out = [f"colors.{r}" for r in COLOR_ROLES if getattr(self.colors, r) is None]
        for k in ("heading", "body"):
            if not getattr(self.typography, k).family:
                out.append(f"typography.{k}.family")
        if not self.logo.file:
            out.append("logo")
        return out

    def _review(self, prefix: str) -> bool:
        """True when values under `prefix` came from inferred/public sources and have not been confirmed."""
        return any(k.startswith(prefix) and (p.source != "manual" or p.confidence < 1.0) for k, p in self.provenance.items())

    def checklist(self) -> list[dict]:
        """Per-area configuration state shown on the Brand Manager overview."""
        def item(key, label, ok, review=False, detail=""):
            return {"key": key, "label": label, "state": "missing" if not ok else ("review" if review else "configured"), "detail": detail}

        c, t = self.colors, self.typography
        refs = [m for m in self.reference_meta.values() if m.active] or self.references
        return [
            item("colors", "Colours", bool(c.primary and c.text_primary and c.background), self._review("colors."),
                 f"{sum(1 for r in ALL_COLOR_ROLES if getattr(c, r))} roles set"),
            item("typography", "Typography", bool(t.heading.family and t.body.family), self._review("typography."),
                 f"{t.heading.family or '-'} / {t.body.family or '-'}"),
            item("logo", "Logo", bool(self.logo.file or self.logo.file_on_dark), self._review("logo."),
                 ", ".join(v for v, f in (("light bg", self.logo.file), ("dark bg", self.logo.file_on_dark)) if f)),
            item("shapes", "Shape system", self.shapes.enabled and bool(self.shapes.motifs), self._review("shapes."),
                 ", ".join(self.shapes.motifs)),
            item("layouts", "Layouts", self.layout.slide_width_in is not None or bool(self.template.file), self._review("layout.")),
            item("components", "Components", any(v is not None for k, v in self.components.model_dump().items() if k != "chart_palette_roles"),
                 self._review("components.")),
            item("references", "Reference images", bool(refs), False, f"{len(refs)} reference(s)"),
            item("template", "PPT template", bool(self.template.file), False,
                 self.template.file or "No official Zensar PowerPoint template supplied yet"),
            item("image_sources", "Image sources", self.image_sources.configured, False, self.image_sources.strategy),
            item("voice", "Voice", bool(self.voice.engine), False, self.voice.voice or ""),
            item("video_style", "Video style", self.video_style.configured, False, self.video_style.transition),
        ]


SETTABLE_PREFIXES = ("colors.", "typography.", "layout.", "components.", "logo.", "footer.", "template.", "shapes.",
                     "grid.", "video_style.", "voice.", "image_sources.")


def apply_value(brand: BrandProfile, path: str, value, source: str = "manual", confidence: float = 1.0, note: str = "",
                url: str = "") -> BrandProfile:
    """Set a dotted path (e.g. 'colors.primary', 'typography.sizes.body') and record its provenance."""
    if not path.startswith(SETTABLE_PREFIXES):
        raise ValueError(f"'{path}' cannot be set")
    data = brand.model_dump()
    parts = path.split(".")
    node = data
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            raise ValueError(f"Unknown brand setting '{path}'")
        node = node[p]
    if not isinstance(node, dict) or (parts[-1] not in node and parts[-2] != "sizes"):
        raise ValueError(f"Unknown brand setting '{path}'")
    node[parts[-1]] = value
    updated = BrandProfile.model_validate(data)  # validates colours, enums, types
    updated.provenance[path] = Provenance(source=source, confidence=confidence, note=note, url=url)  # type: ignore[arg-type]
    return updated


# ------------------------------------------------------------------ storage
FILES = {"brand.json": ("id", "name", "description", "version", "logo", "footer", "template", "references", "reference_meta",
                        "provenance", "updated_at"),
         "colors.json": ("colors",), "typography.json": ("typography",), "layouts.json": ("layout",),
         "components.json": ("components",), "shapes.json": ("shapes",), "grid.json": ("grid",),
         "video.json": ("video_style",), "voice.json": ("voice",), "media.json": ("image_sources",)}


class BrandStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or get_settings().brands_path)
        self.root.mkdir(parents=True, exist_ok=True)

    def dir(self, brand_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", brand_id or ""):
            raise UnsafePathError("Invalid brand id")
        return safe_join(self.root, brand_id)

    def exists(self, brand_id: str) -> bool:
        try:
            return (self.dir(brand_id) / "brand.json").exists()
        except UnsafePathError:
            return False

    def list(self) -> list[BrandProfile]:
        out = []
        for p in sorted(self.root.iterdir()):
            if (p / "brand.json").exists():
                try:
                    out.append(self.load(p.name))
                except Exception:
                    continue
        return out

    def load(self, brand_id: str) -> BrandProfile:
        d = self.dir(brand_id)
        if not (d / "brand.json").exists():
            raise FileNotFoundError(f"Brand '{brand_id}' not found")
        data: dict = json.loads((d / "brand.json").read_text(encoding="utf-8"))
        for fname, keys in FILES.items():
            if fname == "brand.json":
                continue
            f = d / fname
            if f.exists():
                data[keys[0]] = json.loads(f.read_text(encoding="utf-8"))
        return BrandProfile.model_validate(data)

    def save(self, brand: BrandProfile) -> BrandProfile:
        d = self.dir(brand.id)
        for sub in ("assets", "references", "assets/fonts"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        brand.updated_at = utcnow()
        dump = brand.model_dump(mode="json")
        for fname, keys in FILES.items():
            payload = {k: dump[k] for k in keys} if fname == "brand.json" else dump[keys[0]]
            (d / fname).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return brand

    def create(self, name: str, description: str = "") -> BrandProfile:
        base = slugify(name, 40).replace("-", "_") or "brand"
        bid, i = base, 2
        while self.exists(bid):
            bid, i = f"{base}_{i}", i + 1
        return self.save(BrandProfile(id=bid, name=name.strip() or bid, description=description))

    def delete(self, brand_id: str) -> None:
        shutil.rmtree(self.dir(brand_id), ignore_errors=True)

    SUBDIRS = {"assets": "assets", "references": "references", "fonts": "assets/fonts", "logo": "assets/logo"}

    def save_asset(self, brand_id: str, kind: Literal["assets", "references", "fonts", "logo"], filename: str, data: bytes) -> str:
        name = sanitize_filename(filename)
        target = safe_join(self.dir(brand_id), self.SUBDIRS[kind], name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return name

    def asset_path(self, brand_id: str, kind: str, filename: str) -> Path:
        # `filename` may carry one known sub-folder prefix, e.g. "logo/logo_dark.png"
        if kind == "assets" and "/" in filename:
            sub, _, filename = filename.partition("/")
            if sub not in ("logo", "fonts"):
                raise UnsafePathError("Invalid asset path")
            kind = sub
        return safe_join(self.dir(brand_id), self.SUBDIRS[kind], sanitize_filename(filename))


def ensure_default_brands() -> None:
    """Create the Zensar profile shell on first run - intentionally empty (no assumed values)."""
    store = BrandStore()
    if not store.exists("zensar"):
        store.save(BrandProfile(
            id="zensar", name="Zensar",
            description="Zensar brand profile. Configure it from the supplied Zensar references "
                        "(template, colours, typography, logo) in the Brand Manager.",
        ))
