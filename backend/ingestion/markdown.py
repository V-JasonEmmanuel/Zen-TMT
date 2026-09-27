"""Markdown adapter: ATX headings, lists, pipe tables and fenced code."""
from __future__ import annotations

import re
from pathlib import Path

from backend.ingestion.base import DocumentAdapter, ExtractionError, join_lines, register_adapter
from backend.ingestion.txt import CHARS_PER_PAGE, read_text_file
from backend.schemas import Block, ContentType, ExtractedDocument

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")


def _strip_md(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`]{1,3}([^*_`]+)[*_`]{1,3}", r"\1", s)
    return s.strip()


@register_adapter
class MarkdownAdapter(DocumentAdapter):
    extensions = (".md", ".markdown")
    format_name = "markdown"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        text = read_text_file(path)
        out = ExtractedDocument(document_id=document_id, filename=path.name, format="markdown")
        lines = text.replace("\r\n", "\n").split("\n")
        chars, i, table_no = 0, 0, 0
        para: list[str] = []

        def page() -> int:
            return 1 + chars // CHARS_PER_PAGE

        def flush():
            if para:
                out.blocks.append(Block(type=ContentType.paragraph, text=_strip_md(join_lines("\n".join(para))), page=page()))
                para.clear()

        while i < len(lines):
            line = lines[i]
            chars += len(line) + 1
            if line.strip().startswith("```"):
                flush()
                code = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    chars += len(lines[i]) + 1
                    i += 1
                if code:
                    out.blocks.append(Block(type=ContentType.code, text="\n".join(code), page=page()))
            elif m := HEADING.match(line):
                flush()
                out.blocks.append(Block(type=ContentType.heading, text=_strip_md(m.group(2)), page=page(), level=len(m.group(1))))
            elif "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
                flush()
                rows = [[_strip_md(c) for c in line.strip().strip("|").split("|")]]
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    rows.append([_strip_md(c) for c in lines[i].strip().strip("|").split("|")])
                    chars += len(lines[i]) + 1
                    i += 1
                table_no += 1
                out.blocks.append(Block(type=ContentType.table, text="\n".join(" | ".join(r) for r in rows),
                                        page=page(), table=rows, table_index=table_no))
                continue
            elif m := LIST.match(line):
                flush()
                out.blocks.append(Block(type=ContentType.list_item, text=_strip_md(m.group(2)), page=page()))
            elif not line.strip():
                flush()
            else:
                para.append(line)
            i += 1
        flush()
        if not out.blocks:
            raise ExtractionError("The Markdown file is empty.")
        out.page_count = max(b.page for b in out.blocks)
        out.title = next((b.text for b in out.blocks if b.type == ContentType.heading), path.stem)
        return out
