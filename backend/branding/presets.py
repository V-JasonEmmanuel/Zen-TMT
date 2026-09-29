"""Presentation templates: design presets layered on the brand tokens, plus uploaded PPTX templates.

Presets never introduce new colours - they only re-assign the brand's own roles (or use colours
measured from official brand material, e.g. the print indigo). Selecting a template changes the
look of PPTX, PDF, images and video consistently because all renderers share the Theme.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from backend.branding.theme import Theme

PRESETS: dict[str, dict[str, Any]] = {
    "zensar_corporate": {
        "name": "Zensar Corporate", "description": "White pages, wordmark top-left, section tags and a quiet Z-motif corner. The default.",
        "theme": {},
    },
    "zensar_bold": {
        "name": "Zensar Bold", "description": "Indigo title and divider slides, expressive modular shapes, strong KPI panels.",
        "theme": {"cover_style": "solid_primary"}, "shapes": {"density": "expressive"},
    },
    "zensar_minimal": {
        "name": "Zensar Minimal", "description": "No decorative shapes, generous whitespace, outline cards. For dense technical content.",
        "theme": {"card_fill_role": "background", "card_border_role": "border", "card_border_pt": 0.75},
        "shapes": {"density": "none", "section_tag": False},
    },
    "zensar_midnight": {
        "name": "Zensar Midnight", "description": "Dark deck on the brand indigo with light text - for events and screens.",
        "dark": True, "shapes": {"density": "subtle"},
    },
    "zensar_tech": {
        "name": "Zensar Tech", "description": "Blue accents and tinted cards; process and architecture visuals lead.",
        "theme": {"card_fill_role": "surface_alt", "bullet_color_role": "secondary", "accent_bar": True, "accent_bar_role": "secondary"},
        "shapes": {"density": "subtle"},
    },
}
# measured from Zensar's FY25 annual report (print indigo) - used for dark-deck surfaces
PRINT_INDIGO = "#211B5A"


def apply_preset(theme: Theme, preset_id: Optional[str]) -> Theme:
    spec = PRESETS.get(preset_id or "")
    if not spec or preset_id == "zensar_corporate":
        return theme
    t = replace(theme, colors=dict(theme.colors))
    for k, v in spec.get("theme", {}).items():
        setattr(t, k, v)
    if spec.get("shapes") and t.shapes is not None:
        t.shapes = t.shapes.model_copy(update=spec["shapes"])
    if spec.get("dark"):
        c = t.colors
        dark_bg = c["primary"]
        c.update({
            "background": dark_bg, "surface": PRINT_INDIGO, "surface_alt": c["secondary"],
            "text_primary": "#FFFFFF", "text_secondary": c.get("surface_alt") or "#D3E1F4", "border": c["secondary"],
            "primary": c["secondary"],  # indigo is now the canvas: blue carries emphasis
        })
        t.tints = [PRINT_INDIGO, c["secondary"], c["accent"]]
        t.dark_mode = True  # type: ignore[attr-defined]
        t.subtitle_role = "text_secondary"  # light text on the dark canvas (brand blue lacks contrast here)
        t.card_fill_role = "surface"
        # white wordmark on the dark canvas
        if t.logo_dark_path:
            t.logo_path = t.logo_dark_path
        t.palette = [c["secondary"], c["accent"], c.get("accent_2") or c["secondary"], "#FFFFFF"]
    t.preset_id = preset_id  # type: ignore[attr-defined]
    return t


def gallery() -> list[dict[str, str]]:
    return [{"id": k, "name": v["name"], "description": v["description"], "kind": "preset"} for k, v in PRESETS.items()]
