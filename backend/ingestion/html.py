"""HTML adapter (BeautifulSoup). Scripts/styles are discarded; nothing is executed or fetched."""
from __future__ import annotations

from pathlib import Path

from backend.ingestion.base import DocumentAdapter, ExtractionError, clean_text, register_adapter
from backend.ingestion.txt import CHARS_PER_PAGE, read_text_file
from backend.schemas import Block, ContentType, ExtractedDocument


@register_adapter
class HTMLAdapter(DocumentAdapter):
    extensions = (".html", ".htm")
    format_name = "html"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(read_text_file(path), "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "nav", "footer", "form", "svg"]):
            tag.decompose()
        out = ExtractedDocument(document_id=document_id, filename=path.name, format="html")
        chars, table_no = 0, 0
        root = soup.body or soup
        for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "pre", "figcaption", "blockquote"]):
            if el.find_parent(["table", "li"]) and el.name != "table":
                continue
            page = 1 + chars // CHARS_PER_PAGE
            if el.name == "table":
                rows = [[clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])] for tr in el.find_all("tr")]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    table_no += 1
                    out.blocks.append(Block(type=ContentType.table, text="\n".join(" | ".join(r) for r in rows),
                                            page=page, table=rows, table_index=table_no))
                continue
            text = clean_text(el.get_text(" "))
            if not text:
                continue
            chars += len(text)
            if el.name.startswith("h"):
                out.blocks.append(Block(type=ContentType.heading, text=text, page=page, level=int(el.name[1])))
            elif el.name == "li":
                out.blocks.append(Block(type=ContentType.list_item, text=text, page=page))
            elif el.name == "pre":
                out.blocks.append(Block(type=ContentType.code, text=text, page=page))
            elif el.name == "figcaption":
                out.blocks.append(Block(type=ContentType.caption, text=text, page=page))
            else:
                out.blocks.append(Block(type=ContentType.paragraph, text=text, page=page))
        if not out.blocks:
            raise ExtractionError("The HTML file does not contain readable text.")
        out.page_count = max(b.page for b in out.blocks)
        title = soup.title.get_text().strip() if soup.title else ""
        out.title = title or next((b.text for b in out.blocks if b.type == ContentType.heading), path.stem)
        return out
