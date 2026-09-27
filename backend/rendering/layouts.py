"""Layout engine: semantic slide layout + Theme -> positioned Scene.

The planner decides WHAT a slide says and which semantic layout it uses; this module
alone decides WHERE things go, using brand tokens for every visual property.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from backend.branding.theme import Theme
from backend.rendering import components as C
from backend.rendering.scene import Para, Picture, Scene, Shape
from backend.schemas import ContentPlan, Slide

LayoutFn = Callable[[Scene, Theme, Slide, "RenderContext"], None]


class RenderContext:
    def __init__(self, plan: ContentPlan, figures_root: Optional[Path] = None):
        self.plan = plan
        self.figures_root = figures_root
        self.total = len(plan.slides)
        self.theme: Optional[Theme] = None

    def image_path(self, s: Slide) -> Optional[str]:
        """Processed (treated/cropped) local file for the slide's chosen image, if any."""
        if not s.image or self.theme is None:
            return None
        try:
            from backend.media.treatment import render_treated

            p = render_treated(s.image, self.theme)
            return str(p) if p else None
        except Exception:
            return None

    def image_credit(self, s: Slide) -> str:
        if not s.image:
            return ""
        return f"Visual: {s.image.source_label}" if s.image.source_label else ""

    def figure_path(self, rel: Optional[str]) -> Optional[str]:
        if not rel or not self.figures_root:
            return None
        p = (self.figures_root / rel).resolve()
        return str(p) if p.exists() else None


def _speaker_notes(slide: Slide) -> str:
    parts = []
    if slide.narration:
        parts.append(slide.narration)
    flagged = [i for i in (*slide.key_points, *slide.steps, *slide.kpis, *(p for c in slide.columns for p in c.points))
               if i.status in ("needs_review", "unsupported")]
    if flagged:
        parts.append(f"REVIEW: {len(flagged)} statement(s) on this slide have low source confidence.")
    if slide.sources:
        parts.append("Sources:\n" + "\n".join(f"- {r.label}" for r in slide.sources))
    return "\n\n".join(parts)


# ------------------------------------------------------------------ layouts
def lay_cover(scene: Scene, t: Theme, s: Slide, ctx: RenderContext, divider: bool = False) -> None:
    if t.motifs_on and t.cover_style != "template":
        return _zensar_cover(scene, t, s, ctx, divider)
    dark = t.cover_style == "solid_primary"
    C.add_background(scene, t, dark=dark)
    if t.cover_style == "template":
        scene.use_template_background = True
    W, H = t.slide_w, t.slide_h
    fg = "on_primary" if dark else t.title_color_role
    tx, tw = t.margin_x + 0.35, W * 0.72
    ty = H * (0.30 if not divider else 0.36)
    th = H * 0.28
    if t.accent_bar:
        scene.add(Shape("rect", t.margin_x, ty + 0.1, 0.09, th + (0.9 if s.subtitle else 0) - 0.2,
                        fill=t.c("on_primary" if dark else t.accent_bar_role), name="cover_accent"))
    size = t.sizes["cover_title"] * (0.8 if divider else 1.0)
    scene.add(C.text(t, tx, ty, tw, th, s.title, role=fg, size=size, font="heading", bold=t.heading_bold,
                     valign="bottom", min_size=22, name="title"))
    if s.subtitle:
        scene.add(C.text(t, tx, ty + th + 0.15, tw, 0.8, s.subtitle, role="on_primary" if dark else "text_secondary",
                         size=t.sizes["subtitle"], min_size=11, name="subtitle"))
    if not divider:
        doc = next((sl.sources[0].document_name for sl in ctx.plan.slides if sl.sources), "")
        basis = f"Based on: {doc}" if doc else ""
        if basis:
            scene.add(C.text(t, tx, H - t.margin_y - 0.45, tw, 0.35, basis, role="on_primary" if dark else "text_secondary",
                             size=t.sizes["caption"] + 1, font="caption", min_size=7, name="cover_basis"))
    C.chrome(scene, t, s.slide_number, ctx.total, [], dark=dark, cover=True)


