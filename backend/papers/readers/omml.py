"""Office Math (OMML, Word equations) -> LaTeX.

Covers the constructs papers use: fractions, sub/superscripts, radicals, n-ary operators (sums,
integrals, products), delimiters, accents, bars, functions, limits, matrices/arrays, equation
arrays and plain runs (with Unicode math symbols mapped to LaTeX commands).
"""
from __future__ import annotations

from lxml import etree

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"m": M}

SYMBOLS = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon", "ϵ": r"\epsilon", "ζ": r"\zeta",
    "η": r"\eta", "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi",
    "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\phi", "ϕ": r"\phi", "χ": r"\chi",
    "ψ": r"\psi", "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi",
    "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega", "∞": r"\infty", "≤": r"\leq",
    "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "±": r"\pm", "∓": r"\mp", "×": r"\times", "÷": r"\div", "·": r"\cdot",
    "⋅": r"\cdot", "∂": r"\partial", "∇": r"\nabla", "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊆": r"\subseteq",
    "∪": r"\cup", "∩": r"\cap", "∀": r"\forall", "∃": r"\exists", "→": r"\rightarrow", "←": r"\leftarrow",
    "↔": r"\leftrightarrow", "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow", "∑": r"\sum", "∏": r"\prod", "∫": r"\int",
    "∮": r"\oint", "√": r"\sqrt", "…": r"\ldots", "⋯": r"\cdots", "∝": r"\propto", "∼": r"\sim", "≡": r"\equiv",
    "‖": r"\|", "∘": r"\circ", "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}", "ℂ": r"\mathbb{C}",
    "′": "'", "−": "-", "∗": "*", "〈": r"\langle", "〉": r"\rangle", "⟨": r"\langle", "⟩": r"\rangle", "∅": r"\emptyset",
}
NARY = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∬": r"\iint", "∭": r"\iiint", "∮": r"\oint", "⋃": r"\bigcup", "⋂": r"\bigcap"}
ACCENTS = {"̂": r"\hat", "̃": r"\tilde", "̄": r"\bar", "⃗": r"\vec", "̇": r"\dot", "̈": r"\ddot", "ˆ": r"\hat", "~": r"\tilde"}
FUNCS = {"sin", "cos", "tan", "log", "ln", "exp", "max", "min", "lim", "sup", "inf", "det", "arg", "sinh", "cosh", "tanh"}


def _q(tag: str) -> str:
    return f"{{{M}}}{tag}"


def _val(el, path: str, default: str = "") -> str:
    found = el.find(path, NS)
    if found is None:
        return default
    return found.get(_q("val"), default)


