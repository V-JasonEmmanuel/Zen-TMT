"""Generate synthetic sample documents (research-paper style) for tests and demos.

The content is fictional and written for testing the pipeline only.
"""
from __future__ import annotations

from pathlib import Path

TITLE = "Adaptive Retrieval Pipelines for Enterprise Document Question Answering"
SECTIONS: list[tuple[str, list[str]]] = [
    ("Abstract", [
        "We present an adaptive retrieval pipeline for answering questions over large enterprise document collections. "
        "The pipeline combines section-aware chunking, hybrid lexical and dense retrieval, and a lightweight re-ranker. "
        "On a benchmark of 4,200 internal questions, the approach improves answer accuracy from 71.4% to 84.9% while reducing median latency to 380 ms.",
    ]),
    ("1 Introduction", [
        "Enterprises store critical knowledge in long PDF reports, policies and technical manuals. Employees spend significant time searching these documents.",
        "Existing keyword search tools return whole documents rather than precise answers, and generic chat assistants often produce unsupported statements.",
        "This paper studies how retrieval design choices affect accuracy, latency and traceability in an on-premise setting.",
    ]),
    ("2 Background", [
        "Dense retrieval encodes passages into vectors so that semantically similar text can be found even without shared keywords.",
        "Lexical retrieval such as BM25 remains strong for exact identifiers, product codes and rare terms that dense models handle poorly.",
    ]),
    ("3 System Architecture", [
        "The system consists of five components: an Ingestion Service, a Chunking Engine, a Hybrid Index, a Re-ranker and an Answer Composer.",
        "- Ingestion Service: extracts text, tables and layout from PDF and DOCX files.\n- Chunking Engine: splits documents along section boundaries.\n"
        "- Hybrid Index: stores BM25 postings and dense vectors side by side.\n- Re-ranker: scores the top 50 candidates with a cross-encoder.\n"
        "- Answer Composer: assembles the final answer with page-level citations.",
        "All components run on a single server with 16 GB of memory and no external network access.",
    ]),
    ("4 Methodology", [
        "First, we collected 4,200 questions from support tickets across three business units and paired each with a verified answer passage.",
        "Then, documents were chunked using three strategies: fixed windows of 512 tokens, paragraph boundaries, and section-aware chunks.",
        "Next, each chunking strategy was combined with lexical, dense and hybrid retrieval, giving nine configurations in total.",
        "Finally, answers were graded by two annotators; disagreements were resolved by a third reviewer. Inter-annotator agreement was 0.87 Cohen's kappa.",
    ]),
    ("5 Results", [
        "Section-aware chunking with hybrid retrieval achieved the best accuracy of 84.9%, compared to 71.4% for the fixed-window lexical baseline.",
        "Hybrid retrieval improved recall at 10 from 78.2% to 91.6% over dense retrieval alone.",
        "The re-ranker added 45 ms of latency but increased accuracy by 6.3 percentage points.",
        "TABLE",
        "Citation precision, measured as the share of answers whose cited page contained the answer, reached 96.1% for the best configuration.",
    ]),
    ("6 Discussion", [
        "The results indicate that document structure is a stronger signal than chunk size alone. Limitations include the focus on English documents and a single industry domain.",
    ]),
    ("7 Implementation Details", [
        "The prototype is implemented in Python using FastAPI. The index is stored in SQLite and FAISS.",
        "def retrieve(query):\n    hits = index.search(embed(query), k=50)\n    return rerank(query, hits)",
    ]),
    ("8 Conclusion", [
        "Structure-aware retrieval makes enterprise question answering both more accurate and more traceable.",
        "We recommend section-aware chunking with hybrid retrieval as the default configuration, and plan to extend the evaluation to multilingual documents.",
    ]),
    ("References", [
        "[1] Robertson, S. and Zaragoza, H. The Probabilistic Relevance Framework: BM25 and Beyond. 2009.",
        "[2] Karpukhin, V. et al. Dense Passage Retrieval for Open-Domain Question Answering. 2020.",
    ]),
]
TABLE = [
    ["Configuration", "Accuracy (%)", "Recall@10 (%)", "Latency (ms)"],
    ["Fixed window + BM25", "71.4", "74.0", "210"],
    ["Paragraph + Dense", "76.8", "78.2", "290"],
    ["Section-aware + Dense", "79.5", "82.7", "300"],
    ["Section-aware + Hybrid", "84.9", "91.6", "380"],
]


def make_pdf(path: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60.0
    margin, width = 60, 475

    def ensure(space: float):
        nonlocal page, y
        if y + space > 790:
            page = doc.new_page(width=595, height=842)
            y = 60.0

    def write(text: str, size: float, bold: bool = False, mono: bool = False, gap: float = 6):
        nonlocal y
        font = "cour" if mono else ("hebo" if bold else "helv")
        lines = []
        for para in text.split("\n"):
            words, line = para.split(), ""
            for w in words:
                trial = f"{line} {w}".strip()
                if pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width:
                    lines.append(line)
                    line = w
                else:
                    line = trial
            lines.append(line)
        lh = size * 1.35
        ensure(len(lines) * lh + gap)
        for ln in lines:
            page.insert_text((margin, y + size), ln, fontsize=size, fontname=font)
            y += lh
        y += gap

    write(TITLE, 18, bold=True, gap=14)
    write("Enterprise AI Research Group", 10, gap=18)
    for heading, paras in SECTIONS:
        write(heading, 13, bold=True, gap=6)
        for p in paras:
            if p == "TABLE":
                ensure(len(TABLE) * 18 + 30)
                col_w = width / 4
                for r, row in enumerate(TABLE):
                    for c, cell in enumerate(row):
                        rect = pymupdf.Rect(margin + c * col_w, y, margin + (c + 1) * col_w, y + 18)
                        page.draw_rect(rect, color=(0, 0, 0), width=0.5)
                        page.insert_text((rect.x0 + 3, rect.y0 + 12), cell, fontsize=8.5, fontname="hebo" if r == 0 else "helv")
                    y += 18
                y += 4
                write("Table 1: Accuracy, recall and latency by configuration.", 9, gap=10)
            elif p.startswith("def "):
                write(p, 9, mono=True)
            else:
                write(p, 10.5)
        y += 6
    doc.set_metadata({"title": TITLE, "author": "Test Fixture"})
    doc.save(str(path))
    return path


def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading(TITLE, 0)
    for heading, paras in SECTIONS:
        d.add_heading(heading.split(" ", 1)[-1] if heading[0].isdigit() else heading, 1)
        for p in paras:
            if p == "TABLE":
                t = d.add_table(rows=len(TABLE), cols=len(TABLE[0]))
                for r, row in enumerate(TABLE):
                    for c, cell in enumerate(row):
                        t.cell(r, c).text = cell
            else:
                for line in p.split("\n"):
                    if line.startswith("- "):
                        d.add_paragraph(line[2:], style="List Bullet")
                    else:
                        d.add_paragraph(line)
    d.save(str(path))
    return path


if __name__ == "__main__":
    out = Path(__file__).parent
    print(make_pdf(out / "sample_research.pdf"))
    print(make_docx(out / "sample_research.docx"))
