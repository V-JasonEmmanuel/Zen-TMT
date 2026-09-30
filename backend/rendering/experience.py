"""Scene building blocks for the Zensar "Experience" design language (Zensar's LinkedIn posts).

  cover / divider   full-bleed fluid gradient (cover) or glowing data wave on night indigo (divider),
                    sage quarter-circle top-left, mustard/teal/navy cluster bottom-right,
                    light lead line + bold white headline, coral pill, white wordmark top-right
  content slides    pastel section label, bold indigo title, wordmark top-right, small corner cluster,
                    "An RPG Company" footer
All colours are the measured roles from brands/<id>/social.json (li_*).
"""
from __future__ import annotations

from backend.branding.fonts import text_width_pt
from backend.branding.social import data_wave, fluid_gradient, label_role
from backend.branding.theme import Theme
from backend.rendering import components as C
from backend.rendering.scene import Picture, Scene, Shape


def cluster(t: Theme, region: tuple[float, float, float, float], anim: str = "motif") -> list[Shape]:
    """Bottom-right corner cluster from the Monthly Digest covers: mustard quarter-circle above,
    teal triangle to the left, navy square in the corner."""
    x, y, w, h = region
    cw, ch = w / 2, h / 2
    return [
        Shape("quarter_circle", x + cw, y, cw, ch, fill=t.c("li_mustard"), corner="br", name="li_quarter", anim=f"{anim}:0"),
        Shape("right_triangle", x, y + ch, cw, ch, fill=t.c("li_teal"), corner="tr", name="li_triangle", anim=f"{anim}:1"),
        Shape("rect", x + cw, y + ch, cw, ch, fill=t.c("li_navy"), name="li_square", anim=f"{anim}:2"),
    ]


def sage_corner(t: Theme, size: float) -> Shape:
    return Shape("quarter_circle", 0, 0, size, size, fill=t.c("li_sage"), corner="tl", name="li_sage", anim="motif:3")


def label(t: Theme, text: str, x: float, y: float, h: float = 0.32, role: str | None = None) -> list:
    """Pastel section label (the coloured bars heading each item in Zensar's monthly digest)."""
    text = (text or "").strip()[:40]
    if not text:
        return []
    size = t.sizes["caption"] + 1.5
    tw = text_width_pt(text, t.caption_font, True, size) / 72
    w = tw + 0.5
    fill = role or label_role(t, text)
    box = Shape("rect", x, y, w, h, fill=t.c(fill), name="section_label", anim="title")
    tb = C.text(t, x, y, w, h, text, role="text_primary", size=size, font="caption", bold=True, align="center",
                valign="middle", min_size=7, name="section_label_text")
    tb.anim = "title"
    return [box, tb]


def pill(t: Theme, text: str, x: float, y: float, fill_role: str = "li_coral", h: float = 0.42) -> list:
    size = t.sizes["caption"] + 2
    tw = text_width_pt(text, t.body_font, True, size) / 72
    w = min(tw + 0.6, t.slide_w * 0.6)
    fg = "on_" + fill_role
    tb = C.text(t, x, y, w, h, text, role=fg, size=size, bold=True, align="center", valign="middle", min_size=7, name="pill_text")
    tb.anim = "chrome"
    return [Shape("pill", x, y, w, h, fill=t.c(fill_role), name="pill", anim="chrome"), tb]


def title_block(scene: Scene, t: Theme, title: str, subtitle: str = "", tag: str = "") -> float:
    mx, my = t.margin_x, t.margin_y
    y = my
    if tag:
        scene.add(*label(t, tag, mx, y))
        y += 0.48
    reserve = (t.logo_width + 0.4) if t.logo_path else 0.0
    w = t.slide_w - 2 * mx - reserve
    tb = C.text(t, mx, y, w, 0.78, title, role=t.title_color_role, size=t.sizes["title"], font="heading", bold=True,
                valign="top", min_size=18, name="title")
    tb.anim = "title"
    scene.add(tb)
    y += 0.8
    if subtitle:
        st = C.text(t, mx, y, w, 0.4, subtitle, role="text_secondary", size=t.sizes["subtitle"] * 0.85, min_size=11,
                    name="subtitle")
        st.anim = "title"
        scene.add(st)
        y += 0.42
    return max(t.content_top, y + 0.2)


