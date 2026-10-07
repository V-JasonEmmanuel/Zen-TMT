"""LaTeX math -> PNG with matplotlib's mathtext (offline, no TeX installation needed).

Used for Word and PDF output where the source equation is LaTeX (LaTeX / Markdown sources).
Multi-line environments (aligned, gathered, cases-free arrays) are split into rows and stacked.
Unsupported commands fall back to a readable text form and are reported.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from PIL import Image

SIMPLIFY = [
    (r"\\(?:left|right|big|Big|bigg|Bigg)(?=[\\()\[\]|.{}])", ""),
    (r"\\(?:displaystyle|textstyle|limits|nolimits|nonumber|notag)\b", ""),
    (r"\\(?:mathbf|boldsymbol|bm)\{", r"\\mathbf{"),
    (r"\\operatorname\{([^}]*)\}", r"\\mathrm{\1}"),
    (r"\\text(?:rm|normal)?\{([^}]*)\}", r"\\mathrm{\1}"),
    (r"\\mathbb\{([A-Z])\}", r"\\mathbb{\1}"),
    (r"\\(?:quad|qquad)", r"\\ \\ "),
    (r"\\dfrac", r"\\frac"), (r"\\tfrac", r"\\frac"),
    (r"\\coloneqq", ":="), (r"\\le\b", r"\\leq"), (r"\\ge\b", r"\\geq"),
    (r"\\lVert|\\rVert", r"\\|"), (r"\\lvert|\\rvert", "|"),
]


def _rows(latex: str) -> list[str]:
    s = latex.strip()
    s = re.sub(r"\\begin\{(aligned|align\*?|gathered|split|eqnarray\*?)\}", "", s)
    s = re.sub(r"\\end\{(aligned|align\*?|gathered|split|eqnarray\*?)\}", "", s)
    rows = [r.replace("&", "").strip() for r in re.split(r"\\\\(?:\[[^\]]*\])?", s)]
    return [r for r in rows if r]


def _simplify(s: str) -> str:
    for pat, rep in SIMPLIFY:
        s = re.sub(pat, rep, s)
    return s


def render(latex: str, out_dir: Path, size_pt: float = 11.0, dpi: int = 300, inline: bool = False) -> Optional[tuple[Path, float, float]]:
    """-> (png path, width_pt, height_pt) or None if mathtext cannot typeset it."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import mathtext
    from matplotlib.font_manager import FontProperties

    key = hashlib.sha1(f"{latex}|{size_pt}|{dpi}|{inline}".encode()).hexdigest()[:16]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"math_{key}.png"
    if path.exists():
        with Image.open(path) as im:
            return path, im.width * 72 / dpi, im.height * 72 / dpi
    rows = _rows(latex) if not inline else [latex.strip()]
    images = []
    try:
        for r in rows:
            tmp = out_dir / f"_row_{key}_{len(images)}.png"
            mathtext.math_to_image(f"${_simplify(r)}$", str(tmp), prop=FontProperties(family="serif", size=size_pt), dpi=dpi, format="png")
            images.append(Image.open(tmp).convert("RGBA"))
            images[-1].load()
            tmp.unlink(missing_ok=True)
    except Exception:
        for im in images:
            im.close()
        return None
    w = max(im.width for im in images)
    gap = int(dpi * size_pt / 72 * 0.35)
    h = sum(im.height for im in images) + gap * (len(images) - 1)
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    y = 0
    for im in images:
        canvas.paste(im, ((w - im.width) // 2 if not inline else 0, y), im)
        y += im.height + gap
    bg = Image.new("RGB", canvas.size, "white")
    bg.paste(canvas, mask=canvas.getchannel("A"))
    bg.save(path, dpi=(dpi, dpi))
    return path, w * 72 / dpi, h * 72 / dpi


def as_text(latex: str) -> str:
    from pylatexenc.latex2text import LatexNodes2Text

    try:
        return LatexNodes2Text().latex_to_text(latex)
    except Exception:
        return latex
