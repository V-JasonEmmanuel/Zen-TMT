"""Reusable, token-driven building blocks for slides and standalone visuals.

Every colour/font/size comes from the Theme; components never pick their own style.
Regions are (x, y, w, h) in inches.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from PIL import Image

from backend.branding.theme import Theme
from backend.rendering.scene import Chart, Line, Para, Picture, Scene, Shape, Table, TextBox, fit_text
from backend.schemas import KPI, ChartData, Claim, Column, SourceReference, Step, TableData, Visual

Region = tuple[float, float, float, float]


# ------------------------------------------------------------------ primitives
def text(theme: Theme, x, y, w, h, content: str | list[Para], *, role="text_primary", size=None, font="body",
         bold=False, align="left", valign="top", min_size=9.0, italic=False, name="") -> TextBox:
    fam = {"body": theme.body_font, "heading": theme.heading_font, "caption": theme.caption_font,
           "kpi": theme.kpi_font or theme.heading_font}[font]
    paras = content if isinstance(content, list) else [Para(t) for t in str(content).split("\n")]
    box = TextBox(x, y, w, h, paras, fam, size or theme.sizes["body"], theme.c(role), bold=bold, italic=italic,
                  align=align, valign=valign, min_size=min_size, bullet_color=theme.c(theme.bullet_color_role), name=name)
    return fit_text(box)


def card(theme: Theme, x, y, w, h, fill_role: Optional[str] = None, name="card") -> Shape:
    fill = theme.c(fill_role or theme.card_fill_role)
    border = theme.c(theme.card_border_role) if theme.card_border_role else None
    kind = "round_rect" if theme.card_radius > 0 else "rect"
    return Shape(kind, x, y, w, h, fill=fill, line=border, line_pt=theme.card_border_pt if border else 0.0,
                 radius=min(theme.card_radius, w / 4, h / 4), name=name)


def bullet_char(theme: Theme, i: int) -> str:
    return {"dot": "•", "square": "▪", "dash": "–", "number": f"{i + 1}."}.get(theme.bullet_style, "•")


def bullets(theme: Theme, region: Region, claims: Sequence[Claim] | Sequence[str], *, size=None, role="text_primary",
            min_size=11.0, name="bullets") -> TextBox:
    x, y, w, h = region
    items = [c.text if isinstance(c, Claim) else str(c) for c in claims]
    paras = [Para(t, bullet=bullet_char(theme, i), space_after=0.6) for i, t in enumerate(items)]
    return text(theme, x, y, w, h, paras, role=role, size=size or theme.sizes["body"], min_size=min_size, name=name)


# ------------------------------------------------------------------ slide chrome
def add_background(scene: Scene, theme: Theme, dark: bool = False) -> None:
    scene.background = theme.c("primary") if dark else theme.c("background")


def logo_element(theme: Theme, dark: bool = False, cover: bool = False) -> Optional[Picture]:
    path = (theme.logo_dark_path if dark and theme.logo_dark_path else theme.logo_path)
    if not path or theme.logo_position == "none" or theme.logo_show_on == "none":
        return None
    if (theme.logo_show_on == "cover" and not cover) or (theme.logo_show_on == "content" and cover):
        return None
    try:
        with Image.open(path) as im:
            ar = im.height / im.width
    except Exception:
        return None
    w = max(theme.logo_width, theme.logo_min_width)  # never below the brand's minimum size
    h = w * ar
    if h > 0.9:
        h, w = 0.9, 0.9 / ar
    mx, my = theme.margin_x, theme.margin_y
    x = theme.slide_w - mx - w if "right" in theme.logo_position else mx
    y = my if "top" in theme.logo_position else theme.slide_h - my * 0.6 - h
    pic = Picture(x, y, w, h, str(path), name="logo")
    pic.anim = "chrome"
    return pic


def logo_top_left(theme: Theme) -> bool:
    return bool(theme.logo_path) and theme.logo_position == "top_left" and theme.logo_show_on in ("all", "content")


def logo_height(theme: Theme) -> float:
    if not theme.logo_path:
        return 0.0
    try:
        with Image.open(theme.logo_path) as im:
            return max(theme.logo_width, theme.logo_min_width) * im.height / im.width
    except Exception:
        return 0.0


def source_line(refs: list[SourceReference], max_len: int = 150) -> str:
    if not refs:
        return ""
    doc = refs[0].document_name
    parts, seen = [], set()
    for r in refs:
        bits = []
        if r.page:
            bits.append(f"p.{r.page}" if not r.page_end or r.page_end == r.page else f"pp.{r.page}-{r.page_end}")
        sec = r.section.split(" ", 1)[1] if r.section[:1].isdigit() and " " in r.section else r.section
        if sec:
            bits.append(sec)
        if r.table:
            bits.append(f"Table {r.table}")
        if r.figure:
            bits.append(f"Fig. {r.figure}")
        key = " ".join(bits)
        if key and key not in seen:
            seen.add(key)
            parts.append(key)
    line = f"Source: {doc} — " + "; ".join(parts)
    return line if len(line) <= max_len else line[: max_len - 1].rsplit(";", 1)[0] + "; …"


def chrome(scene: Scene, theme: Theme, page: int, total: int, refs: list[SourceReference], *, dark=False,
           cover=False, show_sources=True, tag: str = "", extra_refs_line: str = "") -> None:
    from backend.rendering.motifs import corner_motif, section_tag

    W, H = theme.slide_w, theme.slide_h
    lg = logo_element(theme, dark=dark, cover=cover)
    if lg:
        scene.add(lg)
    if cover:
        return
    motif = theme.motifs_on and not dark
    if motif and theme.shapes and theme.shapes.section_tag and tag and theme.logo_position != "top_right":
        scene.add(*section_tag(theme, tag, W - theme.margin_x, theme.margin_y - 0.02))
    corner = 0.0
    if motif and theme.shapes and theme.shapes.density in ("subtle", "expressive"):
        scene.add(*corner_motif(theme, 0.62 if theme.shapes.density == "subtle" else 0.9))
        corner = 0.7
    fy = H - theme.footer_h + 0.08
    role = "on_primary" if dark else "text_secondary"
    right = []
    if theme.footer_text:
        right.append(theme.footer_text)
    if theme.show_page_numbers:
        right.append(str(page))
    right_txt = "   |   ".join(right)
    right_w = 3.2 if theme.footer_text else 0.8
    rx = W - theme.margin_x - right_w - corner
    if right_txt:
        scene.add(text(theme, rx, fy, right_w, 0.3, right_txt, role=role,
                       size=theme.sizes["caption"], font="caption", align="right", min_size=7, name="footer_right"))
    line = source_line(refs) if (show_sources and theme.show_sources and refs) else ""
    if extra_refs_line:
        line = f"{line}   |   {extra_refs_line}" if line else extra_refs_line
    if line:
        scene.add(text(theme, theme.margin_x, fy, rx - theme.margin_x - 0.3, 0.32, line,
                       role=role, size=theme.sizes["caption"], font="caption", min_size=7, name="sources"))
    for el in scene.elements:
        if el.name in ("sources", "footer_right") and not el.anim:
            el.anim = "chrome"


def title_block(scene: Scene, theme: Theme, title: str, subtitle: str = "") -> float:
    """Adds the slide title (+ optional subtitle / accent bar). Returns the y where content may start."""
    mx, my = theme.margin_x, theme.margin_y
    reserve = theme.logo_width + 0.3 if theme.logo_path and theme.logo_position == "top_right" and theme.logo_show_on in ("all", "content") else 0
    if theme.motifs_on and theme.shapes and theme.shapes.section_tag:
        reserve = max(reserve, 3.4)  # keep the title clear of the section tag
    top = my
    if logo_top_left(theme):
        top = my + logo_height(theme) + 0.22  # wordmark top-left, title below it (Zensar page structure)
    w = theme.slide_w - 2 * mx - reserve if top == my else theme.slide_w - 2 * mx
    align = theme.title_align
    tb = text(theme, mx, top, w, 0.85, title, role=theme.title_color_role, size=theme.sizes["title"], font="heading",
              bold=theme.heading_bold, align=align, valign="bottom" if not subtitle else "top", min_size=18, name="title")
    tb.anim = "title"
    scene.add(tb)
    y = top + 0.85
    if subtitle:
        st = text(theme, mx, y, w, 0.4, subtitle, role=theme.subtitle_role, size=theme.sizes["subtitle"] * 0.85,
                  min_size=11, align=align, name="subtitle")
        st.anim = "title"
        scene.add(st)
        y += 0.42
    if theme.accent_bar:
        bx = mx if align == "left" else (theme.slide_w - 0.8) / 2
        scene.add(Shape("rect", bx, y + 0.08, 0.8, 0.055, fill=theme.c(theme.accent_bar_role), name="accent_bar", anim="title"))
    return max(theme.content_top + (top - my), y + 0.35)


def content_region(theme: Theme, top: float) -> Region:
    x = theme.margin_x
    bottom = theme.slide_h - theme.footer_h - 0.15
    return (x, top, theme.slide_w - 2 * x, bottom - top)


# ------------------------------------------------------------------ composite components
def numbered_rows(theme: Theme, region: Region, claims: Sequence[Claim]) -> list:
    x, y, w, h = region
    n = max(1, len(claims))
    gap = 0.18
    row_h = min(1.15, (h - gap * (n - 1)) / n)
    els = []
    for i, c in enumerate(claims):
        ry = y + i * (row_h + gap)
        d = min(0.5, row_h * 0.7)
        els.append(Shape("ellipse", x, ry + (row_h - d) / 2, d, d, fill=theme.c("primary"), name="marker"))
        els.append(text(theme, x, ry + (row_h - d) / 2, d, d, str(i + 1), role="on_primary", size=d * 72 * 0.45,
                        font="heading", bold=True, align="center", valign="middle", min_size=8, name="marker_text"))
        els.append(text(theme, x + d + 0.25, ry, w - d - 0.25, row_h, c.text, size=theme.sizes["body"] + 2,
                        valign="middle", min_size=11, name="point"))
    return els


def numbered_cards(theme: Theme, region: Region, claims: Sequence[Claim]) -> list:
    x, y, w, h = region
    n = len(claims)
    if n == 0:
        return []
    cols = n if n <= 3 else 2
    rows = math.ceil(n / cols)
    g = theme.gutter
    cw, ch = (w - g * (cols - 1)) / cols, min(2.6, (h - g * (rows - 1)) / rows)
    els = []
    for i, c in enumerate(claims):
        cx, cy = x + (i % cols) * (cw + g), y + (i // cols) * (ch + g)
        els.append(card(theme, cx, cy, cw, ch))
        if theme.accent_bar:
            els.append(Shape("rect", cx, cy, cw, 0.06, fill=theme.c(theme.accent_bar_role), name="card_accent"))
        els.append(text(theme, cx + 0.25, cy + 0.2, 1.2, 0.55, f"{i + 1:02d}", role="secondary" if theme.motifs_on else "accent", size=26, font="heading",
                        bold=True, min_size=14, name="card_number"))
        els.append(text(theme, cx + 0.25, cy + 0.8, cw - 0.5, ch - 1.0, c.text, size=theme.sizes["body"], min_size=11, name="card_text"))
    return els


def column_cards(theme: Theme, region: Region, columns: Sequence[Column], header_band: bool = False) -> list:
    x, y, w, h = region
    n = max(1, len(columns))
    g = theme.gutter
    cw = (w - g * (n - 1)) / n
    roles = ["primary", "secondary", "accent"]
    els = []
    for i, col in enumerate(columns):
        cx = x + i * (cw + g)
        els.append(card(theme, cx, y, cw, h))
        if header_band:
            band_role = roles[i % 3]
            els.append(Shape("rect" if theme.card_radius == 0 else "round_rect", cx, y, cw, 0.75, fill=theme.c(band_role),
                             radius=min(theme.card_radius, 0.1), name="column_header_band"))
            els.append(text(theme, cx + 0.25, y + 0.08, cw - 0.5, 0.6, col.heading, role=f"on_{band_role}",
                            size=theme.sizes["heading"], font="heading", bold=True, valign="middle", min_size=11, name="column_heading"))
            top = y + 0.95
        else:
            els.append(text(theme, cx + 0.25, y + 0.22, cw - 0.5, 0.6, col.heading, role="primary",
                            size=theme.sizes["heading"], font="heading", bold=True, valign="middle", min_size=11, name="column_heading"))
            if theme.accent_bar:
                els.append(Shape("rect", cx + 0.25, y + 0.9, 0.5, 0.045, fill=theme.c(theme.accent_bar_role), name="column_rule"))
            top = y + 1.1
        els.append(bullets(theme, (cx + 0.25, top, cw - 0.5, y + h - top - 0.2), col.points,
                           size=theme.sizes["body"] - (1 if n == 3 else 0), min_size=10))
    return els


def process_diagram(theme: Theme, region: Region, steps: Sequence[Step]) -> list:
    x, y, w, h = region
    n = len(steps)
    if n == 0:
        return []
    g = 0.12
    sw = (w - g * (n - 1)) / n
    head_h = min(0.95, h * 0.3)
    els = []
    for i, s in enumerate(steps):
        sx = x + i * (sw + g)
        kind = "pentagon" if i == 0 else "chevron"
        role = "primary" if i % 2 == 0 else "secondary"
        els.append(Shape(kind, sx, y, sw + (0.18 if i < n - 1 else 0), head_h, fill=theme.c(role), name=f"step_{i + 1}"))
        els.append(text(theme, sx + 0.3, y + 0.06, sw - 0.45, head_h - 0.12, s.title, role=f"on_{role}",
                        size=theme.sizes["heading"] - 2, font="heading", bold=True, align="center", valign="middle", min_size=9,
                        name="step_title"))
        if s.description:
            els.append(text(theme, sx + 0.05, y + head_h + 0.25, sw - 0.1, h - head_h - 0.3, s.description,
                            size=theme.sizes["body"] - 2, align="left", min_size=9, name="step_desc"))
    return els


def timeline_diagram(theme: Theme, region: Region, steps: Sequence[Step]) -> list:
    x, y, w, h = region
    n = len(steps)
    if n == 0:
        return []
    ly = y + h * 0.36
    els: list = [Line(x, ly, x + w, ly, theme.c("text_secondary"), 2.0, name="timeline_axis")]
    seg = w / n
    for i, s in enumerate(steps):
        cx = x + seg * (i + 0.5)
        d = 0.28
        els.append(Shape("ellipse", cx - d / 2, ly - d / 2, d, d, fill=theme.c("primary" if i % 2 == 0 else "accent"),
                         line=theme.c("background"), line_pt=2, name="milestone"))
        els.append(text(theme, cx - seg / 2 + 0.08, y, seg - 0.16, ly - y - 0.3, s.title, role="primary",
                        size=theme.sizes["heading"], font="heading", bold=True, align="center", valign="bottom", min_size=10,
                        name="milestone_title"))
        if s.description:
            els.append(text(theme, cx - seg / 2 + 0.08, ly + 0.3, seg - 0.16, y + h - ly - 0.3, s.description,
                            size=theme.sizes["body"] - 2, align="center", min_size=9, name="milestone_desc"))
    return els


def kpi_cards(theme: Theme, region: Region, kpis: Sequence[KPI], vertical: bool = False, on_panel: bool = False) -> list:
    x, y, w, h = region
    n = len(kpis)
    if n == 0:
        return []
    g = theme.gutter * 0.8
    els = []
    for i, k in enumerate(kpis):
        if vertical:
            ch = (h - g * (n - 1)) / n
            cx, cy, cw = x, y + i * (ch + g), w
        else:
            cw = (w - g * (n - 1)) / n
            ch = min(h, 2.6)
            cx, cy = x + i * (cw + g), y
        if not on_panel:
            els.append(card(theme, cx, cy, cw, ch, name="kpi_card"))
        if theme.accent_bar and not on_panel:
            els.append(Shape("rect", cx, cy, 0.07 if vertical else cw, ch if vertical else 0.07,
                             fill=theme.c(theme.accent_bar_role), name="kpi_accent"))
        vh = ch * 0.52
        value = text(theme, cx + 0.2, cy + 0.12, cw - 0.4, vh, k.value, role="on_primary" if on_panel else "primary",
                     size=theme.sizes["kpi"] * (1.15 if on_panel else 1.0), font="kpi", bold=not on_panel,
                     align="left" if on_panel else "center", valign="bottom", min_size=16, name="kpi_value")
        label = text(theme, cx + 0.2, cy + 0.14 + vh, cw - 0.4, ch - vh - 0.24, k.label,
                     role="on_primary" if on_panel else "text_secondary", size=theme.sizes["body"] - 2,
                     align="left" if on_panel else "center", min_size=9, name="kpi_label")
        value.anim = label.anim = f"build:kpi{i}"
        els += [value, label]
    return els


def architecture_diagram(theme: Theme, region: Region, visual: Visual) -> list:
    x, y, w, h = region
    nodes = visual.nodes[:8]
    if not nodes:
        return []
    groups = list(dict.fromkeys(n.group for n in nodes if n.group))
    pos: dict[str, tuple[float, float, float, float]] = {}
    els: list = []
    if len(groups) >= 2:
        rows = [[n for n in nodes if n.group == g] for g in groups]
        ungrouped = [n for n in nodes if not n.group]
        if ungrouped:
            rows.append(ungrouped)
            groups.append("")
        rh = (h - 0.15 * (len(rows) - 1)) / len(rows)
        label_w = 1.5
        for r, (gname, row) in enumerate(zip(groups, rows)):
            ry = y + r * (rh + 0.15)
            els.append(Shape("rect", x, ry, w, rh, fill=theme.c("surface"), name="layer_band"))
            els.append(text(theme, x + 0.12, ry, label_w - 0.2, rh, gname, role="text_secondary", size=12, font="heading",
                            bold=True, valign="middle", min_size=8, name="layer_label"))
            nw = min(2.4, (w - label_w - 0.2 * (len(row) + 1)) / max(1, len(row)))
            nh = min(0.8, rh - 0.25)
            for i, nd in enumerate(row):
                pos[nd.id] = (x + label_w + 0.2 + i * (nw + 0.2), ry + (rh - nh) / 2, nw, nh)
    else:
        per_row = len(nodes) if len(nodes) <= 4 else math.ceil(len(nodes) / 2)
        nrows = math.ceil(len(nodes) / per_row)
        gx, gy = 0.55, 0.6
        nw = min(2.6, (w - gx * (per_row - 1)) / per_row)
        nh = min(1.0, (h - gy * (nrows - 1)) / nrows)
        total_h = nrows * nh + (nrows - 1) * gy
        oy = y + (h - total_h) / 2
        for i, nd in enumerate(nodes):
            r, c = divmod(i, per_row)
            row_count = min(per_row, len(nodes) - r * per_row)
            ox = x + (w - (row_count * nw + (row_count - 1) * gx)) / 2  # centre each row
            pos[nd.id] = (ox + c * (nw + gx), oy + r * (nh + gy), nw, nh)
    for e in visual.edges:
        if e.source in pos and e.target in pos:
            (x1, y1, w1, h1), (x2, y2, w2, h2) = pos[e.source], pos[e.target]
            c1, c2 = (x1 + w1 / 2, y1 + h1 / 2), (x2 + w2 / 2, y2 + h2 / 2)
            dx, dy = c2[0] - c1[0], c2[1] - c1[1]
            if abs(dx) >= abs(dy):
                p1 = (x1 + w1 if dx > 0 else x1, c1[1])
                p2 = (x2 if dx > 0 else x2 + w2, c2[1])
            else:
                p1 = (c1[0], y1 + h1 if dy > 0 else y1)
                p2 = (c2[0], y2 if dy > 0 else y2 + h2)
            els.append(Line(p1[0], p1[1], p2[0], p2[1], theme.c("text_secondary"), 1.5, arrow_end=True, name="connector"))
    for nd in nodes:
        if nd.id not in pos:
            continue
        nx, ny, nw, nh = pos[nd.id]
        els.append(Shape("round_rect" if theme.card_radius > 0 else "rect", nx, ny, nw, nh, fill=theme.c("primary"),
                         radius=min(0.12, nh / 4), name="node"))
        els.append(text(theme, nx + 0.1, ny + 0.05, nw - 0.2, nh - 0.1, nd.label, role="on_primary", size=14,
                        font="heading", bold=True, align="center", valign="middle", min_size=8, name="node_label"))
    return els


def chart_element(theme: Theme, region: Region, chart: ChartData) -> Chart:
    x, y, w, h = region
    return Chart(x, y, w, h, chart, theme.palette, theme.body_font, theme.c("text_primary"), theme.c("surface"),
                 gridlines=theme.chart_gridlines, data_labels=theme.chart_data_labels, name="chart")


def table_element(theme: Theme, region: Region, table: TableData) -> Table:
    x, y, w, h = region
    rows = len(table.rows) + 1
    size = 14 if rows <= 5 else 12 if rows <= 8 else 10
    return Table(x, y, w, min(h, rows * 0.48), table.headers, table.rows, theme.body_font, size,
                 theme.c(theme.table_header_fill_role), theme.c(theme.table_header_text_role), theme.c("text_primary"),
                 theme.c(theme.table_band_fill_role) if theme.table_band_fill_role else None,
                 theme.c(theme.table_border_role) if theme.table_border_role else None, name="table")


def figure_element(theme: Theme, region: Region, path: str, caption: str = "") -> list:
    x, y, w, h = region
    els: list = [card(theme, x, y, w, h, name="figure_frame")]
    cap_h = 0.4 if caption else 0
    els.append(Picture(x + 0.15, y + 0.15, w - 0.3, h - 0.3 - cap_h, path, name="figure"))
    if caption:
        els.append(text(theme, x + 0.15, y + h - cap_h - 0.08, w - 0.3, cap_h, caption, role="text_secondary",
                        size=theme.sizes["caption"] + 1, font="caption", align="center", min_size=7, name="figure_caption"))
    return els
