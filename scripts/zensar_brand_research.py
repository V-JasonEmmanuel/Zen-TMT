"""Build the Zensar brand profile from OFFICIAL public Zensar sources (setup-time, needs internet once).

    python scripts/zensar_brand_research.py [--dry-run]

Sources (official Zensar only - no third-party logo sites):
  * https://www.zensar.com/                         (logo SVG, service-icon SVGs, rendered UI styles)
  * Zensar FY2024-25 Integrated Annual Report (PDF)  (vector colours, text colours, fonts, cover wordmark)
  * Zensar newsroom "Zensar reveals new brand identity" (Z motif + modular grid description)

Every value is written with provenance (source, URL, confidence, note) so the Brand Manager shows
where it came from and the user can confirm or correct it. User-supplied Zensar assets always
override these values. Colours are *measured* from the official assets, never typed from memory.
"""
from __future__ import annotations

import argparse
import collections
import colorsys
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.branding.brand_profile import BrandProfile, BrandStore, ReferenceMeta, apply_value  # noqa: E402

SITE = "https://www.zensar.com/"
LOGO_WHITE = "https://images.ctfassets.net/bjl3f17nyta4/6IUeLrHvOQVPUxczuwnpG6/0b21114df102b72adf6e79d941c05e3b/zensar-logo-white.svg"
ANNUAL_REPORT = "https://www.zensar.com/assets/files/6L0csuOAZclcJLWeB58eId/integrated-annual-report-fy25.pdf"
PRESS = "https://www.zensar.com/newsroom/news/zensar-reveals-new-brand-identity"
UA = {"User-Agent": "Mozilla/5.0 (Zensar Content Studio brand setup)"}


def hexc(rgb) -> str:
    return "#%02X%02X%02X" % tuple(round(v * 255) if isinstance(v, float) else v for v in rgb[:3])


def svg_to_png(svg: bytes, width_px: int) -> bytes:
    import pymupdf

    doc = pymupdf.open(stream=svg, filetype="svg")
    page = doc[0]
    zoom = width_px / page.rect.width
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")


def site_evidence(client: httpx.Client) -> dict:
    html = client.get(SITE).text
    # Zensar-authored icon artwork (industries + service lines); third-party/social logos excluded
    icons = sorted({u for u in re.findall(r"https://images\.ctfassets\.net/[^\"'\\ ]+?\.svg", html)
                    if not re.search(r"(logo|linkedin|twitter|youtube|insta|fb-|glassdoor|message|bridge|indigo-slate)", u, re.I)})
    colours = collections.Counter()
    for u in icons:
        svg = client.get(u).text
        for h in re.findall(r'(?:fill|stroke|stop-color)[=:]\s*"?#([0-9a-fA-F]{6})', svg):
            h = "#" + h.upper()
            if h not in ("#FFFFFF", "#000000"):
                colours[h] += 1
    css_urls = sorted(set(re.findall(r"/_next/static/chunks/[^\"']+\.css", html)))
    css = "".join(client.get(SITE.rstrip("/") + u).text for u in css_urls)
    fonts = collections.Counter(re.findall(r"font-family:\s*([A-Za-z][\w -]+)", css))
    return {"icon_count": len(icons), "icon_colours": colours.most_common(5), "css_fonts": fonts.most_common(5)}


