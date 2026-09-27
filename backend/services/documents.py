"""Document service: store an upload, extract + structure + chunk it once, and cache the results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.extraction.structure import analyze_structure
from backend.ingestion import ExtractionError, get_adapter, supported_extensions
from backend.intelligence.chunking import chunk_document
from backend.schemas import DocumentChunk, DocumentStructure, ExtractedDocument
from backend.storage.database import Database
from backend.utils.config import get_settings
from backend.utils.files import new_id, safe_join, sanitize_filename, sha256_file
from backend.utils.logging import get_logger

log = get_logger(__name__)
EXTRACTOR_VERSION = "3"


class DocumentError(Exception):
    def __init__(self, message: str, *, ocr_may_help: bool = False):
        super().__init__(message)
        self.ocr_may_help = ocr_may_help


def doc_dir(document_id: str) -> Path:
    return safe_join(get_settings().documents_path, document_id)


def store_upload(db: Database, filename: str, data: bytes) -> dict[str, Any]:
    s = get_settings()
    name = sanitize_filename(filename, default="document")
    ext = Path(name).suffix.lower()
    if ext not in supported_extensions():
        raise DocumentError(f"Unsupported file type '{ext or '?'}'. Supported: {', '.join(supported_extensions())}")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise DocumentError(f"The file is larger than the {s.max_upload_mb} MB limit.")
    if not data:
        raise DocumentError("The file is empty.")
    did = new_id("doc_")
    d = doc_dir(did)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"original{ext}"
    path.write_bytes(data)
    sha = sha256_file(path)
    db.create_document({"id": did, "filename": name, "stored_path": str(path.relative_to(s.data_path)), "sha256": sha,
                        "format": ext.lstrip("."), "size": len(data), "status": "uploaded"})
    log.info("Document uploaded", document=did, format=ext, bytes=len(data))
    return db.get_document(did)  # type: ignore[return-value]


def process_document(db: Database, document_id: str, force: bool = False) -> tuple[ExtractedDocument, DocumentStructure, list[DocumentChunk]]:
    """Extract, analyse and chunk a document. Cached on disk + in SQLite; re-used on every later run."""
    row = db.get_document(document_id)
    if not row:
        raise DocumentError("Document not found")
    d = doc_dir(document_id)
    cache = d / "extraction.json"
    if cache.exists() and not force:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("version") == EXTRACTOR_VERSION:
            doc = ExtractedDocument.model_validate(payload["document"])
            st = DocumentStructure.model_validate(payload["structure"])
            chunks = db.get_chunks(document_id)
            if chunks:
                return doc, st, chunks
    path = get_settings().data_path / row["stored_path"]
    try:
        doc = get_adapter(path).extract(path, document_id, d)
    except ExtractionError as exc:
        db.update_document(document_id, status="failed", error=str(exc), meta={"ocr_may_help": exc.ocr_may_help})
        raise DocumentError(str(exc), ocr_may_help=exc.ocr_may_help) from exc
    except Exception as exc:
        log.exception("Extraction crashed", document=document_id)
        db.update_document(document_id, status="failed", error="The document could not be read.")
        raise DocumentError("The document could not be read. It may be corrupted or in an unsupported variant of the format.") from exc
    doc.filename = row["filename"]
    st = analyze_structure(doc)
    chunks = chunk_document(doc, st)
    for c in chunks:
        c.document_name = row["filename"]
    cache.write_text(json.dumps({"version": EXTRACTOR_VERSION, "document": doc.model_dump(mode="json"),
                                 "structure": st.model_dump(mode="json")}), encoding="utf-8")
    db.replace_chunks(document_id, chunks)
    summary = structure_summary(doc, st, chunks)
    db.update_document(document_id, status="ready", page_count=doc.page_count, extraction_method=doc.extraction_method,
                       error="", structure=summary, meta={"warnings": doc.warnings, "title": doc.title})
    log.info("Document processed", document=document_id, pages=doc.page_count, sections=len(st.sections), chunks=len(chunks))
    return doc, st, chunks


def structure_summary(doc: ExtractedDocument, st: DocumentStructure, chunks: list[DocumentChunk]) -> dict[str, Any]:
    return {
        "title": st.title,
        "pages": doc.page_count,
        "sections": [{"id": s.id, "title": s.title, "level": s.level, "type": s.section_type.value,
                      "pages": [s.page_start, s.page_end]} for s in st.sections],
        "detected_types": [t.value for t in st.detected_types],
        "tables": st.table_count,
        "figures": st.figure_count,
        "chunks": len(chunks),
        "extraction_method": doc.extraction_method,
        "warnings": doc.warnings,
    }
