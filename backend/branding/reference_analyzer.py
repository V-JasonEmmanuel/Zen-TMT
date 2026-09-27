"""Reference image analysis (screenshots of on-brand slides, visual examples).

Assists design extraction only. Colour roles inferred from pixels are *low-confidence
suggestions*; the user confirms them in the Brand Manager. Typography cannot be read
reliably from pixels, so it is never suggested here.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*[int(x) for x in rgb[:3]])


def _saturation(rgb) -> float:
    r, g, b = [x / 255 for x in rgb[:3]]
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _lum(rgb) -> float:
    r, g, b = rgb[:3]
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def analyze_image(path: Path) -> dict[str, Any]:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    small = img.resize((320, max(1, int(320 * h / w))))
    arr = np.asarray(small)
    # palette via median-cut quantisation (deterministic)
    q = small.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:30]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    colors = [{"hex": _hex(pal[i * 3:i * 3 + 3]), "share": round(c / total, 4)} for c, i in counts]

    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    bq = Counter(_hex((px // 8) * 8 + 4) for px in border)
    bg_hex, bg_count = bq.most_common(1)[0]
    bg_consistency = bg_count / len(border)
    bg = np.array([int(bg_hex[i:i + 2], 16) for i in (1, 3, 5)])

    # layout: content mask = pixels differing from background
    diff = np.abs(arr.astype(int) - bg).sum(axis=2) > 60
    whitespace = 1 - float(diff.mean())
    ys, xs = np.where(diff)
    bbox = None
    alignment = "unknown"
    if len(xs):
        x0, x1, y0, y1 = xs.min() / arr.shape[1], xs.max() / arr.shape[1], ys.min() / arr.shape[0], ys.max() / arr.shape[0]
        bbox = {"left": round(x0, 3), "top": round(y0, 3), "right": round(x1, 3), "bottom": round(y1, 3)}
        col_mass = diff.mean(axis=0)
        left_mass, right_mass = col_mass[: len(col_mass) // 2].sum(), col_mass[len(col_mass) // 2:].sum()
        alignment = "left-weighted" if left_mass > right_mass * 1.3 else "right-weighted" if right_mass > left_mass * 1.3 else "balanced"
    # horizontal bands (e.g. header bars): rows mostly non-background
    row_fill = diff.mean(axis=1)
    full = np.concatenate([[False], row_fill > 0.8])
    bands = int((full[1:] & ~full[:-1]).sum())  # band starts, including one at the very top

    non_bg = [c for c in colors if _hex_dist(c["hex"], bg_hex) > 60]
    chromatic = sorted([c for c in non_bg if _saturation(_rgb(c["hex"])) > 0.35], key=lambda c: -c["share"])
    dark = sorted([c for c in non_bg if _lum(_rgb(c["hex"])) < 0.3], key=lambda c: -c["share"])
    return {
        "file": path.name, "size": {"width": w, "height": h}, "aspect": round(w / h, 3),
        "dominant_colors": colors, "background": bg_hex, "background_consistency": round(bg_consistency, 3),
        "chromatic_colors": [c["hex"] for c in chromatic[:4]], "dark_colors": [c["hex"] for c in dark[:2]],
        "whitespace_ratio": round(whitespace, 3), "visual_density": round(1 - whitespace, 3),
        "content_bbox": bbox, "alignment": alignment, "full_width_bands": bands,
    }


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _hex_dist(a: str, b: str) -> int:
    return sum(abs(x - y) for x, y in zip(_rgb(a), _rgb(b)))


def analyze_references(paths: list[Path]) -> dict[str, Any]:
    per = [analyze_image(p) for p in paths]
    if not per:
        return {"images": [], "suggestions": []}
    bg_votes = Counter(a["background"] for a in per if a["background_consistency"] > 0.6)
    chroma = Counter()
    for a in per:
        for rank, c in enumerate(a["chromatic_colors"]):
            chroma[_bucket(c)] += 4 - rank
    dark = Counter(_bucket(c) for a in per for c in a["dark_colors"])
    n = len(per)
    S = []
    if bg_votes:
        v, c = bg_votes.most_common(1)[0]
        S.append({"path": "colors.background", "value": v, "confidence": round(0.3 + 0.4 * c / n, 2),
                  "reason": f"Dominant border colour in {c}/{n} reference image(s)"})
    ranked = [c for c, _ in chroma.most_common(4)]
    for path, idx, conf in (("colors.primary", 0, 0.4), ("colors.secondary", 1, 0.3), ("colors.accent", 2, 0.25)):
        if len(ranked) > idx:
            S.append({"path": path, "value": ranked[idx], "confidence": conf,
                      "reason": f"#{idx + 1} most prominent saturated colour across references - please confirm"})
    if dark:
        S.append({"path": "colors.text_primary", "value": dark.most_common(1)[0][0], "confidence": 0.35,
                  "reason": "Most common dark colour (likely text) - please confirm"})
    summary = {
        "avg_whitespace": round(float(np.mean([a["whitespace_ratio"] for a in per])), 3),
        "alignment": Counter(a["alignment"] for a in per).most_common(1)[0][0],
        "aspects": sorted({a["aspect"] for a in per}),
    }
    return {"images": per, "summary": summary, "suggestions": S}


def _bucket(h: str) -> str:
    """Merge near-identical colours (JPEG noise) by rounding channels."""
    r, g, b = _rgb(h)
    return "#{:02X}{:02X}{:02X}".format(*(min(255, round(x / 6) * 6) for x in (r, g, b)))
