# -*- coding: utf-8 -*-
"""Messy-sheet robustness: stated totals, mixed cells, totals columns, 3+ periods.

Client uploads are rarely clean comparative statements. This pins the
reading-layer guarantees that keep the analysis truthful when a sheet
carries BOTH detail rows and a stated total row for the same concept
(«الإجمالي يفوز»), value cells that embed their own aggregate text
(«الإجمالي 12000»), a cross-period totals COLUMN after the year columns
(whose grand total must never be read as the latest period), and more
than two periods (values must stay in chronological column order).
"""

from app.analyzer import _extract_metrics, _normalise_expense_signs, analyze
from app.ratio_explain import build_yearly_comparison

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _messy_tables() -> list:
    """One sheet, two statements, THREE year columns + a totals column,
    detail rows AND stated total rows, and one mixed value cell."""
    income = [
        ["البند", "عام 2023", "عام 2024", "عام 2025", "الإجمالي"],
        ["إجمالي المبيعات", 200000, 220000, 250000, 670000],
        ["تكلفة المبيعات", -120000, -130000, -140000, -390000],
        # detail rows sum to -45,000/-48,000/-52,000 — deliberately NOT the
        # stated totals below (2023 differs) so «total wins» is observable
        ["مصاريف بيعية وتوزيعية", -40000, -42000, -45000, -127000],
        ["مصاريف إدارية وعمومية", -5000, -6000, -7000, -18000],
        ["إجمالي المصاريف التشغيلية", -46000, -48000, -52000, -146000],
        ["صافي الربح", 34000, 42000, 58000, 134000],
    ]
    balance = [
        ["البند", "عام 2023", "عام 2024", "عام 2025", "الإجمالي"],
        # the middle cell is a NOTE-aggregate, never a period value
        ["النقدية وما يعادلها", 10000, "الإجمالي 12000", 15000, 37000],
        ["ذمم مدينة (عملاء)", 5000, 6000, 8000, 19000],
        ["المخزون السلعي", 20000, 22000, 25000, 67000],
        ["إجمالي الأصول المتداولة", 35000, 40000, 48000, 123000],
        ["إجمالي الأصول", 55000, 62000, 70000, 187000],
        ["ذمم دائنة (موردون)", 8000, 9000, 10000, 27000],
        ["إجمالي الالتزامات المتداولة", 15000, 16000, 17000, 48000],
        ["إجمالي الالتزامات", 15000, 16000, 17000, 48000],
        ["جاري الشركاء", 10000, 16000, 23000, 49000],
        ["إجمالي حقوق الملكية", 40000, 46000, 53000, 139000],
        ["إجمالي الالتزامات وحقوق الملكية", 55000, 62000, 70000, 187000],
    ]
    return [{"name": "قائمة الدخل", "rows": income},
            {"name": "المركز المالي", "rows": balance}]


def test_stated_total_wins_over_details():
    """opex carries a stated total row AND two detail rows: the stated
    totals (-46,000/-48,000/-52,000) win — not the column sums
    (-45,000/-48,000/-52,000) and not an interleaved detail mess."""
    metrics = _extract_metrics(_messy_tables(), [])
    assert metrics["opex"] == [-46000.0, -48000.0, -52000.0]


def test_equity_total_row_beats_component_rows():
    """جاري الشركاء (detail) + إجمالي حقوق الملكية (stated total): the
    series is exactly the stated totals — no component values mixed in."""
    metrics = _extract_metrics(_messy_tables(), [])
    assert metrics["equity"] == [40000.0, 46000.0, 53000.0]
    assert len(metrics["equity"]) == 3


def test_mixed_cell_never_a_period_value():
    """«الإجمالي 12000» inside a data row is an embedded aggregate — the
    cash series keeps only the pure numeric periods."""
    metrics = _extract_metrics(_messy_tables(), [])
    cash = metrics["cash"]
    assert 12000 not in cash
    assert cash == [10000.0, 15000.0]


def test_totals_column_excluded_in_multi_period():
    """The trailing «الإجمالي» column is a cross-period aggregate: its
    grand totals (670,000 revenue / 187,000 assets / 146,000 expenses)
    must NEVER appear in any series — _latest would read them as the
    current period otherwise."""
    metrics = _extract_metrics(_messy_tables(), [])
    assert metrics["revenue"] == [200000.0, 220000.0, 250000.0]
    assert metrics["assets"] == [55000.0, 62000.0, 70000.0]
    assert 187000 not in metrics["assets"]
    assert 670000 not in metrics["revenue"]
    assert 146000 not in metrics["opex"]


