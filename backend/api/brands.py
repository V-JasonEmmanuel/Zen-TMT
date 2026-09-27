"""Brand Manager API: profiles, assets, reference/template analysis, suggestions and previews."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from backend.branding.brand_profile import BrandProfile, BrandStore, Provenance, apply_value
from backend.branding.fonts import list_families, reset_font_index
from backend.branding.reference_analyzer import analyze_references
from backend.branding.template_parser import analyze_pptx
from backend.branding.theme import build_theme
from backend.storage.database import get_db
from backend.utils.config import get_settings
from backend.utils.files import UnsafePathError, new_id, safe_join, sanitize_filename

router = APIRouter(prefix="/api", tags=["brands"])
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_ASSET = 40 * 1024 * 1024


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""


class Suggestion(BaseModel):
    path: str
    value: Any
    confidence: float = 0.5
    source: Literal["pptx_template", "reference_image", "manual"] = "manual"
    reason: str = ""


class ApplyRequest(BaseModel):
    items: list[Suggestion]


def _store() -> BrandStore:
    return BrandStore()


def _load(brand_id: str) -> BrandProfile:
    try:
        return _store().load(brand_id)
    except (FileNotFoundError, UnsafePathError) as exc:
        raise HTTPException(404, "Brand not found") from exc


def _view(b: BrandProfile) -> dict:
    theme = build_theme(b, _store())
    d = _store().dir(b.id)
    refs = sorted(p.name for p in (d / "references").glob("*") if p.suffix.lower() in IMAGE_EXT)
    templates = sorted(p.name for p in (d / "references").glob("*") if p.suffix.lower() in (".pptx", ".potx"))
    return {"profile": b.model_dump(), "status": b.status, "missing": b.missing(), "fallbacks": theme.fallbacks,
            "resolved": {"colors": theme.colors, "heading_font": theme.heading_font, "body_font": theme.body_font,
                         "slide_size": [theme.slide_w, theme.slide_h]},
            "reference_images": refs, "templates": templates}


def _save(b: BrandProfile) -> BrandProfile:
    b = _store().save(b)
    get_db().upsert_brand(b.id, b.name, b.status)
    return b


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_ASSET:
        raise HTTPException(400, "File is too large (40 MB max)")
    if not data:
        raise HTTPException(400, "File is empty")
    return data


@router.get("/brands")
def list_brands():
    return [{"id": b.id, "name": b.name, "description": b.description, "status": b.status, "updated_at": b.updated_at,
             "primary": b.colors.primary, "logo": b.logo.file} for b in _store().list()]


@router.post("/brands")
def create_brand(body: BrandCreate):
    b = _store().create(body.name, body.description)
    get_db().upsert_brand(b.id, b.name, b.status)
    return _view(b)


@router.get("/brands/{brand_id}")
def get_brand(brand_id: str):
    return _view(_load(brand_id))


@router.put("/brands/{brand_id}")
def update_brand(brand_id: str, profile: dict[str, Any]):
    old = _load(brand_id)
    profile["id"] = old.id
    try:
        new = BrandProfile.model_validate(profile)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])) from exc
    # values changed through the editor become 'manual' with full confidence; cleared values lose provenance
    old_d, new_d = old.model_dump(), new.model_dump()
    old_flat, new_flat = {}, {}
    for section in ("colors", "typography", "layout", "components", "logo", "footer"):
        old_flat.update(_flatten(old_d[section], section))
        new_flat.update(_flatten(new_d[section], section))
    for k, v in new_flat.items():
        if old_flat.get(k) != v:
            if v in (None, "", []):
                new.provenance.pop(k, None)
            else:
                new.provenance[k] = Provenance(source="manual", confidence=1.0)
    return _view(_save(new))


def _flatten(d: Any, prefix: str) -> dict[str, Any]:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}.{k}"))
    else:
        out[prefix] = d
    return out


@router.delete("/brands/{brand_id}")
def delete_brand(brand_id: str):
    _load(brand_id)
    if brand_id == "zensar":
        raise HTTPException(400, "The Zensar profile cannot be deleted (it can be reset in the editor).")
    _store().delete(brand_id)
    get_db().delete_brand(brand_id)
    return {"deleted": brand_id}


# ------------------------------------------------------------------ assets
@router.post("/brands/{brand_id}/logo")
async def upload_logo(brand_id: str, file: UploadFile = File(...), variant: Literal["default", "dark"] = "default"):
    b = _load(brand_id)
    if Path(file.filename or "").suffix.lower() not in IMAGE_EXT:
        raise HTTPException(400, "Upload a PNG, JPG or WebP logo")
    name = _store().save_asset(brand_id, "assets", f"logo{'_dark' if variant == 'dark' else ''}{Path(file.filename).suffix.lower()}", await _read(file))
    b = apply_value(b, "logo.file_on_dark" if variant == "dark" else "logo.file", name)
    return _view(_save(b))


@router.post("/brands/{brand_id}/fonts")
async def upload_font(brand_id: str, file: UploadFile = File(...)):
    _load(brand_id)
    if Path(file.filename or "").suffix.lower() not in (".ttf", ".otf"):
        raise HTTPException(400, "Upload a .ttf or .otf font file")
    _store().save_asset(brand_id, "fonts", file.filename, await _read(file))
    reset_font_index()
    return {"fonts": list_families()}


@router.post("/brands/{brand_id}/references")
async def upload_references(brand_id: str, files: list[UploadFile] = File(...)):
    b = _load(brand_id)
    for f in files:
        if Path(f.filename or "").suffix.lower() not in IMAGE_EXT:
            raise HTTPException(400, f"'{f.filename}' is not an image")
        name = _store().save_asset(brand_id, "references", f.filename, await _read(f))
        if name not in b.references:
            b.references.append(name)
    return _view(_save(b))


@router.delete("/brands/{brand_id}/references/{name}")
def delete_reference(brand_id: str, name: str):
    b = _load(brand_id)
    p = _store().asset_path(brand_id, "references", name)
    if p.exists():
        p.unlink()
    b.references = [r for r in b.references if r != sanitize_filename(name)]
    if b.template.file == sanitize_filename(name):
        b.template.file = None
    return _view(_save(b))


@router.get("/brands/{brand_id}/assets/{kind}/{name}")
def get_asset(brand_id: str, kind: Literal["assets", "references"], name: str):
    _load(brand_id)
    try:
        p = _store().asset_path(brand_id, kind, name)
    except UnsafePathError as exc:
        raise HTTPException(400, "Invalid path") from exc
    if not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p)


# ------------------------------------------------------------------ analysis
@router.post("/brands/{brand_id}/analyze-references")
def analyze_brand_references(brand_id: str):
    b = _load(brand_id)
    d = _store().dir(brand_id) / "references"
    paths = [p for p in sorted(d.glob("*")) if p.suffix.lower() in IMAGE_EXT]
    if not paths:
        raise HTTPException(400, "Upload reference images first")
    result = analyze_references(paths)
    for s in result["suggestions"]:
        s["source"] = "reference_image"
    return result | {"brand": b.id}


@router.post("/brands/{brand_id}/template")
async def upload_template(brand_id: str, file: UploadFile = File(...)):
    """Store a reference PPTX/POTX for the brand and return its analysis + suggested values."""
    b = _load(brand_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pptx", ".potx"):
        raise HTTPException(400, "Upload a .pptx or .potx template")
    data = await _read(file)
    name = _store().save_asset(brand_id, "references", f"template{'.pptx'}", data)
    path = _store().asset_path(brand_id, "references", name)
    if suffix == ".potx":  # python-pptx opens POTX once the content type is switched
        _potx_to_pptx(path)
    try:
        analysis = analyze_pptx(path, extract_dir=_store().dir(brand_id) / "assets")
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "The template could not be read as a PowerPoint file.") from exc
    b.template.file = name
    _save(b)
    tid = new_id("tpl_")
    get_db().add_template({"id": tid, "brand_id": brand_id, "name": sanitize_filename(file.filename or name),
                           "path": f"{brand_id}/references/{name}", "analysis": analysis})
    for s in analysis["suggestions"]:
        s["source"] = "pptx_template"
    return {"template_id": tid, "analysis": analysis, "brand": _view(_load(brand_id))}


def _potx_to_pptx(path: Path) -> None:
    import zipfile

    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
            zout.writestr(item, data)
    tmp.replace(path)


@router.post("/brands/{brand_id}/apply-suggestions")
def apply_suggestions(brand_id: str, body: ApplyRequest):
    b = _load(brand_id)
    errors = []
    for s in body.items:
        try:
            b = apply_value(b, s.path, s.value, s.source, s.confidence, s.reason)
        except (ValueError, ValidationError) as exc:
            errors.append(f"{s.path}: {exc}")
    return _view(_save(b)) | {"errors": errors}


@router.post("/brands/{brand_id}/reset")
def reset_brand(brand_id: str):
    b = _load(brand_id)
    fresh = BrandProfile(id=b.id, name=b.name, description=b.description, references=b.references)
    return _view(_save(fresh))


# ------------------------------------------------------------------ preview
@router.post("/brands/{brand_id}/preview")
def preview(brand_id: str):
    """Render sample slides with the brand's theme. Sample text is placeholder, not content."""
    from backend.rendering.images.raster import RasterRenderer
    from backend.rendering.layouts import RenderContext, build_slide_scene
    from backend.schemas import KPI, ChartData, ChartSeries, Claim, ContentContract, ContentPlan, Slide, SourceReference, Step

    b = _load(brand_id)
    theme = build_theme(b, _store())
    ref = SourceReference(document_id="sample", document_name="sample-document.pdf", page=3, section="Results")
    pt = lambda t: Claim(text=t, status="structural")  # noqa: E731
    slides = [
        Slide(slide_number=1, layout="cover", title="Presentation Title Placeholder", subtitle="Subtitle placeholder · Audience"),
        Slide(slide_number=2, layout="key_findings", title="Key Findings Heading", sources=[ref],
              key_points=[pt("First sample finding text shown in the brand body font."), pt("Second sample finding with a little more text to show wrapping behaviour."), pt("Third sample finding.")]),
        Slide(slide_number=3, layout="chart", title="Chart Heading", sources=[ref], key_points=[pt("Sample takeaway for the chart."), pt("Another sample takeaway.")],
              chart=ChartData(categories=["Category A", "Category B", "Category C", "Category D"],
                              series=[ChartSeries(name="Series 1", values=[42, 55, 61, 74]), ChartSeries(name="Series 2", values=[38, 47, 58, 66])], source="")),
        Slide(slide_number=4, layout="process", title="Process Heading", sources=[ref],
              steps=[Step(title="Stage one", description="Sample description of the first stage."), Step(title="Stage two", description="Sample description."),
                     Step(title="Stage three", description="Sample description."), Step(title="Stage four", description="Sample description.")]),
        Slide(slide_number=5, layout="kpi", title="Metrics Heading", sources=[ref],
              kpis=[KPI(value="00%", label="Sample metric label"), KPI(value="0.0x", label="Sample metric label"), KPI(value="000", label="Sample metric label")]),
    ]
    plan = ContentPlan(contract=ContentContract(), slides=slides, title="Preview")
    out_dir = get_settings().data_path / "previews" / brand_id
    out_dir.mkdir(parents=True, exist_ok=True)
    rr = RasterRenderer(1280)
    names = []
    ctx = RenderContext(plan)
    for s in slides:
        name = f"preview_{s.slide_number}.png"
        rr.save(build_slide_scene(s, theme, ctx), out_dir / name)
        names.append(name)
    return {"images": names, "fallbacks": theme.fallbacks}


@router.get("/brands/{brand_id}/preview/{name}")
def preview_image(brand_id: str, name: str):
    try:
        p = safe_join(get_settings().data_path / "previews", brand_id, sanitize_filename(name))
    except UnsafePathError as exc:
        raise HTTPException(400, "Invalid path") from exc
    if not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@router.get("/fonts")
def fonts():
    return {"families": list_families()}


__all__ = ["router", "Optional"]
