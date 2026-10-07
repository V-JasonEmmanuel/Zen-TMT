"""Paper readers. Each returns {elems, title, front, refs, raw_text, ...} for structure.build()."""
from __future__ import annotations

from pathlib import Path


def read_any(path: Path, work_dir: Path, kind: str) -> dict:
    if kind == "pdf":
        from backend.papers.readers import pdf

        return pdf.read(path, work_dir)
    if kind == "docx":
        from backend.papers.readers import docx

        return docx.read(path, work_dir)
    if kind == "latex":
        from backend.papers.readers import latex

        return latex.read(path, work_dir)
    from backend.papers.readers import text

    return text.read(path, work_dir)