def _sym(text: str) -> str:
    out = []
    for ch in text:
        s = SYMBOLS.get(ch)
        if s:
            out.append(s + (" " if s[-1].isalpha() else ""))
        elif ch in "{}":
            out.append("\\" + ch)
        elif ch in "%#&$":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def convert(el) -> str:
    """LaTeX for an OMML element (m:oMath, m:oMathPara or any child)."""
    tag = etree.QName(el).localname
    kids = lambda: "".join(convert(c) for c in el)  # noqa: E731
    sub = lambda name: "".join(convert(c) for c in (el.find(f"m:{name}", NS) if el.find(f"m:{name}", NS) is not None else []))  # noqa: E731
    if tag in ("oMathPara",):
        parts = [convert(c) for c in el if etree.QName(c).localname == "oMath"]
        return r" \\ ".join(parts)
    if tag in ("oMath", "e", "num", "den", "sub", "sup", "deg", "lim", "fName"):
        return kids()
    if tag == "r":
        t = "".join(x.text or "" for x in el.iter(_q("t")))
        normal = el.find("m:rPr/m:nor", NS) is not None or (el.find("m:rPr/m:sty", NS) is not None and _val(el, "m:rPr/m:sty") == "p")
        if t.strip() in FUNCS:
            return "\\" + t.strip() + " "
        if normal and t.strip() and t.strip().isalpha() and len(t.strip()) > 1:
            return r"\mathrm{" + t + "}"
        return _sym(t)
    if tag == "f":
        kind = _val(el, "m:fPr/m:type", "bar")
        if kind == "lin":
            return f"{sub('num')}/{sub('den')}"
        if kind == "noBar":
            return r"\genfrac{}{}{0pt}{}{" + sub("num") + "}{" + sub("den") + "}"
        return r"\frac{" + sub("num") + "}{" + sub("den") + "}"
    if tag == "sSup":
        return "{" + sub("e") + "}^{" + sub("sup") + "}"
    if tag == "sSub":
        return "{" + sub("e") + "}_{" + sub("sub") + "}"
    if tag == "sSubSup":
        return "{" + sub("e") + "}_{" + sub("sub") + "}^{" + sub("sup") + "}"
    if tag == "sPre":
        return "{}_{" + sub("sub") + "}^{" + sub("sup") + "}" + sub("e")
    if tag == "rad":
        deg = sub("deg")
        hide = _val(el, "m:radPr/m:degHide") in ("1", "on", "true")
        return (r"\sqrt{" if hide or not deg.strip() else r"\sqrt[" + deg + "]{") + sub("e") + "}"
    if tag == "nary":
        ch = _val(el, "m:naryPr/m:chr", "∫")
        op = NARY.get(ch, _sym(ch))
        lo, hi = sub("sub"), sub("sup")
        s = op + (("_{" + lo + "}") if lo.strip() else "") + (("^{" + hi + "}") if hi.strip() else "")
        return s + " " + sub("e")
    if tag == "d":
        beg = _val(el, "m:dPr/m:begChr", "(")
        end = _val(el, "m:dPr/m:endChr", ")")
        sep = _val(el, "m:dPr/m:sepChr", ",")
        inner = sep.join(convert(e) for e in el.findall("m:e", NS))
        conv = {"{": r"\{", "}": r"\}", "⟨": r"\langle", "⟩": r"\rangle", "〈": r"\langle", "〉": r"\rangle", "|": "|", "‖": r"\|", "": "."}
        return r"\left" + conv.get(beg, beg) + " " + inner + r" \right" + conv.get(end, end)
    if tag == "acc":
        ch = _val(el, "m:accPr/m:chr", "̂")
        return ACCENTS.get(ch, r"\hat") + "{" + sub("e") + "}"
    if tag == "bar":
        pos = _val(el, "m:barPr/m:pos", "top")
        return (r"\overline{" if pos == "top" else r"\underline{") + sub("e") + "}"
    if tag == "func":
        name = sub("fName").strip()
        return (name if name.startswith("\\") else r"\operatorname{" + name + "}") + " " + sub("e")
    if tag in ("limLow", "limUpp"):
        base = sub("e").strip()
        return base + ("_{" if tag == "limLow" else "^{") + sub("lim") + "}"
    if tag == "groupChr":
        ch = _val(el, "m:groupChrPr/m:chr", "⏟")
        return (r"\underbrace{" if ch in ("⏟", "︸") else r"\overbrace{") + sub("e") + "}"
    if tag == "box" or tag == "borderBox":
        return sub("e")
    if tag == "m":
        rows = []
        for mr in el.findall("m:mr", NS):
            rows.append(" & ".join(convert(e) for e in mr.findall("m:e", NS)))
        return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"
    if tag == "eqArr":
        return r"\begin{aligned}" + r" \\ ".join(convert(e) for e in el.findall("m:e", NS)) + r"\end{aligned}"
    if tag.endswith("Pr") or tag in ("ctrlPr",):
        return ""
    return kids()


def to_latex(xml_el) -> str:
    import re

    s = convert(xml_el)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    s = s.replace("{}^", "^").replace("{}_", "_") if s.startswith("{}") else s
    return s


def to_text(xml_el) -> str:
    return "".join(x.text or "" for x in xml_el.iter(_q("t")))
