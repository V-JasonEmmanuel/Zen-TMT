"""Local font discovery and text measurement (used identically by every renderer)."""
from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

from backend.utils.config import get_settings
from backend.utils.logging import get_logger

log = get_logger(__name__)
_lock = threading.Lock()
_index: Optional[dict[str, dict[str, str]]] = None  # family(lower) -> {"regular": path, "bold": path, "_name": Family}
FALLBACK_FAMILIES = ("Arial", "Segoe UI", "Calibri", "Helvetica", "Liberation Sans", "DejaVu Sans")


def _font_dirs() -> list[Path]:
    dirs = [get_settings().brands_path]
    windir = os.environ.get("WINDIR")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path("/Library/Fonts"), Path.home() / ".fonts"]
    try:
        import matplotlib

        dirs.append(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
    except Exception:
        pass
    return [d for d in dirs if d.exists()]


def _build_index() -> dict[str, dict[str, str]]:
    cache = get_settings().data_path / "font_index.json"
    dirs = _font_dirs()
    sig = ";".join(f"{d}:{int(d.stat().st_mtime)}" for d in dirs)
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            if data.get("sig") == sig:
                return data["index"]
        except Exception:
            pass
    index: dict[str, dict[str, str]] = {}
    for d in dirs:
        for p in d.rglob("*"):
            if p.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                family, style = ImageFont.truetype(str(p), 12).getname()
            except Exception:
                continue
            if not family:
                continue
            key = family.lower()
            s = (style or "Regular").lower()
            entry = index.setdefault(key, {"_name": family})
            slot = "bold" if s in ("bold",) else "regular" if s in ("regular", "normal", "roman", "book") else None
            if slot and slot not in entry:
                entry[slot] = str(p)
            entry.setdefault("_any", str(p))
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"sig": sig, "index": index}))
    except Exception:
        pass
    log.info("Font index built", families=len(index))
    return index


def font_index() -> dict[str, dict[str, str]]:
    global _index
    with _lock:
        if _index is None:
            _index = _build_index()
        return _index


def reset_font_index() -> None:
    global _index
    with _lock:
        _index = None
    _font_cached.cache_clear()


def list_families() -> list[str]:
    return sorted({v["_name"] for v in font_index().values()}, key=str.lower)


def has_family(family: Optional[str]) -> bool:
    return bool(family) and family.lower() in font_index()


def resolve_font_path(family: Optional[str], bold: bool = False) -> str:
    idx = font_index()
    for fam in ([family] if family else []) + list(FALLBACK_FAMILIES):
        entry = idx.get((fam or "").lower())
        if entry:
            return entry.get("bold" if bold else "regular") or entry.get("regular") or entry["_any"]
    return next(iter(idx.values()))["_any"] if idx else ""


@lru_cache(maxsize=512)
def _font_cached(path: str, px: int) -> ImageFont.FreeTypeFont:
    if not path:
        return ImageFont.load_default()
    return ImageFont.truetype(path, px)


MEASURE_SCALE = 4  # measure at 4 px per pt for sub-point precision


def get_font(family: Optional[str], bold: bool, px: int) -> ImageFont.FreeTypeFont:
    return _font_cached(resolve_font_path(family, bold), max(1, int(px)))


def text_width_pt(text: str, family: Optional[str], bold: bool, size_pt: float) -> float:
    f = get_font(family, bold, round(size_pt * MEASURE_SCALE))
    return f.getlength(text) / MEASURE_SCALE


def wrap_text(text: str, family: Optional[str], bold: bool, size_pt: float, width_pt: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        line = ""
        for w in words:
            trial = f"{line} {w}".strip()
            if not line or text_width_pt(trial, family, bold, size_pt) <= width_pt:
                line = trial
            else:
                lines.append(line)
                line = w
            # hard-break single words that are wider than the box
            while text_width_pt(line, family, bold, size_pt) > width_pt and len(line) > 4:
                cut = len(line) - 1
                while cut > 1 and text_width_pt(line[:cut] + "-", family, bold, size_pt) > width_pt:
                    cut -= 1
                lines.append(line[:cut] + "-")
                line = line[cut:]
        lines.append(line)
    return lines
