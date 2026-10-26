"""sheetclean: messy workbook in, clean structured table out.

Usage:
    sheetclean input.xlsx -o clean.csv --model claude-opus-5-5
    sheetclean input.xlsx --sheet "Q3 Data" --chunk-rows 150
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cleaner import clean_sheet, write_csv, DEFAULT_CHUNK_ROWS
from .llm import AnthropicClient
from .reader import read_workbook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheetclean",
        description="Turn a messy spreadsheet into a clean, structured table with per-row confidence.",
    )
    parser.add_argument("input", help="Path to the messy workbook (.xlsx, .xlsm, or .csv)")
    parser.add_argument(
        "-o", "--output",
        help="Output CSV path. Defaults to <input>.clean.csv (or <input>__<sheet>.clean.csv for multi-sheet files).",
    )
    parser.add_argument(
        "--model",
        default="claude-opus-5-5",
        help="Model to use (default: claude-opus-5-5).",
    )
    parser.add_argument("--sheet", help="Clean only this sheet name (default: all sheets).")
    parser.add_argument(
        "--chunk-rows",
        type=int,
        default=DEFAULT_CHUNK_ROWS,
        help=f"Rows per LLM call for large sheets (default: {DEFAULT_CHUNK_ROWS}).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress the per-file cost/row summary printed to stderr.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        sheets = read_workbook(input_path, sheet_name=args.sheet)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not sheets:
        print(f"error: sheet not found: {args.sheet}", file=sys.stderr)
        return 1

    client = AnthropicClient(model=args.model)

    for sheet in sheets:
        if args.output and len(sheets) == 1:
            out_path = Path(args.output)
        elif len(sheets) == 1:
            out_path = input_path.with_suffix("").with_name(input_path.stem + ".clean.csv")
        else:
            out_path = input_path.with_name(f"{input_path.stem}__{sheet.name}.clean.csv")

        table, usage = clean_sheet(sheet, client, chunk_rows=args.chunk_rows)
        write_csv(table, out_path)

        if not args.quiet:
            n_flagged = sum(1 for r in table.rows if r.confidence is not None)
            print(
                f"[{sheet.name}] {len(table.rows)} rows -> {out_path} "
                f"({n_flagged} flagged with confidence, {usage.input_tokens}in/{usage.output_tokens}out tokens)",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
