# -*- coding: utf-8 -*-
"""Word tables with MERGED cells must decompose on the physical grid.

Regression: python-docx's ``row.cells`` repeats a merged cell's text at
EVERY grid position the merge covers — a merged title landed three times
in its row and, financially fatal, a merged amount leaked into the NEXT
period's column as a phantom figure (a «600,000» merged across the 2025+
2024 columns read as a fake 2024 balance), silently corrupting period
series and trial-balance totals.

Contract now (grid-true decomposition):
- a ``gridSpan=n`` cell emits its text ONCE at the anchor column; the
  covered columns are "" (never copies),
- a ``vMerge`` continuation row emits "" — the anchor row above already
  carries the value,
- nested-table text never leaks into the outer cell,
- rows are padded to the table's physical width (rectangular grid),
- plain (unmerged) tables read EXACTLY as before,
- end-to-end: an upload whose statements carry merged cells produces an
  analysis with no duplicated labels and no phantom period values.
"""

import io

from docx import Document
from fastapi.testclient import TestClient

from app.parsers.word import _decompose_table, parse_word

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")


def _merged_statements_doc(path) -> None:
    """Statements-style table: merged title row, merged section label
    (vertical), merged total amount (horizontal across the year columns)."""
    d = Document()
    d.add_heading("قائمة المركز المالي")
    t = d.add_table(rows=7, cols=3)
    t.style = "Table Grid"

    # row0: title merged across the 3 columns
    t.cell(0, 0).text = "قائمة المركز المالي"
    t.cell(0, 0).merge(t.cell(0, 2))
    # row1: plain header
    t.cell(1, 0).text = "البيان"
    t.cell(1, 1).text = "2025"
    t.cell(1, 2).text = "2024"
    # row2: plain data
    t.cell(2, 0).text = "النقدية"
    t.cell(2, 1).text = "120,000"
    t.cell(2, 2).text = "100,000"
    # rows 3-4: vertically merged section label
    t.cell(3, 0).text = "أصول ثابتة (مجموعة)"
    t.cell(3, 1).text = "500,000"
    t.cell(3, 2).text = "450,000"
    t.cell(3, 0).merge(t.cell(4, 0))
    t.cell(4, 1).text = "480,000"
    t.cell(4, 2).text = "430,000"
    # row5: total amount merged across BOTH year columns (the phantom trap)
    t.cell(5, 0).text = "الإجمالي"
    t.cell(5, 1).text = "600,000"
    t.cell(5, 1).merge(t.cell(5, 2))
    # row6: a revenue line so the quality gate has something real to read
    t.cell(6, 0).text = "الإيرادات"
    t.cell(6, 1).text = "700,000"
    t.cell(6, 2).text = "650,000"

    d.save(str(path))


# --------------------------------------------------------------- unit ----

def test_horizontal_span_emits_value_once(tmp_path):
    _merged_statements_doc(tmp_path / "m.docx")
    rows = parse_word(tmp_path / "m.docx")["tables"][0]["rows"]

    assert rows[0] == ["قائمة المركز المالي", "", ""]


def test_vertical_merge_continuation_is_blank(tmp_path):
    _merged_statements_doc(tmp_path / "m.docx")
    rows = parse_word(tmp_path / "m.docx")["tables"][0]["rows"]

    assert rows[3] == ["أصول ثابتة (مجموعة)", "500,000", "450,000"]
    assert rows[4] == ["", "480,000", "430,000"]


def test_merged_amount_never_becomes_phantom_period_value(tmp_path):
    """THE financially dangerous case: «600,000» merged across the 2025 and
    2024 columns must NOT read as a 2024 figure."""
    _merged_statements_doc(tmp_path / "m.docx")
    rows = parse_word(tmp_path / "m.docx")["tables"][0]["rows"]

    total_row = next(r for r in rows if r[0] == "الإجمالي")
    assert total_row == ["الإجمالي", "600,000", ""]


