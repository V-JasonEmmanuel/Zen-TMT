"""Lightweight, deterministic image treatment (no Photoshop): crop, rotate, flip, brightness,
contrast, saturation, opacity, brand tint/duotone/overlay, border and shape masks.

Brand colours come only from theme roles. Results are cached by (asset hash + treatment + colours).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from backend.branding.theme import Theme, hex_to_rgb
from backend.schemas import ImageRef, ImageTreatment

MAX_SIDE = 2400


def apply_treatment(img: Image.Image, t: ImageTreatment, theme: Theme) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGBA")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    if t.crop:
        x, y, w, h = t.crop
        W, H = img.size
        box = (max(0, int(x * W)), max(0, int(y * H)), min(W, int((x + w) * W)), min(H, int((y + h) * H)))
        if box[2] - box[0] > 4 and box[3] - box[1] > 4:
            img = img.crop(box)
    if t.rotate % 360:
        img = img.rotate(-t.rotate, expand=True)
    if t.flip_h:
        img = ImageOps.mirror(img)
    if t.flip_v:
        img = ImageOps.flip(img)
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    if abs(t.brightness - 1) > 1e-3:
        rgb = ImageEnhance.Brightness(rgb).enhance(t.brightness)
    if abs(t.contrast - 1) > 1e-3:
        rgb = ImageEnhance.Contrast(rgb).enhance(t.contrast)
    if abs(t.saturation - 1) > 1e-3:
        rgb = ImageEnhance.Color(rgb).enhance(t.saturation)
    if t.duotone:  # map luminance between the brand primary (shadows) and the background (highlights)
        rgb = ImageOps.colorize(ImageOps.grayscale(rgb), black=hex_to_rgb(theme.c("primary")), white=hex_to_rgb(theme.c("background")))
    if t.tint_role and t.tint_strength > 0:
        rgb = Image.blend(rgb, Image.new("RGB", rgb.size, hex_to_rgb(theme.c(t.tint_role))), min(0.8, t.tint_strength))
    if t.overlay != "none" and t.overlay_strength > 0:
        col = hex_to_rgb(theme.c(t.overlay_role))
        ov = Image.new("RGBA", rgb.size, (*col, 0))
        a = int(255 * min(0.9, t.overlay_strength))
        if t.overlay == "solid":
            ov.putalpha(a)
        else:  # left-to-right gradient keeps one side readable for overlaid text
            grad = Image.linear_gradient("L").rotate(90, expand=True).resize(rgb.size)
            ov.putalpha(grad.point(lambda v: int(v * a / 255)))
        rgb = Image.alpha_composite(rgb.convert("RGBA"), ov).convert("RGB")
    img = rgb.convert("RGBA")
    img.putalpha(alpha)
    if t.border_px and t.border_role:
        img = ImageOps.expand(img, border=t.border_px, fill=(*hex_to_rgb(theme.c(t.border_role)), 255))
    if t.mask != "rect":
        mask = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(mask)
        W, H = img.size
        if t.mask == "circle":
            s = min(W, H)
            d.ellipse(((W - s) / 2, (H - s) / 2, (W + s) / 2, (H + s) / 2), fill=255)
        elif t.mask == "diamond":
            d.polygon([(W / 2, 0), (W, H / 2), (W / 2, H), (0, H / 2)], fill=255)
        elif t.mask == "rounded":
            d.rounded_rectangle((0, 0, W, H), radius=min(W, H) * 0.08, fill=255)
        elif t.mask == "quarter":
            d.pieslice((-W, 0, W, 2 * H), 270, 360, fill=255)  # quarter circle, centre bottom-left
        img.putalpha(Image.composite(img.getchannel("A"), mask, mask))
    if t.opacity < 0.999:
        img.putalpha(img.getchannel("A").point(lambda v: int(v * max(0.0, t.opacity))))
    return img


def render_treated(ref: ImageRef, theme: Theme) -> Optional[Path]:
    from backend.media.library import MediaLibrary

    lib = MediaLibrary()
    asset = lib.get(ref.asset_id)
    if not asset:
        return None
    src = lib.raster_path(asset)
    if not src.exists():
        return None
    key = hashlib.sha1((asset.sha256 + ref.treatment.model_dump_json() + str(sorted(theme.colors.items()))).encode()).hexdigest()[:16]
    out = lib.root / "processed" / f"{asset.id}_{key}.png"
    if not out.exists():
        with Image.open(src) as im:
            apply_treatment(im, ref.treatment, theme).save(out, "PNG", optimize=True)
    return out
