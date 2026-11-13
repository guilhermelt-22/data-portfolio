"""Reads a supplier price list as it arrives: finds the header row, maps the columns and labels every row.

Supplier files rarely start at A1. There are title rows, category banners between blocks and notes at the
bottom, and the next file from the same supplier renames half the columns. Every row of the sheet gets a
kind (product, blank, title, banner or note) so nothing disappears without a trace.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import pandas as pd

from .config import COLUMN_ALIASES, REQUIRED

ALIAS = {alias: col for col, aliases in COLUMN_ALIASES.items() for alias in aliases}


@dataclass
class Layout:
    sheet: str
    header_row: int                 # 1-based, as Excel shows it
    mapped: dict[str, str]          # supplier header -> our column
    ignored: list[str] = field(default_factory=list)


def _norm_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def find_header(rows: list[tuple], max_scan: int = 25) -> int:
    """Index of the first row that names all the required columns."""
    for i, row in enumerate(rows[:max_scan]):
        cols = {ALIAS.get(_norm_header(v)) for v in row if v is not None}
        if all(c in cols for c in REQUIRED):
            return i
    raise ValueError(f"No header row with {', '.join(REQUIRED)} in the first {max_scan} rows")


def _kind(values: list) -> str:
    filled = [v for v in values if v not in (None, "") and str(v).strip()]
    if not filled:
        return "blank"
    if len(filled) == 1 and isinstance(filled[0], str):
        text = filled[0].strip()
        if "---" in text or (text.isupper() and len(text.split()) <= 3):
            return "banner"
        return "note"
    return "product"


def read_supplier(path: Path) -> tuple[pd.DataFrame, Layout]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    last_error = None
    for ws in wb.worksheets:
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        try:
            h = find_header(rows)
        except ValueError as e:
            last_error = e
            continue
        header = list(rows[h])
        mapped, ignored, positions = {}, [], {}
        for j, name in enumerate(header):
            col = ALIAS.get(_norm_header(name))
            if col and col not in positions:
                positions[col] = j
                mapped[str(name).strip()] = col
            elif name not in (None, ""):
                ignored.append(str(name).strip())
        records = []
        for i, row in enumerate(rows):
            if i == h:
                continue
            values = list(row) + [None] * (len(header) - len(row))
            kind = "title" if i < h else _kind(values)
            if kind == "title" and not any(v not in (None, "") for v in values):
                kind = "blank"
            rec = {"row": i + 1, "kind": kind}
            for col, j in positions.items():
                rec[col] = values[j]
            records.append(rec)
        df = pd.DataFrame(records)
        for col in COLUMN_ALIASES:
            if col not in df:
                df[col] = None
        wb.close()
        return df, Layout(ws.title, h + 1, mapped, ignored)
    wb.close()
    raise last_error or ValueError("Empty workbook")
