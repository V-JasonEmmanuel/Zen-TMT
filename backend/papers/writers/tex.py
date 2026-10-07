"""LaTeX project in the publisher's official class (sn-jnl, llncs, elsarticle, IEEEtran, acmart, apa7).

The project compiles as is in Overleaf or any TeX distribution (pdflatex + bibtex/biber). The
publisher's class files are not redistributed here; they ship with TeX Live / MiKTeX / Overleaf
(sn-jnl comes with Springer Nature's template), as noted in the generated README.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from backend.papers.formats import Format, author_year
from backend.papers.model import Block, Inline, Paper
from backend.papers.writers.common import PLACEHOLDER, Layout, ack_title, arrange, statement_title

SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
UNICODE = {"–": "--", "—": "---", "“": "``", "”": "''", "‘": "`", "’": "'", "…": r"\ldots{}", "\u00a0": "~", "•": r"\textbullet{}",
           "×": r"$\times$", "±": r"$\pm$", "≤": r"$\leq$", "≥": r"$\geq$", "≈": r"$\approx$", "→": r"$\rightarrow$",
           "°": r"\textdegree{}", "µ": r"$\mu$", "∼": r"$\sim$", "≠": r"$\neq$", "·": r"$\cdot$"}


def escape(s: str) -> str:
    out = []
    for ch in s:
        if ch in SPECIAL:
            out.append(SPECIAL[ch])
        elif ch in UNICODE:
            out.append(UNICODE[ch])
        elif ord(ch) > 0x24F:  # Greek and other symbols -> LaTeX commands
            try:
                from pylatexenc.latexencode import unicode_to_latex

                out.append(unicode_to_latex(ch))
            except Exception:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def _cite(fmt: Format, style: str, keys: list[str], narrative: bool) -> str:
    k = ",".join(keys)
    if fmt.id == "apa7":
        return (r"\textcite{" if narrative else r"\parencite{") + k + "}"
    if author_year(fmt, style) and fmt.natbib:
        return (r"\citet{" if narrative else r"\citep{") + k + "}"
    return r"\cite{" + k + "}"


def runs(rs: list[Inline], fmt: Format, style: str) -> str:
    out = []
    for r in rs:
        if r.cite:
            narrative = r.t == "narrative"
            pre = "~" if not narrative and out and out[-1].endswith(" ") else ""
            if pre:
                out[-1] = out[-1].rstrip()
            out.append(pre + _cite(fmt, style, r.cite, narrative))
        elif r.math:
            out.append(f"${r.math}$")
        elif r.img:  # inline math cropped from a PDF (no usable text in its fonts)
            out.append(f"\\raisebox{{-0.3\\height}}{{\\includegraphics[height={min(r.img_h, 19):.1f}pt]{{{r.img}}}}}")
        elif r.xref:
            plural = bool(re.match(r"\w+s\b", r.t.split()[0])) if r.t.split() else False
            kind = r.xref[:3]
            if kind == "fig":
                word = fmt.fig_label[:-1] + "s." if plural and fmt.fig_label.endswith(".") else fmt.fig_label + ("s" if plural else "")
                out.append(f"{word}~\\ref{{{_lab(r.xref)}}}")
            elif kind == "tab":
                out.append(f"Table{'s' if plural else ''}~\\ref{{{_lab(r.xref)}}}")
            elif kind == "sec":
                lab = _lab(r.xref)
                if fmt.numbering == "none":  # unnumbered headings (APA): refer to the section by its title
                    out.append(f"the ``\\nameref{{{lab}}}'' section")
                else:
                    out.append(f"{r.t.split()[0] if r.t.split() else 'Section'}~\\ref{{{lab}}}")
            else:
                out.append(f"{'Eqs.' if plural else 'Eq.'}~(\\ref{{{_lab(r.xref)}}})" if fmt.id != "apa7" else f"Equation~\\ref{{{_lab(r.xref)}}}")
        else:
            t = escape(r.t)
            if r.sup:
                t = r"\textsuperscript{" + t + "}"
            if r.sub:
                t = r"\textsubscript{" + t + "}"
            if r.b:
                t = r"\textbf{" + t + "}"
            if r.i:
                t = r"\emph{" + t + "}"
            out.append(t)
    return "".join(out)


def _block(b: Block, fmt: Format, style: str, lay: Layout, wide: bool) -> str:
    if b.kind == "para":
        return runs(b.runs, fmt, style)
    if b.kind == "quote":
        return "\\begin{quote}\n" + runs(b.runs, fmt, style) + "\n\\end{quote}"
    if b.kind == "code":
        return "\\begin{verbatim}\n" + "".join(r.t for r in b.runs) + "\n\\end{verbatim}"
    if b.kind == "list":
        env = "enumerate" if b.ordered else "itemize"
        return f"\\begin{{{env}}}\n" + "\n".join("\\item " + runs(it, fmt, style) for it in b.items) + f"\n\\end{{{env}}}"
    if b.kind == "equation":
        lab = f"\\label{{{_lab(b.label)}}}"
        if b.latex:
            return "\\begin{equation}\n" + b.latex + "\n" + lab + "\n\\end{equation}"
        if b.image:
            env = "equation" if id(b) in lay.eq_no else "equation*"  # unnumbered in the source -> unnumbered here
            return ("% TODO: equation recovered from the PDF as an image - retype it in LaTeX for the final version\n"
                    f"\\begin{{{env}}}\n\\vcenter{{\\hbox{{\\includegraphics[height=1.4\\baselineskip]{{{b.image}}}}}}}\n"
                    + (lab + "\n" if env == "equation" else "") + f"\\end{{{env}}}")
        return "\\begin{equation}\n\\text{" + escape("".join(r.t for r in b.runs)) + "}\n" + lab + "\n\\end{equation}"
    if b.kind == "figure":
        env = "figure*" if wide else "figure"
        body = f"\\includegraphics[width=\\linewidth]{{{b.image}}}" if b.image else "% TODO: figure file missing in the source"
        cap = runs(b.caption, fmt, style)
        return f"\\begin{{{env}}}[!t]\n\\centering\n{body}\n\\caption{{{cap}}}\\label{{{_lab(b.label)}}}\n\\end{{{env}}}"
    if b.kind == "table":
        env = "table*" if wide else "table"
        cap = runs(b.caption, fmt, style)
        if b.rows:
            ncol = max(len(r) for r in b.rows)
            spec = "@{}" + "l" * ncol + "@{}"
            rows = [r + [""] * (ncol - len(r)) for r in b.rows]
            lines = [" & ".join(escape(c) for c in rows[0]) + r" \\", r"\midrule"] + [" & ".join(escape(c) for c in r) + r" \\" for r in rows[1:]]
            size = "\\footnotesize\n" if fmt.columns == 2 else "\\small\n"
            tab = f"{size}\\begin{{tabular}}{{{spec}}}\n\\toprule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}"
            if ncol > 4 and fmt.columns == 2:
                tab = "\\resizebox{\\linewidth}{!}{%\n" + tab + "}"
        else:
            tab = f"\\includegraphics[width=\\linewidth]{{{b.image}}}" if b.image else ""
        return f"\\begin{{{env}}}[!t]\n\\centering\n\\caption{{{cap}}}\\label{{{_lab(b.label)}}}\n{tab}\n\\end{{{env}}}"
    return runs(b.runs, fmt, style)


def _lab(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9:._-]", "", s) or "x"


def _section_cmd(level: int, starred: bool = False) -> str:
    return ["section", "subsection", "subsubsection"][min(3, max(1, level)) - 1] + ("*" if starred else "")


# ------------------------------------------------------------------ front matter per class
def _front(p: Paper, fmt: Format, style: str) -> tuple[str, str]:
    """-> (preamble additions + document front, keywords/abstract placement handled per class)."""
    T = escape(p.title)
    abstract = runs(p.abstract, fmt, style)
    kws = [escape(k) for k in p.keywords]
    affs = [escape(a) for a in p.affiliations]
    authors = p.authors
    c = fmt.latex_class
    if c == "sn-jnl":
        lines = [f"\\title[Article Title]{{{T}}}"]
        for a in authors:
            nm = a.name.split()
            fnm, sur = (" ".join(nm[:-1]), nm[-1]) if len(nm) > 1 else ("", a.name)
            idx = ",".join(str(i + 1) for i in a.affiliations) or "1"
            lines.append(f"\\author{'*' if a.corresponding else ''}[{idx}]{{\\fnm{{{escape(fnm)}}} \\sur{{{escape(sur)}}}}}" +
                         (f"\\email{{{a.email}}}" if a.email else ""))
        for i, a in enumerate(affs, start=1):
            lines.append(f"\\affil[{i}]{{\\orgname{{{a}}}}}")
        lines.append(f"\\abstract{{{abstract}}}")
        if kws:
            lines.append("\\keywords{" + ", ".join(kws) + "}")
        lines.append("\\maketitle")
        return "", "\n".join(lines)
    if c == "llncs":
        auth = " \\and ".join(escape(a.name) + (f"\\inst{{{','.join(str(i + 1) for i in a.affiliations)}}}" if a.affiliations and len(affs) > 1 else "")
                              for a in authors)
        emails = [a.email for a in authors if a.email]
        inst = " \\and\n".join(affs) or "Institution"
        if emails:
            inst += "\\\\\n\\email{" + ", ".join(emails) + "}"
        run = ", ".join(a.name.split()[-1] for a in authors[:3]) + (" et al." if len(authors) > 3 else "")
        kw = "\n\\keywords{" + " \\and ".join(kws) + "}" if kws else ""
        return "", (f"\\title{{{T}}}\n\\author{{{auth}}}\n\\authorrunning{{{escape(run)}}}\n\\institute{{{inst}}}\n\\maketitle\n"
                    f"\\begin{{abstract}}\n{abstract}{kw}\n\\end{{abstract}}")
    if c == "elsarticle":
        lines = ["\\begin{frontmatter}", f"\\title{{{T}}}"]
        for a in authors:
            idx = ",".join(str(i + 1) for i in a.affiliations)
            lines.append(f"\\author[{idx}]{{{escape(a.name)}}}" if idx else f"\\author{{{escape(a.name)}}}")
            if a.corresponding:
                lines.append("\\cortext[cor1]{Corresponding author}")
            if a.email:
                lines.append(f"\\ead{{{a.email}}}")
        for i, a in enumerate(affs, start=1):
            lines.append(f"\\affiliation[{i}]{{organization={{{a}}}}}")
        lines.append(f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}")
        if p.highlights:
            lines.append("\\begin{highlights}\n" + "\n".join("\\item " + escape(h) for h in p.highlights) + "\n\\end{highlights}")
        else:
            lines.append("% TODO: Elsevier asks for 3-5 highlights (max. 85 characters each)\n%\\begin{highlights}\n%\\item ...\n%\\end{highlights}")
        if kws:
            lines.append("\\begin{keyword}\n" + " \\sep ".join(kws) + "\n\\end{keyword}")
        lines.append("\\end{frontmatter}")
        return "", "\n".join(lines)
    if c == "IEEEtran":
        blocks = []
        for a in authors:
            aff = " \\\\ ".join(affs[i] for i in a.affiliations if i < len(affs))
            mail = f" \\\\ {a.email}" if a.email else ""
            blocks.append(f"\\IEEEauthorblockN{{{escape(a.name)}}}\n\\IEEEauthorblockA{{\\textit{{{aff}}}{mail}}}")
        kw = "\\begin{IEEEkeywords}\n" + ", ".join(kws) + "\n\\end{IEEEkeywords}" if kws else ""
        return "", (f"\\title{{{T}}}\n\\author{{" + "\n\\and\n".join(blocks) + "}\n\\maketitle\n"
                    f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}\n{kw}")
    if c == "acmart":
        lines = [f"\\title{{{T}}}"]
        for a in authors:
            lines.append(f"\\author{{{escape(a.name)}}}")
            for i in a.affiliations or [0]:
                if i < len(affs):
                    lines.append(f"\\affiliation{{\\institution{{{affs[i]}}}\\country{{}}}}")
            if a.email:
                lines.append(f"\\email{{{a.email}}}")
        lines.append(f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}")
        lines.append("% TODO: add CCS concepts generated at https://dl.acm.org/ccs")
        if kws:
            lines.append("\\keywords{" + ", ".join(kws) + "}")
        lines.append("\\maketitle")
        return "", "\n".join(lines)
    if c == "apa7":
        names = ", ".join(escape(a.name) for a in authors)
        aff = "\\\\".join(affs)
        short = escape(p.title[:50].upper())
        kw = f"\\keywords{{{', '.join(kws)}}}" if kws else ""
        pre = ("\\usepackage[american]{babel}\n\\usepackage{csquotes}\n"
               "\\usepackage[style=apa,sortcites=true,sorting=nyt,backend=biber]{biblatex}\n"
               "\\DeclareLanguageMapping{american}{american-apa}\n\\addbibresource{references.bib}\n"
               f"\\title{{{T}}}\n\\shorttitle{{{short}}}\n\\authorsnames{{{names}}}\n\\authorsaffiliations{{{{{aff}}}}}\n"
               f"\\abstract{{{abstract}}}\n{kw}\n")
        return pre, "\\maketitle"
    return "", f"\\title{{{T}}}\n\\author{{{', '.join(escape(a.name) for a in authors)}}}\n\\maketitle\n\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}"


def _class_line(fmt: Format, style: str) -> str:
    if fmt.latex_class == "sn-jnl":
        return "\\documentclass[pdflatex," + ("sn-mathphys-ay" if author_year(fmt, style) else "sn-mathphys-num") + "]{sn-jnl}"
    if fmt.latex_class == "elsarticle":
        return "\\documentclass[" + fmt.latex_options + ("" if not author_year(fmt, style) else ",authoryear") + "]{elsarticle}"
    return f"\\documentclass[{fmt.latex_options}]{{{fmt.latex_class}}}" if fmt.latex_options else f"\\documentclass{{{fmt.latex_class}}}"


def write_tex(p: Paper, fmt: Format, style: str) -> str:
    lay = arrange(p, fmt)
    pre, front = _front(p, fmt, style)
    pkgs = ["graphicx", "amsmath", "amssymb", "booktabs"]
    if fmt.latex_class in ("article", "llncs", "IEEEtran"):
        pkgs.append("url")
    if fmt.latex_class == "IEEEtran":
        pkgs.append("cite")
    if fmt.numbering == "none":
        pkgs.append("nameref")  # section cross references by title
    head = [_class_line(fmt, style)]
    if fmt.latex_class not in ("sn-jnl", "acmart"):
        head.append("\\usepackage[T1]{fontenc}")
    head += [f"\\usepackage{{{x}}}" for x in pkgs]
    if fmt.latex_class == "elsarticle":
        head.append("\\journal{Journal Name}  % TODO: the target journal")
    if pre:
        head.append(pre)
    doc = ["\\begin{document}", front, ""]
    wide = lambda b: fmt.columns == 2 and (b.width_frac == 0 or b.width_frac > 0.6) and b.kind in ("figure", "table") and \
        (b.kind == "figure" or (b.rows and max(len(r) for r in b.rows) > 4))  # noqa: E731

    def emit(n, appendix=False):
        s = n.section
        if s.title:
            cmd = _section_cmd(s.level, starred=fmt.numbering == "none" and False)
            doc.append(f"\\{cmd}{{{escape(s.title)}}}" + (f"\\label{{{_lab('sec' + s.source_number.rstrip('.'))}}}" if s.source_number else ""))
        for b in s.blocks:
            doc.append(_block(b, fmt, style, lay, wide(b)))
            doc.append("")

    for n in lay.body:
        emit(n)
    # acknowledgements + statements (class conventions)
    ack = "\n\n".join(_block(b, fmt, style, lay, False) for s in lay.acknowledgements for b in s.blocks)
    if ack:
        if fmt.latex_class == "sn-jnl":
            doc.append("\\bmhead{Acknowledgements}\n" + ack)
        elif fmt.latex_class == "acmart":
            doc.append("\\begin{acks}\n" + ack + "\n\\end{acks}")
        elif fmt.latex_class == "llncs":
            doc.append("\\begin{credits}\n\\subsubsection{\\ackname} " + ack + "\n\\end{credits}")
        else:
            doc.append(f"\\section*{{{ack_title(fmt)}}}\n" + ack)
    stmts = {k: s for k, s in lay.statements.items() if k != "declarations"}
    if stmts or lay.missing or "declarations" in lay.statements:
        if fmt.latex_class == "sn-jnl":
            items = []
            for k in ("funding", "competing", "ethics", "data", "contributions"):
                if k in stmts:
                    items.append(f"\\item {statement_title(fmt, k)}: " + " ".join(_block(b, fmt, style, lay, False) for b in stmts[k].blocks))
                elif k in lay.missing:
                    items.append(f"\\item {statement_title(fmt, k)}: {PLACEHOLDER}  % TODO")
            if "declarations" in lay.statements:
                items.append("\\item " + " ".join(_block(b, fmt, style, lay, False) for b in lay.statements["declarations"].blocks))
            doc.append("\\section*{Declarations}\n\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}")
        else:
            for k, s in stmts.items():
                doc.append(f"\\section*{{{statement_title(fmt, k)}}}\n" + "\n\n".join(_block(b, fmt, style, lay, False) for b in s.blocks))
            if "declarations" in lay.statements:
                doc.append("\\section*{Declarations}\n" + "\n\n".join(_block(b, fmt, style, lay, False) for b in lay.statements["declarations"].blocks))
            for k in lay.missing:
                doc.append(f"\\section*{{{statement_title(fmt, k)}}}\n{PLACEHOLDER} % TODO")
    if lay.appendix:
        if fmt.latex_class == "sn-jnl":
            doc.append("\\begin{appendices}")
        else:
            doc.append("\\appendix")
        for n in lay.appendix:
            s = n.section
            title = re.sub(r"^appendix\s*[A-Z0-9]?\s*[:.—–-]?\s*", "", s.title, flags=re.I) or s.title
            doc.append(f"\\{_section_cmd(s.level)}{{{escape(title)}}}")
            for b in s.blocks:
                doc.append(_block(b, fmt, style, lay, False))
                doc.append("")
        if fmt.latex_class == "sn-jnl":
            doc.append("\\end{appendices}")
    # bibliography
    if fmt.latex_class == "apa7":
        doc.append("\\printbibliography")
    elif fmt.latex_class == "sn-jnl":
        doc.append("\\bibliography{references}")
    else:
        bst = fmt.bst_author_year if author_year(fmt, style) and fmt.bst_author_year else fmt.bst
        doc.append(f"\\bibliographystyle{{{bst}}}\n\\bibliography{{references}}")
    if any(not r.cited for r in p.references):
        doc.insert(-1, "\\nocite{" + ",".join(r.key for r in p.references if not r.cited) + "}  % references not cited in the text")
    doc.append("\\end{document}")
    return "\n".join(head) + "\n\n" + "\n".join(doc) + "\n"


README = """LaTeX project generated by Zensar Content Studio - {name}

