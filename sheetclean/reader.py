"""Read a messy spreadsheet (xlsx, xls, or csv) into a plain 2D grid of strings.

The grid is deliberately "dumb": no assumptions about where the header is,
what the columns mean, or which rows are data. That interpretation is left
to the LLM cleaning step. This module's only job is to faithfully surface
what is actually in the file, including resolving merged cells (a very
common source of "messiness" in real-world spreadsheets) so the model isn't
looking at a grid full of blanks where a merged label actually applies.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path

import openpyxl


@dataclass
class RawSheet:
    """A single sheet's raw contents plus a bit of provenance."""

    name: str
    grid: list[list[str]]
    n_rows: int
    n_cols: int

    def to_text(self, max_rows: int | None = None) -> str:
        """Render as a compact, row-numbered pipe-delimited block for prompting."""
        rows = self.grid if max_rows is None else self.grid[:max_rows]
        lines = []
        for i, row in enumerate(rows):
            lines.append(f"{i}\t" + " | ".join(row))
        return "\n".join(lines)


def _cell_to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_xlsx(path: Path, sheet_name: str | None) -> list[RawSheet]:
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet_names = [sheet_name] if sheet_name else wb.sheetnames
    sheets = []
    for name in sheet_names:
        ws = wb[name]
        n_rows = ws.max_row or 0
        n_cols = ws.max_column or 0
        grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
        for r in range(1, n_rows + 1):
            for c in range(1, n_cols + 1):
                grid[r - 1][c - 1] = _cell_to_str(ws.cell(row=r, column=c).value)

        # Resolve merged cells: fill every cell in the merged range with the
        # top-left value. This is the single biggest "messiness" fix that
        # pays for itself before the data ever reaches the model.
        for merged_range in ws.merged_cells.ranges:
            top_left = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
            fill_value = _cell_to_str(top_left.value)
            for r in range(merged_range.min_row, merged_range.max_row + 1):
                for c in range(merged_range.min_col, merged_range.max_col + 1):
                    if 1 <= r <= n_rows and 1 <= c <= n_cols:
                        grid[r - 1][c - 1] = fill_value

        # Trim fully-empty trailing rows/columns, which are common junk from
        # old exports and just waste tokens.
        while grid and all(cell == "" for cell in grid[-1]):
            grid.pop()
        while grid and all(row[-1] == "" for row in grid if row):
            for row in grid:
                row.pop()
            if not grid or not grid[0]:
                break

        sheets.append(RawSheet(name=name, grid=grid, n_rows=len(grid), n_cols=len(grid[0]) if grid else 0))
    return sheets


def _read_csv(path: Path) -> list[RawSheet]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        # Sniff the dialect since messy exports use ';', tab, etc.
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        grid = [[cell.strip() for cell in row] for row in reader]
    return [RawSheet(name="Sheet1", grid=grid, n_rows=len(grid), n_cols=max((len(r) for r in grid), default=0))]


def read_workbook(path: str | Path, sheet_name: str | None = None) -> list[RawSheet]:
    """Read a workbook (xlsx/xls/csv) into one RawSheet per sheet.

    Raises ValueError on an unsupported extension.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path, sheet_name)
    if suffix in (".csv", ".tsv", ".txt"):
        return _read_csv(path)
    raise ValueError(f"Unsupported file type: {suffix}. Supported: .xlsx, .xlsm, .csv, .tsv")
