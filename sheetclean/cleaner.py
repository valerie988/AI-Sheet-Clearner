"""Turn a RawSheet into a clean table via an LLM, with per-row confidence.

Design notes
------------
* The model decides column names/types itself -- we don't hardcode a schema,
  since "messy workbook in" implies we don't know the shape in advance.
* Large sheets are processed in chunks so token cost stays roughly linear in
  file size instead of quadratic, and so a single sheet doesn't blow past a
  model's output-token limit. Every chunk is shown the sheet's first few rows
  again as header/context, and (after the first chunk) is told the exact
  column list to reuse, so chunks stay consistent with each other.
* Confidence is requested per row, not per cell: simpler to act on ("route
  this row to a human"), and it's what the brief asks for. The prompt asks
  the model to only attach a confidence score when it actually had to guess
  (ambiguous date, illegible/garbled value, inferred merge, reconciled
  conflicting totals, etc.) -- confident rows get no score, so the presence
  of a score is itself a signal, not just its magnitude.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .llm import LLMClient, Usage
from .reader import RawSheet

DEFAULT_CHUNK_ROWS = 200
CONTEXT_ROWS = 8  # rows always shown so the model can see header/structure

SYSTEM_PROMPT = """You clean messy spreadsheet data into a tidy, structured table.

You will be given a raw grid extracted from a spreadsheet (rows are numbered from 0; \
cells in a row are separated by " | "). It may have: a header row not in row 0, \
merged-cell artifacts, stray totals/notes rows, inconsistent date or number formats, \
blank rows used as visual spacing, or multiple tables stacked in one sheet.

Your job: infer the real column headers and emit one clean JSON record per genuine \
data row, skipping rows that are clearly not data (titles, section breaks, blank \
rows, footnotes, grand-total rows that duplicate a breakdown already present).

Normalize as you go: consistent date format (ISO 8601, YYYY-MM-DD), consistent \
number format (plain digits, no thousands separators or currency symbols -- put \
the unit/currency in the column name instead if it's not already implied), and \
consistent column names (short, snake_case).

For EVERY row, decide whether you had to guess at anything to produce it: an \
ambiguous date (e.g. 03/04/26 could be either order), a garbled or partially \
illegible number, a value inferred from a merged cell or from context rather \
than read directly, or a row you had to reconstruct from fragments. If so, \
attach a "confidence" field to that row: a number from 0.0 (pure guess) to \
0.99 (minor ambiguity). If you did NOT have to guess -- the row was read \
directly and unambiguously -- omit the "confidence" field entirely for that row.

Respond with ONLY a single JSON object, no prose before or after, no markdown \
code fences. Shape:

{"columns": ["col_a", "col_b", ...], "rows": [{"values": {"col_a": "...", "col_b": "..."}, "confidence": 0.6}, {"values": {"col_a": "...", "col_b": "..."}}]}

Every row's "values" object must have exactly the keys listed in "columns", in \
the same order, as strings (even for numbers/dates -- just normalize the format)."""


@dataclass
class CleanRow:
    values: dict[str, str]
    confidence: float | None = None


@dataclass
class CleanTable:
    columns: list[str]
    rows: list[CleanRow] = field(default_factory=list)


class CleaningError(ValueError):
    """Raised when the model's response can't be parsed as the expected JSON shape."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip ```json ... ``` fences if the model added them despite instructions.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab the widest {...} span and try again.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise CleaningError(f"No JSON object found in model response: {text[:200]!r}")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise CleaningError(f"Could not parse model response as JSON: {e}") from e


def _parse_table(payload: dict) -> CleanTable:
    if "columns" not in payload or "rows" not in payload:
        raise CleaningError(f"Response missing 'columns' or 'rows' key: {list(payload.keys())}")
    columns = payload["columns"]
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise CleaningError("'columns' must be a list of strings")

    rows = []
    for i, raw_row in enumerate(payload["rows"]):
        if "values" not in raw_row:
            raise CleaningError(f"Row {i} missing 'values' key")
        values = raw_row["values"]
        confidence = raw_row.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                raise CleaningError(f"Row {i} has non-numeric confidence: {confidence!r}")
        rows.append(CleanRow(values={str(k): "" if v is None else str(v) for k, v in values.items()}, confidence=confidence))
    return CleanTable(columns=columns, rows=rows)


def _chunk_row_ranges(n_rows: int, chunk_size: int) -> list[tuple[int, int]]:
    return [(start, min(start + chunk_size, n_rows)) for start in range(0, n_rows, chunk_size)]


def clean_sheet(
    sheet: RawSheet,
    client: LLMClient,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> tuple[CleanTable, Usage]:
    """Clean a whole sheet, chunking if it's larger than chunk_rows.

    Returns the merged CleanTable and the total token Usage across all calls.
    """
    if sheet.n_rows == 0:
        return CleanTable(columns=[]), Usage(0, 0)

    ranges = _chunk_row_ranges(sheet.n_rows, chunk_rows)
    total_usage = Usage(0, 0)
    merged = CleanTable(columns=[])

    for chunk_i, (start, end) in enumerate(ranges):
        header_context = ""
        if start > 0:
            context_rows = sheet.grid[: min(CONTEXT_ROWS, start)]
            header_context = (
                "\n\nFor reference, here are the first rows of this sheet (for header/context only -- "
                "do not re-emit these as data rows unless they also appear below):\n"
                + "\n".join(f"{i}\t" + " | ".join(r) for i, r in enumerate(context_rows))
            )

        column_pin = ""
        if merged.columns:
            column_pin = (
                "\n\nUse exactly this column list, in this order, to stay consistent with "
                f"earlier chunks of the same sheet: {json.dumps(merged.columns)}"
            )

        chunk_text = "\n".join(f"{start + j}\t" + " | ".join(row) for j, row in enumerate(sheet.grid[start:end]))
        user_prompt = (
            f"Sheet name: {sheet.name}\n"
            f"Rows {start}-{end - 1} of {sheet.n_rows} total (0-indexed):\n{chunk_text}"
            f"{header_context}{column_pin}"
        )

        text, usage = client.complete(SYSTEM_PROMPT, user_prompt)
        total_usage = Usage(
            total_usage.input_tokens + usage.input_tokens,
            total_usage.output_tokens + usage.output_tokens,
        )
        payload = _extract_json(text)
        table = _parse_table(payload)

        if not merged.columns:
            merged.columns = table.columns
        merged.rows.extend(table.rows)

    return merged, total_usage


def write_csv(table: CleanTable, output_path: str | Path) -> None:
    output_path = Path(output_path)
    fieldnames = [*table.columns, "confidence"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in table.rows:
            out = {col: row.values.get(col, "") for col in table.columns}
            out["confidence"] = "" if row.confidence is None else f"{row.confidence:.2f}"
            writer.writerow(out)
