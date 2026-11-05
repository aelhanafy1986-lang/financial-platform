# -*- coding: utf-8 -*-
"""A Microsoft-style statements document must produce HONEST statements.

The real annual-report shape (income 3 years + balance sheet 2 years + cash
flows whose «Accounts receivable (10,581)» lines are CHANGES) produced a
report whose balance sheet face read «المدينون -4,087 / غير متوازنة
(الفرق -207,589)» — cash-flow deltas captured as balances, «Total liabilities
and stockholders' equity» captured as equity, year headers missed because
they sit under Word lead-in rows, and ✓/✗ glyphs the Arabic font lacks
rendering as \x00 boxes. Contract now:
- cash-flow change rows never feed the balance-sheet concepts,
- «Total liabilities and … equity» never doubles into equity,
- period labels are found under lead-in rows (duplicated merged cells too),
- balance-sheet series align to the LATEST periods (fewer columns than the
  income statement is normal),
- restated lines («Net income» in 4 statements) don't multiply the series,
- the PDF report carries no unmappable-glyph boxes.
"""

import io

from fastapi.testclient import TestClient

from app.analyzer import _extract_metrics, _extract_period_labels

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")


def _ms_rows(header, data):
    """Microsoft layout: lead-in rows, a duplicated-cells year header, and
    «$»-prefixed value columns separated by empty spacer cells."""
    rows = [["(In millions)", "", "", "", "", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", "", "", "", "", ""]]
    rows.append(header)
    rows.append([""] * 12)
    for label, v1, v2, v3 in data:
        rows.append([label, "", "$", v1, "", "", "$", v2, "", "", "$", v3])
    return rows


def _make_ms_docx(path) -> bytes:
    """Word tables mirroring the real document: income (3y), balance sheet
    (2y), cash flows with change rows — the shape that broke the report."""
    import docx

    header = ["Year Ended June\xa030,", "", "2025", "2025", "", "",
              "2024", "2024", "", "", "2023", "2023"]
    income = _ms_rows(header, [
        ("Revenue:", "281,724", "245,122", "211,915"),
        ("Total cost of revenue", "87,831", "74,114", "65,863"),
        ("Gross margin", "193,893", "171,008", "146,052"),
        ("Sales and marketing", "65,365", "61,575", "57,529"),
        ("Operating income", "128,528", "109,433", "88,523"),
        ("Other income (expense), net", "(4,901)", "(1,646)", "788"),
        ("Provision for income taxes", "21,795", "19,651", "16,950"),
        ("Net income", "101,832", "88,136", "72,361"),
    ])
    balance = _ms_rows(
        ["June\xa030,", "", "2025", "2025", "", "", "2024", "2024",
         "", "", "", ""], [
        ("Cash and cash equivalents", "94,565", "75,543", ""),
        ("Accounts receivable, net", "69,905", "56,924", ""),
        ("Total assets", "619,003", "512,163", ""),
        ("Accounts payable", "27,724", "21,996", ""),
        ("Total liabilities", "275,524", "243,686", ""),
        ("Total stockholders' equity", "343,479", "268,477", ""),
        ("Total liabilities and stockholders' equity",
         "619,003", "512,163", ""),
    ])
    cashflow = _ms_rows(header, [
        ("Net income", "101,832", "88,136", "72,361"),
        ("Accounts receivable", "(10,581)", "(7,191)", "(4,087)"),
        ("Accounts payable", "569", "3,545", "(2,721)"),
        ("Net cash from operations", "136,162", "118,548", "89,435"),
        ("Net cash used in investing", "(72,599)", "(55,664)", "(39,442)"),
        ("Net cash used in financing", "(51,699)", "(38,455)", "(27,222)"),
        ("Effect of foreign exchange rates on cash", "7,158", "4,158", "3,354"),
    ])
    d = docx.Document()
    d.add_heading("القوائم المالية")
    for rows in (income, balance, cashflow):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                t.cell(r, c).text = str(val)
    d.save(str(path))
    return path.read_bytes()


# --------------------------------------------------------------- unit ----

def test_cash_flow_change_rows_never_pollute_balances():
    """«Accounts receivable (10,581)» inside a cash-flow statement is a
    CHANGE, not a balance — it must not enter the receivables series."""
    cf_rows = _ms_rows(
        ["Year Ended June\xa030,", "", "2025", "2025", "", "",
         "2024", "2024", "", "", "2023", "2023"], [
        ("Net income", "101,832", "88,136", "72,361"),
        ("Accounts receivable", "(10,581)", "(7,191)", "(4,087)"),
        ("Accounts payable", "569", "3,545", "(2,721)"),
        ("Net cash from operations", "136,162", "118,548", "89,435"),
        ("Net cash used in investing", "(72,599)", "(55,664)", "(39,442)"),
    ])
    m = _extract_metrics([{"name": "cf", "rows": cf_rows}], [])
    assert "receivables" not in m
    assert "payables" not in m
    # the net anchor itself is legitimate
    assert 101_832.0 in (m.get("net_profit") or [])


def test_total_liabilities_and_equity_not_equity():
    """The closing BS line «Total liabilities and stockholders' equity» IS
    total assets — it must never double into the equity series."""
    rows = [
        ["June 30,", "", "2025", "2024"],
        ["Total assets", "", "619,003", "512,163"],
        ["Total liabilities", "", "275,524", "243,686"],
        ["Total stockholders' equity", "", "343,479", "268,477"],
        ["Total liabilities and stockholders' equity", "",
         "619,003", "512,163"],
    ]
    m = _extract_metrics([{"name": "bs", "rows": rows}], [])
    assert m["assets"] == [512_163.0, 619_003.0]
    assert 619_003.0 not in m["equity"]
    assert 512_163.0 not in m["equity"]
    assert m["equity"] == [268_477.0, 343_479.0]


def test_stated_cash_flow_totals_captured():
    """«Net cash from operations / investing / financing» are the file's own
    cash-flow section totals — captured as cf_* concepts (year-ascending,
    parens negative) and NEVER into the cash balance series."""
    cf_rows = _ms_rows(
        ["Year Ended June\xa030,", "", "2025", "2025", "", "",
         "2024", "2024", "", "", "2023", "2023"], [
        ("Net cash from operations", "136,162", "118,548", "89,435"),
        ("Net cash used in investing", "(72,599)", "(55,664)", "(39,442)"),
        ("Net cash used in financing", "(51,699)", "(38,455)", "(27,222)"),
    ])
    m = _extract_metrics([{"name": "cf", "rows": cf_rows}], [])
    assert m["cf_operating"] == [89_435.0, 118_548.0, 136_162.0]
    assert m["cf_investing"] == [-39_442.0, -55_664.0, -72_599.0]
    assert m["cf_financing"] == [-27_222.0, -38_455.0, -51_699.0]
    assert "cash" not in m  # «Net cash…» must not become a cash balance


def test_stated_net_change_and_closing_cash_captured():
    """The CF statement's own reconciliation anchors — «Net change in cash
    and cash equivalents» and «Cash and cash equivalents, end of period» —
    are captured as cf_* concepts (never into the cash balance), and the
    «beginning of period» line stays blocked."""
    cf_rows = _ms_rows(
        ["Year Ended June\xa030,", "", "2025", "2025", "", "",
         "2024", "2024", "", "", "2023", "2023"], [
        ("Net income", "101,832", "88,136", "72,361"),
        ("Net cash from operations", "136,162", "118,548", "87,582"),
        ("Net cash used in investing", "(72,599)", "(96,970)", "(22,680)"),
        ("Net cash used in financing", "(51,699)", "(37,757)", "(43,935)"),
        ("Effect of foreign exchange rates on cash", "63", "(210)", "(194)"),
        ("Net change in cash and cash equivalents", "11,927", "(16,389)",
         "20,773"),
        ("Cash and cash equivalents, beginning of period",
         "18,315", "34,704", "13,931"),
        ("Cash and cash equivalents, end of period", "30,242", "18,315",
         "34,704"),
    ])
    m = _extract_metrics([{"name": "cf", "rows": cf_rows}], [])
    assert m["cf_net_change"] == [20_773.0, -16_389.0, 11_927.0]
    assert m["cf_cash_end"] == [34_704.0, 18_315.0, 30_242.0]
    assert "cash" not in m  # the closing/beginning lines are not balances


def test_bs_cash_with_investments_reconciles_via_stated_net_change():
    """REAL-FILE SHAPE (analysis 29): the balance sheet's cash line is
    «Total cash, cash equivalents, and short-term investments» — a WIDER
    measure than the cash-flow statement reconciles against (94,565 -
    75,543 = 19,022 ≠ 11,927). The face must verify against the file's own
    stated «Net change in cash» and show the CF's own closing cash."""
    from app.statements import build_statements_from_metrics

    metrics = {
        "revenue": [211_915.0, 245_122.0, 281_724.0],
        "cogs": [65_863.0, 74_114.0, 87_831.0],
        # BS: total cash + short-term investments (2 columns only)
        "cash": [75_543.0, 94_565.0],
        "cf_operating": [87_582.0, 118_548.0, 136_162.0],
        "cf_investing": [-22_680.0, -96_970.0, -72_599.0],
        "cf_financing": [-43_935.0, -37_757.0, -51_699.0],
        "cf_other": [-194.0, -210.0, 63.0],
        "cf_net_change": [20_773.0, -16_389.0, 11_927.0],
        "cf_cash_end": [34_704.0, 18_315.0, 30_242.0],
    }
    st = build_statements_from_metrics(metrics, ["2023", "2024", "2025"])
    assert st is not None
    cf = st["periods"][2]["cash_flow"]
    assert cf["net_change"] == 11_927.0
    # the BS-cash delta would LIE here (19,022) — the stated anchor wins
    assert cf["reconciles"] is True
    # the face's closing cash is the CF statement's own figure, not the BS
    # total-including-investments
    assert cf["cash_balance"] == 30_242.0
    # earlier periods reconcile against their own stated lines too
    assert st["periods"][0]["cash_flow"]["reconciles"] is True
    assert st["periods"][1]["cash_flow"]["reconciles"] is True


def test_fx_effect_captured_and_face_reconciles():
    """«Effect of foreign exchange rates on cash» closes the gap between the
    stated activities and the actual cash movement — the derived face must
    carry it and RECONCILE with the real cash delta."""
    from app.statements import build_statements_from_metrics

    cf_rows = _ms_rows(
        ["Year Ended June\xa030,", "", "2025", "2025", "", "",
         "2024", "2024", "", "", "2023", "2023"], [
        ("Net cash from operations", "136,162", "118,548", "89,435"),
        ("Net cash used in investing", "(72,599)", "(55,664)", "(39,442)"),
        ("Net cash used in financing", "(51,699)", "(38,455)", "(27,222)"),
        ("Effect of foreign exchange rates on cash", "7,158", "4,158", "3,354"),
    ])
    m = _extract_metrics([{"name": "cf", "rows": cf_rows}], [])
    assert m["cf_other"] == [3_354.0, 4_158.0, 7_158.0]

    metrics = {
        "revenue": [211_915.0, 245_122.0, 281_724.0],
        "cogs": [65_863.0, 74_114.0, 87_831.0],
        "cash": [75_543.0, 94_565.0],
        "cf_operating": [89_435.0, 118_548.0, 136_162.0],
        "cf_investing": [-39_442.0, -55_664.0, -72_599.0],
        "cf_financing": [-27_222.0, -38_455.0, -51_699.0],
        "cf_other": [3_354.0, 4_158.0, 7_158.0],
    }
    st = build_statements_from_metrics(metrics, ["2023", "2024", "2025"])
    cf = st["periods"][2]["cash_flow"]
    assert cf["other"]["total"] == 7_158.0
    # 136,162 - 72,599 - 51,699 + 7,158 = 19,022 = 94,565 - 75,543 ✓
    assert cf["net_change"] == 19_022.0
    assert cf["reconciles"] is True


def test_builder_uses_stated_cash_flow_totals():
    """When the file states its activity totals the derived cash-flow face
    carries them verbatim (net change = their sum); without them the old
    balance-delta composition still applies."""
    from app.statements import build_statements_from_metrics

    metrics = {
        "revenue": [211_915.0, 245_122.0, 281_724.0],
        "cogs": [65_863.0, 74_114.0, 87_831.0],
        "opex": [57_529.0, 61_575.0, 65_365.0],
        "investment_income": [788.0, -1_646.0, -4_901.0],
        "tax_expense": [16_950.0, 19_651.0, 21_795.0],
        "cash": [75_543.0, 94_565.0],
        "cf_operating": [89_435.0, 118_548.0, 136_162.0],
        "cf_investing": [-39_442.0, -55_664.0, -72_599.0],
        "cf_financing": [-27_222.0, -38_455.0, -51_699.0],
    }
    st = build_statements_from_metrics(metrics, ["2023", "2024", "2025"])
    cf = st["periods"][2]["cash_flow"]
    assert cf["operating"]["total"] == 136_162.0
    assert cf["investing"]["total"] == -72_599.0
    assert cf["financing"]["total"] == -51_699.0
    assert cf["net_change"] == 11_864.0
    # per-file honesty: the line text marks the stated source
    assert any("حسب الملف" in ln["ar"] for ln in cf["operating"]["lines"])
    # earlier period (2023) reads the file's own 2023 totals
    cf23 = st["periods"][0]["cash_flow"]
    assert cf23["operating"]["total"] == 89_435.0

    # fallback: no stated totals → the balance-delta composition
    st2 = build_statements_from_metrics(
        {k: v for k, v in metrics.items() if not k.startswith("cf_")},
        ["2023", "2024", "2025"])
    cf2 = st2["periods"][2]["cash_flow"]
    assert cf2["operating"]["total"] != 136_162.0
    assert cf2["investing"]["total"] == 0.0


def test_period_labels_under_word_lead_in_rows():
    """Year headers sitting in the FOURTH row (after Word lead-in rows) and
    duplicated across merged cells are still found and made ascending."""
    rows = [
        ["(In millions)", "", "", ""],
        ["", "", "", ""],
        ["", "", "", ""],
        ["Year Ended June\xa030,", "", "2025", "2025", "", "", "2024", "2024", "", "", "2023", "2023"],
        ["Revenue", "", "$", "281,724", "", "", "$", "245,122", "", "", "$", "211,915"],
    ]
    assert _extract_period_labels([{"name": "t", "rows": rows}]) == \
        ["2023", "2024", "2025"]


def test_restated_net_income_not_multiplied():
    """«Net income» restated in the income statement AND the cash flows
    (same 3 values each) must yield ONE series, not 6 points."""
    m = _extract_metrics([
        {"name": "income", "rows": _ms_rows(
            ["Year Ended June\xa030,", "", "2025", "2025", "", "",
             "2024", "2024", "", "", "2023", "2023"], [
            ("Revenue:", "281,724", "245,122", "211,915"),
            ("Total cost of revenue", "87,831", "74,114", "65,863"),
            ("Net income", "101,832", "88,136", "72,361"),
        ])},
        {"name": "cashflow", "rows": _ms_rows(
            ["Year Ended June\xa030,", "", "2025", "2025", "", "",
             "2024", "2024", "", "", "2023", "2023"], [
            ("Net income", "101,832", "88,136", "72,361"),
            ("Net cash from operations", "136,162", "118,548", "89,435"),
        ])},
    ], [])
    assert m["net_profit"] == [72_361.0, 88_136.0, 101_832.0]
    assert m["revenue"] == [211_915.0, 245_122.0, 281_724.0]


def test_balance_sheet_fewer_periods_end_aligned():
    """Income 2023-2025 + balance sheet 2024-2025: the BS face of the
    LATEST period carries the LATEST balance-sheet values, the 2023 period
    honestly misses them, and the sheet BALANCES when L+E ties to assets."""
    from app.statements import build_statements_from_metrics

    metrics = {
        "revenue": [211_915.0, 245_122.0, 281_724.0],
        "cogs": [65_863.0, 74_114.0, 87_831.0],
        "opex": [57_529.0, 61_575.0, 65_365.0],
        "investment_income": [788.0, -1_646.0, -4_901.0],
        "tax_expense": [16_950.0, 19_651.0, 21_795.0],
        "assets": [512_163.0, 619_003.0],
        "cash": [75_543.0, 94_565.0],
        "receivables": [56_924.0, 69_905.0],
        "payables": [21_996.0, 27_724.0],
        "liabilities": [243_686.0, 275_524.0],
        "equity": [268_477.0, 343_479.0],
    }
    st = build_statements_from_metrics(
        metrics, ["2023", "2024", "2025"])
    assert st is not None and len(st["periods"]) == 3
    # 2023 has no balance sheet in the file — nothing is invented
    p23 = st["periods"][0]
    assert p23["assets"] is None
    assert p23["income_statement"]["totals"]["revenue"] == 211_915.0
    # 2025 face = the file's 2025 balance sheet
    p25 = st["periods"][2]
    assert p25["assets"] == 619_003.0
    assert p25["equity"] == 343_479.0
    assert p25["receivables"] == 69_905.0
    # and the whole statement balances (assets = liabilities + equity)
    bs = st["periods"][2]["balance_sheet"]
    assert bs["balanced"] is True


# ------------------------------------------------------- end-to-end ------

class TestMsStatementsE2E:
    def _upload(self, client, tmp_path):
        data = _make_ms_docx(tmp_path / "ms.docx")
        return client.post(
            "/api/upload",
            files={"files": ("ms.docx", io.BytesIO(data), DOCX_MIME)},
            headers=client.auth_headers,
        )

    def test_upload_attaches_matching_statements(self, client, tmp_path):
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        assert item["has_statements"] is True
        metrics = item["result"]["metrics"]
        # clean balances: cash-flow deltas are NOT in the series
        assert metrics["receivables"] == [56_924.0, 69_905.0]
        assert metrics["payables"] == [21_996.0, 27_724.0]
        assert metrics["net_profit"] == [72_361.0, 88_136.0, 101_832.0]
        assert item["result"]["period_labels"] == ["2023", "2024", "2025"]
        aid = item["id"]

        st = client.get(f"/api/analyses/{aid}/statements").json()
        assert st["has_statements"] is True
        s = st["statements"]
        assert s["derived_from_metrics"] is True
        assert len(s["periods"]) == 3
        bs = s["balance_sheet"]
        assert bs["balanced"] is True
        assert bs["assets"]["total"] == 619_003.0
        le = {ln["en"]: ln["amount"]
              for ln in bs["liabilities_equity"]["lines"]}
        assert le["Equity"] == 343_479.0
        # the cash-flow section carries the file's OWN stated activity totals
        cf = s["cash_flow"]
        assert cf["operating"]["total"] == 136_162.0
        assert cf["investing"]["total"] == -72_599.0
        assert cf["financing"]["total"] == -51_699.0
        # the FX line closes the gap → the face reconciles with real cash
        assert cf["other"]["total"] == 7_158.0
        assert cf["reconciles"] is True
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)

    def test_report_matches_file_and_has_no_broken_glyphs(self, client, tmp_path):
        """The PDF statements section matches the UPLOADED figures and the
        Arabic font's missing symbols (✓ ✗ → …) render as supported glyphs,
        never \x00 boxes."""
        resp = self._upload(client, tmp_path)
        assert resp.status_code == 200, resp.text
        item = resp.json()["uploaded"][0]
        assert "error" not in item, item
        aid = item["id"]
        report = client.get(f"/api/analyses/{aid}/report?lang=ar",
                            headers=client.auth_headers)
        assert report.status_code == 200, report.text
        import pymupdf

        doc = pymupdf.open(stream=report.content)
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        assert chr(0) not in text, "unmappable glyph leaked into the PDF"
        # statements figures = the file's own figures (latest year face)
        assert "281,724.00" in text
        assert "101,832.00" in text
        assert "619,003.00" in text
        assert "343,479.00" in text
        assert "69,905.00" in text
        # the stated cash-flow totals, not the delta composition
        assert "136,162.00" in text
        assert "-72,599.00" in text
        assert "-51,699.00" in text
        # the unbalanced-garbage regression must never come back
        assert "-207,589.00" not in text
        client.delete(f"/api/analyses/{aid}", headers=client.auth_headers)
