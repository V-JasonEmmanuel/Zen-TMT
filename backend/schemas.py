"""Canonical Pydantic schemas shared by every pipeline stage.

The content plan (ContentPlan / Slide) is the single source of truth for all renderers.
Nothing is rendered directly from raw LLM output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- documents
class ContentType(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    list_item = "list"
    table = "table"
    figure = "figure"
    caption = "caption"
    code = "code"
    reference = "reference"
    metadata = "metadata"


class SectionType(str, Enum):
    title = "title"
    abstract = "abstract"
    executive_summary = "executive_summary"
    introduction = "introduction"
    background = "background"
    related_work = "related_work"
    methodology = "methodology"
    architecture = "architecture"
    implementation = "implementation"
    experiments = "experiments"
    results = "results"
    discussion = "discussion"
    conclusion = "conclusion"
    recommendations = "recommendations"
    references = "references"
    appendix = "appendix"
    acknowledgements = "acknowledgements"
    other = "other"


class Block(BaseModel):
    """One extracted unit of a document, before sectioning."""

    type: ContentType
    text: str = ""
    page: int = 1  # 1-based page / slide number
    level: int = 0  # heading level (1 = top)
    font_size: float = 0.0
    bold: bool = False
    table: Optional[list[list[str]]] = None
    table_index: Optional[int] = None
    figure_index: Optional[int] = None
    image_path: Optional[str] = None  # extracted figure image (relative to document dir)


class ExtractedDocument(BaseModel):
    document_id: str
    filename: str
    format: str
    title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    page_count: int = 0
    blocks: list[Block] = Field(default_factory=list)
    extraction_method: Literal["native", "ocr", "mixed", "none"] = "native"
    warnings: list[str] = Field(default_factory=list)


class Section(BaseModel):
    id: str
    title: str
    level: int = 1
    section_type: SectionType = SectionType.other
    page_start: int = 1
    page_end: int = 1
    block_indexes: list[int] = Field(default_factory=list)


class DocumentStructure(BaseModel):
    title: str = ""
    sections: list[Section] = Field(default_factory=list)
    detected_types: list[SectionType] = Field(default_factory=list)
    table_count: int = 0
    figure_count: int = 0


class SourceReference(BaseModel):
    document_id: str
    document_name: str = ""
    chunk_id: str = ""
    page: Optional[int] = None
    page_end: Optional[int] = None
    section: str = ""
    content_type: str = "paragraph"
    table: Optional[int] = None
    figure: Optional[int] = None

    @property
    def label(self) -> str:
        parts = [self.document_name or self.document_id]
        if self.page:
            parts.append(f"p.{self.page}" if not self.page_end or self.page_end == self.page else f"pp.{self.page}-{self.page_end}")
        if self.section:
            parts.append(self.section)
        if self.table:
            parts.append(f"Table {self.table}")
        if self.figure:
            parts.append(f"Figure {self.figure}")
        return " · ".join(parts)


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    document_name: str = ""
    index: int
    page: int
    page_end: int
    section: str = ""
    section_type: SectionType = SectionType.other
    content_type: ContentType = ContentType.paragraph
    text: str
    table: Optional[list[list[str]]] = None
    table_index: Optional[int] = None
    figure_index: Optional[int] = None
    image_path: Optional[str] = None

    @property
    def source_reference(self) -> str:
        return self.ref().label

    def ref(self) -> SourceReference:
        return SourceReference(
            document_id=self.document_id,
            document_name=self.document_name,
            chunk_id=self.id,
            page=self.page,
            page_end=self.page_end,
            section=self.section,
            content_type=self.content_type.value,
            table=self.table_index,
            figure=self.figure_index,
        )


# --------------------------------------------------------------------------- contract
class ContentContract(BaseModel):
    audience: str = "general_business"
    purpose: str = "presentation"
    slide_count: int = Field(default=10, ge=1, le=40)
    tone: str = "professional"
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    output_formats: list[str] = Field(default_factory=lambda: ["pptx", "png"])
    brand_profile: str = "zensar"
    detail_level: Literal["low", "medium", "high"] = "medium"
    language: str = "en"
    notes: str = ""
    raw_instruction: str = ""
    parse_method: str = "rules"

    @field_validator("include", "exclude")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v or []:
            s = str(item).strip().lower().replace(" ", "_")
            if s and s not in out:
                out.append(s)
        return out


# --------------------------------------------------------------------------- plan
LAYOUTS: tuple[str, ...] = (
    "cover", "section_divider", "executive_summary", "two_column", "three_column",
    "text_image", "image_text", "process", "timeline", "architecture", "workflow",
    "comparison", "kpi", "chart", "table", "research_methodology", "research_results",
    "key_findings", "quote", "conclusion", "references",
)

ClaimStatus = Literal["verified", "needs_review", "unsupported", "user_edited", "structural"]


class Claim(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)  # chunk ids
    confidence: float = 0.0
    status: ClaimStatus = "needs_review"
    evidence_page: Optional[int] = None


class Step(BaseModel):
    title: str
    description: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: ClaimStatus = "needs_review"


class KPI(BaseModel):
    value: str
    label: str
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: ClaimStatus = "needs_review"


class Column(BaseModel):
    heading: str
    points: list[Claim] = Field(default_factory=list)


class TableData(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""
    source: str = ""  # chunk id


class ChartSeries(BaseModel):
    name: str
    values: list[float]


class ChartData(BaseModel):
    chart_type: Literal["bar", "column", "line", "pie"] = "column"
    title: str = ""
    categories: list[str]
    series: list[ChartSeries]
    unit: str = ""
    source: str = ""  # chunk id


class GraphNode(BaseModel):
    id: str
    label: str
    group: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str = ""


VisualKind = Literal[
    "none", "process", "timeline", "architecture", "workflow", "kpi_cards", "chart",
    "comparison", "table", "knowledge_graph", "document_figure", "key_points",
]


class Visual(BaseModel):
    kind: VisualKind = "none"
    title: str = ""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    chart: Optional[ChartData] = None
    image_path: Optional[str] = None  # document figure
    caption: str = ""
    sources: list[str] = Field(default_factory=list)


class ImageTreatment(BaseModel):
    crop: Optional[tuple[float, float, float, float]] = None  # x, y, w, h as fractions of the source image
    rotate: int = 0  # 0/90/180/270
    flip_h: bool = False
    flip_v: bool = False
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    opacity: float = 1.0
    tint_role: Optional[str] = None  # brand colour role only
    tint_strength: float = 0.0
    duotone: bool = False
    overlay: Literal["none", "gradient", "solid"] = "none"
    overlay_role: str = "primary"
    overlay_strength: float = 0.35
    border_role: Optional[str] = None
    border_px: int = 0
    mask: Literal["rect", "circle", "diamond", "rounded", "quarter"] = "rect"


class ImageRef(BaseModel):
    asset_id: str
    fit: Literal["cover", "contain", "crop", "fill", "original"] = "cover"
    treatment: ImageTreatment = Field(default_factory=ImageTreatment)
    user_selected: bool = False  # user choices are never replaced automatically
    source_label: str = ""  # e.g. "User-provided asset", "Openverse · Jane Doe · CC BY 2.0"
    query: str = ""  # generic search query used (never document text)
    caption: str = ""


class CustomShape(BaseModel):
    """User-added brand shape. Geometry in fractions of the slide so it survives size changes."""

    kind: Literal["circle", "square", "triangle", "quarter_circle", "diamond", "module", "grid", "line", "connector", "frame", "pill"]
    x: float = Field(ge=-0.5, le=1.5)
    y: float = Field(ge=-0.5, le=1.5)
    w: float = Field(gt=0, le=2)
    h: float = Field(gt=0, le=2)
    fill_role: Optional[str] = "secondary"
    stroke_role: Optional[str] = None
    stroke_pt: float = 0.0
    opacity: float = Field(default=1.0, ge=0, le=1)
    rotation: float = 0.0
    corner: Literal["tl", "tr", "bl", "br"] = "bl"
    layer: Literal["back", "front"] = "back"


class Slide(BaseModel):
    slide_number: int
    layout: str = "executive_summary"
    title: str = ""
    subtitle: str = ""
    key_points: list[Claim] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    table: Optional[TableData] = None
    chart: Optional[ChartData] = None
    quote: Optional[Claim] = None
    visual: Optional[Visual] = None
    narration: str = ""
    speaker_notes: str = ""
    sources: list[SourceReference] = Field(default_factory=list)
    accent_role: str = "accent"  # brand colour role - never a raw colour
    image: Optional[ImageRef] = None
    custom_shapes: list[CustomShape] = Field(default_factory=list)
    background_role: Optional[str] = None  # brand role, e.g. "primary" for an indigo slide
    topic: str = ""  # planner's focus descriptor for regeneration
    candidate_chunks: list[str] = Field(default_factory=list)
    edited: bool = False
    warnings: list[str] = Field(default_factory=list)

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: str) -> str:
        if v not in LAYOUTS:
            raise ValueError(f"unsupported layout '{v}'")
        return v

    @property
    def needs_review(self) -> bool:
        items = [*self.key_points, *self.steps, *self.kpis, *(p for c in self.columns for p in c.points)]
        if self.quote:
            items.append(self.quote)
        return any(i.status in ("needs_review", "unsupported") for i in items)


class ContentPlan(BaseModel):
    project_id: str = ""
    version: int = 1
    title: str = ""
    subtitle: str = ""
    contract: ContentContract
    slides: list[Slide] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)
    generator: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- jobs
StageState = Literal["pending", "running", "done", "failed", "skipped", "warning"]


class StageStatus(BaseModel):
    key: str
    label: str
    status: StageState = "pending"
    message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class GenerationJob(BaseModel):
    id: str
    project_id: str
    kind: str = "full"
    status: Literal["queued", "running", "completed", "completed_with_warnings", "failed", "cancelled"] = "queued"
    stages: list[StageStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class OutputFile(BaseModel):
    id: str
    project_id: str
    kind: str  # pptx | pdf | image | slide_image | video | subtitles | content_plan | source_mapping
    path: str  # relative to project output dir
    size: int = 0
    created_at: str = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)
