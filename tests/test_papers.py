"""Research papers: reading (PDF, Word, LaTeX, text), references, citations, conversion to every format."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "samples" / "papers"))


@pytest.fixture(scope="module")
def samples(tmp_path_factory) -> dict[str, Path]:
    import make_sample_papers as m

    d = tmp_path_factory.mktemp("papers")
    fig = m.chart(d / "f1_vs_k.png")
    return {"pdf": m.make_pdf(d / "ieee.pdf", fig), "docx": m.make_docx(d / "ay.docx", fig),
            "latex": m.make_latex(d / "proj.zip", fig), "text": m.make_text(d / "raw.txt")}


# ------------------------------------------------------------------ references
REFS = [
    ('K. He, X. Zhang, S. Ren, and J. Sun, “Deep residual learning for image recognition,” in Proc. IEEE Conf. Comput. Vis. Pattern Recognit. (CVPR), 2016, pp. 770–778.',
     "paper-conference", "He", "Deep residual learning for image recognition", 2016),
    ('Y. LeCun, Y. Bengio, and G. Hinton, “Deep learning,” Nature, vol. 521, no. 7553, pp. 436–444, May 2015, doi: 10.1038/nature14539.',
     "article-journal", "LeCun", "Deep learning", 2015),
    ("LeCun Y, Bengio Y, Hinton G (2015) Deep learning. Nature 521(7553):436–444. https://doi.org/10.1038/nature14539",
     "article-journal", "LeCun", "Deep learning", 2015),
    ("LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539",
     "article-journal", "LeCun", "Deep learning", 2015),
    ("Y. LeCun, Y. Bengio, G. Hinton, Deep learning, Nature 521 (2015) 436–444. https://doi.org/10.1038/nature14539.",
     "article-journal", "LeCun", "Deep learning", 2015),
    ("LeCun, Y., Bengio, Y., Hinton, G.: Deep learning. Nature 521(7553), 436–444 (2015)", "article-journal", "LeCun", "Deep learning", 2015),
    ("Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. 2016. Deep residual learning for image recognition. In Proceedings of the IEEE CVPR. 770–778.",
     "paper-conference", "He", "Deep residual learning for image recognition", 2016),
    ("Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep learning. MIT Press.", "book", "Goodfellow", "Deep learning", 2016),
    ("T. Brown et al., “Language models are few-shot learners,” arXiv preprint arXiv:2005.14165, 2020.", "article", "Brown",
     "Language models are few-shot learners", 2020),
]


@pytest.mark.parametrize("raw,typ,family,title,year", REFS)
def test_reference_parsing(raw, typ, family, title, year):
    from backend.papers.references import completeness, parse_rules, verify

    csl = verify(parse_rules(raw), raw)
    assert completeness(csl) == "parsed", csl
    assert csl["type"] == typ and csl["author"][0]["family"] == family and csl["title"] == title
    assert csl["issued"]["date-parts"][0][0] == year


def test_apa_volume_after_comma():
    from backend.papers.references import parse_rules, verify

    raw = ("Brown, T., Mann, B., & Askell, A. (2020). Language models are few-shot learners. "
           "Advances in Neural Information Processing Systems, 33, 1877–1901.")
    csl = verify(parse_rules(raw), raw)
    assert csl["volume"] == "33" and csl["page"] == "1877–1901"
    assert csl["container-title"] == "Advances in Neural Information Processing Systems"


def test_verification_drops_invented_fields():
    from backend.papers.references import verify

    raw = "LeCun Y (2015) Deep learning. Nature 521:436–444"
    csl = verify({"title": "Deep learning", "container-title": "Science", "author": [{"family": "Smith", "given": "J"}],
                  "issued": {"date-parts": [[2015]]}}, raw)
    assert "container-title" not in csl and "author" not in csl and csl["title"] == "Deep learning"


def test_reference_list_splitting():
    from backend.papers.references import split_entries

    numbered = [("[1] A. B. Name, “Title one,” J. X, vol. 1,", 0), ("pp. 1–2, 2020.", 16), ("[2] C. Other, “Title two,” 2021.", 0)]
    assert [l for l, _ in split_entries(numbered)] == ["[1]", "[2]"]
    ay = [("LeCun, Y., & Hinton, G. (2015). Deep learning. Nature, 521, 436–444. https://doi.org/10.1038/nature14539", 0),
          ("Lewis, P., & Perez, E. (2020). Retrieval-augmented generation. NeurIPS, 33, 9459–9474.", 0)]
    assert len(split_entries(ay)) == 2


def test_numeric_and_author_year_citations():
    from backend.papers.citations import Linker, link_runs
    from backend.papers.model import Inline, Reference

    refs = [Reference(key="a", raw="", source_label="[1]", csl={"author": [{"family": "Smith"}], "issued": {"date-parts": [[2020]]}}),
            Reference(key="b", raw="", source_label="[2]", csl={"author": [{"family": "Lee"}], "issued": {"date-parts": [[2019]]}}),
            Reference(key="c", raw="", source_label="[3]", csl={"author": [{"family": "Park"}], "issued": {"date-parts": [[2018]]}})]
    out = link_runs([Inline(t="as in [1]–[3] and [2, 3].")], Linker(refs), "numeric")
    assert [r.cite for r in out if r.cite] == [["a", "b", "c"], ["b", "c"]]
    out = link_runs([Inline(t="shown (Smith et al., 2020; Lee & Kim, 2019) and by Park (2018).")], Linker(refs), "author-year")
    assert [r.cite for r in out if r.cite] == [["a", "b"], ["c"]]
    assert "Park" in "".join(r.t for r in out if not r.cite)  # narrative: author name stays in the sentence


def test_omml_to_latex():
    from lxml import etree

    from backend.papers.readers.omml import to_latex

    xml = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>'
           '<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f><m:r><m:t>+</m:t></m:r><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e>'
           '<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup><m:r><m:t>≤α</m:t></m:r></m:oMath>')
    assert to_latex(etree.fromstring(xml)) == r"\frac{a}{b}+{x}^{2}\leq \alpha"


# ------------------------------------------------------------------ reading
def _read(path: Path, kind: str, tmp: Path):
    from backend.papers import citations, crossrefs, references, structure
    from backend.papers.readers import read_any

    data = read_any(path, tmp, kind)
    p = structure.build(data["elems"], title=data["title"], front=data.get("front"), source_format=kind)
    if data.get("bib"):
        p.references = references.from_bibtex(data["bib"])
        p.source_citation_style = "latex"
    else:
        p.references = references.build_references(references.split_entries(data["refs"]), use_llm=False)
        p.source_citation_style = citations.detect_style([" ".join(r.t for r in b.runs) for b in p.all_blocks()])
        citations.link_paper(p)
    crossrefs.link(p)
    structure.normalize(p)
    return p, data


def test_read_two_column_pdf(samples, tmp_path):
    p, data = _read(samples["pdf"], "pdf", tmp_path)
    assert p.title.startswith("Retrieval-Augmented Invoice Understanding")
    assert [a.name for a in p.authors] == ["Asha Raman", "David Chen", "Priya Nair"]
    assert len(p.affiliations) == 2 and p.authors[1].affiliations == [1] and p.authors[0].email == "asha.raman@example.edu"
    assert len(p.abstract) and not any(r.b for r in p.abstract)  # IEEE's bold abstract is a style, not content
    assert len(p.keywords) == 4
    assert [s.title for s in p.sections if s.level == 1][:6] == ["Introduction", "Related Work", "Method", "Experiments", "Results", "Conclusion"]
    assert any(s.level == 2 and s.title == "Retrieval of Similar Invoices" for s in p.sections)
    kinds = [b.kind for b in p.all_blocks()]
    assert kinds.count("figure") == 1 and kinds.count("table") == 1 and kinds.count("equation") == 1
    tab = next(b for b in p.all_blocks() if b.kind == "table")
    assert tab.rows[0][0] == "Configuration" and len(tab.rows) == 4
    eq = next(b for b in p.all_blocks() if b.kind == "equation")
    assert eq.number == "1" and (tmp_path / eq.image).exists()
    assert len(p.references) == 6 and all(r.status == "parsed" and r.cited for r in p.references)
    assert any(s.kind == "acknowledgements" for s in p.sections)
    xrefs = [r.xref for b in p.all_blocks() for r in b.runs if r.xref]
    assert {"tab1", "fig1", "eq1"} <= set(xrefs)


def test_read_word_with_equations(samples, tmp_path):
    p, _ = _read(samples["docx"], "docx", tmp_path)
    assert len(p.authors) == 3 and p.source_citation_style == "author-year"
    eq = next(b for b in p.all_blocks() if b.kind == "equation")
    assert eq.omml and "\\frac" in eq.latex
    assert len(p.references) == 6 and all(r.cited for r in p.references)


def test_read_latex_project(samples, tmp_path):
    p, _ = _read(samples["latex"], "latex", tmp_path)
    assert p.source_citation_style == "latex" and len(p.references) == 6
    assert all(r.status == "parsed" for r in p.references)
    eq = next(b for b in p.all_blocks() if b.kind == "equation")
    assert "\\frac" in eq.latex
    fig = next(b for b in p.all_blocks() if b.kind == "figure")
    assert fig.image and (tmp_path / fig.image).exists()
    assert p.affiliations == ["Department of Computer Science, Example Institute of Technology, Pune, India"]


def test_read_raw_text(samples, tmp_path):
    p, _ = _read(samples["text"], "text", tmp_path)
    assert len(p.authors) == 3 and len(p.keywords) == 4
    assert any(b.kind == "table" and len(b.rows) == 4 for b in p.all_blocks())
    assert len(p.references) == 6 and all(r.cited for r in p.references)


# ------------------------------------------------------------------ conversion
@pytest.fixture(scope="module")
def converted(samples):
    from backend.papers import service

    meta = service.create("ieee.pdf", samples["pdf"], "", "springer_nature", "", use_ai=False)
    service._running[meta["id"]].join(timeout=300)
    return meta["id"]


def test_conversion_outputs(converted):
    from backend.papers import service

    meta = service.load_meta(converted)
    assert meta["status"] == "done", meta
    files = meta["outputs"]["springer_nature"]["files"]
    base = service.pdir(converted)
    for k in ("pdf", "docx", "latex", "bib", "tex", "report"):
        assert (base / files[k]).exists(), k
    tex = (base / files["tex"]).read_text(encoding="utf-8")
    assert "\\documentclass[pdflatex,sn-mathphys-num]{sn-jnl}" in tex and "\\cite{" in tex and "Table~\\ref{tab1}" in tex
    assert "\\section*{Declarations}" in tex and "\\bmhead{Acknowledgements}" in tex
    with zipfile.ZipFile(base / files["latex"]) as z:
        names = z.namelist()
    assert {"main.tex", "references.bib", "README.txt"} <= set(names) and any(n.startswith("figures/") for n in names)
    assert meta["report"]["fidelity"]["coverage"] >= 0.97


@pytest.mark.parametrize("fmt,style,needle", [
    ("ieee", "", "\\documentclass[conference]{IEEEtran}"), ("elsevier", "author-year", "\\documentclass[preprint,12pt,authoryear]{elsarticle}"),
    ("springer_lncs", "", "\\documentclass[runningheads]{llncs}"), ("acm", "", "\\documentclass[sigconf]{acmart}"),
    ("apa7", "", "\\documentclass[man,12pt]{apa7}")])
def test_reexport_every_format(converted, fmt, style, needle):
    import docx
    import fitz

    from backend.papers import service

    service.reexport(converted, fmt, style)
    service._running[converted].join(timeout=300)
    meta = service.load_meta(converted)
    assert meta["status"] == "done", meta
    out = meta["outputs"][fmt]
    base = service.pdir(converted)
    tex = (base / out["files"]["tex"]).read_text(encoding="utf-8")
    assert needle in tex
    if fmt == "apa7":
        assert "\\parencite{" in tex
    elif style == "author-year":
        assert "\\citep{" in tex
    assert len(fitz.open(str(base / out["files"]["pdf"]))) >= 2
    d = docx.Document(str(base / out["files"]["docx"]))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Retrieval-Augmented Invoice Understanding" in text
    if fmt == "ieee":
        assert "I. Introduction" in text and "[1]" in text
    if fmt == "apa7":
        assert "(LeCun et al., 2015)" in text and "LeCun, Y., Bengio, Y., & Hinton, G. (2015)" in text


def test_api_flow(samples):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.papers import service

    c = TestClient(app)
    assert {f["id"] for f in c.get("/api/papers/formats").json()} >= {"springer_nature", "springer_lncs", "elsevier", "ieee", "acm", "apa7"}
    r = c.post("/api/papers", files={"file": ("raw.txt", samples["text"].read_bytes(), "text/plain")},
               data={"format": "ieee", "citation_style": "", "use_ai": "false"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    service._running[pid].join(timeout=300)
    j = c.get(f"/api/papers/{pid}").json()
    assert j["status"] == "done" and j["paper"]["title"]
    pdf = c.get(f"/api/papers/{pid}/files/{j['outputs']['ieee']['files']['pdf']}?download=true")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert c.get(f"/api/papers/{pid}/files/../../meta.json").status_code in (404, 400)
    assert c.post("/api/papers", data={"format": "ieee", "text": "too short"}).status_code == 400
    assert c.post("/api/papers/parse-reference", json={"raw": REFS[0][0]}).json()["status"] == "parsed"
    assert c.delete(f"/api/papers/{pid}").status_code == 200


def test_pasted_text_with_windows_line_endings(samples):
    """Browsers submit textarea content with CRLF; tables and paragraphs must survive."""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.papers import service

    c = TestClient(app)
    text = samples["text"].read_text(encoding="utf-8").replace("\n", "\r\n")
    r = c.post("/api/papers", data={"format": "springer_lncs", "text": text, "use_ai": "false"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    service._running[pid].join(timeout=300)
    p = service.load_paper(pid)
    assert any(b.kind == "table" and len(b.rows) == 4 for b in p.all_blocks())
    assert len(p.references) == 6
    service.delete(pid)


# ------------------------------------------------------------------ journal-PDF details (PLOS-style)
def test_vancouver_reference_and_broken_doi():
    from backend.papers.references import build_references, join_urls

    assert join_urls("IEEE Trans. 2011. https://doi.org/10. 1109/TSE.2011.103") == "IEEE Trans. 2011. https://doi.org/10.1109/TSE.2011.103"
    assert join_urls("(https://github.com/ lining-nwpu/JiT)") == "(https://github.com/lining-nwpu/JiT)"
    assert join_urls("https://x.org/a. Accessed 2020") == "https://x.org/a. Accessed 2020"
    refs = build_references([("5", "Hall T, Beecham S, Bowes D, Gray D, Counsell S. A systematic literature review on fault "
                             "prediction performance in software engineering. IEEE Trans Softw Eng. 2011; 38(6):1276–1304. "
                             "https://doi.org/10. 1109/TSE.2011.103")], use_llm=False)
    r = refs[0]
    assert r.csl["author"][0]["family"] == "Hall" and r.csl["DOI"] == "10.1109/TSE.2011.103"


def test_dehyphenation_keeps_compounds():
    from backend.papers.readers import pdf as R

    R._VOCAB.clear()
    R._VOCAB.update({"coarser-grained": 1, "finer": 1, "grained": 1, "parame": 1, "terized": 1, "quanti": 1, "fied": 1})
    assert not R._dehyphen("produces finer-", "grained predictions")  # 'coarser-grained' elsewhere
    assert R._dehyphen("is parame-", "terized using")
    assert R._dehyphen("quanti-", "fied by")


def test_section_cross_references_follow_the_format():
    from backend.papers.crossrefs import link, render
    from backend.papers.formats import FORMATS

    get_format = FORMATS.__getitem__
    from backend.papers.model import Block, Inline, Paper, Section
    from backend.papers.writers.common import arrange, email_line
    from backend.papers.model import Author

    p = Paper(title="T", sections=[
        Section(title="Introduction", level=1, source_number="1",
                blocks=[Block(kind="para", runs=[Inline(t="As shown in Section 2.1, it works.")])]),
        Section(title="Methods", level=1, source_number="2"),
        Section(title="Graph modeling", level=2, source_number="2.1")])
    assert link(p) == 1
    x = next(r for r in p.sections[0].blocks[0].runs if r.xref)
    assert render(get_format("ieee"), arrange(p, get_format("ieee")), x.xref, x.t) == "Section II-A"
    assert render(get_format("springer_nature"), arrange(p, get_format("springer_nature")), x.xref, x.t) == "Section 2.1"
    assert "Graph modeling" in render(get_format("apa7"), arrange(p, get_format("apa7")), x.xref, x.t)
    p.authors = [Author(name="A B", email="a@b.org", corresponding=True)]
    assert email_line(p) == "*Corresponding author: a@b.org"