Compile:  pdflatex main  ->  {bib} main  ->  pdflatex main  ->  pdflatex main
(or upload this folder to Overleaf and press Recompile)

Document class: {cls}
  {cls_note}
Bibliography:   references.bib ({style_note})

Lines marked "% TODO" need the authors' attention (missing statements, retyped equations,
target journal name, ACM CCS concepts). See conversion_report.md for the full list of checks.
"""
CLASS_NOTES = {
    "sn-jnl": "Springer Nature LaTeX template: download sn-jnl.cls and the sn-*.bst files from the Springer Nature "
              "author guidelines (also on Overleaf as 'Springer Nature LaTeX Template') and place them in this folder.",
    "llncs": "Springer LNCS class: included in TeX Live/MiKTeX (llncs.cls, splncs04.bst) and on Overleaf.",
    "elsarticle": "Elsevier elsarticle class: included in TeX Live/MiKTeX (elsarticle.cls, elsarticle-num/-harv.bst) and on Overleaf.",
    "IEEEtran": "IEEEtran class: included in TeX Live/MiKTeX (IEEEtran.cls, IEEEtran.bst) and on Overleaf.",
    "acmart": "ACM acmart class: included in TeX Live/MiKTeX (acmart.cls, ACM-Reference-Format.bst) and on Overleaf.",
    "apa7": "apa7 class with biblatex-apa: included in TeX Live/MiKTeX and on Overleaf (compile with biber).",
}


def write_project(p: Paper, fmt: Format, style: str, paper_dir: Path, out_zip: Path) -> Path:
    from backend.papers.writers import bibtex

    tex = write_tex(p, fmt, style)
    bib = bibtex.write(p.references)
    readme = README.format(name=fmt.name, cls=fmt.latex_class, cls_note=CLASS_NOTES.get(fmt.latex_class, ""),
                           bib="biber" if fmt.latex_class == "apa7" else "bibtex",
                           style_note="biblatex-apa" if fmt.latex_class == "apa7" else "BibTeX style " +
                           (fmt.bst_author_year if author_year(fmt, style) and fmt.bst_author_year else fmt.bst))
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("main.tex", tex)
        z.writestr("references.bib", bib)
        z.writestr("README.txt", readme)
        used = set(re.findall(r"\{(figures/[^}]+)\}", tex))
        for rel in used:
            f = paper_dir / rel
            if f.exists():
                z.write(f, rel)
    (out_zip.parent / "main.tex").write_text(tex, encoding="utf-8")
    (out_zip.parent / "references.bib").write_text(bib, encoding="utf-8")
    return out_zip
