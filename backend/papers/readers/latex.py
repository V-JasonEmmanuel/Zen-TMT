"""LaTeX papers: a .tex file, or a .zip with the .tex, .bib and figures.

The front matter is read from the common class conventions (article, IEEEtran, llncs, elsarticle,
sn-jnl, acmart, revtex): \\title, \\author (\\and, \\inst, \\IEEEauthorblockN/A, \\fnm/\\sur, [n]
indexes), \\affiliation / \\institute / \\address, abstract, keywords. The body keeps equations as
LaTeX source and citations as keys (\\cite, \\citep, \\citet, ...), so nothing is re-parsed from text.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from backend.papers.model import Block, Inline
from backend.papers.structure import Elem

CITE = re.compile(r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|parencite|textcite|autocite|Cite)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")


def _l2t(s: str) -> str:
    from pylatexenc.latex2text import LatexNodes2Text

    try:
        return LatexNodes2Text(math_mode="verbatim").latex_to_text(s)
    except Exception:
        return re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?|[{}]", "", s)


def _arg(s: str, start: int) -> tuple[str, int]:
    """Balanced {...} argument starting at s[start] == '{'."""
    if start >= len(s) or s[start] != "{":
        return "", start
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "\\":
            continue
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            depth += 1
        elif c == "}" and s[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    return s[start + 1:], len(s)


def _commands(s: str, name: str) -> list[tuple[str, str]]:
    """All \\name[opt]{arg} occurrences -> [(opt, arg)]."""
    out = []
    for m in re.finditer(r"\\" + name + r"\*?\s*(\[([^\]]*)\])?\s*(?=\{)", s):
        arg, _ = _arg(s, m.end())
        out.append((m.group(2) or "", arg))
    return out


def _env(s: str, name: str) -> list[str]:
    return re.findall(r"\\begin\{" + re.escape(name) + r"\}(.*?)\\end\{" + re.escape(name) + r"\}", s, re.S)


def _strip_comments(s: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", s)


def _load(path: Path, work_dir: Path) -> tuple[str, str, dict[str, Path]]:
    """-> (main tex source with \\input expanded, concatenated .bib text, files by name)."""
    files: dict[str, Path] = {}
    if path.suffix.lower() == ".zip":
        src_dir = work_dir / "source"
        with zipfile.ZipFile(path) as z:
            for m in z.infolist():
                n = m.filename.replace("\\", "/")
                if m.is_dir() or n.startswith("/") or ".." in n.split("/"):
                    continue
                target = (src_dir / n).resolve()
                if src_dir.resolve() not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(m))
                files[n] = target
        texs = [p for n, p in files.items() if n.endswith(".tex")]
        main = next((p for p in texs if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")), texs[0] if texs else None)
        if main is None:
            raise ValueError("The archive contains no .tex file.")
    else:
        main = path
        files[path.name] = path
    root = main.parent
    src = _strip_comments(main.read_text(encoding="utf-8", errors="ignore"))

    def expand(s: str, depth: int = 0) -> str:
        if depth > 4:
            return s

        def rep(m):
            name = m.group(1).strip()
            cand = root / (name if name.endswith(".tex") else name + ".tex")
            if cand.exists():
                return expand(_strip_comments(cand.read_text(encoding="utf-8", errors="ignore")), depth + 1)
            return ""
        return re.sub(r"\\(?:input|include)\{([^}]+)\}", rep, s)

    src = expand(src)
    bib = ""
    for _, arg in _commands(src, "bibliography") + _commands(src, "addbibresource"):
        for name in arg.split(","):
            name = name.strip()
            cand = root / (name if name.endswith(".bib") else name + ".bib")
            if cand.exists():
                bib += cand.read_text(encoding="utf-8", errors="ignore") + "\n"
    if not bib:
        for n, p in files.items():
            if n.endswith(".bib"):
                bib += p.read_text(encoding="utf-8", errors="ignore") + "\n"
    return src, bib, files


def _inline(s: str, labels: dict[str, str]) -> list[Inline]:
    """LaTeX paragraph -> runs: text (via latex2text), $math$, \\cite keys, \\emph/\\textbf."""
    s = re.sub(r"~", " ", s)
    s = re.sub(r"\\(?:eq)?ref\{([^}]*)\}", lambda m: labels.get(m.group(1), "?"), s)
    s = re.sub(r"\\(?:footnote)\{[^{}]*\}", "", s)
    tokens = re.split(r"(\$\$.+?\$\$|\$[^$]+\$|\\\(.+?\\\)|" + CITE.pattern + r"|\\(?:emph|textit|textbf)\{[^{}]*\})", s, flags=re.S)
    out: list[Inline] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok is None:
            continue
        if not tok:
            continue
        cm = CITE.fullmatch(tok)
        if cm:
            keys = [k.strip() for k in cm.group(1).split(",") if k.strip()]
            narrative = tok.startswith(("\\citet", "\\textcite", "\\citeauthor"))
            out.append(Inline(cite=keys, raw_cite=tok, t="narrative" if narrative else ""))
            i += 1  # skip the captured key group of CITE inside the split pattern
            continue
        if tok.startswith("$") or tok.startswith("\\("):
            out.append(Inline(math=tok.strip("$").removeprefix("\\(").removesuffix("\\)").strip()))
            continue
        fm = re.fullmatch(r"\\(emph|textit|textbf)\{([^{}]*)\}", tok)
        if fm:
            out.append(Inline(t=_l2t(fm.group(2)), i=fm.group(1) != "textbf", b=fm.group(1) == "textbf"))
            continue
        t = _l2t(tok)
        if t:
            out.append(Inline(t=t))
    # normalise whitespace
    for r in out:
        if r.t and not r.cite:
            r.t = re.sub(r"\s+", " ", r.t)
    if out and out[0].t:
        out[0].t = out[0].t.lstrip()
    if out and out[-1].t and not out[-1].cite:
        out[-1].t = out[-1].t.rstrip()
    return [r for r in out if r.t or r.math or r.cite]


def _figure(env: str, files: dict[str, Path], work_dir: Path, n: int, labels: dict[str, str]) -> Block:
    import shutil

    blk = Block(kind="figure", label=f"fig{n}")
    m = re.search(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", env)
    if m:
        want = m.group(1).strip()
        cand = [p for name, p in files.items() if name.endswith(want) or Path(name).stem == Path(want).stem]
        if cand:
            src = cand[0]
            fig_dir = work_dir / "figures"
            fig_dir.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() == ".pdf":
                import fitz

                doc = fitz.open(str(src))
                out = fig_dir / f"figure_{n:02d}.png"
                doc[0].get_pixmap(matrix=fitz.Matrix(3, 3)).save(str(out))
            else:
                out = fig_dir / f"figure_{n:02d}{src.suffix.lower()}"
                shutil.copyfile(src, out)
            blk.image = f"figures/{out.name}"
        else:
            blk.note = f"Figure file '{want}' was not included in the upload."
    caps = _commands(env, "caption")
    if caps:
        blk.caption = _inline(caps[0][1], labels)
    return blk


def _table(env: str, n: int, labels: dict[str, str]) -> Block:
    blk = Block(kind="table", label=f"tab{n}")
    caps = _commands(env, "caption")
    if caps:
        blk.caption = _inline(caps[0][1], labels)
    tab = re.search(r"\\begin\{(tabular\*?|tabularx|longtable)\}(?:\{[^}]*\}){1,2}(.*?)\\end\{\1\}", env, re.S)
    if tab:
        body = re.sub(r"\\(?:hline|toprule|midrule|bottomrule|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\})", "", tab.group(2))
        rows = []
        for row in re.split(r"\\\\(?:\[[^\]]*\])?", body):
            if not row.strip():
                continue
            cells = [re.sub(r"\s+", " ", _l2t(re.sub(r"\\multicolumn\{\d+\}\{[^}]*\}\{(.*?)\}", r"\1", c))).strip() for c in re.split(r"(?<!\\)&", row)]
            rows.append(cells)
        blk.rows = [r for r in rows if any(r)]
    return blk


def read(path: Path, work_dir: Path) -> dict:
    src, bib, files = _load(path, work_dir)
    pre, _, rest = src.partition("\\begin{document}")
    doc = rest.split("\\end{document}")[0] if rest else src
    head = pre + doc
    # ---- labels -> numbers (figures, tables, equations, sections in order of appearance)
    labels: dict[str, str] = {}
    counts = {"figure": 0, "table": 0, "equation": 0, "section": 0}
    for m in re.finditer(r"\\begin\{(figure\*?|table\*?|equation\*?|align\*?)\}(.*?)\\end\{\1\}|\\section\*?\{[^}]*\}(\s*\\label\{([^}]*)\})?", doc, re.S):
        if m.group(1):
            kind = m.group(1).rstrip("*")
            kind = "equation" if kind == "align" else kind
            counts[kind] += 1
            for lab in re.findall(r"\\label\{([^}]*)\}", m.group(2)):
                labels[lab] = str(counts[kind])
        else:
            counts["section"] += 1
            if m.group(4):
                labels[m.group(4)] = str(counts["section"])
    # ---- front matter
    title = _l2t(_commands(head, "title")[0][1]).strip() if _commands(head, "title") else ""
    title = re.sub(r"\s+", " ", title)
    front: list[str] = []
    authors_raw = [a for _, a in _commands(head, "author")]
    after_break: list[str] = []
    for a in authors_raw:
        # article class: \author{A \and B \\ Affiliation} - text after \\ is the affiliation
        for part in re.split(r"\\and", a):
            if "\\\\" in part and "IEEEauthorblock" not in part:
                aff = re.sub(r"\s+", " ", _l2t(part.split("\\\\", 1)[1].replace("\\\\", ", "))).strip(" ,")
                if aff and aff not in after_break:
                    after_break.append(aff)
        a = re.sub(r"\\(?:fnm|sur|spfx|dgr)\{([^}]*)\}", r"\1", a)
        a = re.sub(r"\\inst\{([^}]*)\}", r"^\1", a)
        a = re.sub(r"\\(?:thanks|footnote|email|orcid|orcidID)\{[^}]*\}", "", a)
        a = re.sub(r"\\(?:IEEEauthorblockA)\{.*", "", a, flags=re.S)
        a = a.replace("\\IEEEauthorblockN{", "").replace("\\and", ",")
        a = re.sub(r"\\\\.*", "", a, flags=re.S)
        names = re.sub(r"\s+", " ", _l2t(a)).strip(" ,")
        if names:
            front.append(names)
    front += after_break
    affs = [a for _, a in _commands(head, "affiliation")] + [a for _, a in _commands(head, "institute")] + \
        [a for _, a in _commands(head, "address")] + re.findall(r"\\IEEEauthorblockA\{(.*?)\}\s*(?:\\and|\}|$)", head, re.S)
    for a in affs:
        for part in re.split(r"\\and", a):
            t = re.sub(r"\\(?:orgdiv|orgname|orgaddress|street|city|postcode|state|country|institution|department)\{([^}]*)\}", r"\1, ", part)
            t = re.sub(r"\s+", " ", _l2t(re.sub(r"\\\\", ", ", t))).strip(" ,")
            t = re.sub(r"(,\s*)+", ", ", t)
            if t:
                front.append(t)
    abstract = _env(doc, "abstract") or [a for _, a in _commands(head, "abstract")]
    kw = _env(doc, "keyword") + _env(doc, "IEEEkeywords") + [a for _, a in _commands(head, "keywords")]
    elems: list[Elem] = []
    labels_inv = labels
    if abstract:
        elems.append(Elem(kind="para", runs=[Inline(t="Abstract ")] + _inline(abstract[0].strip(), labels_inv)))
    if kw:
        k = re.sub(r"\\sep|\\and", ",", kw[0])
        elems.append(Elem(kind="para", runs=[Inline(t="Keywords: " + re.sub(r"\s+", " ", _l2t(k)).strip())]))
    # ---- body
    body = doc
    for marker in ("\\maketitle", "\\end{abstract}", "\\end{keyword}", "\\end{IEEEkeywords}"):
        if marker in body:
            body = body.split(marker, 1)[1] if marker == "\\maketitle" else body
    if "\\maketitle" not in doc:
        body = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", "", doc, flags=re.S)
    body = re.sub(r"\\begin\{(abstract|keyword|IEEEkeywords)\}.*?\\end\{\1\}", "", body, flags=re.S)
    bibitems = _env(body, "thebibliography")
    body = re.split(r"\\bibliography\{|\\printbibliography|\\begin\{thebibliography\}|\\bibliographystyle\{", body)[0]
    pos = 0
    pattern = re.compile(r"\\(section|subsection|subsubsection|paragraph)\*?\{|\\begin\{(figure\*?|table\*?|equation\*?|align\*?|gather\*?|multline\*?|itemize|enumerate|verbatim|lstlisting|quote)\}|\\\[|\$\$|\\appendix")
    nfig = ntab = neq = 0
    while True:
        m = pattern.search(body, pos)
        chunk = body[pos:m.start() if m else len(body)]
        for para in re.split(r"\n\s*\n", chunk):
            runs = _inline(para.strip(), labels_inv)
            text = "".join(r.t for r in runs).strip()
            if runs and (text or any(r.math or r.cite for r in runs)) and not re.fullmatch(r"[\W\d]*", text or "x"):
                elems.append(Elem(kind="para", runs=runs))
        if not m:
            break
        if m.group(1):
            arg, end = _arg(body, m.end() - 1)
            level = {"section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 3}[m.group(1)]
            elems.append(Elem(kind="heading", runs=[Inline(t=re.sub(r"\s+", " ", _l2t(arg)).strip())], level=level))
            pos = end
            continue
        if m.group(0) == "\\appendix":
            elems.append(Elem(kind="heading", runs=[Inline(t="Appendix")], level=1))
            pos = m.end()
            continue
        if m.group(0) in ("\\[", "$$"):
            close = "\\]" if m.group(0) == "\\[" else "$$"
            end = body.find(close, m.end())
            end = len(body) if end < 0 else end
            neq += 1
            elems.append(Elem(kind="equation", block=Block(kind="equation", latex=body[m.end():end].strip(), label=f"eq{neq}")))
            pos = end + len(close)
            continue
        env = m.group(2)
        end_tag = "\\end{" + env + "}"
        end = body.find(end_tag, m.end())
        end = len(body) if end < 0 else end
        inner = body[m.end():end]
        base = env.rstrip("*")
        if base == "figure":
            nfig += 1
            elems.append(Elem(kind="figure", block=_figure(inner, files, work_dir, nfig, labels_inv)))
        elif base == "table":
            ntab += 1
            elems.append(Elem(kind="table", block=_table(inner, ntab, labels_inv)))
        elif base in ("equation", "align", "gather", "multline"):
            neq += 1
            lab = re.search(r"\\label\{([^}]*)\}", inner)
            latex = re.sub(r"\\label\{[^}]*\}", "", inner).strip()
            if base != "equation":
                latex = r"\begin{aligned}" + latex.replace("\\nonumber", "") + r"\end{aligned}"
            elems.append(Elem(kind="equation", block=Block(kind="equation", latex=latex, label=lab.group(1) if lab else f"eq{neq}")))
        elif base in ("itemize", "enumerate"):
            items = [it.strip() for it in re.split(r"\\item\b(?:\[[^\]]*\])?", inner)[1:]]
            elems.append(Elem(kind="list", items=[_inline(it, labels_inv) for it in items if it], ordered=base == "enumerate"))
        elif base in ("verbatim", "lstlisting"):
            elems.append(Elem(kind="code", block=Block(kind="code", runs=[Inline(t=inner.strip("\n"))])))
        elif base == "quote":
            elems.append(Elem(kind="quote", runs=_inline(inner.strip(), labels_inv)))
        pos = end + len(end_tag)
    refs_lines: list[tuple[str, float]] = []
    bibitem_refs = []
    if bibitems:
        for k, item in re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]*)\}(.*?)(?=\\bibitem|$)", bibitems[0], re.S):
            bibitem_refs.append((k.strip(), re.sub(r"\s+", " ", _l2t(item)).strip()))
    content = re.sub(r"\\(?:cite\w*|ref|eqref|autoref|label|bibliography|bibliographystyle|includegraphics|input|include)\*?(?:\[[^\]]*\])?\{[^}]*\}|\\maketitle|\\begin\{thebibliography\}.*?\\end\{thebibliography\}", " ", doc, flags=re.S)
    content = re.sub(r"\\(?:begin|end)\{[^}]*\}(\{[^}]*\})*", " ", content)
    return {"elems": elems, "title": title, "front": front, "refs": refs_lines, "raw_text": _l2t(content), "bib": bib,
            "bibitems": bibitem_refs, "footnotes": [], "notes": [], "pages": 0}
