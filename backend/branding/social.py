"""Zensar "Experience" design language, taken from Zensar Technologies' LinkedIn posts.

brands/<id>/social.json holds the measured colours (sampled from the published post images, with
their sources) and the observed rules. This module applies them to a Theme and generates the
background art those posts use: the fluid blue-violet -> coral gradient and the glowing data wave.
The same Theme drives PPTX, PDF, images and video, so all outputs share the look.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from backend.branding.theme import Theme, hex_to_rgb

DESIGN_ID = "experience"


def load_social(brand_id: str) -> Optional[dict]:
    from backend.branding.brand_profile import BrandStore

    p = BrandStore().dir(brand_id) / "social.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apply_social(theme: Theme, spec: Optional[dict] = None) -> Theme:
    """Theme in the LinkedIn design language (no-op for brands without a social.json)."""
    spec = spec or load_social(theme.brand_id)
    if not spec:
        return theme
    t = replace(theme, colors=dict(theme.colors))
    for role, v in spec.get("colors", {}).items():
        t.colors[role] = v["hex"] if isinstance(v, dict) else v
    rules = spec.get("rules", {})
    t.design = DESIGN_ID
    t.logo_position = "top_right" if rules.get("wordmark", "top_right") == "top_right" else t.logo_position
    t.footer_text = rules.get("footer_text", t.footer_text)
    t.title_color_role = "primary"
    t.accent_bar = False  # the pastel section label replaces the accent bar
    t.card_fill_role = "surface_alt"
    t.bullet_color_role = "li_coral" if "li_coral" in t.colors else t.bullet_color_role
    if t.shapes is not None:
        t.shapes = t.shapes.model_copy(update={"section_tag": False})
    t.section_label_roles = [r for r in rules.get("section_label_roles", []) if r in t.colors]
    t.tints = [t.colors[r] for r in ("li_lavender", "li_sage", "li_mustard", "li_teal") if r in t.colors] or t.tints
    return t


def is_experience(t: Theme) -> bool:
    return getattr(t, "design", "") == DESIGN_ID


def label_role(t: Theme, key: str) -> str:
    roles = getattr(t, "section_label_roles", None) or ["surface_alt"]
    return roles[int(hashlib.md5(key.lower().encode()).hexdigest(), 16) % len(roles)]


# ------------------------------------------------------------------ background art
def _art_dir() -> Path:
    from backend.utils.config import get_settings

    d = get_settings().data_path / "cache" / "brand_art"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cached(kind: str, t: Theme, w: int, h: int, seed: int, roles: tuple[str, ...]) -> tuple[Path, bool]:
    key = hashlib.sha1(f"{kind}|{w}x{h}|{seed}|{[t.c(r) for r in roles]}|v3".encode()).hexdigest()[:14]
    p = _art_dir() / f"{kind}_{key}.png"
    return p, p.exists()


def fluid_gradient(t: Theme, w: int = 1920, h: int = 1080, seed: int = 7) -> str:
    """Soft fluid blend of the measured gradient colours (as on the New Year 2026 post)."""
    roles = ("li_grad_deep", "li_grad_blue", "li_grad_coral", "li_pink")
    p, ok = _cached("fluid", t, w, h, seed, roles)
    if ok:
        return str(p)
    sw, sh = 480, int(480 * h / w)
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    xx, yy = xx / sw, yy / sh
    # gentle domain warp gives the "liquid" bands
    wx = xx + 0.08 * np.sin(yy * 6.0 + seed) + 0.05 * np.sin(yy * 13.0 + 1.3 * seed)
    wy = yy + 0.08 * np.cos(xx * 5.0 + 0.7 * seed)
    base = np.array(hex_to_rgb(t.c(roles[0])), np.float32)
    acc = base * 0.9
    wsum = np.full_like(xx, 0.9)
    blobs = [(roles[1], 0.18, 0.30, 0.40), (roles[1], 0.85, 0.45, 0.35), (roles[2], 0.55, 0.78, 0.30),
             (roles[3], 0.92, 0.08, 0.22), (roles[0], 0.35, 0.10, 0.25)]
    for role, cx, cy, r in blobs:
        cx, cy = cx + rng.uniform(-0.06, 0.06), cy + rng.uniform(-0.06, 0.06)
        d2 = ((wx - cx) * (w / h)) ** 2 + (wy - cy) ** 2
        wgt = np.exp(-d2 / (r * r)) * 2.2
        acc = acc + wgt[..., None] * np.array(hex_to_rgb(t.c(role)), np.float32)
        wsum = wsum + wgt
    img = (acc / wsum[..., None]).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(img, "RGB").filter(ImageFilter.GaussianBlur(3)).resize((w, h), Image.BICUBIC)
    im.save(p)
    return str(p)


def data_wave(t: Theme, w: int = 1920, h: int = 1080, seed: int = 3, bg_role: str = "li_night") -> str:
    """Dark field with a glowing ribbon of fine lines (as on the product-launch posts)."""
    roles = (bg_role, "li_coral", "li_pink_deep", "li_blue")
    p, ok = _cached("wave", t, w, h, seed, roles)
    if ok:
        return str(p)
    S = 2
    im = Image.new("RGB", (w * S, h * S), hex_to_rgb(t.c(bg_role)))
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    cols = [np.array(hex_to_rgb(t.c(r)), np.float32) for r in roles[1:]]
    n_lines = 46
    for i in range(n_lines):
        f = i / (n_lines - 1)
        col = cols[0] * (1 - f) + cols[1] * f if f < 0.5 else cols[1] * (1 - (f - 0.5) * 2) + cols[2] * ((f - 0.5) * 2)
        pts = []
        for k in range(0, 121):
            x = k / 120
            y = 0.64 + 0.13 * math.sin(x * 4.6 + f * 2.4 + seed) * (0.35 + x) + (f - 0.5) * 0.42 * (0.15 + x) ** 1.3
            pts.append((x * w * S, y * h * S))
        alpha = int(120 + 135 * (1 - abs(f - 0.5) * 2))
        d.line(pts, fill=(*[int(c) for c in col], alpha), width=max(1, int(1.4 * S)))
    blur = glow.filter(ImageFilter.GaussianBlur(9 * S))
    im = im.convert("RGBA")
    for _ in range(2):  # stacked blur = soft glow around the ribbon
        im = Image.alpha_composite(im, blur)
    im = Image.alpha_composite(im, glow).convert("RGB")
    im.resize((w, h), Image.LANCZOS).save(p)
    return str(p)