def test_rows_are_rectangular(tmp_path):
    _merged_statements_doc(tmp_path / "m.docx")
    rows = parse_word(tmp_path / "m.docx")["tables"][0]["rows"]

    assert all(len(r) == 3 for r in rows)


def test_plain_table_unchanged(tmp_path):
    """No merges → identical output to the classic row.cells reading."""
    d = Document()
    t = d.add_table(rows=3, cols=3)
    data = [["البيان", "2025", "2024"],
            ["النقدية", "120,000", "100,000"],
            ["الإيرادات", "700,000", "650,000"]]
    for r, row in enumerate(data):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    d.save(str(tmp_path / "plain.docx"))

    assert parse_word(tmp_path / "plain.docx")["tables"][0]["rows"] == data


def test_nested_table_text_does_not_leak(tmp_path):
    d = Document()
    outer = d.add_table(rows=1, cols=1)
    outer.cell(0, 0).text = "الخلايا الخارجية"
    inner = outer.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "999,999"
    d.save(str(tmp_path / "nested.docx"))

    rows = parse_word(tmp_path / "nested.docx")["tables"][0]["rows"]
    assert rows == [["الخلايا الخارجية"]]


def test_decompose_table_pad_uneven_writer(tmp_path):
    """A writer that drops trailing tcs on some rows still yields a
    rectangular grid (consumers index columns blindly)."""
    d = Document()
    d.add_table(rows=2, cols=3)
    d.save(str(tmp_path / "t.docx"))
    doc = Document(str(tmp_path / "t.docx"))
    tbl = doc.tables[0]
    # simulate a ragged writer: remove the last tc of the second row
    trs = tbl._tbl.tr_lst
    trs[1].remove(trs[1].tc_lst[-1])

    rows = _decompose_table(tbl)
    assert len(rows[0]) == len(rows[1]) == 3


# ---------------------------------------------------------- end-to-end ----

def test_upload_with_merged_cells_no_phantoms(client: TestClient, tmp_path):
    """THE regression at the API boundary: a statements docx full of merged
    cells uploads cleanly (quality gate passes on the decomposed grid) and
    the stored metrics carry the REAL figures — no phantom period value
    from the merged total, no duplicated merged label."""
    _merged_statements_doc(tmp_path / "merged.docx")
    data = (tmp_path / "merged.docx").read_bytes()

    resp = client.post(
        "/api/upload",
        files={"files": ("merged.docx", io.BytesIO(data), DOCX_MIME)},
        headers=client.auth_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["uploaded"][0]
    assert "error" not in item, item
    try:
        aid = item["id"]
        metrics = item["result"]["metrics"]
        # the balance-sheet lines read their two REAL period values
        # (ascending) — untouched by the merged rows around them. (The
        # revenue line is NOT captured: the merged title scopes the table
        # to the balance face — pre-existing _table_scope behaviour,
        # IDENTICAL under the old repeating parser, verified in
        # TEMP/scope_compare_probe.py.)
        assert metrics.get("cash") == [100_000.0, 120_000.0]
        assert metrics.get("revenue") is None
        # no phantom 600,000 anywhere in the stored metrics (the merged
        # total's 2024 slot stayed empty, so nothing was classified).
        # Under the OLD parser the merged «600,000» leaked into the 2024
        # column and the total row was read as a second assets line.
        assert 600_000.0 not in [v for vals in metrics.values()
                                 for v in (vals if isinstance(vals, list) else [vals])]

        # the reading-sample endpoint shows the parsed labels live: the
        # vertically-merged section label appears EXACTLY once (the old
        # parser repeated it on the continuation row)
        sample = client.get(f"/api/analyses/{aid}/reading-sample").json()
        labels = [r["label"] for t in sample["tables"]
                  for r in (t.get("rows") or [])]
        assert sum(1 for lb in labels
                   if "أصول ثابتة (مجموعة)" in lb) == 1
    finally:
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
