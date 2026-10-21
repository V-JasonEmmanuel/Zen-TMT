"""Build the documentation PDFs from the text in docs/source/.

    python scripts/make_docs_pdfs.py
    -> docs/User_Manual.pdf, docs/Project_Documentation.pdf, docs/Pipeline_Explanation.pdf

Markdown -> styled HTML (python-markdown) -> PDF (Microsoft Edge via Playwright, headless).
Layout: title block and contents on page 1, navy section headings, page header and "Page N of M" footer.
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "source"
OUT = ROOT / "docs"
TITLE = "Zensar Content Studio"
DOCS = [  # source, output, subtitle
    ("USER_MANUAL.md", "User_Manual.pdf", "Installation and User Manual"),
    ("PROJECT_DOCUMENTATION.md", "Project_Documentation.pdf", "Project Documentation"),
    ("PIPELINE.md", "Pipeline_Explanation.pdf", "Pipeline Explanation"),
]

NAVY, BLUE, CODE = "#1F3864", "#2E74B5", "#C0392B"
CSS = f"""
@page {{ size: A4; margin: 22mm 25mm 20mm 25mm; }}
body {{ font-family: Calibri, Carlito, 'Segoe UI', Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #262626; margin: 0; }}
h1.title {{ font-size: 30pt; color: {NAVY}; margin: 0; line-height: 1.2; }}
.subtitle {{ font-size: 17pt; color: {BLUE}; padding-bottom: 2mm; border-bottom: 1.5px solid {BLUE}; margin: 1mm 0 5mm; }}
h2 {{ font-size: 17pt; color: {NAVY}; margin: 9mm 0 3mm; padding-bottom: 1.2mm; border-bottom: 1px solid #c9d3e3;
      page-break-after: avoid; }}
h2.contents {{ font-size: 15pt; margin-top: 6mm; border-bottom: 1.5px solid {BLUE}; }}
h3 {{ font-size: 13pt; color: {BLUE}; margin: 6mm 0 2mm; page-break-after: avoid; }}
h4 {{ font-size: 11.5pt; color: #2b3a55; margin: 6mm 0 2mm; page-break-after: avoid; }}
h4 code {{ font-size: 10.5pt; font-weight: 700; background: none; padding: 0; }}
.part-title {{ font-size: 17pt; font-weight: 700; color: {NAVY}; margin: 0 0 3mm; page-break-before: always; }}
p {{ margin: 0 0 2.6mm; }}
ul, ol {{ margin: 0 0 3mm; padding-left: 9mm; }}
li {{ margin: 1mm 0; }}
ul li::marker {{ color: {BLUE}; }}
ol li::marker {{ color: {BLUE}; font-weight: 700; }}
ul ul li::marker {{ content: "–  "; color: #555; }}
code {{ font-family: Consolas, 'Courier New', monospace; font-size: 9.6pt; color: {CODE}; background: #f2f2f2;
        padding: .2mm 1mm; border-radius: .6mm; }}
pre {{ background: #f2f3f5; border: 1px solid #cfd2d8; padding: 2.4mm 3mm; margin: 2mm 0 4mm; line-height: 1.35;
       white-space: pre-wrap; page-break-inside: avoid; }}
pre code {{ background: none; color: #262626; padding: 0; font-size: 9.4pt; }}
blockquote {{ margin: 3mm 0 4mm; padding: 1.6mm 4mm; background: #e8f0fa; border-left: 4px solid {BLUE}; }}
blockquote p {{ margin: 1mm 0; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin: 2mm 0 6mm; font-size: 10pt; line-height: 1.4; }}
tr {{ page-break-inside: avoid; }}
th {{ background: {NAVY}; color: #fff; text-align: left; padding: 2.2mm 2.6mm; font-weight: 700; }}
td {{ padding: 2mm 2.6mm; border-bottom: 1px solid #d5dbe5; border-right: 1px solid #e3e7ee; vertical-align: middle; }}
td:first-child {{ border-left: 1px solid #e3e7ee; width: 34%; }}
tr:nth-child(even) td {{ background: #f4f6fa; }}
td code {{ font-size: 9.2pt; }}
hr {{ display: none; }}
a {{ color: {BLUE}; text-decoration: none; }}
.toc {{ list-style: none; padding-left: 9mm; margin: 0 0 4mm; }}
.toc li {{ margin: .6mm 0; }}
.toc li::marker {{ content: ""; }}
"""

HEADER = ('<div style="width:100%;margin:0 25mm;padding-bottom:1.5mm;border-bottom:1px solid #d0d0d0;text-align:right;'
          'font-size:8.5pt;color:#555;font-family:Calibri,Segoe UI">{text}</div>')
FOOTER = ('<div style="width:100%;text-align:center;font-size:8.5pt;color:#555;font-family:Calibri,Segoe UI">'
          'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>')


def normalise(md_text: str) -> str:
    """python-markdown needs 4-space nested lists and a blank line before a list."""
    out: list[str] = []
    item = re.compile(r"^\s*(?:[*-]|\d+\.) ")
    for line in md_text.splitlines():
        line = re.sub(r"^ {2,3}(?=[*-] |\d+\. )", "    ", line)
        if item.match(line) and out and out[-1].strip() and not item.match(out[-1]) \
                and not out[-1].startswith(("#", "    ")):
            out.append("")
        out.append(line)
    return "\n".join(out)


def build_html(md_text: str, subtitle: str) -> str:
    lines = normalise(md_text).splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]  # the title block replaces the document's own first heading
    body = markdown.markdown("\n".join(lines), extensions=["tables", "fenced_code", "sane_lists", "toc"])
    body = re.sub(r"<h1 ", "<h2 ", body).replace("</h1>", "</h2>")  # "Part" headings become sections
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    toc = "".join(f'<li><a href="#{i}">{re.sub("<[^>]+>", "", t)}</a></li>' for i, t in heads)
    contents = f'<h2 class="contents">Contents</h2><ul class="toc">{toc}</ul>'
    first_h2 = body.find("<h2")
    body = body[:first_h2] + contents + body[first_h2:] if first_h2 >= 0 else body + contents
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{TITLE} - {subtitle}</title>'
            f'<style>{CSS}</style></head><body><h1 class="title">{TITLE}</h1>'
            f'<div class="subtitle">{subtitle}</div>{body}</body></html>')


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        for src, out, subtitle in DOCS:
            page.set_content(build_html((SRC / src).read_text(encoding="utf-8"), subtitle), wait_until="load")
            page.pdf(path=str(OUT / out), format="A4", print_background=True, prefer_css_page_size=True,
                     display_header_footer=True, header_template=HEADER.format(text=f"{TITLE} - {subtitle}"),
                     footer_template=FOOTER)
            print("wrote", OUT / out)
        browser.close()


if __name__ == "__main__":
    main()
