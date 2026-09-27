"""Section-aware chunking. Every chunk keeps document / page / section provenance."""
from __future__ import annotations

import hashlib
import re

from backend.schemas import ContentType, DocumentChunk, DocumentStructure, ExtractedDocument, SectionType

TARGET_CHARS = 900
MAX_CHARS = 1400
REFERENCE_ENTRY = re.compile(r"^\[?\d{1,3}[\].]\s|^[A-Z][a-z]+,\s+[A-Z]\.")


def _chunk_id(document_id: str, index: int, text: str) -> str:
    h = hashlib.sha1(f"{document_id}:{index}:{text[:200]}".encode()).hexdigest()[:10]
    return f"ch_{h}"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_document(doc: ExtractedDocument, structure: DocumentStructure) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    name = doc.filename

    def emit(section_title: str, stype: SectionType, ctype: ContentType, text: str, p0: int, p1: int, **extra):
        text = text.strip()
        if not text:
            return
        idx = len(chunks)
        chunks.append(DocumentChunk(
            id=_chunk_id(doc.document_id, idx, text), document_id=doc.document_id, document_name=name,
            index=idx, page=p0, page_end=p1, section=section_title, section_type=stype,
            content_type=ctype, text=text, **extra,
        ))

    for sec in structure.sections:
        buf: list[str] = []
        p0 = p1 = sec.page_start
        buf_type = ContentType.paragraph

        def flush():
            nonlocal buf, p0
            if buf:
                emit(sec.title, sec.section_type, buf_type, "\n".join(buf), p0, p1)
            buf = []

        for bi in sec.block_indexes:
            b = doc.blocks[bi]
            if b.type == ContentType.table:
                flush()
                emit(sec.title, sec.section_type, ContentType.table, b.text[:3000], b.page, b.page,
                     table=b.table, table_index=b.table_index)
                p0 = b.page
                continue
            if b.type == ContentType.figure:
                flush()
                emit(sec.title, sec.section_type, ContentType.figure, b.text, b.page, b.page,
                     figure_index=b.figure_index, image_path=b.image_path)
                p0 = b.page
                continue
            if b.type == ContentType.code:
                flush()
                emit(sec.title, sec.section_type, ContentType.code, b.text[:2000], b.page, b.page)
                p0 = b.page
                continue
            ctype = ContentType.reference if sec.section_type == SectionType.references else (
                ContentType.caption if b.type == ContentType.caption else ContentType.paragraph)
            if ctype != buf_type and buf:
                flush()
            if not buf:
                p0 = b.page
            buf_type = ctype
            text = f"- {b.text}" if b.type == ContentType.list_item else b.text
            if len(text) > MAX_CHARS:  # very long paragraph: split on sentences
                flush()
                p0 = b.page
                cur = ""
                for s in split_sentences(text):
                    if len(cur) + len(s) > TARGET_CHARS and cur:
                        emit(sec.title, sec.section_type, ctype, cur, b.page, b.page)
                        cur = ""
                    cur = f"{cur} {s}".strip()
                if cur:
                    buf, p1 = [cur], b.page
                continue
            if sum(len(x) for x in buf) + len(text) > TARGET_CHARS and buf:
                flush()
                p0 = b.page
            buf.append(text)
            p1 = b.page
        flush()
    return chunks
