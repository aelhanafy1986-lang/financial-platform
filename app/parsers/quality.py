"""Extraction-quality scoring — the referee of the parsing methodology.

Every extraction pass (pdfplumber text layer, PyMuPDF, Windows OCR at a
given DPI, an image upscale) is scored on the only thing that matters:
how much PRICING-READY signal survived — labeled money rows and distinct
financial concepts. «Has digits» (the old escalation gate) was not enough:
a garbage text layer (broken encodings, misaligned lattice tables) carries
digits no classifier can price, and the old cascade kept it silently while
the real statement sat unread on the page below.
"""

from __future__ import annotations

import re

# an amount cell: digits with optional separators/parens — a year-like 4+
# digit run alone is NOT money (labels carry dates); mirror of the grid
# parser's rule kept self-contained to avoid an import cycle
_MONEY_RE = re.compile(r"^\(?[\d][\d,.\s]*[\d]\)?%?$")

# the income-statement spine: the concepts a statement face must carry
# before its capture can be trusted
_SPINE = {"revenue", "cogs", "net_profit"}

STRONG_SCORE = 20.0


def _money_like(text: str) -> bool:
    t = text.strip()
    if not t or not _MONEY_RE.match(t):
        return False
    digits = sum(ch.isdigit() for ch in t)
    return digits >= 3 or "," in t or "." in t


def _labelish(text: str) -> bool:
    """A LABEL token carries ≥3 letters — gibberish text layers split their
    digits with 2-letter noise tokens («zz9 4102 qq 552013») that must not
    count the line as a labeled money row."""
    return sum(ch.isalpha() for ch in text) >= 3


def score_extraction(tables: list, texts: list) -> dict:
    """Score one extraction candidate.

    Returns {"score", "labeled_rows", "numeric_rows", "concepts", "spine"}.
    The classifier runs on the LABEL cells (imported lazily — analyzer owns
    the keyword tables and must not import parsers at module level).
    """
    from ..analyzer import _classify_row

    labeled = 0
    numeric = 0
    concepts: set[str] = set()
    for t in tables:
        for row in t.get("rows") or []:
            cells = [str(c or "").strip() for c in row]
            money_cells = [c for c in cells if _money_like(c)]
            if not money_cells:
                continue
            numeric += 1
            label_cells = [c for c in cells
                           if c and not _money_like(c) and _labelish(c)]
            if label_cells:
                labeled += 1
                for lc in label_cells[:2]:
                    concept = _classify_row(lc[:60])
                    if concept:
                        concepts.add(concept)
    # free-text lines are a REAL capture path ("Net Profit 640,000" in a
    # bare statement) — price them like table rows
    for line in texts:
        tokens = str(line or "").split()
        if not any(_money_like(t) for t in tokens):
            continue
        label_tokens = [t for t in tokens
                        if not _money_like(t) and _labelish(t)]
        if label_tokens:
            labeled += 1
            for lt in label_tokens[:2]:
                concept = _classify_row(lt[:60])
                if concept:
                    concepts.add(concept)
    prose = sum(1 for line in texts if line.strip())
    spine = "revenue" in concepts and bool(concepts & {"cogs", "net_profit"})
    score = min(labeled, 60) * 1.0 + len(concepts) * 3.0
    if spine:
        score += 12.0
    score += min(prose, 10) * 0.2
    return {
        "score": round(score, 2),
        "labeled_rows": labeled,
        "numeric_rows": numeric,
        "concepts": sorted(concepts),
        "spine": spine,
    }