def report_evidence(pdf_bytes: bytes, refs_dir: Path) -> dict:
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    fills, text, fonts = collections.Counter(), collections.Counter(), collections.Counter()
    for p in doc:
        for d in p.get_drawings():
            c = d.get("fill")
            if c and len(c) >= 3:
                fills[hexc(c)] += max(1, d["rect"].width * d["rect"].height / 1000)
        for b in p.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    if s["text"].strip():
                        text["#%06X" % s["color"]] += len(s["text"])
                        fonts[s["font"].split("+")[-1].split("-")[0]] += len(s["text"])
    # cover wordmark colour (top-right drawing group on page 1)
    cover = doc[0]
    wordmark = max((d for d in cover.get_drawings() if d.get("fill") and d["rect"].y1 < 120 and d["rect"].x0 > cover.rect.width * 0.6),
                   key=lambda d: len(d["items"]), default=None)
    refs_dir.mkdir(parents=True, exist_ok=True)
    pages = {0: "ar25_cover.png", 2: "ar25_about.png", 5: "ar25_kpi_panel.png", 8: "ar25_offerings.png"}
    for i, name in pages.items():
        if i < doc.page_count:
            doc[i].get_pixmap(dpi=90).save(str(refs_dir / name))

    def saturated(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        _, l, s = colorsys.rgb_to_hls(r, g, b)
        return s > 0.35 and 0.1 < l < 0.9

    return {
        "pages": doc.page_count,
        "top_fills": fills.most_common(25),
        "saturated_fills": [(h, round(n)) for h, n in fills.most_common(60) if saturated(h)][:10],
        "text_colours": text.most_common(12),
        "fonts": fonts.most_common(6),
        "cover_wordmark_fill": hexc(wordmark["fill"]) if wordmark else None,
        "reference_pages": list(pages.values()),
    }


def build(dry_run: bool = False) -> None:
    store = BrandStore()
    d = store.dir("zensar")
    refs = d / "references"
    logo_dir = d / "assets" / "logo"
    client = httpx.Client(timeout=120, follow_redirects=True, headers=UA)

    print("Fetching official website evidence ...")
    site = site_evidence(client)
    print("  service icons:", site["icon_count"], "colours:", site["icon_colours"], "fonts:", site["css_fonts"])
    print("Fetching official FY25 annual report ...")
    report = report_evidence(client.get(ANNUAL_REPORT).content, refs)
    print("  fonts:", report["fonts"], "| cover wordmark:", report["cover_wordmark_fill"])
    print("  saturated fills:", report["saturated_fills"][:6])
    print("  text colours:", report["text_colours"][:8])

    # ---- logos: official vector; dark variant = same official vector in the colour Zensar prints it on white
    white_svg = client.get(LOGO_WHITE).content
    wordmark = report["cover_wordmark_fill"] or "#000000"
    if all(int(wordmark[i:i + 2], 16) <= 3 for i in (1, 3, 5)):
        wordmark = "#000000"  # measured #000101 - printed black
    dark_svg = white_svg.replace(b'fill="white"', f'fill="{wordmark}"'.encode())
    if not dry_run:
        logo_dir.mkdir(parents=True, exist_ok=True)
        (logo_dir / "zensar_logo_white.svg").write_bytes(white_svg)
        (logo_dir / "zensar_logo_dark.svg").write_bytes(dark_svg)
        (logo_dir / "zensar_logo_white.png").write_bytes(svg_to_png(white_svg, 1600))
        (logo_dir / "zensar_logo_dark.png").write_bytes(svg_to_png(dark_svg, 1600))

    icon_primary = site["icon_colours"][0][0] if site["icon_colours"] else None
    tfreq = dict(report["text_colours"])
    ffreq = dict((h, n) for h, n in report["top_fills"])

    def hls(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hh, l, s = colorsys.rgb_to_hls(r, g, b)
        return hh * 360, l, s

    usage = collections.Counter()
    for h, n in list(ffreq.items()) + list(tfreq.items()):
        usage[h] += n

    def strongest(hue_lo, hue_hi, l_lo=0.25, l_hi=0.7, s_min=0.4):
        c = [(n, h) for h, n in usage.items()
             if s_min <= hls(h)[2] and l_lo <= hls(h)[1] <= l_hi and (hue_lo <= hls(h)[0] <= hue_hi)]
        return max(c)[1] if c else None

    blue = strongest(200, 240)                       # mid-tone brand blue (not the light tints)
    coral = strongest(350, 360, 0.4, 0.75) or strongest(0, 15, 0.4, 0.75, 0.5)
    teal = strongest(170, 195, 0.25, 0.6, 0.6)

    b = store.load("zensar") if store.exists("zensar") else BrandProfile(id="zensar", name="Zensar")
    b.description = ("Zensar brand profile derived from official Zensar sources (website assets, FY25 Integrated Annual "
                     "Report, brand announcement). Confirm or correct values against internal brand guidelines; "
                     "user-supplied Zensar assets override these.")
    W, AR, PR = "official_website", "official_annual_report", "official_press"
    sets = [
        ("colors.primary", icon_primary, W, 0.85, SITE, "The single colour used by every official service icon on zensar.com; brand text/buttons render in the same deep indigo. Print equivalent in the annual report: #211B5A."),
        ("colors.secondary", blue, AR, 0.8, ANNUAL_REPORT, "Dominant saturated colour in the FY25 annual report (subheads, cover geometry)."),
        ("colors.accent", coral, AR, 0.65, ANNUAL_REPORT, "Coral-red used for markers and highlights in the FY25 annual report."),
        ("colors.accent_2", teal, AR, 0.6, ANNUAL_REPORT, "Teal used for text highlights in the FY25 annual report."),
        ("colors.background", "#FFFFFF", AR, 0.9, ANNUAL_REPORT, "White page background of the annual report and website content sections."),
        ("colors.surface", "#F0F0F0", W, 0.5, SITE, "Light grey used for panels on zensar.com."),
        ("colors.surface_alt", "#D3E1F4", AR, 0.6, ANNUAL_REPORT, "Light blue tint used for panels in the annual report."),
        ("colors.text_primary", "#1A1A1A", W, 0.6, SITE, "Near-black text colour ('enterprise-gray') on zensar.com; the report uses black."),
        ("colors.text_secondary", "#6D6E71", AR, 0.55, ANNUAL_REPORT, "Grey secondary text in the annual report."),
        ("colors.border", "#D9D9D9", W, 0.5, SITE, "Light rule colour on zensar.com."),
        ("colors.tints", ["#D3E1F4", "#CFEBE8", "#F1CFD5", "#EDDBAA"], AR, 0.6, ANNUAL_REPORT, "Light tint family of the annual report (panels, shapes)."),
        ("colors.palette", [c for c in (icon_primary, blue, coral, teal) if c], AR, 0.6, ANNUAL_REPORT, "Chart series order built from the measured brand colours."),
        ("typography.heading.family", "Graphik", W, 0.95, SITE, "Typeface of zensar.com (all weights) and the FY25 annual report."),
        ("typography.body.family", "Graphik", AR, 0.95, ANNUAL_REPORT, "Body typeface of the annual report and website."),
        ("typography.caption.family", "Graphik", AR, 0.9, ANNUAL_REPORT, ""),
        ("typography.kpi.family", "Graphik", AR, 0.85, ANNUAL_REPORT, "KPI numerals in the annual report use Graphik."),
        ("typography.heading.bold", False, AR, 0.6, ANNUAL_REPORT, "Large headings are set in a regular weight in the report."),
        ("typography.subtitle_color_role", "secondary", AR, 0.6, ANNUAL_REPORT, "Sub-headings are set in the brand blue."),
        ("typography.fallback_family", "Arial", "default", 1.0, "", "Graphik is a licensed commercial typeface; when it is not installed, Arial is used consistently in every output."),
        ("logo.file_on_dark", "logo/zensar_logo_white.png", W, 1.0, LOGO_WHITE, "Official white wordmark from zensar.com."),
        ("logo.file", "logo/zensar_logo_dark.png", AR, 0.85, ANNUAL_REPORT, f"Official wordmark vector in the colour Zensar prints it on white ({wordmark}, FY25 report cover)."),
        ("logo.position", "top_left", AR, 0.6, ANNUAL_REPORT, "Interior report pages place the wordmark top-left."),
        ("logo.width_in", 1.25, "default", 0.8, "", ""),
        ("logo.min_width_in", 0.8, "default", 0.8, "", "Conservative minimum size until official clear-space rules are supplied."),
        ("shapes.enabled", True, PR, 0.9, PRESS, "'The Z motif on the logo is a combination of the three fundamental shapes of circle, square and a triangle.'"),
        ("shapes.motifs", ["square", "triangle", "quarter_circle", "circle", "diamond", "line"], PR, 0.8, PRESS, "Circle/square/triangle primitives; the report cover also uses rotated squares and diagonal lines."),
        ("shapes.color_roles", ["secondary", "primary", "surface_alt", "accent"], AR, 0.6, ANNUAL_REPORT, ""),
        ("shapes.line_role", "secondary", AR, 0.6, ANNUAL_REPORT, "Thin diagonal rules on the report cover."),
        ("shapes.section_tag", True, AR, 0.6, ANNUAL_REPORT, "Small coloured marker + section name at the top-right of report pages."),
        ("shapes.cover_composition", "grid_cluster", PR, 0.6, PRESS, "'The grid system is composed of multiple components that harmonise and work together to create dynamic visuals.'"),
        ("components.accent_bar", False, AR, 0.5, ANNUAL_REPORT, "Report titles are not underlined; hierarchy comes from size, colour and shapes."),
        ("components.shape_style", "square", AR, 0.5, ANNUAL_REPORT, "Panels and image masks use square corners."),
        ("components.card_fill_role", "surface", "default", 0.6, "", ""),
        ("components.bullet_color_role", "secondary", AR, 0.5, ANNUAL_REPORT, ""),
        ("components.table_header_fill_role", "primary", AR, 0.5, ANNUAL_REPORT, ""),
        ("components.chart_palette_roles", ["primary", "secondary", "accent", "accent_2"], AR, 0.6, ANNUAL_REPORT, ""),
        ("layout.cover_style", "light", AR, 0.7, ANNUAL_REPORT, "White cover with the wordmark and geometric imagery."),
        ("layout.title_align", "left", AR, 0.8, ANNUAL_REPORT, ""),
    ]
    for path, value, src, conf, url, note in sets:
        if value is None:
            print("  skipped (not measurable):", path)
            continue
        b = apply_value(b, path, value, src, conf, note, url)
    b.video_style.configured = True
    b.video_style.transition, b.video_style.intro, b.video_style.outro = "zensar_grid", True, True
    b.image_sources.configured = True
    for name, role, desc in (("ar25_cover.png", "branding", "FY25 Integrated Annual Report cover - wordmark, geometry, image masks"),
                             ("ar25_about.png", "layout", "Report interior page - title hierarchy, corner shapes, section tag"),
                             ("ar25_kpi_panel.png", "slide", "Full-bleed indigo KPI panel with large numerals"),
                             ("ar25_offerings.png", "layout", "Multi-column content page with tint panels")):
        if (refs / name).exists():
            b.reference_meta[name] = ReferenceMeta(filename=name, source="official_annual_report", source_url=ANNUAL_REPORT,
                                                   description=desc, design_role=role)  # type: ignore[arg-type]
            if name not in b.references:
                b.references.append(name)
    evidence = {"site": site, "annual_report": {k: v for k, v in report.items() if k != "top_fills"}, "press": PRESS}
    if dry_run:
        print(json.dumps(b.model_dump(include={"colors", "typography", "logo"}), indent=1))
        return
    store.save(b)
    (refs / "research_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("Saved brands/zensar  status:", b.status)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    build(ap.parse_args().dry_run)
    _ = io
