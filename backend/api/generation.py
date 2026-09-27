"""Generation jobs (background, sequential)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.pipeline.jobs import runner
from backend.pipeline.orchestrator import STAGES_BY_KIND
from backend.storage.database import get_db

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    project_id: str
    kind: Literal["full", "render", "video"] = "full"
    include_video: bool = False  # for kind=render


class InstructionPreview(BaseModel):
    instruction: str


@router.post("/instruction/parse")
def parse_instruction_preview(body: InstructionPreview):
    """Fast, rule-based interpretation shown to the user before generating (the LLM refines it later)."""
    from backend.planning.content_contract import parse_instruction_rules

    c = parse_instruction_rules(body.instruction)
    return c.model_dump(exclude={"raw_instruction", "brand_profile", "output_formats"})


@router.post("/generate")
def generate(body: GenerateRequest):
    db = get_db()
    p = db.get_project(body.project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if p.get("last_job_id"):
        last = db.get_job(p["last_job_id"])
        if last and last.status in ("queued", "running"):
            raise HTTPException(409, "A generation job for this project is already in progress.")
    if body.kind != "full" and not db.latest_plan(body.project_id):
        raise HTTPException(400, "Generate the presentation first.")
    job = runner.submit(body.project_id, body.kind, STAGES_BY_KIND[body.kind], {"video": body.include_video})
    return job.model_dump()


@router.get("/generation/{job_id}")
def job_status(job_id: str):
    job = get_db().get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    data = job.model_dump()
    data["queue_position"] = runner.queue_position(job_id)
    return data


@router.post("/generation/{job_id}/cancel")
def cancel(job_id: str):
    job = get_db().get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    runner.cancel(job_id)
    return {"cancelling": job_id}


@router.get("/projects/{project_id}/jobs")
def project_jobs(project_id: str):
    return [j.model_dump() for j in get_db().list_jobs(project_id)[:20]]


@router.get("/outputs/{output_id}")
def output(output_id: str):
    from fastapi.responses import RedirectResponse

    o = get_db().get_output(output_id)
    if not o:
        raise HTTPException(404, "Output not found")
    return RedirectResponse(f"/api/projects/{o.project_id}/files/{o.path}?download=true")
