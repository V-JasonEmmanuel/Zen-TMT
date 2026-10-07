"""Research Papers API: convert a paper (file or pasted text) to a publisher format, review and correct
the recognised structure and references, re-export to any format, download the results."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from backend.papers import service
from backend.papers.formats import FORMATS, gallery
from backend.papers.model import Paper

router = APIRouter(prefix="/api/papers", tags=["papers"])
MAX_MB = 200


class ExportRequest(BaseModel):
    format: str
    citation_style: str = ""


class ParseRequest(BaseModel):
    raw: str


def _meta(pid: str) -> dict:
    try:
        return service.load_meta(pid)
    except KeyError as exc:
        raise HTTPException(404, "Paper not found") from exc


@router.get("/formats")
def formats():
    return gallery()


@router.get("")
def list_papers():
    return service.list_all()


@router.post("")
def convert(file: Optional[UploadFile] = File(None), text: str = Form(""), format: str = Form(...),
            citation_style: str = Form(""), use_ai: bool = Form(True), name: str = Form("")):
    if format not in FORMATS:
        raise HTTPException(400, "Choose a target format")
    tmp = None
    try:
        if file is not None and file.filename:
            fd, tmp_name = tempfile.mkstemp(suffix=Path(file.filename).suffix.lower())
            os.close(fd)
            tmp = Path(tmp_name)
            with open(tmp, "wb") as out:
                shutil.copyfileobj(file.file, out, 1 << 20)
            if tmp.stat().st_size > MAX_MB * 1024 * 1024:
                raise HTTPException(400, f"The file is larger than {MAX_MB} MB")
            return service.create(file.filename, tmp, "", format, citation_style, use_ai)
        if not text.strip():
            raise HTTPException(400, "Upload a paper or paste its text")
        return service.create(name.strip() or "Pasted paper.txt", None, text, format, citation_style, use_ai)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@router.get("/{pid}")
def get_paper(pid: str):
    meta = _meta(pid)
    paper = service.load_paper(pid)
    return {**meta, "running": service.is_running(pid), "paper": paper.model_dump() if paper else None}


@router.put("/{pid}/paper")
def save_paper(pid: str, body: dict[str, Any]):
    """Corrections from the review screen (title, authors, affiliations, abstract, keywords, references)."""
    _meta(pid)
    if service.is_running(pid):
        raise HTTPException(409, "The paper is being converted - wait for it to finish.")
    try:
        paper = Paper.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])) from exc
    from backend.papers.references import completeness

    for r in paper.references:
        if r.method == "user" or r.csl:
            r.csl["id"] = r.key
            r.status = completeness(r.csl) if r.csl.get("title") else "raw"
    service.save_paper(pid, paper)
    return {"ok": True}


@router.post("/{pid}/export")
def export(pid: str, body: ExportRequest):
    meta = _meta(pid)
    if service.is_running(pid):
        raise HTTPException(409, "The paper is being converted - wait for it to finish.")
    if service.load_paper(pid) is None:
        raise HTTPException(400, "The paper has not been read yet - convert it first.")
    try:
        return service.reexport(pid, body.format, body.citation_style)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{pid}/reread")
def reread(pid: str):
    """Read the source again (discards corrections) and convert to the current format."""
    _meta(pid)
    if service.is_running(pid):
        raise HTTPException(409, "The paper is being converted.")
    service.update(pid, status="queued", message="Waiting to start", progress=0)
    service.start(pid, read_source=True)
    return service.load_meta(pid)


@router.post("/parse-reference")
def parse_reference(body: ParseRequest):
    """Parse one reference string (used when a reference is corrected in the review screen)."""
    from backend.papers.references import completeness, parse_rules, verify

    csl = verify(parse_rules(body.raw), body.raw)
    return {"csl": csl, "status": completeness(csl)}


@router.get("/{pid}/files/{rel:path}")
def get_file(pid: str, rel: str, download: bool = False):
    meta = _meta(pid)
    try:
        p = service.file_path(pid, rel)
    except KeyError as exc:
        raise HTTPException(404, "File not found") from exc
    stem = "".join(c for c in (meta.get("title") or "paper")[:60] if c.isalnum() or c in " -_").strip().replace(" ", "_") or "paper"
    name = f"{stem}_{meta.get('format', '')}{p.suffix}" if p.name.startswith("paper.") or p.name.startswith("latex_project") else p.name
    if p.name.startswith("latex_project"):
        name = f"{stem}_{meta.get('format', '')}_latex.zip"
    return FileResponse(p, filename=name if download else None, content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "no-cache"})


@router.delete("/{pid}")
def delete(pid: str):
    _meta(pid)
    if service.is_running(pid):
        raise HTTPException(409, "The paper is being converted.")
    service.delete(pid)
    return {"deleted": pid}
