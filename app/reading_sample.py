"""Reading-sample inspector — show the user HOW their file was read.

The analysis is only trustworthy when the user can SEE what the parsers
did with their file: the detected tables, which columns were taken as
periods, which were excluded as change/total columns, and which rows were
rejected (and WHY). One instrumented pass over the parsed tables rebuilds
that picture with the EXACT predicates the metric extractor uses — the
sample never disagrees with the analysis.
"""

from __future__ import annotations

from pathlib import Path

from .analyzer import (_is_cash_flow_table, _is_equity_change_table,
                       _is_tb_table, _table_scope, _year_columns,
                       _change_columns, _classify_row, _is_summary_row)
from .parsers import parse_file
from .parsers.quality import score_extraction

_MAX_ROW_SAMPLES = 6
_MAX_SAMPLE_ROWS = 14


def _row_cells(row: list) -> list[str]:
    return ["" if c is None else str(c) for c in row]


def inspect_table(table: dict) -> dict:
    """Rebuild the extractor's view of ONE table."""
    rows = table.get("rows") or []
    cells = [_row_cells(r) for r in rows]
    year_cols = _year_columns(rows)
    change_cols = _change_columns(rows)
    if year_cols:
        change_cols |= _change_columns(rows, year_cols)
    scope = _table_scope(rows)
    kind = ("cash_flow" if _is_cash_flow_table(rows)
            else "equity" if _is_equity_change_table(rows)
            else "trial_balance" if _is_tb_table(rows)
            else {"income": "income_statement", "balance": "balance_sheet",
                  "mixed": "mixed", "none": "generic"}[scope])

    col_roles = {}
    width = max((len(r) for r in cells), default=0)
    for j in range(width):
        if j in year_cols:
            col_roles[j] = "period"
        elif j in change_cols:
            col_roles[j] = "excluded"
        elif j == 0:
            col_roles[j] = "label"
        else:
            col_roles[j] = "value"

    accepted: list[str] = []
    rejected: list[dict] = []
    for row in rows:
        raw = _row_cells(row)
        concepts = []
        for i, cell in enumerate(raw):
            c = _classify_row(str(cell))
            if c:
                concepts.append(c)
        if not concepts:
            rejected.append({"label": (raw[0] or "—")[:44], "reason": "no_concept"})
            continue
        label = next((raw[i] for i, c in enumerate(raw) if c), raw[0])
        if _is_summary_row(label, concepts[0]):
            rejected.append({"label": label[:44],
                             "reason": f"summary:{concepts[0]}"})
            continue
        money = [c for c in raw[1:]
                 if c and any(ch.isdigit() for ch in c)]
        if not money:
            rejected.append({"label": label[:44], "reason": "no_values"})
            continue
        accepted.append(label[:52])

    sample = [{"label": lb, "reason": "accepted"} for lb in accepted]
    shown = (sample[:_MAX_ROW_SAMPLES]
             + rejected[:_MAX_ROW_SAMPLES])
    shown = shown[:_MAX_SAMPLE_ROWS]
    return {
        "name": table.get("name") or "",
        "kind": kind,
        "rows_total": len(rows),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "columns": [
            {"index": j, "role": col_roles[j], "year": year_cols.get(j)}
            for j in sorted(col_roles)
        ],
        "rows": shown,
    }


def build_reading_sample(path: Path, sheet: str | None = None) -> dict:
    """Full reading picture for one stored file."""
    parsed = parse_file(path)
    tables = parsed.get("tables") or []
    if sheet:
        tables = [t for t in tables if t.get("name") == sheet] or tables
    inspected = [inspect_table(t) for t in tables[:12]]
    # Excel/Word parsers don't carry a cascade score (no multi-engine race)
    # — score their output here so the panel shows ONE quality number for
    # every file type
    quality = parsed.get("quality") or score_extraction(
        tables, parsed.get("texts") or [])
    return {
        "ocr_used": bool(parsed.get("ocr_used")),
        "quality": {
            "score": quality.get("score", 0.0),
            "labeled_rows": quality.get("labeled_rows", 0),
            "concepts": quality.get("concepts", []),
            "spine": quality.get("spine", False),
        },
        "tables_count": len(tables),
        "texts_count": len(parsed.get("texts") or []),
        "tables": inspected,
    }