def _zensar_cover(scene: Scene, t: Theme, s: Slide, ctx: RenderContext, divider: bool) -> None:
    """Brand cover: wordmark top-left, large regular-weight title, blue subtitle and a modular
    composition of the Z-motif primitives on the right (divider: indigo field, lighter modules)."""
    from backend.rendering.grid import ModularGrid
    from backend.rendering.motifs import ZensarModule, cover_composition

    W, H = t.slide_w, t.slide_h
    dark = divider
    scene.background = t.c("primary") if dark else t.c("background")
    cols = 3 if not divider else 2
    cell = W * (0.40 if not divider else 0.28) / cols
    rows = 4 if not divider else 3
    region = (W - cols * cell, H - rows * cell, cols * cell, rows * cell)
    img = ctx.image_path(s)
    if divider:
        scene.add(*ZensarModule(t, region, "divider", cols=cols))
    else:
        scene.add(*cover_composition(t, region))
        if img:  # a chosen image sits inside two grid modules of the composition
            g = ModularGrid.square(region, cols)
            x, y, w, h = g.cell(0, 0, 2, 2)
            scene.add(Picture(x, y, w, h, img, fit="cover", name="cover_image", anim="motif:img"))
    tx, tw = t.margin_x, W - region[2] - t.margin_x - 0.6
    ty, th = H * (0.26 if not divider else 0.32), H * 0.30
    fg = "on_primary" if dark else t.title_color_role
    title = C.text(t, tx, ty, tw, th, s.title, role=fg, size=t.sizes["cover_title"] * (0.85 if divider else 1.0),
                   font="heading", bold=t.heading_bold, valign="bottom", min_size=22, name="title")
    title.anim = "title"
    scene.add(title)
    if s.subtitle:
        sub = C.text(t, tx, ty + th + 0.2, tw, 0.9, s.subtitle, role="on_primary" if dark else t.subtitle_role,
                     size=t.sizes["subtitle"], min_size=11, name="subtitle")
        sub.anim = "title"
        scene.add(sub)
    if not divider:
        doc = next((sl.sources[0].document_name for sl in ctx.plan.slides if sl.sources), "")
        if doc:
            b = C.text(t, tx, H - t.margin_y - 0.4, tw, 0.32, f"Based on: {doc}", role="text_secondary",
                       size=t.sizes["caption"] + 1, font="caption", min_size=7, name="cover_basis")
            b.anim = "chrome"
            scene.add(b)
    C.chrome(scene, t, s.slide_number, ctx.total, [], dark=dark, cover=True)


def lay_section_divider(scene, t, s, ctx):
    lay_cover(scene, t, s, ctx, divider=True)


def _tag(s: Slide) -> str:
    """Section label for the top-right tag: the planner topic, else the main source section."""
    fixed = {"executive_summary": "Executive summary", "conclusion": "Conclusion", "references": "Sources"}
    if s.layout in fixed:
        return fixed[s.layout]
    if s.topic and s.topic not in ("overview", "sources"):
        return s.topic.replace("_", " ").title()
    if s.sources:
        sec = s.sources[0].section
        return (sec.split(" ", 1)[1] if sec[:1].isdigit() and " " in sec else sec)[:40]
    return ""


def _std(scene: Scene, t: Theme, s: Slide, ctx: RenderContext) -> tuple[float, float, float, float]:
    C.add_background(scene, t)
    if s.background_role:
        scene.background = t.c(s.background_role)
    top = C.title_block(scene, t, s.title, s.subtitle)
    C.chrome(scene, t, s.slide_number, ctx.total, s.sources, tag=_tag(s), extra_refs_line=ctx.image_credit(s))
    return C.content_region(t, top)


def lay_executive_summary(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.numbered_rows(t, (x, y, w * 0.92, h), s.key_points))


def lay_key_findings(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.numbered_cards(t, (x, y, w, h), s.key_points))


