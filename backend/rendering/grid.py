"""Modular grid: 2x2, 3x3, 4x4, 6x6 modules and 12-column layouts.

Components occupy cells (optionally spanning several), so compositions stay aligned instead of
being placed at arbitrary coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class ModularGrid:
    x: float
    y: float
    w: float
    h: float
    cols: int
    rows: int
    gutter: float = 0.0

    @classmethod
    def module(cls, region: Rect, module: str = "3x3", gutter: float = 0.0) -> "ModularGrid":
        c, r = (int(v) for v in module.split("x"))
        return cls(*region, cols=c, rows=r, gutter=gutter)

    @classmethod
    def square(cls, region: Rect, cols: int, gutter: float = 0.0) -> "ModularGrid":
        """Square modules: rows follow from the region height (used for motif clusters)."""
        x, y, w, h = region
        size = (w - gutter * (cols - 1)) / cols
        rows = max(1, int((h + gutter) // (size + gutter)))
        return cls(x, y, w, rows * size + (rows - 1) * gutter, cols, rows, gutter)

    @property
    def cell_w(self) -> float:
        return (self.w - self.gutter * (self.cols - 1)) / self.cols

    @property
    def cell_h(self) -> float:
        return (self.h - self.gutter * (self.rows - 1)) / self.rows

    def cell(self, row: int, col: int, row_span: int = 1, col_span: int = 1) -> Rect:
        row, col = max(0, min(row, self.rows - 1)), max(0, min(col, self.cols - 1))
        row_span, col_span = min(row_span, self.rows - row), min(col_span, self.cols - col)
        return (self.x + col * (self.cell_w + self.gutter), self.y + row * (self.cell_h + self.gutter),
                col_span * self.cell_w + (col_span - 1) * self.gutter, row_span * self.cell_h + (row_span - 1) * self.gutter)

    def cells(self):
        for r in range(self.rows):
            for c in range(self.cols):
                yield r, c, self.cell(r, c)


def columns(region: Rect, n: int = 12, gutter: float = 0.3) -> ModularGrid:
    """12-column layout grid (single row)."""
    return ModularGrid(*region, cols=n, rows=1, gutter=gutter)


def span(grid: ModularGrid, start: int, count: int) -> Rect:
    return grid.cell(0, start, 1, count)
