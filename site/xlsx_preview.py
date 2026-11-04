"""Render sheets of the generated Excel pack to HTML, faithfully, for screenshots on the site.

Only formatting stored in the file is drawn: fonts, fills, number formats and the borders the
pack sets on subtotal and total rows. The pack hides gridlines, so the preview does too.

Usage:  python site/xlsx_preview.py <pack.xlsx> <out.html> "Summary,P&L"
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

from openpyxl import load_workbook


def fmt(value, number_format: str) -> str:
    if isinstance(value, (int, float)):
        if "%" in number_format:
            return f"{value:.1%}" if value >= 0 else f"({abs(value):.1%})"
        if number_format.startswith("0.0"):
            return f"{value:.1f}"
        if number_format.startswith("+"):
            return f"{value:+,.0f}"
        return f"{value:,.0f}" if value >= 0 else f"({abs(value):,.0f})"
    return html.escape(str(value)).replace("\n", "<br>") if value is not None else ""


def color(c) -> str | None:
    rgb = getattr(c, "rgb", None)
    return f"#{rgb[-6:]}" if isinstance(rgb, str) and len(rgb) >= 6 and rgb != "00000000" else None


def render_sheet(ws) -> str:
    merged: dict[tuple[int, int], int] = {}
    for rng in ws.merged_cells.ranges:
        merged[(rng.min_row, rng.min_col)] = rng.max_col - rng.min_col + 1
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                if (r, c) != (rng.min_row, rng.min_col):
                    merged[(r, c)] = 0
    # set_column(first, last, width) is stored once as a range (min..max); expand it per column
    width_of = {c: 9.0 for c in range(1, ws.max_column + 1)}
    for dim in ws.column_dimensions.values():
        if dim.width and dim.min and dim.max:
            for c in range(dim.min, min(dim.max, ws.max_column) + 1):
                width_of[c] = dim.width
    widths = [width_of[c] * 7.2 for c in range(1, ws.max_column + 1)]
    rows = []
    for r in range(1, ws.max_row + 1):
        height = ws.row_dimensions[r].height
        cells = []
        for c in range(1, ws.max_column + 1):
            span = merged.get((r, c), 1)
            if span == 0:
                continue
            cell = ws.cell(r, c)
            style = []
            if cell.font and cell.font.b:
                style.append("font-weight:700")
            if cell.font and cell.font.i:
                style.append("font-style:italic")
            if cell.font and cell.font.sz and cell.font.sz != 11:
                style.append(f"font-size:{cell.font.sz * 1.333:.0f}px")
            if cell.font and (fc := color(cell.font.color)):
                style.append(f"color:{fc}")
            if cell.fill and cell.fill.fill_type == "solid" and (bg := color(cell.fill.fgColor)):
                style.append(f"background:{bg}")
            if cell.border and cell.border.top and cell.border.top.style:
                style.append("border-top:1px solid #7f7f7f")
            if cell.border and cell.border.bottom and cell.border.bottom.style:
                style.append("border-bottom:3px double #7f7f7f" if cell.border.bottom.style == "double"
                             else "border-bottom:1px solid #7f7f7f")
            for side in ("left", "right"):
                b = getattr(cell.border, side, None)
                if b is not None and b.style:
                    style.append(f"border-{side}:1px solid #bfbfbf")
            wrap = bool(cell.alignment and cell.alignment.wrap_text) or span > 1
            style.append("white-space:normal" if wrap else "white-space:nowrap")
            value = cell.value
            # like Excel: text spills into the next cell only when that cell is empty
            neighbour = ws.cell(r, c + span).value if c + span <= ws.max_column else None
            if not wrap and isinstance(value, str) and neighbour is not None:
                style.append("overflow:hidden")
            numeric = isinstance(value, (int, float))
            # the pack colours variance columns with conditional formats; mirror that
            if numeric and ws.title in ("P&L", "Opex by department") and c in (4, 5, 8, 9) and r > 4 and value:
                style.append("color:#2E7D32" if value > 0 else "color:#C62828")
            style.append(f"text-align:{'right' if numeric else 'left'}")
            cells.append(f'<td colspan="{span}" style="{";".join(style)}">{fmt(value, cell.number_format)}</td>')
        tr_style = f' style="height:{height * 1.333:.0f}px"' if height else ""
        rows.append(f"<tr{tr_style}>{''.join(cells)}</tr>")
    cols = "".join(f'<col style="width:{w:.0f}px">' for w in widths)
    return (f'<div class="sheet"><div class="tab">{html.escape(ws.title)}</div>'
            f'<table style="width:{sum(widths):.0f}px"><colgroup>{cols}</colgroup>{"".join(rows)}</table></div>')


def main() -> None:
    src, out, names = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(",")
    wb = load_workbook(src)
    body = "".join(render_sheet(wb[n]) for n in names)
    out.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#e9eaec;font:14.5px Calibri,"Segoe UI",sans-serif;color:#0b0b0b}}
.sheet{{background:#ffffff;margin:16px;box-shadow:0 1px 4px rgba(0,0,0,.18);display:inline-block}}
.tab{{background:#217346;color:#fff;font-weight:600;padding:6px 14px;font-family:"Segoe UI",sans-serif}}
table{{border-collapse:collapse;table-layout:fixed;margin:10px 14px 16px}}
td{{padding:3px 7px;height:22px;vertical-align:middle;overflow:visible}}
</style></head><body>{body}</body></html>""", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