def lay_conclusion(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    pw = w * 0.34
    scene.add(C.card(t, x, y, pw, h, fill_role="primary", name="conclusion_panel"))
    scene.add(C.text(t, x + 0.35, y + 0.35, pw - 0.7, h - 0.7, "Key takeaways", role="on_primary", size=t.sizes["title"],
                     font="heading", bold=True, valign="middle", min_size=14, name="panel_label"))
    scene.add(C.bullets(t, (x + pw + t.gutter + 0.1, y + 0.1, w - pw - t.gutter - 0.1, h - 0.1), s.key_points,
                        size=t.sizes["body"] + 2))


def lay_two_column(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.column_cards(t, (x, y, w, h), s.columns[:2]))


def lay_three_column(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.column_cards(t, (x, y, w, h), s.columns[:3]))


def lay_comparison(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.column_cards(t, (x, y, w, h), s.columns[:2], header_band=True))


def _visual_into(scene: Scene, t: Theme, s: Slide, ctx: RenderContext, region) -> bool:
    v = s.visual
    if s.chart:
        scene.add(C.chart_element(t, region, s.chart))
        return True
    if v is None:
        return False
    if v.kind == "document_figure":
        p = ctx.figure_path(v.image_path)
        if p:
            scene.add(*C.figure_element(t, region, p, v.caption))
            return True
        return False
    if v.kind in ("architecture", "workflow", "knowledge_graph") and v.nodes:
        scene.add(*C.architecture_diagram(t, region, v))
        return True
    if v.kind in ("process",) and s.steps:
        scene.add(*C.process_diagram(t, region, s.steps))
        return True
    if v.kind == "timeline" and s.steps:
        scene.add(*C.timeline_diagram(t, region, s.steps))
        return True
    if v.kind == "kpi_cards" and s.kpis:
        scene.add(*C.kpi_cards(t, region, s.kpis, vertical=True))
        return True
    return False


def lay_text_image(scene, t, s, ctx, image_left: bool = False):
    x, y, w, h = _std(scene, t, s, ctx)
    tw = w * 0.42
    vw = w - tw - t.gutter
    tx, vx = (x + vw + t.gutter, x) if image_left else (x, x + tw + t.gutter)
    img = ctx.image_path(s)
    if img:  # a chosen/uploaded image takes the visual slot (user selection wins over generated visuals)
        scene.add(Picture(vx, y, vw, h, img, fit=_fit(s), name="slide_image", anim="build:image"))
        scene.add(C.bullets(t, (tx, y + 0.1, tw, h - 0.1), s.key_points))
    elif _visual_into(scene, t, s, ctx, (vx, y, vw, h)):
        scene.add(C.bullets(t, (tx, y + 0.1, tw, h - 0.1), s.key_points))
    else:
        scene.add(*C.numbered_cards(t, (x, y, w, h), s.key_points))


def lay_image_text(scene, t, s, ctx):
    lay_text_image(scene, t, s, ctx, image_left=True)


def lay_process(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.process_diagram(t, (x, y + 0.1, w, h - 0.1), s.steps))


def lay_timeline(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    scene.add(*C.timeline_diagram(t, (x, y, w, h), s.steps))


def lay_research_methodology(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    if s.key_points:
        ph = h * 0.64
        scene.add(*C.process_diagram(t, (x, y, w, ph), s.steps))
        scene.add(C.card(t, x, y + ph + 0.2, w, h - ph - 0.2, name="design_choices"))
        scene.add(C.bullets(t, (x + 0.3, y + ph + 0.35, w - 0.6, h - ph - 0.45), s.key_points, size=t.sizes["body"] - 1, min_size=10))
    else:
        scene.add(*C.process_diagram(t, (x, y + 0.1, w, h - 0.1), s.steps))


def lay_architecture(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    if s.visual and s.visual.nodes:
        dw = w * 0.64 if s.key_points else w
        scene.add(*C.architecture_diagram(t, (x, y, dw, h), s.visual))
        if s.key_points:
            scene.add(C.bullets(t, (x + dw + t.gutter, y, w - dw - t.gutter, h), s.key_points, size=t.sizes["body"] - 1, min_size=10))
    else:
        scene.add(*C.numbered_cards(t, (x, y, w, h), s.key_points))


def lay_workflow(scene, t, s, ctx):
    lay_process(scene, t, s, ctx)


def _fit(s: Slide) -> str:
    f = s.image.fit if s.image else "cover"
    return "contain" if f in ("contain", "original") else "cover"


def lay_kpi(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    kh = min(2.6, h * 0.55) if s.key_points else h * 0.7
    if t.motifs_on:
        # full-bleed brand panel with large white numerals (as in Zensar's report KPI pages)
        from backend.rendering.motifs import ZensarModule

        scene.add(Shape("rect", 0, y - 0.15, t.slide_w, kh + 0.3, fill=t.c("primary"), name="kpi_panel", anim="panel"))
        scene.add(*ZensarModule(t, (t.slide_w - 0.9, y - 0.15, 0.9, 0.9), "panel", cols=2))
        scene.add(*C.kpi_cards(t, (x, y, w - 0.8, kh), s.kpis, on_panel=True))
    else:
        scene.add(*C.kpi_cards(t, (x, y, w, kh), s.kpis))
    if s.key_points:
        scene.add(C.bullets(t, (x, y + kh + 0.35, w, h - kh - 0.35), s.key_points))


def lay_research_results(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    right_x = x
    if s.kpis:
        kw = w * 0.3
        scene.add(*C.kpi_cards(t, (x, y, kw, h), s.kpis[:3], vertical=True))
        right_x = x + kw + t.gutter
    rw = x + w - right_x
    if s.chart:
        ch = h * (0.68 if s.key_points else 1.0)
        scene.add(C.chart_element(t, (right_x, y, rw, ch), s.chart))
        if s.key_points:
            scene.add(C.bullets(t, (right_x, y + ch + 0.15, rw, h - ch - 0.15), s.key_points[:2], size=t.sizes["body"] - 2, min_size=10))
    elif s.key_points:
        scene.add(C.bullets(t, (right_x + 0.1, y + 0.1, rw - 0.1, h - 0.1), s.key_points))


def lay_chart(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    if s.chart is None:
        scene.add(C.bullets(t, (x, y, w, h), s.key_points))
        return
    cw = w * 0.62 if s.key_points else w
    scene.add(C.chart_element(t, (x, y, cw, h), s.chart))
    if s.key_points:
        px = x + cw + t.gutter
        scene.add(C.card(t, px, y, w - cw - t.gutter, h))
        scene.add(C.bullets(t, (px + 0.25, y + 0.3, w - cw - t.gutter - 0.5, h - 0.5), s.key_points,
                            size=t.sizes["body"] - 1, min_size=10))


def lay_table(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    if s.table is None:
        scene.add(C.bullets(t, (x, y, w, h), s.key_points))
        return
    th = h * (0.66 if s.key_points else 1.0)
    tbl = C.table_element(t, (x, y, w, th), s.table)
    scene.add(tbl)
    if s.key_points:
        by = y + tbl.h + 0.3
        scene.add(C.bullets(t, (x, by, w, y + h - by), s.key_points, size=t.sizes["body"] - 1, min_size=10))


def lay_quote(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    if not s.quote:
        return
    scene.add(C.text(t, x, y - 0.2, 1.2, 1.3, "“", role="accent", size=96, font="heading", bold=True, min_size=40, name="quote_mark"))
    scene.add(C.text(t, x + 1.0, y + 0.2, w - 2.0, h * 0.65, s.quote.text, role="text_primary", size=28, font="heading",
                     italic=True, valign="middle", min_size=16, name="quote"))
    if s.sources:
        scene.add(C.text(t, x + 1.0, y + h * 0.7 + 0.2, w - 2.0, 0.4, "— " + C.source_line(s.sources[:1]).replace("Source: ", ""),
                         role="text_secondary", size=t.sizes["body"] - 2, min_size=9, name="quote_source"))


def lay_references(scene, t, s, ctx):
    x, y, w, h = _std(scene, t, s, ctx)
    items = [p.text for p in s.key_points]
    doc = s.sources[0].document_name if s.sources else ""
    if doc:
        scene.add(C.text(t, x, y, w, 0.4, f"All content is drawn from: {doc}", role="text_secondary", size=t.sizes["body"] - 2,
                         min_size=9, name="references_intro"))
        y, h = y + 0.55, h - 0.55
    half = (len(items) + 1) // 2
    cw = (w - t.gutter) / 2
    for i, chunk in enumerate((items[:half], items[half:])):
        if chunk:
            scene.add(C.bullets(t, (x + i * (cw + t.gutter), y, cw, h), chunk, size=t.sizes["body"] - 2, min_size=9))


LAYOUT_FUNCS: dict[str, LayoutFn] = {
    "cover": lay_cover, "section_divider": lay_section_divider, "executive_summary": lay_executive_summary,
    "two_column": lay_two_column, "three_column": lay_three_column, "text_image": lay_text_image,
    "image_text": lay_image_text, "process": lay_process, "timeline": lay_timeline, "architecture": lay_architecture,
    "workflow": lay_workflow, "comparison": lay_comparison, "kpi": lay_kpi, "chart": lay_chart, "table": lay_table,
    "research_methodology": lay_research_methodology, "research_results": lay_research_results,
    "key_findings": lay_key_findings, "quote": lay_quote, "conclusion": lay_conclusion, "references": lay_references,
}


def build_slide_scene(slide: Slide, theme: Theme, ctx: RenderContext) -> Scene:
    if slide.accent_role in ("primary", "secondary") and slide.accent_role != theme.accent_bar_role:
        # per-slide accent override chosen in review - always a brand colour role, never a raw colour
        theme = replace(theme, accent_bar_role=slide.accent_role, bullet_color_role=slide.accent_role)
    scene = Scene(theme.slide_w, theme.slide_h, theme.c("background"), name=f"slide_{slide.slide_number:02d}")
    ctx.theme = theme
    LAYOUT_FUNCS.get(slide.layout, lay_key_findings)(scene, theme, slide, ctx)
    if slide.custom_shapes:
        back, front = custom_shape_elements(slide, theme)
        scene.elements = back + scene.elements + front
    for i, el in enumerate(scene.elements):
        if not el.anim:
            el.anim = f"build:{i}"
    scene.notes = _speaker_notes(slide)
    return scene


def custom_shape_elements(slide: Slide, t: Theme) -> tuple[list, list]:
    """User-added brand shapes (fractions of the slide -> inches), default colours from the theme."""
    from backend.rendering.motifs import ZensarGrid, ZensarModule
    from backend.rendering.scene import Line

    W, H = t.slide_w, t.slide_h
    back, front = [], []
    kinds = {"circle": "ellipse", "square": "rect", "triangle": "right_triangle", "quarter_circle": "quarter_circle",
             "diamond": "diamond", "pill": "pill", "frame": "rect"}
    for cs in slide.custom_shapes:
        x, y, w, h = cs.x * W, cs.y * H, cs.w * W, cs.h * H
        target = back if cs.layer == "back" else front
        if cs.kind in ("line", "connector"):
            target.append(Line(x, y, x + w, y + h, t.c(cs.stroke_role or cs.fill_role or "secondary"), max(cs.stroke_pt, 1.0),
                               arrow_end=cs.kind == "connector", name="custom_line", anim="custom"))
        elif cs.kind == "module":
            target += ZensarModule(t, (x, y, w, h), "corner", cols=2, anim_prefix="custom")
        elif cs.kind == "grid":
            target += ZensarGrid(t, (x, y, w, h), t.grid_module, cs.stroke_role or "border")
        else:
            fill = None if cs.kind == "frame" else t.c(cs.fill_role) if cs.fill_role else None
            line_role = cs.stroke_role or ("secondary" if cs.kind == "frame" else None)
            target.append(Shape(kinds[cs.kind], x, y, w, h, fill=fill, line=t.c(line_role) if line_role else None,
                                line_pt=cs.stroke_pt or (1.5 if cs.kind == "frame" else 0.0), opacity=cs.opacity,
                                rotation=cs.rotation, corner=cs.corner, name="custom_shape", anim="custom"))
    return back, front


# ------------------------------------------------------------------ standalone visuals
VISUAL_W, VISUAL_H = 13.333, 7.5


def visual_kind_for(slide: Slide) -> Optional[str]:
    if slide.layout in ("cover", "section_divider", "references"):
        return None
    if slide.chart:
        return "chart"
    if slide.visual and slide.visual.kind not in ("none",):
        if slide.visual.kind in ("architecture", "workflow") and not slide.visual.nodes:
            return None
        return slide.visual.kind
    if slide.table:
        return "table"
    if slide.columns:
        return "comparison" if slide.layout == "comparison" else "columns"
    if slide.key_points:
        return "key_points"
    return None


def build_visual_scene(slide: Slide, theme: Theme, ctx: RenderContext) -> Optional[Scene]:
    """A single infographic for the slide's main visual, independent of the slide layout."""
    kind = visual_kind_for(slide)
    if kind is None:
        return None
    t = theme
    W, H = VISUAL_W * t.slide_w / 13.333, VISUAL_H * t.slide_h / 7.5
    scene = Scene(W, H, t.c("background"), name=f"visual_{slide.slide_number:02d}")
    mx = t.margin_x
    scene.add(C.text(t, mx, 0.4, W - 2 * mx, 0.8, slide.title, role=t.title_color_role, size=t.sizes["title"],
                     font="heading", bold=t.heading_bold, valign="bottom", min_size=16, name="title"))
    if t.accent_bar:
        scene.add(Shape("rect", mx, 1.3, 0.8, 0.055, fill=t.c(t.accent_bar_role), name="accent_bar"))
    region = (mx, 1.65, W - 2 * mx, H - 1.65 - 0.75)
    x, y, w, h = region
    if kind == "chart" and slide.chart:
        scene.add(C.chart_element(t, region, slide.chart))
    elif kind == "table" and slide.table:
        scene.add(C.table_element(t, region, slide.table))
    elif kind in ("process",) and slide.steps:
        scene.add(*C.process_diagram(t, region, slide.steps))
    elif kind == "timeline" and slide.steps:
        scene.add(*C.timeline_diagram(t, region, slide.steps))
    elif kind == "kpi_cards" and slide.kpis:
        scene.add(*C.kpi_cards(t, (x, y + h * 0.15, w, h * 0.7), slide.kpis))
    elif kind in ("architecture", "workflow", "knowledge_graph") and slide.visual:
        scene.add(*C.architecture_diagram(t, region, slide.visual))
    elif kind == "document_figure" and slide.visual:
        p = ctx.figure_path(slide.visual.image_path)
        if not p:
            return None
        scene.add(*C.figure_element(t, region, p, slide.visual.caption))
    elif kind in ("comparison", "columns") and slide.columns:
        scene.add(*C.column_cards(t, region, slide.columns[:3], header_band=kind == "comparison"))
    elif kind == "key_points" and slide.key_points:
        scene.add(*C.numbered_cards(t, region, slide.key_points[:4]))
    else:
        return None
    if slide.sources:
        scene.add(C.text(t, mx, H - 0.55, W - 2 * mx - 1.8, 0.35, C.source_line(slide.sources), role="text_secondary",
                         size=t.sizes["caption"], font="caption", min_size=7, name="sources"))
    lg = C.logo_element(t)
    if lg:
        lg.x, lg.y = W - mx - lg.w, H - 0.2 - lg.h
        scene.add(lg)
    return scene


__all__ = ["RenderContext", "build_slide_scene", "build_visual_scene", "visual_kind_for", "Para"]
