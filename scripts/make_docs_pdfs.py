"""Build the documentation PDFs from the text in docs/source/.

    python scripts/make_docs_pdfs.py
    -> docs/User_Manual.pdf, docs/Project_Documentation.pdf, docs/Pipeline_Explanation.pdf

Markdown -> styled HTML (python-markdown) -> PDF (Microsoft Edge via Playwright, headless).
The cover is printed without the page header/footer and joined in front with PyMuPDF.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import markdown
import pymupdf
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "source"
OUT = ROOT / "docs"
LOGO_W = ROOT / "brands/zensar/assets/logo/zensar_logo_white.png"
DOCS = [  # source, output, cover subtitle
    ("USER_MANUAL.md", "User_Manual.pdf", "User Manual"),
    ("PROJECT_DOCUMENTATION.md", "Project_Documentation.pdf", "Project Documentation"),
    ("PIPELINE.md", "Pipeline_Explanation.pdf", "Pipeline Explanation"),
]

CSS = """
@page { size: A4; margin: 20mm 16mm 18mm 16mm; }
@page cover { margin: 0; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1c1c28; margin: 0; }
.cover { page: cover; height: 297mm; background: #10005D; color: #fff; padding: 34mm 22mm; position: relative; overflow: hidden;
         }
.cover img { height: 15mm; }
.cover .kicker { margin-top: 70mm; font-size: 13pt; letter-spacing: .12em; text-transform: uppercase; color: #9fb0ff; }
.cover h1 { font-size: 34pt; line-height: 1.15; margin: 4mm 0 6mm; color: #fff; border: 0; }
.cover .bar { width: 22mm; height: 2mm; background: #F04E45; margin-bottom: 8mm; }
.cover .sub { font-size: 13pt; max-width: 130mm; color: #dfe3ff; }
.cover .c1 { position: absolute; right: -40mm; top: -30mm; width: 120mm; height: 120mm; border-radius: 50%; background: #3A57A7; }
.cover .c2 { position: absolute; right: 18mm; bottom: 30mm; width: 60mm; height: 60mm; border-radius: 50%; background: #00B0C0; }
.cover .c3 { position: absolute; right: 64mm; bottom: 10mm; width: 34mm; height: 34mm; border-radius: 50%; background: #F04E45; }
.cover .foot { position: absolute; left: 22mm; bottom: 18mm; font-size: 9.5pt; color: #b9c0f0; }
.toc { page-break-after: always; }
.toc h2 { margin-top: 0; }
.toc ul { padding-left: 0; list-style: none; } .toc li { margin: 1.6mm 0; } .toc a { color: #10005D; text-decoration: none; }
h1 { font-size: 20pt; color: #10005D; margin: 0 0 4mm; padding-bottom: 2mm; border-bottom: 2px solid #F04E45; }
h2 { font-size: 15pt; color: #10005D; margin: 8mm 0 3mm; page-break-after: avoid; }
.doc h1 { page-break-before: always; }
.toc li.part { font-weight: 600; margin-top: 4mm; }
.toc li.sub { padding-left: 6mm; }
h3 { font-size: 12pt; color: #3A57A7; margin: 6mm 0 2mm; page-break-after: avoid; }
p { margin: 0 0 2.6mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; } li { margin: .8mm 0; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #eef0f8; color: #10005D; padding: .2mm 1.2mm; border-radius: 1mm; }
pre { background: #f4f5fa; border-left: 3px solid #3A57A7; padding: 3mm 4mm; font-size: 8.4pt; line-height: 1.3;
      white-space: pre; overflow: hidden; page-break-inside: avoid; }
pre code { background: none; padding: 0; color: #1c1c28; font-size: 8.4pt; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 5mm; font-size: 9.3pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #10005D; color: #fff; text-align: left; padding: 1.8mm 2.4mm; font-weight: 600; }
td { padding: 1.6mm 2.4mm; border-bottom: 1px solid #e2e4ee; vertical-align: top; }
tr:nth-child(even) td { background: #f7f8fc; }
td:first-child code { white-space: nowrap; }
hr { border: 0; height: 0; margin: 4mm 0; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; background: #fff4f3; border-left: 3px solid #F04E45; }
strong { color: #10005D; }
"""

HEADER = '<div style="font-size:7.5pt;color:#8a8fa8;width:100%;padding:0 16mm;font-family:Segoe UI">' \
         'Zensar Content Studio &nbsp;|&nbsp; {title}</div>'
FOOTER = '<div style="font-size:7.5pt;color:#8a8fa8;width:100%;padding:0 16mm;text-align:right;font-family:Segoe UI">' \
         'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'


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


def build_html(md_text: str, subtitle: str) -> tuple[str, str]:
    lines = normalise(md_text).splitlines()
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else subtitle
    intro = ""
    body_md = "\n".join(lines[1:])
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    # table of contents from the h1 (parts) and h2 headings; each part starts a new page (CSS)
    heads = re.findall(r'<h([12]) id="([^"]+)">(.*?)</h[12]>', body)
    has_parts = any(lv == "1" for lv, _, _ in heads)
    toc = "".join(f'<li class="{"part" if lv == "1" else "sub" if has_parts else ""}"><a href="#{i}">{re.sub("<[^>]+>", "", t)}</a></li>'
                  for lv, i, t in heads)
    first = re.search(r"<p>(.*?)</p>", body, re.S)
    if first:
        intro = re.sub("<[^>]+>", "", first.group(1))[:260]
    logo = base64.b64encode(LOGO_W.read_bytes()).decode()
    head = f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>'
    cover = f"""{head}<div class="cover"><div class="c1"></div><div class="c2"></div><div class="c3"></div>
<img src="data:image/png;base64,{logo}"><div class="kicker">Zensar Content Studio</div>
<h1>{subtitle}</h1><div class="bar"></div><div class="sub">{intro}</div>
<div class="foot">Offline AI &nbsp;·&nbsp; Your documents never leave the machine</div></div></body></html>"""
    return cover, f'{head}<div class="toc"><h1>Contents</h1><ul>{toc}</ul></div><div class="doc">{body}</div></body></html>'



def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        for src, out, subtitle in DOCS:
            cover, html = build_html((SRC / src).read_text(encoding="utf-8"), subtitle)
            page.set_content(cover, wait_until="load")
            doc = pymupdf.open("pdf", page.pdf(format="A4", print_background=True, prefer_css_page_size=True))
            page.set_content(html, wait_until="load")
            doc.insert_pdf(pymupdf.open("pdf", page.pdf(
                format="A4", print_background=True, prefer_css_page_size=True, display_header_footer=True,
                header_template=HEADER.format(title=subtitle), footer_template=FOOTER)))
            doc.set_metadata({"title": f"Zensar Content Studio - {subtitle}", "author": "Zensar Content Studio"})
            doc.save(OUT / out, garbage=3, deflate=True)
            print("wrote", OUT / out)
        browser.close()


if __name__ == "__main__":
    main()
