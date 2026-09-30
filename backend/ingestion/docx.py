"""DOCX adapter (python-docx). Pages are estimated because DOCX has no fixed pagination."""
from __future__ import annotations

import re
from pathlib import Path

from backend.ingestion.base import (
    NUMBERED_HEADING,
    DocumentAdapter,
    ExtractionError,
    clean_text,
    heading_level_from_numbering,
    register_adapter,
)
from backend.schemas import Block, ContentType, ExtractedDocument

CHARS_PER_PAGE = 3000  # rough estimate used for page references


@register_adapter
class DOCXAdapter(DocumentAdapter):
    extensions = (".docx",)
    format_name = "docx"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        try:
            d = docx.Document(str(path))
        except Exception as exc:
            raise ExtractionError("The DOCX file could not be opened. It may be corrupted or password-protected.") from exc

        out = ExtractedDocument(document_id=document_id, filename=path.name, format="docx")
        cp = d.core_properties
        out.metadata = {k: v for k, v in {"title": cp.title, "author": cp.author, "subject": cp.subject}.items() if v}
        chars, page, table_no, figure_no = 0, 1, 0, 0
        explicit_breaks = False

        body = d.element.body
        for child in body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, d)
                xml = child.xml
                if 'w:type="page"' in xml or "lastRenderedPageBreak" in xml:
                    explicit_breaks = True
                    page += xml.count('w:type="page"') + xml.count("lastRenderedPageBreak")
                for rid in child.xpath(".//a:blip/@r:embed"):  # embedded pictures (diagrams, screenshots)
                    fig = self._figure(d, rid, work_dir, figure_no + 1)
                    if fig:
                        figure_no += 1
                        out.blocks.append(Block(type=ContentType.figure, text=f"Figure {figure_no}", page=page,
                                                figure_index=figure_no, image_path=fig))
                text = clean_text(p.text)
                if not text:
                    continue
                style = (p.style.name if p.style is not None else "") or ""
                b = self._classify(text, style, p, page)
                out.blocks.append(b)
                chars += len(text)
            elif tag == "tbl":
                t = Table(child, d)
                rows = []
                for r in t.rows:
                    cells = []
                    for c in r.cells:
                        v = clean_text(c.text)
                        if not cells or cells[-1] != v or len(r.cells) <= 1:  # merged cells repeat text
                            cells.append(v)
                    rows.append(cells)
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    table_no += 1
                    out.blocks.append(Block(type=ContentType.table, text="\n".join(" | ".join(r) for r in rows),
                                            page=page, table=rows, table_index=table_no))
                    chars += sum(len(c) for r in rows for c in r)
            if not explicit_breaks:
                page = 1 + chars // CHARS_PER_PAGE

        if not out.blocks:
            raise ExtractionError("The DOCX file does not contain readable text.")
        out.page_count = max(b.page for b in out.blocks)
        out.title = out.metadata.get("title") or next(
            (b.text for b in out.blocks if b.type == ContentType.heading), path.stem.replace("_", " ")
        )
        if not explicit_breaks:
            out.warnings.append("Page numbers for DOCX files are estimated.")
        return out

    @staticmethod
    def _figure(d, rid: str, work_dir: Path, n: int) -> str | None:
        """Save an embedded image as figures/figure_NN.png (icons and tiny images are skipped)."""
        import io

        from PIL import Image

        try:
            blob = d.part.related_parts[rid].blob
            with Image.open(io.BytesIO(blob)) as im:
                if min(im.size) < 120 or n > 40:
                    return None
                rel = f"figures/figure_{n:02d}.png"
                (work_dir / "figures").mkdir(parents=True, exist_ok=True)
                im.convert("RGB").save(work_dir / rel)
                return rel
        except Exception:
            return None

    @staticmethod
    def _classify(text: str, style: str, p, page: int) -> Block:
        s = style.lower()
        if s == "title":
            return Block(type=ContentType.heading, text=text, page=page, level=1, bold=True)
        m = re.match(r"heading\s*(\d)", s)
        if m:
            return Block(type=ContentType.heading, text=text, page=page, level=int(m.group(1)))
        if "caption" in s:
            return Block(type=ContentType.caption, text=text, page=page)
        if "list" in s or p._p.pPr is not None and p._p.pPr.numPr is not None:
            return Block(type=ContentType.list_item, text=text, page=page)
        if "code" in s or "source" in s:
            return Block(type=ContentType.code, text=text, page=page)
        runs = [r for r in p.runs if r.text.strip()]
        all_bold = bool(runs) and all(r.bold for r in runs)
        if (all_bold or NUMBERED_HEADING.match(text)) and len(text) < 90 and not text.endswith("."):
            return Block(type=ContentType.heading, text=text, page=page,
                         level=heading_level_from_numbering(text) if NUMBERED_HEADING.match(text) else 2, bold=True)
        return Block(type=ContentType.paragraph, text=text, page=page)
