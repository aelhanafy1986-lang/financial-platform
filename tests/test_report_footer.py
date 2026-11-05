"""Report closing footer: «مُعد وفق IFRS» on every printed page + a management
signature block with the preparation date at the bottom of the statements."""

import arabic_reshaper
from bidi.algorithm import get_display


def _shape(s: str) -> str:
    return get_display(arabic_reshaper.reshape(s))


def _pages(out) -> list[str]:
    import pdfplumber

    with pdfplumber.open(str(out)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def _flat(text: str) -> str:
    return text.replace(" ", "").replace("\u00a0", "")


def _minimal_result() -> dict:
    return {
        "kpis": {
            "revenue": {"value": 1_200_000.0, "en": "Revenue", "ar": "الإيرادات"},
            "net_profit": {"value": 180_000.0, "en": "Net Profit", "ar": "صافي الربح"},
        },
        "ratios": {},
        "series": {},
        "tables_found": 1,
        "texts_found": 0,
    }


class TestReportSignatureFooter:
    def test_arabic_ifrs_footer_on_every_page(self, tmp_path):
        from app.report import build_report

        out = tmp_path / "sig_ar.pdf"
        build_report(filename="sig.xlsx", result=_minimal_result(),
                     out_path=out, lang="ar")
        assert out.exists() and out.stat().st_size > 10_000

        pages = _pages(out)
        assert pages
        marker = _flat(_shape("مُعد وفق IFRS"))
        for p_text in pages:
            assert marker in _flat(p_text)

    def test_arabic_signature_block_with_date(self, tmp_path):
        from datetime import date

        from app.report import build_report

        out = tmp_path / "sig_date_ar.pdf"
        build_report(filename="sig.xlsx", result=_minimal_result(),
                     out_path=out, lang="ar")
        last = _flat(_pages(out)[-1])

        assert _flat(_shape("توقيع الإدارة")) in last
        assert _flat(_shape("التاريخ")) in last
        assert date.today().strftime("%Y/%m/%d") in last
        # the dotted signature leader renders (≥ 30 dots on the final page)
        assert last.count(".") >= 30

    def test_english_footer_and_signature(self, tmp_path):
        from datetime import date

        from app.report import build_report

        out = tmp_path / "sig_en.pdf"
        build_report(filename="sig.xlsx", result=_minimal_result(),
                     out_path=out, lang="en")
        pages = _pages(out)
        marker = "Prepared in accordance with IFRS"
        for p_text in pages:
            assert _flat(marker) in _flat(p_text)
        assert "Managementsignature" in _flat(pages[-1])
        assert date.today().strftime("%Y/%m/%d") in pages[-1]
