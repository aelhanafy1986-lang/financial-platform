"""Word (.docx) parser — grid-true table decomposition.

python-docx's ``row.cells`` repeats a MERGED cell's text at every grid
position the merge covers (horizontal ``w:gridSpan`` AND vertical
``w:vMerge`` continuation alike): a merged title lands three times in its
row and — the financially dangerous case — a merged amount lands in the
NEXT period's column as a phantom figure («600,000» for 2025 becomes a
fake 2024 reading), silently corrupting period series and trial-balance
totals. The decomposition below walks the raw ``w:tc`` elements instead
and emits each merged value exactly ONCE, at its anchor position; every
covered grid slot becomes "".
"""
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table as DocxTable

MAX_ROWS = 300


def _span_of(tc) -> int:
    """Grid columns covered by this cell (``w:gridSpan``, default 1)."""
    tcPr = tc.tcPr
    el = tcPr.find(qn("w:gridSpan")) if tcPr is not None else None
    if el is None:
        return 1
    try:
        return max(1, int(el.get(qn("w:val"))))
    except (TypeError, ValueError):
        return 1


def _vmerge_state(tc) -> str | None:
    """'restart' (merge anchor), 'continue' (slot covered by the cell
    above) or None (no vertical merge)."""
    tcPr = tc.tcPr
    el = tcPr.find(qn("w:vMerge")) if tcPr is not None else None
    if el is None:
        return None
    val = el.get(qn("w:val"))
    # <w:vMerge/> with no val means continue (OOXML default)
    return val if val == "restart" else "continue"


def _tc_text(tc) -> str:
    """Cell text = its DIRECT ``w:p`` paragraphs' ``w:t`` runs joined.

    Direct-children only: a nested table's paragraphs are not children of
    this ``w:tc``'s paragraphs, so nested-table text never leaks in.
    """
    parts = []
    for p in tc.findall(qn("w:p")):
        parts.append("".join(t.text or "" for t in p.iter(qn("w:t"))))
    return "\n".join(parts).strip()


def _decompose_table(table: DocxTable) -> list[list[str]]:
    """Rows on the PHYSICAL grid, each merged value placed exactly once.

    A ``gridSpan=n`` cell occupies n grid columns: its text sits at the
    anchor column and the covered columns are "". A ``vMerge`` continuation
    cell (Word emits one per covered row) is "" — the anchor row above
    already carries the value. Rows shorter than the widest row (writers
    that drop trailing tcs) are padded with "" so the grid stays
    rectangular for the row-wise consumers downstream.
    """
    tr_lst = table._tbl.tr_lst
    spans = [sum(_span_of(tc) for tc in tr.tc_lst) for tr in tr_lst]
    width = max(spans, default=0)
    rows: list[list[str]] = []
    for tr, row_span in zip(tr_lst, spans):
        row: list[str] = []
        for tc in tr.tc_lst:
            if _vmerge_state(tc) != "continue":
                row.append(_tc_text(tc))
                row.extend([""] * (_span_of(tc) - 1))
            else:
                row.extend([""] * _span_of(tc))
        rows.append(row + [""] * (width - row_span))
    return rows


def parse_word(path: Path) -> dict:
    doc = Document(str(path))
    tables = []
    texts = []

    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            texts.append(text)

    for i, table in enumerate(doc.tables, start=1):
        try:
            rows = _decompose_table(table)[:MAX_ROWS]
        except Exception:
            # never let an exotic table shape kill the whole document —
            # fall back to python-docx's (merge-repeating) view
            rows = [[cell.text.strip() for cell in row.cells]
                    for row in table.rows[:MAX_ROWS]]
        if rows:
            tables.append({"name": f"table_{i}", "rows": rows})

    return {"tables": tables, "texts": texts}
