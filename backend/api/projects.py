"""Projects: CRUD, content plan review/editing, per-slide regeneration, file access and downloads."""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from backend.pipeline.jobs import runner
from backend.pipeline.orchestrator import STAGES_BY_KIND, apply_slide_edit, context_for_project
from backend.pipeline.outputs import OutputWriter, project_output_dir, project_work_dir
from backend.planning.slide_planner import SPECS
from backend.schemas import LAYOUTS
from backend.storage.database import get_db
from backend.utils.files import UnsafePathError, new_id, safe_join, slugify

router = APIRouter(prefix="/api/projects", tags=["projects"])
FORMATS = {"pptx", "pdf", "png", "mp4"}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    document_id: str
    brand_id: str = "zensar"
    template_id: Optional[str] = None
    instruction: str = Field(min_length=3, max_length=4000)
    output_formats: list[str] = Field(default_factory=lambda: ["pptx", "pdf", "png"])
    options: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    brand_id: Optional[str] = None
    instruction: Optional[str] = Field(default=None, min_length=3, max_length=4000)
    output_formats: Optional[list[str]] = None
    options: Optional[dict[str, Any]] = None


class RegenerateRequest(BaseModel):
    layout: Optional[str] = None
    guidance: str = Field(default="", max_length=600)


def _get(project_id: str) -> dict:
    p = get_db().get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _formats(values: list[str]) -> list[str]:
    bad = [v for v in values if v not in FORMATS]
    if bad:
        raise HTTPException(400, f"Unsupported output format(s): {', '.join(bad)}")
    return list(dict.fromkeys(values)) or ["pptx"]


def _summary(p: dict) -> dict:
    db = get_db()
    doc = db.get_document(p["document_id"]) if p.get("document_id") else None
    job = db.get_job(p["last_job_id"]) if p.get("last_job_id") else None
    outs = db.list_outputs(p["id"])
    thumb = next((o.path for o in outs if o.kind == "slide_image"), None)
    return {**p, "document": {"id": doc["id"], "filename": doc["filename"], "pages": doc["page_count"], "status": doc["status"]} if doc else None,
            "last_job": job.model_dump() if job else None, "thumbnail": thumb,
            "output_counts": {k: sum(1 for o in outs if o.kind == k) for k in {o.kind for o in outs}}}


@router.get("")
def list_projects():
    return [_summary(p) for p in get_db().list_projects()]


@router.post("")
def create_project(body: ProjectCreate):
    db = get_db()
    doc = db.get_document(body.document_id)
    if not doc:
        raise HTTPException(400, "Upload a document first")
    if doc["status"] == "failed":
        raise HTTPException(400, doc.get("error") or "The document could not be processed")
    from backend.branding.brand_profile import BrandStore

    if not BrandStore().exists(body.brand_id):
        raise HTTPException(400, f"Brand '{body.brand_id}' not found")
    pid = new_id("prj_")
    slug = slugify(body.name)
    p = db.create_project({"id": pid, "name": body.name.strip(), "slug": slug, "status": "draft", "brand_id": body.brand_id,
                           "template_id": body.template_id, "document_id": body.document_id, "instruction": body.instruction.strip(),
                           "output_formats": _formats(body.output_formats), "options": body.options,
                           "output_dir": f"{slug}_{pid[-6:]}"})
    return _summary(p)


@router.get("/{project_id}")
def get_project(project_id: str):
    p = _get(project_id)
    out = _summary(p)
    out["outputs"] = [o.model_dump() for o in get_db().list_outputs(project_id)]
    out["jobs"] = [j.model_dump() for j in get_db().list_jobs(project_id)[:10]]
    return out


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectPatch):
    p = _get(project_id)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.brand_id is not None:
        fields["brand_id"] = body.brand_id
    if body.instruction is not None:
        fields["instruction"] = body.instruction.strip()
    if body.output_formats is not None:
        fields["output_formats"] = _formats(body.output_formats)
    if body.options is not None:
        fields["options"] = {**p["options"], **body.options}
    get_db().update_project(project_id, **fields)
    return _summary(_get(project_id))


@router.delete("/{project_id}")
def delete_project(project_id: str):
    p = _get(project_id)
    if runner.current and (j := get_db().get_job(runner.current)) and j.project_id == project_id:
        raise HTTPException(409, "This project is generating. Cancel the job first.")
    for d in (project_output_dir(p), project_work_dir(p)):
        shutil.rmtree(d, ignore_errors=True)
    get_db().delete_project(project_id)
    return {"deleted": project_id}


# ------------------------------------------------------------------ plan / review
@router.get("/{project_id}/plan")
def get_plan(project_id: str):
    _get(project_id)
    plan = get_db().latest_plan(project_id)
    if not plan:
        raise HTTPException(404, "No content plan yet")
    data = plan.model_dump()
    for s, sd in zip(plan.slides, data["slides"]):
        sd["needs_review"] = s.needs_review
    return data


