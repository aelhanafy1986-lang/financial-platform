"""Data hygiene: detect and repair broken revenue signs at the source.

Some real-world Excel/PDF statements interleave column formats (absolute
values vs "change from previous year"), which makes the extracted revenue
series alternate in sign (… +5,029,288 → −5,023,397 …). Those corrupted
series used to poison every downstream ratio (net margin, debt ratio) and
scenario (the historical +15,987% growth bug).

The cleaner runs once at extraction time (upload / reanalyze), flips any
negative revenue value to its absolute magnitude, and records a prominent,
user-facing warning so the file is flagged for manual review. Everything
else (scenarios, score, brief) stays deterministic and derives from the
cleaned series.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .database import DB_PATH

# Concepts whose series must be positive: revenue and its cost drivers.
_SIGN_CRITICAL = ("revenue", "cogs", "opex", "assets", "cash", "liabilities")

# A "broken sign" is a negative value in a concept that is positive
# elsewhere in the series (mixed sign conventions) — or every value
# negative while the concept is positive by nature.
_NEG_NATURE = {"revenue", "cogs", "opex", "assets", "cash"}


def detect_broken_signs(metrics: dict) -> list[str]:
    """Concepts whose series mix positive and negative values."""
    broken = []
    for concept, values in metrics.items():
        if concept not in _SIGN_CRITICAL or not isinstance(values, list):
            continue
        nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums and any(v < 0 for v in nums) and any(v > 0 for v in nums):
            broken.append(concept)
    return broken


def fix_broken_signs(metrics: dict) -> tuple[dict, int]:
    """Flip negative values to positive in sign-critical concepts.

    Revenue/cogs/opex/assets/cash are positive by nature → every negative
    value is a sign bug and is flipped. Liabilities may legitimately be
    negative in some conventions, so only mixed-sign series are normalised
    (the majority-positive convention wins).

    Returns (cleaned_metrics, number_of_flipped_values).
    """
    cleaned = {k: list(v) if isinstance(v, list) else v for k, v in metrics.items()}
    fixed = 0
    for concept, values in cleaned.items():
        if concept not in _SIGN_CRITICAL or not isinstance(values, list):
            continue
        nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not nums:
            continue
        negatives = sum(1 for v in nums if v < 0)
        positives = sum(1 for v in nums if v > 0)
        if negatives == 0:
            continue
        # Flip when: any positive exists (mixed convention) — or the concept
        # is positive-by-nature and there is at least one positive value
        # somewhere (else it is a wholesale sign convention, left as-is).
        should_flip = positives > 0 and (
            concept in _NEG_NATURE or positives >= negatives
        )
        if not should_flip:
            continue
        cleaned[concept] = [abs(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                            for v in values]
        fixed += negatives
    return cleaned, fixed


WARN_AR_FIXED = (
    "رُصدت قيم بإشارات سالبة متكسرة في سلسلة {concepts} داخل الملف — "
    "عولجت تلقائياً باعتماد قيمتها المطلقة، لكن الملف يحتاج مراجعة يدوية "
    "للتأكد من صحة الأعمدة المستخرجة."
)
WARN_AR_FLAGGED = (
    "رُصدت إشارات سالبة متكسرة في سلسلة {concepts} داخل هذا التحليل — "
    "اضغط «إعادة تحليل» لتطبيق التنظيف التلقائي، أو صحّح القيم يدوياً."
)
WARN_EN_FIXED = (
    "Broken sign flips were detected in the {concepts} series — "
    "auto-corrected to absolute values, but the file needs manual review "
    "to confirm the extracted columns are correct."
)
WARN_EN_FLAGGED = (
    "Broken sign flips detected in the {concepts} series of this "
    "analysis — run Reanalyze to apply the automatic fix, or edit the "
    "values manually."
)

_AR_NAMES = {
    "revenue": "الإيرادات",
    "cogs": "تكلفة المبيعات",
    "opex": "المصاريف التشغيلية",
    "assets": "الأصول",
    "cash": "النقدية",
    "liabilities": "الالتزامات",
}
_EN_NAMES = {
    "revenue": "Revenue",
    "cogs": "Cost of Sales",
    "opex": "Operating Expenses",
    "assets": "Assets",
    "cash": "Cash",
    "liabilities": "Liabilities",
}


def data_quality_warnings(result: dict, lang: str = "ar") -> list[str]:
    """The stored data-quality warnings, localised for display.

    The cleaned series is always shown to the user; this warning tells them
    the underlying file needs review (details live in data_quality block).
    """
    dq = result.get("data_quality") or {}
    concepts = dq.get("fixed_concepts") or []
    if not concepts:
        return []
    names = _AR_NAMES if lang == "ar" else _EN_NAMES
    joined = " و".join(names.get(c, c) for c in concepts)
    if lang == "ar":
        template = WARN_AR_FIXED if dq.get("auto_fixed") else WARN_AR_FLAGGED
    else:
        template = WARN_EN_FIXED if dq.get("auto_fixed") else WARN_EN_FLAGGED
    return [template.format(concepts=joined)]


def clean_result(result: dict) -> dict:
    """Clean raw values + record data-quality info on the analysis result.

    Safe to call on any result (with or without a metrics block). Returns
    the same dict, mutated in place:

    - ``metrics``: sign-critical concepts flipped to positive magnitudes.
    - ``data_quality``: {auto_fixed, fixed_concepts, fixed_values} for
      auditability.
    """
    metrics = result.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return result

    detected = detect_broken_signs(metrics)
    if not detected:
        return result

    cleaned, fixed = fix_broken_signs(metrics)
    if fixed == 0:
        return result

    result["metrics"] = cleaned
    # original_metrics keeps the raw extraction for the user's reset button.
    original = result.get("original_metrics")
    if not isinstance(original, dict) or not original:
        result["original_metrics"] = metrics
    result["data_quality"] = {
        "auto_fixed": True,
        "fixed_concepts": detected,
        "fixed_values": fixed,
    }
    return result


def backfill_warnings(db_path=DB_PATH) -> int:
    """Attach data-quality warnings to legacy rows with broken series.

    Legacy rows keep their series as extracted — only the warning is added,
    so nothing the user sees changes until the file is reanalysed.
    """
    con = sqlite3.connect(db_path)
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='analyses'"
        ).fetchall()
        if not tables:
            return 0
        rows = con.execute("SELECT id, result_json FROM analyses").fetchall()
        updated = 0
        for aid, raw in rows:
            try:
                result = json.loads(raw or "{}")
            except (TypeError, ValueError):
                continue
            metrics = result.get("metrics")
            if not isinstance(metrics, dict) or not metrics:
                continue
            if result.get("data_quality"):
                continue  # already processed
            detected = detect_broken_signs(metrics)
            if not detected:
                continue
            result["data_quality"] = {
                "auto_fixed": False,  # legacy row: flagged, not rewritten
                "fixed_concepts": detected,
                "fixed_values": 0,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            con.execute(
                "UPDATE analyses SET result_json = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), aid),
            )
            updated += 1
        con.commit()
        return updated
    finally:
        con.close()
