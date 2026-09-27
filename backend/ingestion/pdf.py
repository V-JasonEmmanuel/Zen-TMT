"""PDF adapter (PyMuPDF). OCR is only used for pages without machine-readable text."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from backend.ingestion.base import (
    NUMBERED_HEADING,
    DocumentAdapter,
    ExtractionError,
    clean_text,
    heading_level_from_numbering,
    join_lines,
    register_adapter,
)
from backend.schemas import Block, ContentType, ExtractedDocument
from backend.utils.logging import get_logger

log = get_logger(__name__)

CAPTION_RE = re.compile(r"^(fig(?:ure)?\.?|table)\s*(\d+)[.:]?", re.I)
BULLET_RE = re.compile(r"^([•●▪‣–\-\*]|\(?[a-z0-9]\))\s+")
MONO_HINTS = ("mono", "courier", "consolas", "code")
MIN_PAGE_CHARS = 25


def _is_mono(font: str) -> bool:
    f = font.lower()
    return any(h in f for h in MONO_HINTS)


def _is_bold(span: dict) -> bool:
    f = span["font"].lower()
    return bool(span["flags"] & 16) or "bold" in f or f.endswith(("-bd", "bo", ",bold")) or "black" in f


def _line_style(line: dict) -> tuple[float, bool, bool]:
    spans = [s for s in line["spans"] if s["text"].strip()]
    if not spans:
        return (0.0, False, False)
    main = max(spans, key=lambda s: len(s["text"]))
    return (round(main["size"], 1), all(_is_bold(s) for s in spans), _is_mono(main["font"]))


def _style_groups(lines: list[dict]) -> list[list[dict]]:
    """Split a PyMuPDF block where the font style changes (headings are often merged with the next paragraph)."""
    groups: list[list[dict]] = []
    prev = None
    for line in lines:
        style = _line_style(line)
        if style[0] == 0.0:
            continue
        if prev is None or abs(style[0] - prev[0]) > 0.6 or style[1] != prev[1] or style[2] != prev[2]:
            groups.append([line])
        else:
            groups[-1].append(line)
        prev = style
    return groups


def _order_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """Reading order that copes with two-column layouts."""
    mid = page_width / 2
    full, cols = [], []
    for b in blocks:
        x0, _, x1, _ = b["bbox"]
        (full if (x1 - x0) > page_width * 0.6 else cols).append(b)
    two_col = sum(1 for b in cols if b["bbox"][0] > mid * 0.9) >= 2 and sum(
        1 for b in cols if b["bbox"][2] < mid * 1.1
    ) >= 2
    if not two_col:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1]), b["bbox"][0]))
    ordered: list[dict] = []
    separators = sorted(full, key=lambda b: b["bbox"][1])
    bands_top = [-1.0] + [s["bbox"][1] for s in separators] + [1e9]
    for i in range(len(bands_top) - 1):
        top, bottom = bands_top[i], bands_top[i + 1]
        band = [b for b in cols if top <= b["bbox"][1] < bottom]
        left = sorted([b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 < mid], key=lambda b: b["bbox"][1])
        right = sorted([b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 >= mid], key=lambda b: b["bbox"][1])
        ordered += left + right
        if i < len(separators):
            ordered.append(separators[i])
    return ordered


@register_adapter
class PDFAdapter(DocumentAdapter):
    extensions = (".pdf",)
    format_name = "pdf"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        import pymupdf

        try:
            doc = pymupdf.open(path)
        except Exception as exc:  # corrupt / not a PDF
            raise ExtractionError("The PDF could not be opened. It may be corrupted or not a valid PDF file.") from exc
        if doc.needs_pass:
            raise ExtractionError("The PDF is password-protected. Please upload an unprotected copy.")

        out = ExtractedDocument(document_id=document_id, filename=path.name, format="pdf", page_count=doc.page_count)
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        out.metadata = {k: meta[k] for k in ("title", "author", "subject", "keywords", "creationDate") if k in meta}

        # ---- pass 1: collect raw blocks + font statistics
        pages: list[tuple[int, float, float, list[dict]]] = []
        size_counter: Counter[float] = Counter()
        edge_texts: Counter[str] = Counter()
        text_pages, ocr_pages = 0, []
        for pno, page in enumerate(doc, start=1):
            d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            raw = []
            chars = 0
            for b in d["blocks"]:
                if b.get("type") != 0:
                    continue
                for grp in _style_groups(b["lines"]):
                    spans = [s for line in grp for s in line["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = "\n".join("".join(s["text"] for s in line["spans"]) for line in grp)
                    n = sum(len(s["text"]) for s in spans)
                    chars += n
                    sizes = Counter()
                    for s in spans:
                        sizes[round(s["size"], 1)] += len(s["text"])
                        size_counter[round(s["size"], 1)] += len(s["text"])
                    bold_chars = sum(len(s["text"]) for s in spans if _is_bold(s))
                    mono_chars = sum(len(s["text"]) for s in spans if _is_mono(s["font"]))
                    bbox = (min(l["bbox"][0] for l in grp), min(l["bbox"][1] for l in grp),
                            max(l["bbox"][2] for l in grp), max(l["bbox"][3] for l in grp))
                    raw.append({
                        "bbox": bbox, "text": text, "size": sizes.most_common(1)[0][0],
                        "bold": bold_chars > n * 0.6, "mono": mono_chars > n * 0.6, "lines": len(grp),
                    })
                    if bbox[3] < page.rect.height * 0.08 or bbox[1] > page.rect.height * 0.92:
                        edge_texts[re.sub(r"\d+", "#", text.strip())] += 1
            if chars >= MIN_PAGE_CHARS:
                text_pages += 1
            else:
                ocr_pages.append(pno)
            pages.append((pno, page.rect.width, page.rect.height, raw))

        body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0
        repeated_edges = {t for t, c in edge_texts.items() if c >= max(3, doc.page_count * 0.4)}
        heading_sizes = sorted({s for s in size_counter if s >= body_size * 1.15}, reverse=True)[:4]

        # ---- OCR only for pages lacking text
        ocr_text: dict[int, str] = {}
        if ocr_pages:
            from backend.extraction.ocr import get_ocr_engine

            engine = get_ocr_engine()
            if engine is None:
                if text_pages == 0:
                    raise ExtractionError(
                        "This PDF appears to be scanned (no machine-readable text) and no offline OCR engine "
                        "is installed. Install an OCR engine (see README) or upload a text-based PDF.",
                        ocr_may_help=True,
                    )
                out.warnings.append(f"{len(ocr_pages)} page(s) had no readable text and OCR is unavailable; they were skipped.")
            else:
                for pno in ocr_pages:
                    try:
                        pix = doc[pno - 1].get_pixmap(dpi=200)
                        ocr_text[pno] = engine.image_to_text(pix.tobytes("png"))
                    except Exception as exc:  # OCR must never break the whole extraction
                        out.warnings.append(f"OCR failed on page {pno}: {type(exc).__name__}")
                out.extraction_method = "ocr" if text_pages == 0 else "mixed"

        # ---- pass 2: classify blocks, tables and figures
        fig_dir = work_dir / "figures"
        table_no = figure_no = 0
        for pno, pw, ph, raw in pages:
            page = doc[pno - 1]
            table_boxes = []
            try:
                for t in page.find_tables().tables:
                    rows = [[clean_text(c or "") for c in r] for r in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                        table_no += 1
                        table_boxes.append((t.bbox, table_no, rows))
            except Exception:
                pass
            tables_by_y = sorted(table_boxes, key=lambda t: t[0][1])

            def in_table(bbox):
                return any(bbox[0] >= tb[0] - 2 and bbox[1] >= tb[1] - 2 and bbox[2] <= tb[2] + 2 and bbox[3] <= tb[3] + 2
                           for tb, _, _ in table_boxes)

            emitted_tables: set[int] = set()
            for rb in _order_blocks(raw, pw):
                # emit tables in reading position
                for tb, tno, rows in tables_by_y:
                    if tno not in emitted_tables and tb[1] <= rb["bbox"][1]:
                        emitted_tables.add(tno)
                        out.blocks.append(Block(type=ContentType.table, text=_table_text(rows), page=pno,
                                                table=rows, table_index=tno))
                if in_table(rb["bbox"]):
                    continue
                text = clean_text(rb["text"])
                if not text or re.fullmatch(r"[\d\s./-]{1,8}", text):
                    continue
                if re.sub(r"\d+", "#", rb["text"].strip()) in repeated_edges:
                    continue
                out.blocks.append(self._classify(rb, text, pno, body_size, heading_sizes))
            for tb, tno, rows in tables_by_y:
                if tno not in emitted_tables:
                    out.blocks.append(Block(type=ContentType.table, text=_table_text(rows), page=pno, table=rows, table_index=tno))

            if pno in ocr_text:
                for para in re.split(r"\n\s*\n", ocr_text[pno]):
                    para = join_lines(para)
                    if para:
                        out.blocks.append(Block(type=ContentType.paragraph, text=para, page=pno))

            # figures: large embedded images rendered from the page region
            try:
                for info in page.get_image_info():
                    x0, y0, x1, y1 = info["bbox"]
                    if (x1 - x0) * (y1 - y0) < pw * ph * 0.04 or (x1 - x0) < 80:
                        continue
                    figure_no += 1
                    fig_dir.mkdir(parents=True, exist_ok=True)
                    rel = f"figures/figure_{figure_no:02d}.png"
                    page.get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), dpi=150).save(str(work_dir / rel))
                    out.blocks.append(Block(type=ContentType.figure, text=f"Figure on page {pno}", page=pno,
                                            figure_index=figure_no, image_path=rel))
                    if figure_no >= 40:
                        break
            except Exception:
                out.warnings.append(f"Figure extraction failed on page {pno}")

        _attach_captions(out.blocks)
        out.title = self._title(out, meta, pages, body_size)
        if not out.blocks:
            raise ExtractionError("No readable content was found in this PDF.", ocr_may_help=True)
        log.info("PDF extracted", pages=doc.page_count, blocks=len(out.blocks), tables=table_no, figures=figure_no,
                 ocr_pages=len(ocr_text))
        doc.close()
        return out

    @staticmethod
    def _classify(rb: dict, text: str, pno: int, body: float, heading_sizes: list[float]) -> Block:
        flat = join_lines(text)
        size, bold, short = rb["size"], rb["bold"], len(flat) < 120 and rb["lines"] <= 3
        if CAPTION_RE.match(flat):
            return Block(type=ContentType.caption, text=flat, page=pno, font_size=size)
        if rb["mono"]:
            return Block(type=ContentType.code, text=text, page=pno, font_size=size)
        ends_sentence = flat.endswith((".", ",", ";", ":")) and not NUMBERED_HEADING.match(flat)
        is_heading = short and not ends_sentence and (
            size >= body * 1.15
            or (bold and len(flat) < 90)
            or (NUMBERED_HEADING.match(flat) and len(flat) < 80 and size >= body * 0.98)
            or (flat.isupper() and 3 < len(flat) < 60)
        )
        if is_heading and len(flat.split()) <= 14:
            if size in heading_sizes:
                level = heading_sizes.index(size) + 1
            else:
                level = heading_level_from_numbering(flat) if NUMBERED_HEADING.match(flat) else len(heading_sizes) + 1
            return Block(type=ContentType.heading, text=flat, page=pno, level=min(level, 4), font_size=size, bold=bold)
        if BULLET_RE.match(flat):
            return Block(type=ContentType.list_item, text=BULLET_RE.sub("", flat), page=pno, font_size=size)
        return Block(type=ContentType.paragraph, text=flat, page=pno, font_size=size, bold=bold)

    @staticmethod
    def _title(out: ExtractedDocument, meta: dict, pages, body: float) -> str:
        mt = (meta.get("title") or "").strip()
        if mt and len(mt) > 6 and not re.search(r"\.(docx?|pdf|tex)$|^untitled|^microsoft", mt, re.I):
            return mt
        if pages:
            first = [b for b in pages[0][3] if len(join_lines(b["text"])) > 4]
            if first:
                best = max(first, key=lambda b: b["size"])
                if best["size"] >= body * 1.2:
                    return join_lines(best["text"])[:200]
        for b in out.blocks:
            if b.type == ContentType.heading:
                return b.text
        return Path(out.filename).stem.replace("_", " ")


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(c for c in r) for r in rows)


def _attach_captions(blocks: list[Block]) -> None:
    """Use 'Table N' / 'Figure N' captions to number adjacent tables and figures."""
    for i, b in enumerate(blocks):
        if b.type != ContentType.caption:
            continue
        m = CAPTION_RE.match(b.text)
        if not m:
            continue
        kind, num = m.group(1).lower(), int(m.group(2))
        want = ContentType.table if kind.startswith("table") else ContentType.figure
        for j in (i + 1, i - 1, i + 2, i - 2):
            if 0 <= j < len(blocks) and blocks[j].type == want and blocks[j].page == b.page:
                if want == ContentType.table:
                    blocks[j].table_index = num
                else:
                    blocks[j].figure_index = num
                    blocks[j].text = b.text
                break
