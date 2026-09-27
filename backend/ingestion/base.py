"""Plugin-based document ingestion.

Each adapter converts one file format into an `ExtractedDocument` (a flat list of
typed blocks with page numbers). New formats are added by subclassing
`DocumentAdapter` and decorating it with `@register_adapter`.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from backend.schemas import ExtractedDocument


class ExtractionError(Exception):
    """Raised with a user-facing message when a document cannot be read."""

    def __init__(self, message: str, *, ocr_may_help: bool = False):
        super().__init__(message)
        self.ocr_may_help = ocr_may_help


class DocumentAdapter(ABC):
    extensions: ClassVar[tuple[str, ...]] = ()
    format_name: ClassVar[str] = ""

    @abstractmethod
    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        """Extract blocks. `work_dir` is a private directory for figure images etc."""


_REGISTRY: list[type[DocumentAdapter]] = []


def register_adapter(cls: type[DocumentAdapter]) -> type[DocumentAdapter]:
    _REGISTRY.append(cls)
    return cls


def supported_extensions() -> list[str]:
    _load_builtin()
    return sorted({e for a in _REGISTRY for e in a.extensions})


def get_adapter(path: Path) -> DocumentAdapter:
    _load_builtin()
    ext = path.suffix.lower()
    for cls in _REGISTRY:
        if ext in cls.extensions:
            return cls()
    raise ExtractionError(f"Unsupported file type '{ext}'. Supported: {', '.join(supported_extensions())}")


def _load_builtin() -> None:
    # Import for registration side effects.
    from backend.ingestion import docx, html, markdown, pdf, pptx, txt  # noqa: F401


# ------------------------------------------------------------------ shared text helpers
_WS = re.compile(r"[ \t ]+")


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line breaks
    text = _WS.sub(" ", text)
    return text.strip()


def join_lines(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", clean_text(text)).strip()


NUMBERED_HEADING = re.compile(r"^((\d+(\.\d+){0,3})|([IVX]{1,5}))[.)]?\s+[A-Z][^.!?]{1,90}$")


def heading_level_from_numbering(text: str) -> int:
    m = re.match(r"^(\d+(?:\.\d+){0,3})[.)]?\s", text)
    if m:
        return m.group(1).count(".") + 1
    return 1
