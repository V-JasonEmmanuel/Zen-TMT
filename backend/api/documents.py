"""Source upload and inspection: documents, demo videos, repository archives and GitHub repositories."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.ingestion import supported_extensions
from backend.services.documents import HEAVY_FORMATS, DocumentError, process_document, store_upload_file
from backend.storage.database import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


class GitHubImport(BaseModel):
    url: str
    token: str = ""


def _public(row: dict) -> dict:
    meta = row.get("meta") or {}
    kind = "video" if row.get("format") in ("mp4", "mov", "webm", "mkv", "avi", "m4v") else \
        "repository" if row.get("format") == "zip" else "document"
    return {k: row.get(k) for k in ("id", "filename", "format", "size", "page_count", "status", "extraction_method",
                                    "error", "structure", "created_at")} | {
        "warnings": meta.get("warnings", []), "title": meta.get("title", ""), "ocr_may_help": meta.get("ocr_may_help", False),
        "kind": kind, "media_asset_id": meta.get("media_asset_id"), "duration": meta.get("duration"),
        "source_url": meta.get("source_url", ""),
        "deferred": row.get("status") == "uploaded" and row.get("format") in HEAVY_FORMATS}


@router.get("/formats")
def formats():
    return {"extensions": supported_extensions()}


def _stream_to_temp(file: UploadFile) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(tmp, "wb") as out:
        shutil.copyfileobj(file.file, out, 1 << 20)
    return Path(tmp)


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    db = get_db()
    tmp = _stream_to_temp(file)
    try:
        row = store_upload_file(db, file.filename or "document", tmp)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)
    if row["format"] not in HEAVY_FORMATS:  # documents are analysed immediately; videos/repos during generation
        try:
            process_document(db, row["id"])
        except DocumentError:
            pass  # status + user-facing error are stored on the document row
    return _public(db.get_document(row["id"]))


@router.post("/github")
def import_github(body: GitHubImport):
    """Download a GitHub repository (explicit online action; only the repository URL is sent)."""
    from backend.services.github import GitHubError, download_repo

    try:
        path, name = download_repo(body.url, body.token)
    except GitHubError as exc:
        raise HTTPException(400, str(exc)) from exc
    db = get_db()
    try:
        row = store_upload_file(db, name, path)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)
    db.update_document(row["id"], meta={**(row.get("meta") or {}), "source_url": body.url.strip()})
    return _public(db.get_document(row["id"]))


@router.get("")
def list_documents(limit: int = 50):
    return [_public(r) for r in get_db().list_documents(min(limit, 200))]


@router.get("/{document_id}")
def get_document(document_id: str):
    row = get_db().get_document(document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    return _public(row)


@router.post("/{document_id}/reprocess")
def reprocess(document_id: str):
    db = get_db()
    if not db.get_document(document_id):
        raise HTTPException(404, "Document not found")
    try:
        process_document(db, document_id, force=True)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _public(db.get_document(document_id))


@router.get("/{document_id}/chunks")
def chunks(document_id: str, limit: int = 500):
    db = get_db()
    if not db.get_document(document_id):
        raise HTTPException(404, "Document not found")
    return [{"id": c.id, "page": c.page, "page_end": c.page_end, "section": c.section, "section_type": c.section_type.value,
             "content_type": c.content_type.value, "text": c.text, "reference": c.source_reference}
            for c in db.get_chunks(document_id)[: min(limit, 2000)]]
