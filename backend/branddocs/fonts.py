"""Fonts for brand documents.

The reference's own family (e.g. Graphik) is used when its files are installed in the brand's fonts folder
(brands/<brand>/assets/fonts - licensed fonts are never committed). OpenType/CFF files (.otf) are converted
once to TrueType outlines, because the PDF library embeds TrueType only. Otherwise the brand's declared
fallback family is used and the conversion report says so.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.utils.config import get_settings
from backend.utils.logging import get_logger

log = get_logger(__name__)
_lock = threading.Lock()
_registered: dict[str, str] = {}


@dataclass
class FontFile:
    path: Path
    family: str
    weight: int
    italic: bool


def _scan(dirs: list[Path]) -> list[FontFile]:
    from fontTools.ttLib import TTFont

    out = []
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                f = TTFont(str(p), lazy=True)
                name = f["name"]
                fam = (name.getDebugName(16) or name.getDebugName(1) or "").strip()
                sub = (name.getDebugName(17) or name.getDebugName(2) or "").lower()
                weight = int(f["OS/2"].usWeightClass) if "OS/2" in f else 400
                italic = "italic" in sub or "oblique" in sub or bool(f["head"].macStyle & 2)
                out.append(FontFile(p, fam, weight, italic))
                f.close()
            except Exception:
                continue
    return out


def _otf_to_ttf(src: Path) -> Path:
    """CFF outlines -> TrueType (quadratic) outlines, cached."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    cache = get_settings().data_path / "branddocs" / "fontcache"
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / (hashlib.sha1(f"{src}:{src.stat().st_mtime}".encode()).hexdigest()[:16] + ".ttf")
    if dst.exists():
        return dst
    font = TTFont(str(src))
    if "CFF " not in font:
        return src
    order = font.getGlyphOrder()
    gs = font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = {}
    for g in order:
        pen = TTGlyphPen(gs)
        try:
            gs[g].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
            glyf[g] = pen.glyph()
        except Exception:
            glyf[g] = TTGlyphPen(gs).glyph()
    font["glyf"] = glyf
    font["loca"] = newTable("loca")
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for k in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs", "maxStackElements",
              "maxSizeOfInstructions", "maxComponentElements"):
        setattr(maxp, k, 0 if k not in ("maxZones",) else 1)
    maxp.maxPoints = maxp.maxContours = maxp.maxCompositePoints = maxp.maxCompositeContours = maxp.maxComponentDepth = 0
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    font["head"].glyphDataFormat = 0
    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    font.sfntVersion = "\x00\x01\x00\x00"
    font.recalcBBoxes = True
    font.save(str(dst))
    return dst


@dataclass
class FontSet:
    """Maps (weight, italic) of the reference family to registered PDF font names."""
    family: str
    using_reference: bool
    fallback: str
    names: dict[tuple[int, bool], str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def get(self, weight: int, italic: bool = False) -> str:
        if not self.names:
            return "Helvetica"
        cands = [k for k in self.names if k[1] == italic] or list(self.names)
        best = min(cands, key=lambda k: (abs(k[0] - weight), -k[0] if weight >= 500 else k[0]))
        return self.names[best]


def _register(path: Path, tag: str) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    key = f"{path}"
    with _lock:
        if key in _registered:
            return _registered[key]
        name = f"BD{len(_registered)}-{tag}"[:60]
        pdfmetrics.registerFont(TTFont(name, str(path)))
        _registered[key] = name
        return name


def resolve(reference_family: str, brand_id: str = "", fallback: str = "") -> FontSet:
    from backend.branding.fonts import font_index

    dirs = []
    if brand_id:
        dirs.append(get_settings().brands_path / brand_id / "assets" / "fonts")
    files = [f for f in _scan(dirs) if f.family.lower().replace(" ", "") == reference_family.lower().replace(" ", "")]
    fs = FontSet(family=reference_family, using_reference=bool(files), fallback=fallback or "Arial")
    if files:
        for f in files:
            try:
                p = _otf_to_ttf(f.path) if f.path.suffix.lower() == ".otf" else f.path
                fs.names[(f.weight, f.italic)] = _register(p, f"{reference_family}-{f.weight}{'i' if f.italic else ''}")
            except Exception as exc:
                log.warning("Brand font not usable", font=f.path.name, error=str(exc)[:160])
        if fs.names:
            return fs
        fs.using_reference = False
    idx = font_index()
    fam = idx.get(fs.fallback.lower()) or idx.get("arial") or {}
    if not fam:
        fs.notes.append(f"Neither {reference_family} nor {fs.fallback} is installed; the PDF uses Helvetica.")
        return fs
    fs.fallback = fam.get("_name", fs.fallback)
    reg = fam.get("regular") or fam.get("_any")
    for key, wt, it in (("regular", 400, False), ("bold", 700, False), ("italic", 400, True), ("bolditalic", 700, True)):
        p = fam.get(key)
        if p:
            fs.names[(wt, it)] = _register(Path(p), f"{fs.fallback}-{key}")
    if (400, False) not in fs.names and reg:
        fs.names[(400, False)] = _register(Path(reg), f"{fs.fallback}-regular")
    # light/medium do not exist in most fallbacks: light -> regular, medium -> bold (closest visual weight)
    if (300, False) not in fs.names:
        fs.names[(300, False)] = fs.names[(400, False)]
    if (500, False) not in fs.names and (700, False) in fs.names:
        fs.names[(500, False)] = fs.names[(700, False)]
    fs.notes.append(f"{reference_family} is not installed, so the PDF uses {fs.fallback}. Put the licensed {reference_family} "
                    f"font files (.otf/.ttf) in brands/{brand_id or '<brand>'}/assets/fonts to use the exact typeface.")
    return fs


def installed_reference(reference_family: str, brand_id: str) -> Optional[list[str]]:
    dirs = [get_settings().brands_path / brand_id / "assets" / "fonts"] if brand_id else []
    files = [f for f in _scan(dirs) if f.family.lower().replace(" ", "") == reference_family.lower().replace(" ", "")]
    return [f"{f.path.name} ({f.weight}{' italic' if f.italic else ''})" for f in files] or None