def test_three_periods_in_chronological_order():
    """3+ periods keep the sheet's left-to-right (oldest → newest) order
    across every balance-sheet concept."""
    metrics = _extract_metrics(_messy_tables(), [])
    assert metrics["current_assets"] == [35000.0, 40000.0, 48000.0]
    assert metrics["current_liabilities"] == [15000.0, 16000.0, 17000.0]
    assert metrics["liabilities"] == [15000.0, 16000.0, 17000.0]
    assert metrics["inventory"] == [20000.0, 22000.0, 25000.0]


def test_totals_column_kept_in_single_period():
    """«البيان | الفرعي | الإجمالي» has NO year columns: the الإجمالي
    column IS the authoritative value column and must survive."""
    tables = [{
        "name": "قائمة دخل",
        "rows": [
            ["البيان", "", "الفرعي", "", "الإجمالي"],
            ["المبيعات", "", 95000, "", ""],
            ["إجمالي المصروفات", "", "", "", 40000],
        ],
    }]
    metrics = _extract_metrics(tables, [])
    assert metrics["revenue"] == [95000.0]
    assert metrics["opex"] == [40000.0]


def test_analyze_on_messy_workbook_sane_kpis():
    """Full pipeline: latest-period KPIs and ratios stay truthful — assets
    70,000 (not the 187,000 grand total), net 58,000, three period labels."""
    result = analyze(_messy_tables(), [])
    assert result["period_labels"] == ["2023", "2024", "2025"]
    assert result["kpis"]["revenue"]["value"] == 250000.0
    assert result["kpis"]["assets"]["value"] == 70000.0
    assert result["kpis"]["cash"]["value"] == 15000.0
    assert abs(result["kpis"]["net_profit"]["value"] - 58000.0) < 0.01
    gm = result["ratios"]["gross_margin"]["value"]
    assert abs(gm - (250000 - 140000) / 250000 * 100) < 0.01
    cr = result["ratios"]["current_ratio"]["value"]
    assert abs(cr - 48000 / 17000) < 0.01


def test_yearly_comparison_derives_net_for_three_periods():
    """The comparison sheet derives net profit per period (IFRS 18 chain)
    even when the sheet's صافي الربح row is rejected as a derived line."""
    tables = _messy_tables()
    metrics = _extract_metrics(tables, [])
    _normalise_expense_signs(metrics)  # the pipeline normalises before compare
    comp = build_yearly_comparison({"metrics": metrics}, "ar")
    assert comp is not None
    by_key = {row["key"]: row for row in comp["rows"]}
    assert "revenue" in by_key and "net_profit" in by_key
    # first vs last period of the three-year span
    assert by_key["revenue"]["curr"] == "250,000"
    assert by_key["net_profit"]["curr"] == "58,000"


def _upload_messy(client, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "القوائم"
    for table in _messy_tables():
        for row in table["rows"]:
            ws.append(row)
        ws.append([""] * 5)  # blank separator between the two statements
    path = tmp_path / "فوضى.xlsx"
    wb.save(path)
    with open(path, "rb") as fh:
        return client.post(
            "/api/upload",
            files={"files": (path.name, fh, XLSX_MIME)},
            headers=client.auth_headers,
        )


def test_api_upload_messy_workbook_truthful(client, tmp_path):
    """End-to-end: the messy three-period workbook uploads cleanly and the
    API returns the true latest-period figures — assets 70,000 (never the
    187,000 totals-column grand total) and the three period labels."""
    response = _upload_messy(client, tmp_path)
    assert response.status_code == 200, response.text
    uploaded = response.json()["uploaded"]
    assert len(uploaded) == 1

    res = uploaded[0]["result"]
    assert res["period_labels"] == ["2023", "2024", "2025"]
    assert res["kpis"]["revenue"]["value"] == 250000.0
    assert res["kpis"]["assets"]["value"] == 70000.0
    assert abs(res["kpis"]["net_profit"]["value"] - 58000.0) < 0.01
    cr = res["ratios"]["current_ratio"]["value"]
    assert abs(cr - 48000 / 17000) < 0.01

    # the series survive the round trip: equity is the stated totals only
    metrics = res["metrics"]
    assert metrics["equity"] == [40000.0, 46000.0, 53000.0]
    assert 187000 not in metrics["assets"]
