"""Plain-text adapter with heading heuristics."""
from __future__ import annotations

import re
from pathlib import Path

from backend.ingestion.base import (
    NUMBERED_HEADING,
    DocumentAdapter,
    ExtractionError,
    heading_level_from_numbering,
    join_lines,
    register_adapter,
)
from backend.schemas import Block, ContentType, ExtractedDocument

CHARS_PER_PAGE = 3000
BULLET = re.compile(r"^\s*([-*•]|\d+[.)])\s+")


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ExtractionError("The file appears to be binary, not text.")
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Unable to decode the text file.")


def looks_like_heading(line: str, next_blank: bool) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";")):
        return False
    if NUMBERED_HEADING.match(s):
        return True
    if s.isupper() and len(s.split()) <= 10 and re.search(r"[A-Z]{3}", s):
        return True
    return next_blank and len(s.split()) <= 8 and s[0].isupper() and not BULLET.match(s)


@register_adapter
class TXTAdapter(DocumentAdapter):
    extensions = (".txt", ".text")
    format_name = "txt"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        text = read_text_file(path)
        out = ExtractedDocument(document_id=document_id, filename=path.name, format="txt")
        out.blocks = blocks_from_plain_text(text)
        if not out.blocks:
            raise ExtractionError("The text file is empty.")
        out.page_count = max(b.page for b in out.blocks)
        out.title = next((b.text for b in out.blocks if b.type == ContentType.heading), path.stem.replace("_", " "))
        out.warnings.append("Page numbers for text files are estimated.")
        return out


def blocks_from_plain_text(text: str) -> list[Block]:
    blocks: list[Block] = []
    chars = 0
    paras = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for para in paras:
        lines = [l for l in para.split("\n") if l.strip()]
        if not lines:
            continue
        page = 1 + chars // CHARS_PER_PAGE
        # a heading may be the first line of a paragraph block
        if len(lines) >= 1 and looks_like_heading(lines[0], next_blank=len(lines) == 1):
            h = lines[0].strip()
            blocks.append(Block(type=ContentType.heading, text=h, page=page,
                                level=heading_level_from_numbering(h) if NUMBERED_HEADING.match(h) else 1))
            lines = lines[1:]
        if lines and all(BULLET.match(l) for l in lines):
            for l in lines:
                blocks.append(Block(type=ContentType.list_item, text=BULLET.sub("", l).strip(), page=page))
        elif lines:
            blocks.append(Block(type=ContentType.paragraph, text=join_lines("\n".join(lines)), page=page))
        chars += len(para)
    return blocks
