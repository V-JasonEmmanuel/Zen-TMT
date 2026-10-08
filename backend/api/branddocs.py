"""Brand Documents API: learn a template from a reference PDF; convert text / PDF / Word documents into it
(PDF output with images generated on this computer for the content)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.branddocs import service

router = APIRouter(prefix="/api/branddocs", tags=["branddocs"])
MAX_MB = 200


def _save_upload(file: UploadFile) -> Path:
    fd, name = tempfile.mkstemp(suffix=Path(file.filename or "").suffix.lower())
    os.close(fd)
    tmp = Path(name)
    with open(tmp, "wb") as out:
        shutil.copyfileobj(file.file, out, 1 << 20)
    if tmp.stat().st_size > MAX_MB * 1024 * 1024:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"The file is larger than {MAX_MB} MB")
    return tmp


@router.get("/status")
def status(refresh: bool = False):
    from backend.branddocs import imagegen

    return {"images": imagegen.status(refresh=refresh)}


# ------------------------------------------------------------------ templates
@router.get("/templates")
def templates():
    return service.list_templates()


@router.post("/templates")
def create_template(file: UploadFile = File(...), name: str = Form(""), brand_id: str = Form("")):
    tmp = _save_upload(file)
    try:
        return service.create_template(file.filename or "reference.pdf", tmp, name, brand_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)


def _tpl(tid: str):
    try:
        return service.load_template(tid)
    except KeyError as exc:
        raise HTTPException(404, "Template not found") from exc


@router.get("/templates/{tid}")
def get_template(tid: str):
    return service.template_summary(_tpl(tid))


@router.put("/templates/{tid}")
def update_template(tid: str, body: dict[str, Any]):
    _tpl(tid)
    return service.update_template(tid, body)


@router.delete("/templates/{tid}")
def delete_template(tid: str):
    _tpl(tid)
    service.delete_template(tid)
    return {"deleted": tid}


@router.get("/templates/{tid}/files/{rel:path}")
def template_file(tid: str, rel: str):
    _tpl(tid)
    try:
        return FileResponse(service.template_file(tid, rel))
    except KeyError as exc:
        raise HTTPException(404, "File not found") from exc


# ------------------------------------------------------------------ documents
@router.get("")
def docs():
    return service.list_docs()


@router.post("")
def convert(file: Optional[UploadFile] = File(None), text: str = Form(""), name: str = Form(""), template_id: str = Form(...),
            label: Optional[str] = Form(None), title: str = Form(""), images: int = Form(-1), use_llm: bool = Form(True),
            generate_images: bool = Form(True), length: str = Form("reference"), words: int = Form(0)):
    _tpl(template_id)
    if length not in ("reference", "custom", "full"):
        raise HTTPException(400, "length must be reference, custom or full")
    opts = {"label": label, "title": title, "images": max(-1, min(6, images)), "use_llm": use_llm, "generate_images": generate_images,
            "length": length, "words": max(0, min(20000, words))}
    tmp = None
    try:
        if file is not None and file.filename:
            tmp = _save_upload(file)
            return service.create_doc(file.filename, tmp, "", template_id, opts)
        if not text.strip():
            raise HTTPException(400, "Upload a document or paste its text")
        return service.create_doc(name.strip() or "Pasted text.md", None, text, template_id, opts)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _meta(did: str) -> dict:
    try:
        return service.load_meta(did)
    except KeyError as exc:
        raise HTTPException(404, "Document not found") from exc


@router.get("/{did}")
def get_doc(did: str):
    return {**_meta(did), "running": service.is_running(did)}


@router.post("/{did}/rerun")
def rerun(did: str, body: dict[str, Any]):
    _meta(did)
    if service.is_running(did):
        raise HTTPException(409, "The document is being converted - wait for it to finish.")
    try:
        return service.rerun(did, body)
    except KeyError as exc:
        raise HTTPException(404, "Template not found") from exc


@router.delete("/{did}")
def delete_doc(did: str):
    _meta(did)
    if service.is_running(did):
        raise HTTPException(409, "The document is being converted.")
    service.delete_doc(did)
    return {"deleted": did}


@router.get("/{did}/files/{rel:path}")
def doc_file(did: str, rel: str, download: bool = False):
    meta = _meta(did)
    try:
        p = service.doc_file(did, rel)
    except KeyError as exc:
        raise HTTPException(404, "File not found") from exc
    stem = "".join(ch for ch in (meta.get("title") or "document")[:70] if ch.isalnum() or ch in " -_").strip().replace(" ", "_") or "document"
    name = f"{stem}.pdf" if p.name == "document.pdf" else p.name
    return FileResponse(p, filename=name if download else None, content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "no-cache"})
