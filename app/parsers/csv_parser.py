"""CSV parser: an invoice-grain / sales-operations CSV is a first-class
upload (like Excel). BOM-utf-8 and Windows-Arabic (cp1256) encodings are
both sniffed; the delimiter is detected per file (`,` `;` tab).

Output shape matches parse_excel: {"tables": [{"name": "CSV", "rows":
[[...], ...]}], "texts": []} — all cells are strings (the sales header
matcher and numeric parsers handle strings natively; financial analyses
of CSVs go through the same coercion the other parsers feed).
"""

from __future__ import annotations

import csv
from pathlib import Path

MAX_ROWS_PER_SHEET = 500


def _sniff_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # cp1256 covers Windows-Arabic exports; utf-16 leaves too many NULs to
    # be worth a full detection dance — try it first via BOM.
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1256"


def parse_csv(path: Path) -> dict:
    raw = path.read_bytes()
    encoding = _sniff_encoding(raw)
    text = raw.decode(encoding, errors="replace")

    sample = text[:64_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        # single-column or undecidable: default to comma
        class _D(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            escapechar = None
            lineterminator = "\r\n"
            quoting = csv.QUOTE_MINIMAL
        dialect = _D()

    rows = []
    reader = csv.reader(text.splitlines(), dialect)
    for row in reader:
        if any(c is not None and str(c).strip() for c in row):
            rows.append(row)
        if len(rows) >= MAX_ROWS_PER_SHEET:
            break
    return {"tables": [{"name": "CSV", "rows": rows}], "texts": []}
