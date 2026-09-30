"""Deterministic, brand-driven motion graphics for presentation videos.

A slide Scene is split into layers by the `anim` tags the layout engine assigns:
    chrome -> static base (background, logo, footer, section tag)
    motif:* / custom -> Z-motif shape build (scale + fade, staggered)
    panel -> brand panel wipe
    title -> rise + fade
    build:* -> content groups appear in reading order (cards, steps, rows, nodes, KPIs)
    chart -> progressive reveal ("bars grow")      KPI values -> count-up
Transitions between slides: "zensar_grid" (modular tiles cover/uncover the frame), "fade", "wipe", "none".

Only the short build phase is rendered frame by frame; the hold is a still frame, which keeps
rendering fast on modest hardware. Motion stays subtle: no spins, no zoom-punches.
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageDraw

from backend.branding.theme import Theme, hex_to_rgb
from backend.rendering.images.raster import RasterRenderer
from backend.rendering.scene import Chart, Line, Picture, Scene, Shape, TextBox

NUM = re.compile(r"^([^\d-]*)(-?\d[\d,]*\.?\d*)(.*)$")


def ease_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


@dataclass
class Layer:
    img: Image.Image
    x: int
    y: int
    kind: str
    start: float
    dur: float
    frames: list[Image.Image] = field(default_factory=list)  # pre-rendered steps (KPI count-up)


def _bbox(el) -> tuple[float, float, float, float]:
    if hasattr(el, "x1"):
        return (min(el.x1, el.x2), min(el.y1, el.y2), max(el.x1, el.x2), max(el.y1, el.y2))
    return (el.x, el.y, el.x + el.w, el.y + el.h)


def _inside(inner, outer, tol=0.05) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def group_elements(scene: Scene) -> tuple[list, list[tuple[str, list]]]:
    """(static elements, ordered animated groups [(kind, elements)])."""
    static, groups = [], []
    for el in scene.elements:
        tag = el.anim or ""
        if tag == "chrome" or tag == "" and isinstance(el, TextBox) and el.name in ("sources", "footer_right"):
            static.append(el)
            continue
        if tag.startswith("motif") or tag == "custom":
            groups.append(("motif", [el]))
        elif tag == "panel":
            groups.append(("panel", [el]))
        elif tag == "title":
            if groups and groups[-1][0] == "title":
                groups[-1][1].append(el)
            else:
                groups.append(("title", [el]))
        elif isinstance(el, Chart):
            groups.append(("chart", [el]))
        elif isinstance(el, Picture) and el.name != "logo":
            groups.append(("image", [el]))
        elif tag.startswith("build:kpi"):
            key = ("kpi:" + tag, )
            if groups and groups[-1][0] == key[0]:
                groups[-1][1].append(el)
            else:
                groups.append((key[0], [el]))
        else:
            # containment grouping: a card/shape and the texts inside it build together
            bb = _bbox(el)
            if groups and groups[-1][0] == "content" and _inside(bb, _bbox(groups[-1][1][0])):
                groups[-1][1].append(el)
            else:
                groups.append(("content", [el]))
    return static, groups


def _kpi_steps(scene: Scene, rr: RasterRenderer, el: TextBox, steps: int = 14) -> list[tuple[Image.Image, int, int]]:
    """Pre-render a KPI value counting up from zero, preserving prefix/suffix/decimals."""
    text = el.paras[0].text if el.paras else ""
    m = NUM.match(text.strip())
    if not m:
        return []
    pre, num, post = m.groups()
    decimals = len(num.split(".")[1]) if "." in num else 0
    target = float(num.replace(",", ""))
    out = []
    for i in range(1, steps + 1):
        v = target * ease_out(i / steps)
        s = f"{v:,.{decimals}f}" if "," in num else f"{v:.{decimals}f}"
        e = copy.deepcopy(el)
        e.paras[0].text = pre + s + post
        e.paras[0].lines = [pre + s + post]
        r = rr.render_layer(scene, [e])
        if r:
            out.append(r)
    return out


def build_layers(scene: Scene, width_px: int, motion: str = "subtle") -> tuple[Image.Image, list[Layer], float]:
    rr = RasterRenderer(width_px)
    static, groups = group_elements(scene)
    base = rr.render(Scene(scene.width, scene.height, scene.background, static)).convert("RGB")
    if motion == "none":
        full = rr.render(scene).convert("RGB")
        return full, [], 0.0
    layers: list[Layer] = []
    motif_i = 0
    # build slots: connectors (drawn under the boxes) animate after the boxes they join, never before
    content = [i for i, (k, _) in enumerate(groups) if k in ("content", "chart", "image") or k.startswith("kpi")]
    is_line = {i: all(isinstance(e, Line) for e in groups[i][1]) for i in content}
    order = [i for i in content if not is_line[i]] + [i for i in content if is_line[i]]
    slot = {gi: n for n, gi in enumerate(order)}
    n_content = sum(1 for k, _ in groups if k == "content" or k.startswith("kpi"))
    stagger = 0.18 if n_content <= 8 else max(0.06, 1.4 / n_content)
    t_content = 0.65
    for gi, (kind, els) in enumerate(groups):
        content_i = slot.get(gi, 0)
        r = rr.render_layer(scene, els)
        if not r:
            continue
        img, x, y = r
        if kind == "motif":
            layers.append(Layer(img, x, y, "motif", 0.05 + motif_i * 0.07, 0.45))
            motif_i += 1
        elif kind == "panel":
            layers.append(Layer(img, x, y, "panel", 0.05, 0.5))
        elif kind == "title":
            layers.append(Layer(img, x, y, "title", 0.2, 0.5))
        elif kind == "chart":
            layers.append(Layer(img, x, y, "chart_h" if (els[0].data.chart_type == "bar") else "chart_v",
                                t_content + content_i * stagger, 1.0))
        elif kind == "image":
            layers.append(Layer(img, x, y, "image", t_content + content_i * stagger, 0.6))
        elif kind.startswith("kpi"):
            start = t_content + content_i * stagger
            value = next((e for e in els if isinstance(e, TextBox) and e.name == "kpi_value"), None)
            rest = [e for e in els if e is not value]
            if rest:
                rr_rest = rr.render_layer(scene, rest)
                if rr_rest:
                    layers.append(Layer(rr_rest[0], rr_rest[1], rr_rest[2], "content", start, 0.45))
            if value is not None:
                steps = _kpi_steps(scene, rr, value)
                if steps:
                    lay = Layer(steps[-1][0], steps[-1][1], steps[-1][2], "kpi", start, 0.9)
                    lay.frames = [s[0] for s in steps]
                    lay.x_list = [s[1] for s in steps]  # type: ignore[attr-defined]
                    layers.append(lay)
        else:
            layers.append(Layer(img, x, y, "content", t_content + content_i * stagger, 0.45))
    t_build = max((l.start + l.dur for l in layers), default=0.0)
    return base, layers, t_build


def _alpha(img: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: int(v * max(0.0, a))))
    return out


def compose(base: Image.Image, layers: list[Layer], t: float, scale_px: float) -> Image.Image:
    frame = base.copy()
    for l in layers:
        p = (t - l.start) / l.dur if l.dur else 1.0
        if p <= 0:
            continue
        e = ease_out(p)
        if l.kind == "motif":
            sc = 0.35 + 0.65 * e
            w, h = max(1, int(l.img.width * sc)), max(1, int(l.img.height * sc))
            im = _alpha(l.img.resize((w, h), Image.BILINEAR) if sc < 0.999 else l.img, min(1.0, p * 1.6))
            frame.paste(im, (l.x + (l.img.width - w) // 2, l.y + (l.img.height - h) // 2), im)
        elif l.kind == "panel":  # wipe from the left
            w = max(1, int(l.img.width * e))
            im = l.img.crop((0, 0, w, l.img.height))
            frame.paste(im, (l.x, l.y), im)
        elif l.kind in ("title", "content", "image"):
            dy = int((1 - e) * 22 * scale_px)
            im = _alpha(l.img, e)
            frame.paste(im, (l.x, l.y + dy), im)
        elif l.kind == "chart_v":  # grow from the baseline
            h = max(1, int(l.img.height * e))
            im = l.img.crop((0, l.img.height - h, l.img.width, l.img.height))
            frame.paste(im, (l.x, l.y + l.img.height - h), im)
        elif l.kind == "chart_h":
            w = max(1, int(l.img.width * e))
            im = l.img.crop((0, 0, w, l.img.height))
            frame.paste(im, (l.x, l.y), im)
        elif l.kind == "kpi":
            i = min(len(l.frames) - 1, int(p * len(l.frames))) if l.frames else 0
            im = _alpha(l.frames[i] if l.frames else l.img, min(1.0, p * 2.5))
            xs = getattr(l, "x_list", None)
            frame.paste(im, (xs[i] if xs else l.x, l.y), im)
    return frame


# ------------------------------------------------------------------ transitions
def _tile_colors(theme: Theme) -> list[tuple[int, int, int]]:
    roles = ["primary", "secondary", "tint_0", "primary", "accent", "secondary", "tint_1"]
    if getattr(theme, "design", "") == "experience":  # the LinkedIn palette: indigo, mustard, teal, sage, navy, lavender
        roles = ["li_indigo", "li_mustard", "li_navy", "li_teal", "li_indigo", "li_sage", "li_lavender"]
    return [hex_to_rgb(theme.c(r)) for r in roles]


def transition_frame(kind: str, prev: Image.Image, nxt: Image.Image, p: float, theme: Theme) -> Image.Image:
    """p in [0,1]. prev/nxt are same-size RGB frames."""
    if kind == "fade":
        return Image.blend(prev, nxt, ease_in_out(p))
    if kind == "wipe":
        w = int(nxt.width * ease_in_out(p))
        out = prev.copy()
        if w > 0:
            out.paste(nxt.crop((0, 0, w, nxt.height)), (0, 0))
        return out
    if kind != "zensar_grid":
        return nxt if p >= 1 else prev
    # modular tiles cover the old frame column by column, then uncover the new one
    W, H = prev.size
    cols, rows = 8, 5
    cw, ch = math.ceil(W / cols), math.ceil(H / rows)
    cover = p < 0.5
    q = p / 0.5 if cover else (p - 0.5) / 0.5
    out = (prev if cover else nxt).copy()
    d = ImageDraw.Draw(out)
    colors = _tile_colors(theme)
    for c in range(cols):
        for r in range(rows):
            delay = (c + (r % 2) * 0.5) / (cols + 1)
            local = min(1.0, max(0.0, (q - delay * 0.6) / 0.4))
            s = ease_out(local) if cover else 1 - ease_out(local)
            if s <= 0.01:
                continue
            x0, y0 = c * cw, r * ch
            color = colors[(c + r * 3) % len(colors)]
            size_w, size_h = cw * s, ch * s
            shape = (c * 7 + r * 3) % 5
            if shape == 0:  # triangle modules echo the Z motif
                d.polygon([(x0, y0 + ch), (x0 + size_w, y0 + ch), (x0, y0 + ch - size_h)], fill=color)
                if s > 0.98:
                    d.rectangle((x0, y0, x0 + cw, y0 + ch), fill=color)
            elif shape == 1:  # quarter circle
                d.pieslice((x0 - size_w, y0 + ch - size_h, x0 + size_w, y0 + ch + size_h), 270, 360, fill=color)
                if s > 0.98:
                    d.rectangle((x0, y0, x0 + cw, y0 + ch), fill=color)
            else:
                d.rectangle((x0, y0 + ch - size_h, x0 + size_w, y0 + ch), fill=color)
    return out


TRANSITION_SECONDS = {"zensar_grid": 0.9, "fade": 0.5, "wipe": 0.6, "none": 0.0}


def slide_frames(scene: Scene, theme: Theme, width_px: int, fps: int, motion: str = "subtle",
                 transition: str = "zensar_grid", prev: Optional[Image.Image] = None):
    """Yield the animated frames of one slide (transition-in + build). Returns the final frame
    via StopIteration.value; the caller holds that frame for the rest of the slide duration."""
    base, layers, t_build = build_layers(scene, width_px, motion)
    tt = TRANSITION_SECONDS.get(transition, 0.0) if prev is not None else 0.0
    scale_px = width_px / 1920
    final = compose(base, layers, t_build + 1, scale_px) if layers else base
    n_trans = int(round(tt * fps))
    # the build starts under the transition, so the incoming slide is never revealed as an empty page
    for i in range(n_trans):
        p = (i + 1) / n_trans
        yield transition_frame(transition, prev, compose(base, layers, p * tt, scale_px), p, theme)
    t0 = tt if n_trans else 0.0
    n_build = int(math.ceil(max(0.0, t_build - t0) * fps))
    for i in range(n_build):
        yield compose(base, layers, t0 + (i + 1) / fps, scale_px)
    return final


def intro_frames(theme: Theme, width_px: int, height_px: int, fps: int, logo: Optional[str], seconds: float = 2.6):
    """Brand opener: circle -> square -> triangle assemble on the modular grid, then the wordmark."""
    W, H = width_px, height_px
    bg = hex_to_rgb(theme.c("background"))
    cols = [hex_to_rgb(theme.c(r)) for r in ("primary", "secondary", "accent")]
    unit = int(H * 0.16)
    cx, cy = W // 2, int(H * 0.42)
    logo_img = None
    if logo:
        try:
            li = Image.open(logo).convert("RGBA")
            lw = int(W * 0.22)
            logo_img = li.resize((lw, int(li.height * lw / li.width)), Image.LANCZOS)
        except Exception:
            logo_img = None
    n = int(seconds * fps)
    for i in range(n):
        t = i / fps
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        for k, kind in enumerate(("circle", "square", "triangle")):
            p = ease_out((t - 0.15 - k * 0.22) / 0.5)
            if p <= 0:
                continue
            x0 = cx - int(1.6 * unit) + k * int(1.1 * unit)
            y0 = cy - unit // 2 + int((1 - p) * unit * 0.6)
            s = int(unit * (0.4 + 0.6 * p))
            off = (unit - s) // 2
            box = (x0 + off, y0 + off, x0 + off + s, y0 + off + s)
            color = cols[k]
            if kind == "circle":
                d.ellipse(box, fill=color)
            elif kind == "square":
                d.rectangle(box, fill=color)
            else:
                d.polygon([(box[0], box[3]), (box[2], box[3]), (box[0], box[1])], fill=color)
        if logo_img is not None:
            p = ease_out((t - 1.1) / 0.6)
            if p > 0:
                li = _alpha(logo_img, p)
                im.paste(li, ((W - li.width) // 2, int(H * 0.66) + int((1 - p) * 12)), li)
        yield im