def cover(scene: Scene, t: Theme, s, ctx, divider: bool = False) -> None:
    W, H = t.slide_w, t.slide_h
    scene.background = t.c("li_indigo")
    art = data_wave(t) if divider else fluid_gradient(t, seed=7 + (s.slide_number % 3))
    scene.add(Picture(0, 0, W, H, art, fit="cover", name="background_art", anim="chrome"))
    scene.add(sage_corner(t, H * (0.2 if divider else 0.24)))
    cell = H * (0.16 if divider else 0.19)
    scene.add(*cluster(t, (W - 2 * cell, H - 2 * cell, 2 * cell, 2 * cell)))
    mx = t.margin_x + 0.2
    tw = W * 0.66
    y = H * (0.30 if not divider else 0.34)
    if s.subtitle:  # light lead line, then the bold headline (the posts' two-weight headline)
        lead = C.text(t, mx, y, tw, 0.55, s.subtitle, role="on_li_indigo", size=t.sizes["subtitle"] + 2, min_size=11,
                      valign="bottom", name="subtitle")
        lead.anim = "title"
        scene.add(lead)
        y += 0.65
    title = C.text(t, mx, y, tw, H * 0.3, s.title, role="on_li_indigo", size=t.sizes["cover_title"] * (0.85 if divider else 1.05),
                   font="heading", bold=True, valign="top", min_size=22, name="title")
    title.anim = "title"
    scene.add(title)
    if not divider:
        doc = next((sl.sources[0].document_name for sl in ctx.plan.slides if sl.sources), "")
        if doc:
            scene.add(*pill(t, f"Based on {doc}", mx, H - t.margin_y - 1.05))
    if t.footer_text:
        f = C.text(t, mx, H - t.margin_y - 0.3, 3.5, 0.3, t.footer_text, role="on_li_indigo", size=t.sizes["caption"] + 1,
                   font="caption", min_size=7, name="footer_brand")
        f.anim = "chrome"
        scene.add(f)
    C.chrome(scene, t, s.slide_number, ctx.total, [], dark=True, cover=True)


def brand_card(t: Theme, kind: str = "intro", title: str = "") -> Scene:
    """Video opener / closer in the posts' style: fluid gradient (intro) or data wave (outro), the corner
    shapes, and the white wordmark; the outro adds a closing line."""
    from PIL import Image as _Image

    W, H = t.slide_w, t.slide_h
    scene = Scene(W, H, t.c("li_indigo"), name=f"brand_{kind}")
    art = fluid_gradient(t, seed=11) if kind == "intro" else data_wave(t, seed=5)
    scene.add(Picture(0, 0, W, H, art, fit="cover", name="background_art", anim="chrome"))
    scene.add(sage_corner(t, H * 0.26))
    cell = H * 0.2
    scene.add(*cluster(t, (W - 2 * cell, H - 2 * cell, 2 * cell, 2 * cell)))
    logo = t.logo_dark_path or t.logo_path
    if logo:
        with _Image.open(logo) as im:
            ar = im.height / im.width
        lw = W * 0.34
        pic = Picture((W - lw) / 2, H * 0.40 - lw * ar / 2, lw, lw * ar, str(logo), name="logo_large", anim="title")
        scene.add(pic)
    y = H * 0.40 + (W * 0.34 * ar / 2 if logo else 0) + 0.35
    if kind == "outro":
        tb = C.text(t, W * 0.15, y, W * 0.7, 0.8, title or "Thank you", role="on_li_indigo", size=t.sizes["cover_title"] * 0.8,
                    font="heading", bold=True, align="center", valign="top", min_size=18, name="closing")
        tb.anim = "build:1"
        scene.add(tb)
    if t.footer_text:
        f = C.text(t, W * 0.25, H - t.margin_y - 0.45, W * 0.5, 0.35, t.footer_text, role="on_li_indigo",
                   size=t.sizes["caption"] + 3, font="caption", align="center", min_size=7, name="footer_brand")
        f.anim = "build:2"
        scene.add(f)
    return scene
