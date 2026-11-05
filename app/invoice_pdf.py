"""Official invoice PDF for a (simulated) subscription charge.

Feeds the «سجل المدفوعات» download button: one A4 page per payment —
invoice header, invoice number/date, the account holder, a line-item
table (plan, period, amount), totals and a payment-details block. Built
with the same machinery as the financial reports (Arabic TTF via
reportlab, _shape() for connected RTL text, the glyph guard refusing
builds that would print hollow boxes)."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from . import report as _rep
from .auth import PLANS
from .report import (
    INK,
    LINE,
    MUTED,
    TEAL_DARK,
    _flip,
    _rt,
    _shape,
    glyph_guard_begin,
    glyph_guard_flush,
    _register_font,
)

_AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
              "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

_PLAN_AR = {"pro": "برو", "business": "الأعمال", "firm": "المؤسسات",
            "monthly": "شهري", "yearly": "سنوي"}


def _fmt_date(iso: str, lang: str) -> str:
    """2026-10-07T15:38:38… → «7 أكتوبر 2026 · 15:38» / «7 Oct 2026 · 15:38»."""
    try:
        d = iso[:16].split("T")
        y, m, day = d[0].split("-")
        hhmm = d[1]
        if lang == "ar":
            return f"{int(day)} {_AR_MONTHS[int(m) - 1]} {y} · {hhmm}"
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                  "Sep", "Oct", "Nov", "Dec"]
        return f"{int(day)} {months[int(m) - 1]} {y} · {hhmm}"
    except Exception:
        return iso


def build_invoice_pdf(payload: dict, out_path: Path, lang: str = "ar") -> Path:
    """Render one official invoice page for a single payment row."""
    _register_font()
    glyph_guard_begin()
    # live module attributes: _register_font() rebinds them after import
    # time, so a `from .report import _FONT_NAME` snapshot would still hold
    # the pre-registration default («Helvetica») — read via the module.
    FN = _rep._FONT_NAME
    FB = _rep._FONT_BOLD_NAME
    try:
        rtl = lang == "ar"
        plan_key = payload.get("plan", "")
        plan_label = (_PLAN_AR.get(plan_key, plan_key) if lang == "ar"
                      else (PLANS.get(plan_key, {}).get("en") or plan_key))
        amount = float(payload.get("amount") or 0.0)
        invoice_no = payload.get("invoice_no") or "-"
        paid_at = _fmt_date(payload.get("paid_at") or "", lang)
        card = payload.get("masked_card") or "-"
        account_name = payload.get("account_name") or "-"
        expires = payload.get("plan_expires")
        L = {
            "title": "فاتورة اشتراك" if lang == "ar" else "Subscription invoice",
            "inv": "رقم الفاتورة" if lang == "ar" else "Invoice no.",
            "date": "تاريخ العملية" if lang == "ar" else "Date",
            "status": "الحالة" if lang == "ar" else "Status",
            "paid": "مدفوع" if lang == "ar" else "Paid",
            "billed": "المشترك" if lang == "ar" else "Billed to",
            "item": "البند" if lang == "ar" else "Item",
            "period": "الفترة" if lang == "ar" else "Period",
            "amount": "المبلغ" if lang == "ar" else "Amount",
            "sub": "الإجمالي الفرعي" if lang == "ar" else "Subtotal",
            "total": "الإجمالي المستحق" if lang == "ar" else "Total due",
            "paidBy": "وسيلة الدفع" if lang == "ar" else "Payment method",
            "note": ("فاتورة آلية لعملية سداد اشتراك — لا حاجة لأي إجراء."
                     if lang == "ar" else
                     "Automated invoice for a subscription charge — no action needed."),
            "thx": ("شكرًا لاشتراكك في منصة التحليل المالي" if lang == "ar"
                    else "Thank you for subscribing to the financial-analysis platform"),
            "month": "شهر" if lang == "ar" else "month",
        }

        title = ParagraphStyle(
            "t", fontName=FB, fontSize=19, leading=25,
            textColor=TEAL_DARK, alignment=TA_RIGHT if rtl else TA_LEFT)
        body = ParagraphStyle(
            "b", fontName=FN, fontSize=11, leading=16,
            alignment=TA_RIGHT if rtl else TA_LEFT)
        small = ParagraphStyle(
            "s", fontName=FN, fontSize=9, leading=13,
            textColor=MUTED, alignment=TA_RIGHT if rtl else TA_LEFT)

        story = []
        story.append(_rt(L["title"], title))
        story.append(_rt(L["thx"], body))
        story.append(Spacer(1, 8 * mm))

        # meta block (invoice no / date / status) — column order per direction
        meta = [
            [L["inv"], invoice_no],
            [L["date"], paid_at],
            [L["status"], L["paid"]],
        ]
        if rtl:
            meta_rows = [[_shape(k), _shape(str(v))] for k, v in meta]
            meta_cols = [70 * mm, 30 * mm]
            label_col, value_col = 1, 0
        else:
            meta_rows = [[_shape(k), _shape(str(v))] for k, v in meta]
            meta_cols = [30 * mm, 70 * mm]
            label_col, value_col = 0, 1
        meta_t = Table(meta_rows, colWidths=meta_cols)
        meta_t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FN),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (label_col, 0), (label_col, -1), INK),
            ("TEXTCOLOR", (value_col, 0), (value_col, -1), MUTED),
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(meta_t)
        story.append(Spacer(1, 6 * mm))

        story.append(_rt(f"{L['billed']}: {account_name}", body))
        story.append(Spacer(1, 4 * mm))

        # line items — header row + item row + total row over the amount col
        item = (f"اشتراك باقة {plan_label}" if lang == "ar"
                else f"{plan_label} plan subscription")
        period = (f"{payload.get('months', 1)} {L['month']}")
        rows = [
            [L["item"], L["period"], L["amount"]],
            [item, period, f"${amount:.2f}"],
            ["", "", f"${amount:.2f}"],
        ]
        shaped = [[_shape(str(c)) if c else c for c in r] for r in rows]
        style = [
            ("FONTNAME", (0, 0), (-1, -1), FN),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("FONTNAME", (0, 0), (-1, 0), FB),
            ("FONTNAME", (0, 2), (2, 2), FB),
            ("TEXTCOLOR", (0, 2), (2, 2), TEAL_DARK),
            ("BACKGROUND", (0, 0), (-1, 0), TEAL_DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("SPAN", (0, 2), (1, 2)),
        ]
        if rtl:
            shaped = [list(reversed(r)) for r in shaped]
            items = Table(shaped, colWidths=[30 * mm, 50 * mm, 70 * mm])
            style = _flip(style, 3)
        else:
            items = Table(shaped, colWidths=[70 * mm, 50 * mm, 30 * mm])
        items.setStyle(TableStyle(style))
        story.append(items)
        story.append(Spacer(1, 6 * mm))

        # payment details
        pay_rows = [[L["paidBy"], card]]
        if rtl:
            pay_t = Table([[_shape(pay_rows[0][1]), _shape(pay_rows[0][0])]],
                          colWidths=[80 * mm, 40 * mm])
            lbl, val = 1, 0
        else:
            pay_t = Table([[_shape(pay_rows[0][0]), _shape(pay_rows[0][1])]],
                          colWidths=[40 * mm, 80 * mm])
            lbl, val = 0, 1
        pay_t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FN),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (lbl, 0), (lbl, -1), MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(pay_t)
        if expires:
            story.append(_rt(f"{'تنتهي الباقة' if lang == 'ar' else 'Plan expires'}: "
                             f"{_fmt_date(expires, lang)}", small))
        story.append(Spacer(1, 8 * mm))
        story.append(_rt(L["note"], small))

        doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                                topMargin=18 * mm, bottomMargin=18 * mm)
        doc.build(story)
    finally:
        glyph_guard_flush()
    return out_path
