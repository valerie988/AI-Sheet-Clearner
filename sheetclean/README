# sheetclean

Messy workbook in, clean structured table out — with a confidence value on every row the model was unsure about.

## What it does

`sheetclean` takes a messy `.xlsx`/`.xlsm`/`.csv` file — merged cells, mixed date formats, stray totals rows, blank spacer rows, inconsistent casing — and sends it to a Claude model with instructions to infer the real header, normalize dates/numbers/column names, and skip junk rows. The output is a plain CSV with the model's inferred columns plus a `confidence` column: blank for rows it read cleanly, a number (0.0–0.99) for rows it had to guess on (ambiguous date, garbled number, a value inferred from a merge).

## Install & run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-your-key-here
python3 -m sheetclean.cli messy_file.xlsx -o clean.csv --model claude-sonnet-5
```

Flags: `--model`, `--sheet "Sheet Name"`, `--chunk-rows N` (large sheets are split automatically, default 200 rows/call), `--quiet`.

## Cost comparison

Measured on a single 5-row fixture file (`tests/fixtures/messy_sales.xlsx` — merged title row, 4 different date formats, mixed casing, a stray totals row). Token counts are the tool's own reported usage per run; rates are Anthropic's published per-MTok pricing as of 2026-09-30.

| Model                     | Input tokens | Output tokens | Cost / file | Cost / 100 files | Rows flagged |
| ------------------------- | ------------ | ------------- | ----------- | ---------------- | ------------ |
| claude-haiku-4-5-20251001 | 685          | 324           | $0.0023     | **$0.23**        | 0/5          |
| claude-sonnet-5           | 923          | 684           | $0.0130     | **$1.30**        | 1/5          |
| claude-opus-5-5           | 925          | 760           | $0.0236     | **$2.36**        | 1/5          |

**Accuracy: pending.** This run checks that each model produces a parseable, well-formed table — it does not yet check correctness against a hand-verified answer. Before this table is final, run the same comparison across the full Level 1 evaluation set and add an Accuracy column scored against the gold answers (cell-level exact match is a reasonable starting metric). Rates for each model should also be reconfirmed at docs.claude.com/en/docs/about-claude/pricing before publishing, since they can change.

### Recommendation

Provisional, pending the accuracy column above: **Haiku 4.5** is ~5.6x cheaper than Sonnet 5 and ~10x cheaper than Opus 5.5 on this fixture, and still produced a well-formed table. If accuracy across the full eval set holds up at a similar level to Sonnet/Opus, Haiku is the better default with human review routed to any `confidence`-flagged row. If Haiku's accuracy drops materially on harder files in the real eval set, Sonnet 5 is the fallback — noticeably cheaper than Opus while still flagging its uncertain rows for review.

## Known limitations

- One call per chunk, no retry/backoff on malformed JSON or rate limits yet.
- Accuracy scoring against a gold answer set isn't wired up yet (see above).
- Very wide sheets with no stable header pattern may confuse column-name consistency across chunks.
