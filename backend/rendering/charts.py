"""Brand-styled chart rendering with matplotlib (raster/SVG backends; PPTX uses native charts)."""
from __future__ import annotations

import io
import threading

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from backend.branding.fonts import resolve_font_path  # noqa: E402
from backend.rendering.scene import Chart  # noqa: E402

_lock = threading.Lock()  # pyplot is not thread-safe
_registered: set[str] = set()


def _font_name(family: str) -> str:
    path = resolve_font_path(family)
    if path and path not in _registered:
        try:
            font_manager.fontManager.addfont(path)
            _registered.add(path)
        except Exception:
            return "DejaVu Sans"
    try:
        return font_manager.FontProperties(fname=path).get_name() if path else "DejaVu Sans"
    except Exception:
        return "DejaVu Sans"


def fmt_value(v: float, unit: str) -> str:
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}" if abs(v) >= 10 else f"{v:,.2f}".rstrip("0").rstrip(".")
    return f"{s}{unit}" if unit in ("%", "x") else s


def _draw(ch: Chart, w_in: float, h_in: float, dpi: float):
    d = ch.data
    fam = _font_name(ch.font)
    fig, ax = plt.subplots(figsize=(w_in, h_in), dpi=dpi)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    base = max(9.0, min(13.0, h_in * 2.2))
    plt.rcParams["font.family"] = fam
    n_series = len(d.series)
    palette = ch.palette or ["#555555"]
    if d.chart_type == "pie":
        vals = d.series[0].values
        wedges, *_ = ax.pie(vals, labels=d.categories, colors=[palette[i % len(palette)] for i in range(len(vals))],
                            autopct=(lambda p: f"{p:.0f}%") if ch.data_labels else None, startangle=90,
                            textprops={"color": ch.text_color, "fontsize": base, "fontfamily": fam},
                            wedgeprops={"linewidth": 1, "edgecolor": "white"})
        ax.axis("equal")
    else:
        import numpy as np

        idx = np.arange(len(d.categories))
        width = 0.8 / max(1, n_series)
        horizontal = d.chart_type == "bar"
        for k, s in enumerate(d.series):
            color = palette[k % len(palette)]
            off = (k - (n_series - 1) / 2) * width
            if d.chart_type == "line":
                ax.plot(idx, s.values, marker="o", color=color, linewidth=2.5, label=s.name)
                bars = None
            elif horizontal:
                bars = ax.barh(idx + off, s.values, height=width * 0.92, color=color, label=s.name)
            else:
                bars = ax.bar(idx + off, s.values, width=width * 0.92, color=color, label=s.name)
            if ch.data_labels and bars is not None and len(d.categories) * n_series <= 24:
                ax.bar_label(bars, labels=[fmt_value(v, d.unit) for v in s.values], padding=3,
                             fontsize=base * 0.85, color=ch.text_color, fontfamily=fam)
        if horizontal:
            ax.set_yticks(idx, d.categories)
            ax.invert_yaxis()
        else:
            ax.set_xticks(idx, d.categories)
            if max(len(c) for c in d.categories) * len(d.categories) > w_in * 9:
                plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(ch.grid_color)
        ax.tick_params(colors=ch.text_color, labelsize=base)
        for lbl in ax.get_xticklabels() + ax.get_yticklabels():
            lbl.set_fontfamily(fam)
        if ch.gridlines:
            ax.grid(axis="x" if horizontal else "y", color=ch.grid_color, linewidth=0.8)
            ax.set_axisbelow(True)
        if n_series > 1:
            ax.legend(frameon=False, fontsize=base * 0.9, labelcolor=ch.text_color, loc="upper center",
                      bbox_to_anchor=(0.5, 1.12), ncol=min(n_series, 3), prop={"family": fam, "size": base * 0.9})
        elif d.series:
            (ax.set_xlabel if horizontal else ax.set_ylabel)(d.series[0].name, color=ch.text_color, fontsize=base, fontfamily=fam)
    fig.tight_layout()
    return fig


def chart_png(ch: Chart, px_w: int, px_h: int) -> bytes:
    """Render at the chart's real size in inches so font sizes match the slide typography."""
    with _lock:
        dpi = px_w / ch.w
        fig = _draw(ch, ch.w, ch.h, dpi)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, transparent=True)
        plt.close(fig)
    return buf.getvalue()


def chart_svg(ch: Chart, w_in: float, h_in: float) -> bytes:
    with _lock:
        fig = _draw(ch, w_in, h_in, 72)
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", transparent=True)
        plt.close(fig)
    return buf.getvalue()
