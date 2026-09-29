"""Multi-source projects: several documents, demo videos and code repositories per project.

Each source is processed (and cached) on its own; chunks are merged with their provenance intact,
so every slide statement still points at the right file, page, scene or code module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from backend.intelligence.embeddings import embed_chunks_cached
from backend.schemas import DocumentChunk, DocumentStructure, ExtractedDocument
from backend.services.documents import doc_dir, process_document
from backend.storage.database import Database
from backend.utils.progress import progress_to


def project_document_ids(project: dict) -> list[str]:
    ids = [project["document_id"]] if project.get("document_id") else []
    for d in project.get("options", {}).get("extra_document_ids", []) or []:
        if d and d not in ids:
            ids.append(d)
    return ids


@dataclass
class SourceBundle:
    docs: list[tuple[str, ExtractedDocument, DocumentStructure, list[DocumentChunk]]] = field(default_factory=list)

    @property
    def chunks(self) -> list[DocumentChunk]:
        return [c for _, _, _, cs in self.docs for c in cs]

    @property
    def figure_dirs(self) -> list[Path]:
        return [doc_dir(did) for did, *_ in self.docs]

    @property
    def graphs(self) -> dict[str, dict]:
        return {did: d.metadata["architecture_graph"] for did, d, _, _ in self.docs if d.metadata.get("architecture_graph")}

    def title(self, project_name: str) -> str:
        if len(self.docs) == 1:
            d, st = self.docs[0][1], self.docs[0][2]
            return d.title or st.title or project_name
        return project_name

    @property
    def videos(self) -> list[tuple[str, ExtractedDocument]]:
        return [(did, d) for did, d, _, _ in self.docs if d.format == "video"]

    def summary(self) -> str:
        kinds = [d.format for _, d, _, _ in self.docs]
        parts = []
        for k, label in (("pdf", "PDF"), ("docx", "Word"), ("pptx", "PowerPoint"), ("txt", "text"), ("markdown", "Markdown"),
                         ("html", "HTML"), ("video", "video"), ("repository", "repository")):
            n = kinds.count(k)
            if n:
                parts.append(f"{n} {label}")
        return ", ".join(parts)


def load_sources(db: Database, project: dict, on_progress: Optional[Callable[[str], None]] = None) -> SourceBundle:
    b = SourceBundle()
    ids = project_document_ids(project)
    for i, did in enumerate(ids, 1):
        row = db.get_document(did) or {}
        name = row.get("filename", did)
        if on_progress:
            on_progress(f"Source {i} of {len(ids)}: {name}")
        with progress_to(lambda m, n=name: on_progress and on_progress(f"{n}: {m}")):
            doc, st, chunks = process_document(db, did)
        b.docs.append((did, doc, st, chunks))
    return b


def index_sources(bundle: SourceBundle):
    """Embed each source with its own on-disk cache; return stacked vectors in chunk order."""
    vecs, emb = [], None
    for did, _, _, chunks in bundle.docs:
        if not chunks:
            continue
        v, emb = embed_chunks_cached(doc_dir(did), [c.id for c in chunks], [c.text for c in chunks])
        vecs.append(v)
    if emb is None:
        from backend.intelligence.embeddings import get_embedder

        emb = get_embedder()
        return np.zeros((0, 1), np.float32), emb
    return np.vstack(vecs), emb
