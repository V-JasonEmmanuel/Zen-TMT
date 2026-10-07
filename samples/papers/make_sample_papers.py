"""Sample research papers for trying the Research Papers converter (all fictional authors/data;
the cited works are real, well-known publications).

  sample_ieee_two_column.pdf   two-column IEEE-style PDF: numeric citations, chart, table, equation
  sample_author_year.docx      single-column Word paper: author-year citations, Word equations, table
  sample_latex_project.zip     LaTeX source (article class) + references.bib + figure
  sample_raw_text.txt          raw pasted-style text with APA references

Run:  python samples/papers/make_sample_papers.py
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

TITLE = "Retrieval-Augmented Invoice Understanding with Small Language Models"
AUTHORS = [("Asha Raman", 1, "asha.raman@example.edu"), ("David Chen", 2, "d.chen@example.com"), ("Priya Nair", 1, "")]
AFFS = ["Department of Computer Science, Example Institute of Technology, Pune, India",
        "Applied AI Lab, Example Analytics Ltd., London, UK"]
ABSTRACT = ("Automating accounts-payable workflows requires reading invoices whose layouts vary across thousands of "
            "vendors. Large language models handle this variety but are expensive to run on premises. We study whether small "
            "language models, combined with retrieval of similar past invoices, can match larger models on field extraction. "
            "Our pipeline retrieves the five most similar labelled invoices from a vector index and provides them as worked "
            "examples to a 3-billion-parameter model running locally. On a benchmark of 2,400 invoices from 310 vendors, the "
            "approach reaches an F1 score of 0.94 on key fields, within 0.01 of a 70-billion-parameter model, while reducing "
            "inference cost by a factor of 18. We further show that retrieval reduces hallucinated values by 63% and that "
            "accuracy remains stable for vendors not seen during development. The results indicate that retrieval-augmented "
            "small models are a practical option for private, on-premises document automation.")
KEYWORDS = ["document understanding", "retrieval-augmented generation", "small language models", "invoice processing"]
SECTIONS = [
    ("Introduction", 1, [
        "Invoice processing remains one of the most labour-intensive finance operations. Rule-based templates break when "
        "vendors change layouts, and deep learning approaches based on convolutional networks {c:lecun} or residual "
        "architectures {c:he} require large labelled datasets for every document type.",
        "Transformer models {c:vaswani} and pre-trained language models {c:devlin} changed this picture, and very large "
        "models can now extract fields from unseen layouts with few or no examples {c:brown}. However, running such models "
        "on premises is costly, and sending financial documents to external services is often not permitted.",
        "Retrieval-augmented generation {c:lewis} offers a middle path: a small model receives relevant context retrieved "
        "from a local index. In this paper we ask whether retrieval of similar, already-processed invoices allows a small "
        "model to reach the accuracy of a much larger one. Our contributions are a retrieval-augmented extraction pipeline, "
        "a benchmark of 2,400 invoices, and an analysis of accuracy, cost and hallucination."]),
    ("Related Work", 1, [
        "Early document understanding systems combined optical character recognition with hand-written rules. Neural "
        "approaches learned layout features directly from pixels {c:lecun}, and residual networks enabled much deeper "
        "visual encoders {c:he}. Language-model based methods instead treat a document as text with positions {c:devlin}.",
        "Few-shot prompting showed that sufficiently large models can follow worked examples {c:brown}, and retrieval "
        "augmentation grounds generation in external knowledge {c:lewis}. Our work combines both ideas for structured "
        "extraction on resource-constrained hardware."]),
    ("Method", 1, []),
    ("Retrieval of Similar Invoices", 2, [
        "Each labelled invoice is embedded with a sentence encoder and stored in a vector index. For a new invoice we "
        "retrieve the k most similar documents by cosine similarity, defined in Eq. (1), and use their labelled fields as "
        "worked examples."]),
    ("EQ", 0, ["sim(a, b) = (a · b) / (‖a‖ ‖b‖)"]),
    ("Extraction with a Small Model", 2, [
        "The prompt contains the retrieved examples followed by the new invoice. A 3-billion-parameter model generates "
        "the fields as JSON, which is validated against a schema. Values that do not appear in the invoice text are "
        "rejected, which prevents invented amounts or dates."]),
    ("Experiments", 1, [
        "We collected 2,400 invoices from 310 vendors, labelled with vendor name, invoice number, date, total amount and "
        "currency. Table I compares the configurations, and Fig. 1 shows how accuracy changes with the number of retrieved "
        "examples."]),
    ("TABLE", 0, []),
    ("FIGURE", 0, []),
    ("Results", 1, [
        "Retrieval with five examples raises the F1 score of the small model from 0.81 to 0.94, within 0.01 of the large "
        "model, while inference cost falls by a factor of 18. Hallucinated values drop by 63% because the model copies "
        "formats from the examples instead of guessing them."]),
    ("Conclusion", 1, [
        "Retrieval-augmented small language models extract invoice fields almost as accurately as models twenty times "
        "larger, at a fraction of the cost and without sending documents outside the organisation. Future work will study "
        "multi-page invoices and purchase-order matching."]),
    ("Acknowledgment", 1, ["The authors thank the finance operations team of the pilot organisation for labelling support."]),
]
REFS = {
    "lecun": ("Y. LeCun, Y. Bengio, and G. Hinton, “Deep learning,” Nature, vol. 521, no. 7553, pp. 436–444, 2015, doi: 10.1038/nature14539.",
              "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539",
              "@article{lecun2015deep,\n  author = {LeCun, Yann and Bengio, Yoshua and Hinton, Geoffrey},\n  title = {Deep learning},\n  journal = {Nature},\n  volume = {521},\n  number = {7553},\n  pages = {436--444},\n  year = {2015},\n  doi = {10.1038/nature14539}\n}"),
    "he": ("K. He, X. Zhang, S. Ren, and J. Sun, “Deep residual learning for image recognition,” in Proc. IEEE Conf. Comput. Vis. Pattern Recognit. (CVPR), 2016, pp. 770–778.",
           "He, K., Zhang, X., Ren, S., & Sun, J. (2016). Deep residual learning for image recognition. In Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (pp. 770–778).",
           "@inproceedings{he2016deep,\n  author = {He, Kaiming and Zhang, Xiangyu and Ren, Shaoqing and Sun, Jian},\n  title = {Deep residual learning for image recognition},\n  booktitle = {Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition},\n  pages = {770--778},\n  year = {2016}\n}"),
    "vaswani": ("A. Vaswani et al., “Attention is all you need,” in Adv. Neural Inf. Process. Syst., vol. 30, 2017, pp. 5998–6008.",
                "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30, 5998–6008.",
                "@inproceedings{vaswani2017attention,\n  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, Lukasz and Polosukhin, Illia},\n  title = {Attention is all you need},\n  booktitle = {Advances in Neural Information Processing Systems},\n  volume = {30},\n  pages = {5998--6008},\n  year = {2017}\n}"),
    "devlin": ("J. Devlin, M.-W. Chang, K. Lee, and K. Toutanova, “BERT: Pre-training of deep bidirectional transformers for language understanding,” in Proc. NAACL-HLT, 2019, pp. 4171–4186.",
               "Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In Proceedings of NAACL-HLT (pp. 4171–4186).",
               "@inproceedings{devlin2019bert,\n  author = {Devlin, Jacob and Chang, Ming-Wei and Lee, Kenton and Toutanova, Kristina},\n  title = {{BERT}: Pre-training of deep bidirectional transformers for language understanding},\n  booktitle = {Proceedings of NAACL-HLT},\n  pages = {4171--4186},\n  year = {2019}\n}"),
    "brown": ("T. Brown et al., “Language models are few-shot learners,” in Adv. Neural Inf. Process. Syst., vol. 33, 2020, pp. 1877–1901.",
              "Brown, T., Mann, B., Ryder, N., Subbiah, M., Kaplan, J., Dhariwal, P., Neelakantan, A., Shyam, P., Sastry, G., & Askell, A. (2020). Language models are few-shot learners. Advances in Neural Information Processing Systems, 33, 1877–1901.",
              "@inproceedings{brown2020language,\n  author = {Brown, Tom and Mann, Benjamin and Ryder, Nick and Subbiah, Melanie and others},\n  title = {Language models are few-shot learners},\n  booktitle = {Advances in Neural Information Processing Systems},\n  volume = {33},\n  pages = {1877--1901},\n  year = {2020}\n}"),
    "lewis": ("P. Lewis et al., “Retrieval-augmented generation for knowledge-intensive NLP tasks,” in Adv. Neural Inf. Process. Syst., vol. 33, 2020, pp. 9459–9474.",
              "Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., & Rocktäschel, T. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. Advances in Neural Information Processing Systems, 33, 9459–9474.",
              "@inproceedings{lewis2020retrieval,\n  author = {Lewis, Patrick and Perez, Ethan and Piktus, Aleksandra and Petroni, Fabio and others},\n  title = {Retrieval-augmented generation for knowledge-intensive {NLP} tasks},\n  booktitle = {Advances in Neural Information Processing Systems},\n  volume = {33},\n  pages = {9459--9474},\n  year = {2020}\n}"),
}
ORDER = ["lecun", "he", "vaswani", "devlin", "brown", "lewis"]
AY = {"lecun": "LeCun et al., 2015", "he": "He et al., 2016", "vaswani": "Vaswani et al., 2017", "devlin": "Devlin et al., 2019",
      "brown": "Brown et al., 2020", "lewis": "Lewis et al., 2020"}
TABLE = [["Configuration", "Parameters", "F1 (key fields)", "Relative cost"],
         ["Small model, zero-shot", "3B", "0.81", "1.0"], ["Small model + retrieval (k = 5)", "3B", "0.94", "1.3"],
         ["Large model, zero-shot", "70B", "0.95", "23.4"]]


def chart(path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    k = [0, 1, 2, 3, 5, 8]
    small = [0.81, 0.87, 0.90, 0.92, 0.94, 0.94]
    fig, ax = plt.subplots(figsize=(3.4, 2.2), dpi=200)
    ax.plot(k, small, marker="o", color="black", label="3B + retrieval")
    ax.axhline(0.95, color="grey", linestyle="--", label="70B zero-shot")
    ax.set_xlabel("Retrieved examples (k)")
    ax.set_ylabel("F1 score")
    ax.set_ylim(0.78, 0.97)
    ax.legend(fontsize=7, frameon=False)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _numeric_text(s: str) -> str:
    import re

    nums = {k: i + 1 for i, k in enumerate(ORDER)}
    return re.sub(r"\{c:(\w+)\}", lambda m: f"[{nums[m.group(1)]}]", s)


def _ay_text(s: str) -> str:
    import re

    return re.sub(r"\{c:(\w+)\}", lambda m: f"({AY[m.group(1)]})", s)


# ------------------------------------------------------------------ IEEE-style two-column PDF
def make_pdf(path: Path, fig: Path) -> Path:
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import BaseDocTemplate, Frame, FrameBreak, Image, NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors

    from backend.papers.writers.pdf import _register_fonts

    F = _register_fonts()
    W, H = LETTER
    lm = rm = 0.65 * inch
    tm, bm = 0.75 * inch, 0.9 * inch
    gap = 0.25 * inch
    cw = (W - lm - rm - gap) / 2
    body = ParagraphStyle("b", fontName=F, fontSize=10, leading=12, alignment=TA_JUSTIFY, firstLineIndent=10)
    h1 = ParagraphStyle("h1", fontName=F, fontSize=10, leading=12, alignment=TA_CENTER, spaceBefore=8, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName=F + "-I", fontSize=10, leading=12, spaceBefore=6, spaceAfter=3)
    cap = ParagraphStyle("c", fontName=F, fontSize=8, leading=9.5, alignment=TA_CENTER, spaceAfter=6, spaceBefore=3)
    ref = ParagraphStyle("r", fontName=F, fontSize=8, leading=9.5, leftIndent=16, firstLineIndent=-16, spaceAfter=2)
    front = [Paragraph(TITLE, ParagraphStyle("t", fontName=F, fontSize=22, leading=26, alignment=TA_CENTER, spaceAfter=10))]
    front.append(Paragraph(", ".join(f"{n}<super>{a}</super>" for n, a, _ in AUTHORS),
                           ParagraphStyle("a", fontName=F, fontSize=11, leading=14, alignment=TA_CENTER)))
    for i, a in enumerate(AFFS, 1):
        front.append(Paragraph(f"<super>{i}</super><i>{a}</i>", ParagraphStyle("af", fontName=F, fontSize=9, leading=11, alignment=TA_CENTER)))
    front.append(Paragraph(", ".join(e for _, _, e in AUTHORS if e), ParagraphStyle("em", fontName=F, fontSize=9, leading=11, alignment=TA_CENTER)))
    front.append(Spacer(1, 10))
    fh = sum(x.wrap(W - lm - rm, H)[1] for x in front) + 30
    story = [NextPageTemplate("later")] + front + [FrameBreak()]
    abst = ParagraphStyle("ab", fontName=F + "-B", fontSize=9, leading=11, alignment=TA_JUSTIFY, spaceAfter=6)
    story.append(Paragraph("<i>Abstract</i>—" + ABSTRACT, abst))
    story.append(Paragraph("<i>Index Terms</i>—" + ", ".join(KEYWORDS) + ".", abst))
    roman = ["I", "II", "III", "IV", "V", "VI", "VII"]
    n1 = n2 = 0
    for title, lvl, paras in SECTIONS:
        if title == "EQ":
            t = Table([[Paragraph("<i>sim</i>(<b>a</b>, <b>b</b>) = (<b>a</b> · <b>b</b>) / (‖<b>a</b>‖ ‖<b>b</b>‖)",
                                  ParagraphStyle("eq", fontName=F, fontSize=10, alignment=TA_CENTER)), Paragraph("(1)", body)]],
                      colWidths=[cw * 0.85, cw * 0.15])
            story.append(t)
            continue
        if title == "TABLE":
            story.append(Paragraph("TABLE I<br/>COMPARISON OF EXTRACTION CONFIGURATIONS", cap))
            t = Table(TABLE, colWidths=[cw * 0.4, cw * 0.18, cw * 0.22, cw * 0.2])
            t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 7.5), ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            story += [t, Spacer(1, 6)]
            continue
        if title == "FIGURE":
            story.append(Image(str(fig), width=cw * 0.95, height=cw * 0.95 * 2.2 / 3.4))
            story.append(Paragraph("Fig. 1. F1 score of the small model as a function of the number of retrieved examples.", cap))
            continue
        if lvl == 1:
            n1 += 1
            n2 = 0
            story.append(Paragraph(f"{roman[n1 - 1]}. {title.upper()}" if title != "Acknowledgment" else "ACKNOWLEDGMENT", h1))
        else:
            n2 += 1
            story.append(Paragraph(f"{'ABCDEFG'[n2 - 1]}. {title}", h2))
        for ptxt in paras:
            story.append(Paragraph(_numeric_text(ptxt), body))
    story.append(Paragraph("REFERENCES", h1))
    for i, k in enumerate(ORDER, 1):
        story.append(Paragraph(f"[{i}] " + REFS[k][0], ref))

    def footer(canv, doc):
        canv.setFont(F, 8)
        canv.drawCentredString(W / 2, 0.5 * inch, str(doc.page))

    doc = BaseDocTemplate(str(path), pagesize=LETTER)
    ch = H - tm - bm - fh
    doc.addPageTemplates([
        PageTemplate("first", [Frame(lm, H - tm - fh, W - lm - rm, fh, id="f"), Frame(lm, bm, cw, ch, id="a"), Frame(lm + cw + gap, bm, cw, ch, id="b")], onPage=footer),
        PageTemplate("later", [Frame(lm, bm, cw, H - tm - bm, id="c"), Frame(lm + cw + gap, bm, cw, H - tm - bm, id="d")], onPage=footer)])
    doc.build(story)
    return path


# ------------------------------------------------------------------ Word (author-year)
OMML_EQ = ('<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:oMath>'
           '<m:r><m:t>sim</m:t></m:r><m:d><m:dPr><m:begChr m:val="("/><m:endChr m:val=")"/></m:dPr><m:e><m:r><m:t>a,b</m:t></m:r></m:e></m:d>'
           '<m:r><m:t>=</m:t></m:r><m:f><m:num><m:r><m:t>a·b</m:t></m:r></m:num><m:den><m:d><m:dPr><m:begChr m:val="‖"/><m:endChr m:val="‖"/></m:dPr>'
           '<m:e><m:r><m:t>a</m:t></m:r></m:e></m:d><m:d><m:dPr><m:begChr m:val="‖"/><m:endChr m:val="‖"/></m:dPr><m:e><m:r><m:t>b</m:t></m:r></m:e></m:d></m:den></m:f>'
           '</m:oMath></m:oMathPara>')


def make_docx(path: Path, fig: Path) -> Path:
    import docx
    from docx.oxml import parse_xml
    from docx.shared import Inches

    d = docx.Document()
    d.add_heading(TITLE, 0)
    d.add_paragraph(", ".join(f"{n}{a}" for n, a, _ in AUTHORS))
    for i, a in enumerate(AFFS, 1):
        d.add_paragraph(f"{i} {a}")
    d.add_paragraph("Email: " + ", ".join(e for _, _, e in AUTHORS if e))
    d.add_heading("Abstract", 1)
    d.add_paragraph(ABSTRACT)
    d.add_paragraph("Keywords: " + "; ".join(KEYWORDS))
    n1 = 0
    for title, lvl, paras in SECTIONS:
        if title == "EQ":
            p = d.add_paragraph()
            p._p.append(parse_xml(OMML_EQ))
            continue
        if title == "TABLE":
            d.add_paragraph("Table 1. Comparison of extraction configurations", style="Caption")
            t = d.add_table(rows=len(TABLE), cols=4)
            t.style = "Table Grid"
            for r, row in enumerate(TABLE):
                for c, v in enumerate(row):
                    t.cell(r, c).text = v
            continue
        if title == "FIGURE":
            d.add_picture(str(fig), width=Inches(4.5))
            d.add_paragraph("Figure 1. F1 score of the small model as a function of the number of retrieved examples.", style="Caption")
            continue
        if lvl == 1:
            n1 += 1
            d.add_heading(f"{n1} {title}" if title != "Acknowledgment" else "Acknowledgements", 1)
        else:
            d.add_heading(title, 2)
        for ptxt in paras:
            d.add_paragraph(_ay_text(ptxt).replace("Eq. (1)", "Equation (1)").replace("Table I", "Table 1"))
    d.add_heading("References", 1)
    for k in sorted(ORDER, key=lambda k: REFS[k][1]):
        d.add_paragraph(REFS[k][1])
    d.save(path)
    return path


# ------------------------------------------------------------------ LaTeX project
def make_latex(path: Path, fig: Path) -> Path:
    import re

    def cite(s):
        return re.sub(r"\{c:(\w+)\}", lambda m: "\\cite{" + REFS[m.group(1)][2].split("{", 1)[1].split(",", 1)[0] + "}", s)

    body = []
    for title, lvl, paras in SECTIONS:
        if title == "EQ":
            body.append("\\begin{equation}\n\\mathrm{sim}(\\mathbf{a},\\mathbf{b}) = \\frac{\\mathbf{a}\\cdot\\mathbf{b}}{\\lVert\\mathbf{a}\\rVert\\,\\lVert\\mathbf{b}\\rVert}\n\\label{eq:sim}\n\\end{equation}")
            continue
        if title == "TABLE":
            rows = " \\\\\n".join(" & ".join(r) for r in TABLE[1:])
            body.append("\\begin{table}[t]\n\\centering\n\\caption{Comparison of extraction configurations}\\label{tab:cmp}\n"
                        "\\begin{tabular}{lccc}\n\\hline\n" + " & ".join(TABLE[0]) + " \\\\\n\\hline\n" + rows + " \\\\\n\\hline\n\\end{tabular}\n\\end{table}")
            continue
        if title == "FIGURE":
            body.append("\\begin{figure}[t]\n\\centering\n\\includegraphics[width=0.8\\linewidth]{figures/f1_vs_k.png}\n"
                        "\\caption{F1 score of the small model as a function of the number of retrieved examples.}\\label{fig:k}\n\\end{figure}")
            continue
        cmd = "section" if lvl == 1 else "subsection"
        body.append(f"\\{cmd}{{{title}}}" if title != "Acknowledgment" else "\\section*{Acknowledgements}")
        for ptxt in paras:
            t = cite(ptxt).replace("Eq. (1)", "Eq.~(\\ref{eq:sim})").replace("Table I", "Table~\\ref{tab:cmp}").replace("Fig. 1", "Fig.~\\ref{fig:k}")
            t = t.replace("%", "\\%")
            body.append(t)
    tex = ("\\documentclass[11pt]{article}\n\\usepackage{graphicx}\n\\usepackage{amsmath}\n\n"
           f"\\title{{{TITLE}}}\n\\author{{" + " \\and ".join(n for n, _, _ in AUTHORS) + "\\\\ " + AFFS[0] + "}\n\n"
           "\\begin{document}\n\\maketitle\n\\begin{abstract}\n" + ABSTRACT.replace("%", "\\%") + "\n\\end{abstract}\n\n"
           + "\n\n".join(body) + "\n\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("paper/main.tex", tex)
        z.writestr("paper/references.bib", "\n\n".join(REFS[k][2] for k in ORDER))
        z.write(fig, "paper/figures/f1_vs_k.png")
    return path


# ------------------------------------------------------------------ raw text
def make_text(path: Path) -> Path:
    lines = [TITLE, "", ", ".join(n for n, _, _ in AUTHORS), AFFS[0], "", "Abstract", ABSTRACT, "",
             "Keywords: " + ", ".join(KEYWORDS), ""]
    n1 = n2 = 0
    for title, lvl, paras in SECTIONS:
        if title in ("EQ", "FIGURE"):
            continue
        if title == "TABLE":
            lines += ["Table 1. Comparison of extraction configurations", ""]
            lines += ["  ".join(r) for r in TABLE] + [""]
            continue
        if lvl == 1:
            n1 += 1
            n2 = 0
            lines += [f"{n1}. {title}" if title != "Acknowledgment" else "Acknowledgements", ""]
        else:
            n2 += 1
            lines += [f"{n1}.{n2} {title}", ""]
        for ptxt in paras:
            lines += [_ay_text(ptxt).replace("Table I", "Table 1").replace("Fig. 1", "Figure 1"), ""]
    lines += ["References", ""]
    lines += [REFS[k][1] for k in sorted(ORDER, key=lambda k: REFS[k][1])]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    fig = chart(HERE / "f1_vs_k.png")
    out = [make_pdf(HERE / "sample_ieee_two_column.pdf", fig), make_docx(HERE / "sample_author_year.docx", fig),
           make_latex(HERE / "sample_latex_project.zip", fig), make_text(HERE / "sample_raw_text.txt")]
    fig.unlink(missing_ok=True)
    for p in out:
        print(f"{p.name:32} {p.stat().st_size / 1024:6.0f} KB")


if __name__ == "__main__":
    main()