@router.get("/{project_id}/layouts")
def layouts(project_id: str):
    return [{"id": l, "guidance": SPECS[l].guidance} for l in LAYOUTS]


@router.put("/{project_id}/plan/slides/{slide_number}")
def edit_slide(project_id: str, slide_number: int, edited: dict[str, Any]):
    """Human review edits. Source mappings are preserved; changed statements are re-verified and flagged."""
    p = _get(project_id)
    db = get_db()
    plan = db.latest_plan(project_id)
    if not plan or not any(s.slide_number == slide_number for s in plan.slides):
        raise HTTPException(404, "Slide not found")
    if "layout" in edited and edited["layout"] not in LAYOUTS:
        raise HTTPException(400, "Unsupported layout")
    try:
        ctx = context_for_project(p)
    except Exception:
        ctx = None
    try:
        plan = apply_slide_edit(plan, slide_number, edited, ctx)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"Invalid slide content: {exc}") from exc
    db.save_plan(plan)
    job = runner.submit(project_id, "render", STAGES_BY_KIND["render"], {"reason": "edit", "slide_number": slide_number})
    return {"plan_version": plan.version, "job": job.model_dump()}


@router.post("/{project_id}/slides/{slide_number}/regenerate")
def regenerate_slide(project_id: str, slide_number: int, body: RegenerateRequest):
    _get(project_id)
    if body.layout and body.layout not in LAYOUTS:
        raise HTTPException(400, "Unsupported layout")
    job = runner.submit(project_id, "slide", STAGES_BY_KIND["slide"],
                        {"slide_number": slide_number, "layout": body.layout, "guidance": body.guidance})
    return job.model_dump()


@router.get("/{project_id}/sources")
def sources(project_id: str):
    p = _get(project_id)
    f = project_output_dir(p) / "source" / "source_mapping.json"
    if not f.exists():
        raise HTTPException(404, "No source mapping yet")
    return Response(f.read_text(encoding="utf-8"), media_type="application/json")


# ------------------------------------------------------------------ files
@router.get("/{project_id}/outputs")
def outputs(project_id: str):
    _get(project_id)
    return [o.model_dump() for o in get_db().list_outputs(project_id)]


@router.get("/{project_id}/files/{rel_path:path}")
def get_file(project_id: str, rel_path: str, download: bool = False, format: Optional[str] = None):
    p = _get(project_id)
    base = project_output_dir(p)
    try:
        path = safe_join(base, rel_path)
    except UnsafePathError as exc:
        raise HTTPException(400, "Invalid path") from exc
    if not path.is_file():
        raise HTTPException(404, "File not found")
    name = f"{p['slug']}_{path.name}" if download else path.name
    if format and format.lower() in ("jpg", "jpeg") and path.suffix.lower() == ".png":
        buf = io.BytesIO()
        Image.open(path).convert("RGB").save(buf, "JPEG", quality=92)
        headers = {"Content-Disposition": f'attachment; filename="{Path(name).stem}.jpg"'} if download else {}
        return Response(buf.getvalue(), media_type="image/jpeg", headers=headers)
    return FileResponse(path, filename=name if download else None,
                        headers={"Cache-Control": "no-cache"}, content_disposition_type="attachment" if download else "inline")


def _zip(base: Path, sub: Optional[str], name: str, background: BackgroundTasks) -> FileResponse:
    root = base / sub if sub else base
    if not root.exists() or not any(root.rglob("*")):
        raise HTTPException(404, "Nothing to download yet")
    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)  # Windows: an open handle would block both writing and later deletion
    tmp = Path(tmp_name)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())

    def cleanup() -> None:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # still being streamed on some platforms; the OS temp cleaner removes it

    background.add_task(cleanup)
    return FileResponse(tmp, filename=name, media_type="application/zip")


@router.get("/{project_id}/download/all")
def download_all(project_id: str, background: BackgroundTasks):
    p = _get(project_id)
    return _zip(project_output_dir(p), None, f"{p['slug']}_outputs.zip", background)


@router.get("/{project_id}/download/images")
def download_images(project_id: str, background: BackgroundTasks):
    p = _get(project_id)
    return _zip(project_output_dir(p), "images", f"{p['slug']}_images.zip", background)


@router.post("/{project_id}/rebuild-files")
def rebuild_plan_files(project_id: str):
    """Re-write content_plan.json / source_mapping.json from the latest plan (no rendering)."""
    from backend.pipeline.orchestrator import _theme

    p = _get(project_id)
    plan = get_db().latest_plan(project_id)
    if not plan:
        raise HTTPException(404, "No content plan yet")
    OutputWriter(get_db(), p, plan, _theme(p)).write_plan_files()
    return {"ok": True}
