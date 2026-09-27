"""Reference PPTX/POTX analysis: slide size, theme colours/fonts, layouts, placeholders, logo, footer.

Output = observations + *suggested* brand values, each with a confidence score. Nothing is
applied automatically; the Brand Manager lets the user accept or correct each suggestion.
"""
from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
EMU_PER_IN = 914400


def _in(v) -> float:
    return round((v or 0) / EMU_PER_IN, 3)


def _clr(el) -> str | None:
    if el is None:
        return None
    s = el.find("a:srgbClr", NS)
    if s is not None:
        return "#" + s.get("val", "").upper()
    s = el.find("a:sysClr", NS)
    if s is not None and s.get("lastClr"):
        return "#" + s.get("lastClr").upper()
    return None


def theme_from_zip(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"colors": {}, "fonts": {}}
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.startswith("ppt/theme/theme") and n.endswith(".xml"))
        if not names:
            return out
        root = etree.fromstring(z.read(names[0]))
    scheme = root.find(".//a:clrScheme", NS)
    if scheme is not None:
        for child in scheme:
            tag = etree.QName(child).localname
            col = _clr(child)
            if col:
                out["colors"][tag] = col
    for kind in ("majorFont", "minorFont"):
        el = root.find(f".//a:fontScheme/a:{kind}/a:latin", NS)
        if el is not None and el.get("typeface"):
            out["fonts"][kind] = el.get("typeface")
    return out


def analyze_pptx(path: Path, extract_dir: Path | None = None) -> dict[str, Any]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    W, H = prs.slide_width, prs.slide_height
    theme = theme_from_zip(path)
    result: dict[str, Any] = {
        "slide_size": {"width_in": _in(W), "height_in": _in(H), "aspect": round(W / H, 3) if H else None},
        "theme_colors": theme["colors"], "theme_fonts": theme["fonts"],
        "layouts": [], "master": {}, "slides_analyzed": len(prs.slides), "observed": {}, "suggestions": [],
    }

    def ph_info(shape) -> dict[str, Any]:
        return {"name": shape.name, "type": str(shape.placeholder_format.type).split(".")[-1].split(" ")[0].lower(),
                "left": _in(shape.left), "top": _in(shape.top), "width": _in(shape.width), "height": _in(shape.height)}

    master = prs.slide_master
    logo_candidates = []
    for shape in master.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            area = (shape.width or 0) * (shape.height or 0)
            if area < W * H * 0.08:
                logo_candidates.append(shape)
    title_ph = next((s for s in master.placeholders if "TITLE" in str(s.placeholder_format.type)), None)
    result["master"] = {
        "placeholders": [ph_info(s) for s in master.placeholders],
        "picture_count": sum(1 for s in master.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE),
    }
    for layout in master.slide_layouts:
        result["layouts"].append({
            "name": layout.name,
            "placeholders": [ph_info(s) for s in layout.placeholders],
            "pictures": sum(1 for s in layout.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE),
        })
    blank = min(master.slide_layouts, key=lambda l: (len(l.placeholders), 0 if "blank" in l.name.lower() else 1))
    result["blank_layout"] = blank.name

    # master background colour
    bg = master.element.find(".//p:cSld/p:bg//a:solidFill", NS)
    bg_col = _clr(bg) if bg is not None else None

    # observations from existing slides: fonts, sizes, text colours
    fonts, sizes, colors = Counter(), Counter(), Counter()
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    n = len(run.text)
                    if run.font.name:
                        fonts[run.font.name] += n
                    if run.font.size:
                        sizes[round(run.font.size.pt)] += n
                    try:
                        if run.font.color and run.font.color.type is not None and run.font.color.rgb is not None:
                            colors["#" + str(run.font.color.rgb)] += n
                    except (AttributeError, TypeError):
                        pass
    result["observed"] = {"fonts": fonts.most_common(6), "font_sizes_pt": sizes.most_common(8), "text_colors": colors.most_common(6)}

    # extract the most likely logo image
    if logo_candidates and extract_dir is not None:
        shape = max(logo_candidates, key=lambda s: s.width or 0)
        extract_dir.mkdir(parents=True, exist_ok=True)
        fname = f"template_logo.{shape.image.ext}"
        (extract_dir / fname).write_bytes(shape.image.blob)
        cx, cy = (shape.left + shape.width / 2) / W, (shape.top + shape.height / 2) / H
        pos = ("top" if cy < 0.5 else "bottom") + "_" + ("left" if cx < 0.5 else "right")
        result["logo"] = {"file": fname, "position": pos, "width_in": _in(shape.width)}

    # ---------------- suggestions (value, confidence, reason)
    tc = theme["colors"]
    S = result["suggestions"]

    def suggest(path: str, value: Any, conf: float, reason: str):
        if value not in (None, ""):
            S.append({"path": path, "value": value, "confidence": conf, "reason": reason})

    suggest("colors.text_primary", tc.get("dk1"), 0.8, "Theme colour 'Dark 1' (default text colour)")
    suggest("colors.background", bg_col or tc.get("lt1"), 0.8 if bg_col else 0.7, "Master background" if bg_col else "Theme colour 'Light 1'")
    suggest("colors.primary", tc.get("accent1") or tc.get("dk2"), 0.6, "Theme 'Accent 1' - confirm this is the main brand colour")
    suggest("colors.secondary", tc.get("dk2") if tc.get("dk2") != tc.get("dk1") else tc.get("accent2"), 0.5, "Theme 'Dark 2'")
    suggest("colors.accent", tc.get("accent2"), 0.5, "Theme 'Accent 2'")
    suggest("colors.surface", tc.get("lt2"), 0.5, "Theme 'Light 2'")
    extra = [tc[k] for k in ("accent3", "accent4", "accent5", "accent6") if tc.get(k)]
    if extra:
        suggest("colors.palette", extra, 0.5, "Theme accents 3-6 (chart colours)")
    suggest("typography.heading.family", theme["fonts"].get("majorFont"), 0.85, "Theme heading font")
    suggest("typography.body.family", theme["fonts"].get("minorFont"), 0.85, "Theme body font")
    suggest("layout.slide_width_in", _in(W), 1.0, "Template slide size")
    suggest("layout.slide_height_in", _in(H), 1.0, "Template slide size")
    if title_ph is not None:
        suggest("layout.margin_x_in", _in(title_ph.left), 0.7, "Left edge of the master title placeholder")
        suggest("layout.margin_y_in", _in(title_ph.top), 0.6, "Top of the master title placeholder")
        suggest("layout.content_top_in", _in(title_ph.top + title_ph.height) + 0.15, 0.6, "Below the master title placeholder")
    if sizes:
        body_pt = sizes.most_common(1)[0][0]
        suggest("typography.sizes.body", float(body_pt), 0.5, "Most frequent font size in template slides")
    if result.get("logo"):
        suggest("logo.file", result["logo"]["file"], 0.6, "Small picture on the slide master (likely the logo)")
        suggest("logo.position", result["logo"]["position"], 0.6, "Position of that picture")
        suggest("logo.width_in", result["logo"]["width_in"], 0.6, "Width of that picture")
    suggest("template.blank_layout", blank.name, 0.9, "Layout with the fewest placeholders")
    return result
