"""Reference template analysis (without attaching it to a brand)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.branding.template_parser import analyze_pptx
from backend.storage.database import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
def list_templates(brand_id: Optional[str] = None):
    return [{k: t[k] for k in ("id", "brand_id", "name", "created_at")} |
            {"slide_size": (t.get("analysis") or {}).get("slide_size"), "layouts": len((t.get("analysis") or {}).get("layouts", []))}
            for t in get_db().list_templates(brand_id)]


@router.get("/gallery")
def gallery(brand_id: str = "zensar"):
    """Design presets for the brand + uploaded PowerPoint templates, each with preview images."""
    from backend.branding.presets import gallery as presets

    items = [{**g, "id": f"preset:{g['id']}", "previews": [f"/api/templates/preview/preset:{g['id']}/{n}?brand_id={brand_id}" for n in (1, 2, 3)]}
             for g in presets()]
    for t in get_db().list_templates(brand_id):
        items.append({"id": t["id"], "name": t["name"], "kind": "pptx",
                      "description": f"Uploaded PowerPoint template · {len((t.get('analysis') or {}).get('layouts', []))} layouts",
                      "previews": [f"/api/templates/preview/{t['id']}/{n}?brand_id={brand_id}" for n in (1, 2, 3)]})
    return items


@router.get("/preview/{template_id}/{n}")
def template_preview(template_id: str, n: int, brand_id: str = "zensar"):
    """Render (and cache) sample slides in a template: 1 cover, 2 content, 3 data."""
    from fastapi.responses import FileResponse

    from backend.pipeline.orchestrator import _theme
    from backend.rendering.images.raster import RasterRenderer
    from backend.rendering.layouts import RenderContext, build_slide_scene
    from backend.schemas import KPI, Claim, ContentContract, ContentPlan, Slide, SourceReference, Step
    from backend.utils.config import get_settings
    from backend.utils.files import sanitize_filename

    if n not in (1, 2, 3):
        raise HTTPException(404, "Unknown preview")
    theme = _theme({"brand_id": brand_id, "options": {"template_id": template_id}})
    import hashlib

    sig = hashlib.sha1(str(sorted((k, str(v)) for k, v in vars(theme).items() if k != "shapes")).encode()).hexdigest()[:10]
    out = get_settings().data_path / "previews" / "templates" / sanitize_filename(f"{template_id}_{brand_id}_{sig}_{n}.png")
    if not out.exists():
        ref = SourceReference(document_id="sample", document_name="sample.pdf", page=4, section="Results")
        pt = lambda t: Claim(text=t, status="structural")  # noqa: E731
        slides = {
            1: Slide(slide_number=1, layout="cover", title="Presentation title in this template", subtitle="Subtitle · audience"),
            2: Slide(slide_number=2, layout="process", title="How the solution works", topic="methodology", sources=[ref],
                     steps=[Step(title="Ingest", description="Sample step description."), Step(title="Understand", description="Sample step."),
                            Step(title="Plan", description="Sample step."), Step(title="Render", description="Sample step.")]),
            3: Slide(slide_number=3, layout="kpi", title="Key metrics", topic="results", sources=[ref],
                     kpis=[KPI(value="00%", label="Sample metric"), KPI(value="0.0x", label="Sample metric"), KPI(value="000", label="Sample metric")],
                     key_points=[pt("Sample takeaway text for the metrics.")]),
        }
        plan = ContentPlan(contract=ContentContract(), slides=list(slides.values()), title="Preview")
        out.parent.mkdir(parents=True, exist_ok=True)
        RasterRenderer(960).save(build_slide_scene(slides[n], theme, RenderContext(plan)), out)
    return FileResponse(out, headers={"Cache-Control": "max-age=3600"})


@router.get("/{template_id}")
def get_template(template_id: str):
    t = get_db().get_template(template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    return t


@router.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() not in (".pptx",):
        raise HTTPException(400, "Upload a .pptx file")
    data = await file.read()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "template.pptx"
        p.write_bytes(data)
        try:
            return analyze_pptx(p)
        except Exception as exc:
            raise HTTPException(422, "The file could not be read as a PowerPoint template.") from exc
