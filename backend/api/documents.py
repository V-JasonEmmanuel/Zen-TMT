"""Document upload and inspection."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.ingestion import supported_extensions
from backend.services.documents import DocumentError, process_document, store_upload
from backend.storage.database import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "filename", "format", "size", "page_count", "status", "extraction_method",
                                    "error", "structure", "created_at")} | {"warnings": row.get("meta", {}).get("warnings", []),
                                                                            "title": row.get("meta", {}).get("title", ""),
                                                                            "ocr_may_help": row.get("meta", {}).get("ocr_may_help", False)}


@router.get("/formats")
def formats():
    return {"extensions": supported_extensions()}


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    db = get_db()
    data = file.file.read()
    try:
        row = store_upload(db, file.filename or "document", data)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        process_document(db, row["id"])
    except DocumentError:
        pass  # status + user-facing error are stored on the document row
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
