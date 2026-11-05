"""PDF parser.

Root-cause fix for Arabic PDFs «رفعت ولم تُقرأ»: PDF writers (reportlab,
Word export, accounting suites) store Arabic as GLYPHS — presentation
forms (U+FB50–U+FEFF) already shaped and laid out in VISUAL order. What
pdfplumber therefore extracts for the cell «الحساب» is ``'ﺏﺎﺴﺤﻟﺍ'`` —
reversed presentation forms — which no classifier can read (zero metrics
→ the quality gate rejects the upload with 422).

``_restore_visual_arabic`` un-shackles exactly that representation:
  1. only strings that CONTAIN presentation forms are touched (logical
     Arabic/English passes through untouched);
  2. the string is reversed with the bidi algorithm (base RTL) — this
     restores logical order while keeping digit/Latin runs LTR, and it
     runs BEFORE NFKC so the lam-alef ligature stays one codepoint while
     reordering (NFKC first would split it into ل+إ and the reversal
     would swap them: «الإجمالي» ← «اإلجمالي»);
  3. NFKC then decomposes the presentation forms (incl. lam-alef) into
     their standard logical-order letters.

Digits like ``'380,000'`` survive round-trip exactly.
"""

from pathlib import Path

import pdfplumber
import pymupdf
from bidi.algorithm import get_display
import unicodedata
import asyncio
import threading
import os
import re
import tempfile
import time
from collections import Counter

from .quality import STRONG_SCORE, score_extraction

MAX_ROWS = 300
MAX_CHARS = 60_000

# Windows OCR accepts images up to 10,000 px (OcrEngine.max_image_dimension);
# the old 2500 cap starved dense A4 statements of resolution — «مكفكككك»-
# class label garbage and digit-group splits («19 575585») on Almarai-type
# scans. 400 dpi stays 3x below the engine's hard limit.
_OCR_MAX_DIM = 10_000
_OCR_MAX_PAGES = 20
# pages read in parallel during OCR (each worker = own engine + own doc
# handle; measured sweet spot — beyond 4 the engine saturates the CPU)
_OCR_PARALLEL_PAGES = 4
_OCR_DPI = 400

# Full-page renders get silently downscaled by the engine and zebra-shaded
# table rows («تكلفة الإيرادات» on the Almarai balance sheet) then VANISH —
# the amounts are unreadable at every DPI of a whole-page pass. Rendering
# the page in overlapping horizontal BANDS keeps each image small enough
# for full-resolution recognition, and OCRing every band twice more with
# fixed binarization thresholds recovers the shaded rows: no single
# variant reads every cell, but each cell is read WELL by some variant —
# the per-cell vote below unions them (validated against the real
# al-Marāʾī figures: 13,524,295 / 13,098,035 / 2,051,529 / 546,916).
_OCR_BAND_H = 1100       # px at OCR scale — < half the engine's 2600px limit
_OCR_BAND_OVERLAP = 220  # > the tallest table row, so every row fits whole in ≥1 band
_OCR_BIN_THRESHOLDS = (128, 170)
# fixed thresholds for the WHOLE-PAGE renders. The engine downscales the
# huge full-page image: its bin170/bin200 reads are UNSTABLE and produce
# poisoned phantom-digit reads on several rows at once («10778138» for
# 1,778,138) that outvote the true consensus. bin128 stayed correct on
# every probed cell of the al-Marāʾī scan — bands carry the rest.
_OCR_FULL_BIN_THRESHOLDS = (128,)

# LOCAL (Sauvola-style) binarization of every band — an extra candidate in
# the per-cell vote beside the fixed thresholds: shaded/zebra bands keep
# their faint digits where no single fixed threshold survives
from .preprocess import binarize_local

# ---- live OCR progress -------------------------------------------------
# The OCR of a scanned page takes seconds; the upload layer passes an
# optional shared ``progress`` dict that gets stage ticks ("pdf" while the
# text engines run, then "ocr" with page N of total) so a concurrent
# reader (GET /api/upload/progress/{id}) can drive the frontend's progress
# indicator. Purely observational — parsing never reads it back.

def _progress_set(progress, stage: str, page: int, total: int) -> None:
    if progress is None:
        return
    progress["stage"] = stage
    progress["page"] = int(page)
    progress["total"] = int(total)
    progress["ts"] = time.time()


def _parallel_cap() -> int:
    """Worker cap lifted to the machine's CPU count (upload path only —
    a progress reader means the request thread is parked on the pool
    anyway, so the conservative cap is the only throttle left)."""
    try:
        cap = len(os.sched_getaffinity(0))
    except Exception:
        cap = (os.cpu_count() or _OCR_PARALLEL_PAGES)
    return max(1, min(cap, 16))


# Arabic Presentation Forms-A + Forms-B (shaped glyph codepoints)
_PRESENTATION_FORMS = range(0xFB50, 0xFEFF + 1)


def _has_presentation_forms(text: str) -> bool:
    return any(ch in _PRESENTATION_FORMS for ch in text) or any(
        0xFB50 <= ord(ch) <= 0xFEFF for ch in text
    )


def _restore_visual_arabic(text: str) -> str:
    """Visual-order Arabic presentation forms → logical standard Arabic.

    Identity on text that carries no presentation forms (logical Arabic,
    English, numbers) — so already-readable PDFs are unaffected.
    """
    if not text or not _has_presentation_forms(text):
        return text
    # reverse FIRST (ligature still one codepoint), THEN NFKC (decompose)
    restored = get_display(text, base_dir="R")
    return unicodedata.normalize("NFKC", restored)


def parse_pdf(path: Path, progress: dict | None = None) -> dict:
    """Extract tables + text with a SCORE-BASED best-of cascade (the
    parsing methodology's referee lives in ``.quality``):

    1. pdfplumber (lattice/stream tables + text),
    2. PyMuPDF — tried when pdfplumber scores WEAK (not only when empty:
       a garbage text layer — broken/Type3 encodings, misaligned lattice —
       carries digits no classifier can price and used to be kept
       silently while the real statement sat unread),
    3. Windows OCR of the rendered pages — tried when the text engines
       still score weak; a SECOND opinion at a lower DPI when OCR itself
       reads weak.

    The strongest candidate WINS (never merely the first non-empty), and
    the winning score rides out as ``quality`` for callers to see.

    ``progress`` is an optional shared dict receiving stage ticks ("pdf"
    while the text engines run, "ocr" with page N of total) for a live
    progress indicator — never read back by the parser itself.
    """
    _progress_set(progress, "pdf", 0, 0)
    tables, texts = _extract_pdfplumber(path)
    best_score = score_extraction(tables, texts)

    if best_score["score"] < STRONG_SCORE:
        _progress_set(progress, "pdf", 0, 0)
        f_tables, f_texts = _parse_pdf_fallback(path)
        f_score = score_extraction(f_tables, f_texts)
        if f_score["score"] > best_score["score"]:
            tables, texts, best_score = f_tables, f_texts, f_score

    ocr_used = False
    # OCR is a second opinion not only when the text engines scored weak.
    # Two text-engine pathologies deserve the OCR referee (the score still
    # decides who wins):
    #   1. a «strong» score WITHOUT the income-statement spine — e.g. a
    #      balance sheet misread as the only face, or mis-decoded labels
    #      whose stray keyword hits fabricate a fake spine;
    #   2. a CONCEPT-THIN large extraction — 30+ labeled rows yet ≤6 account
    #      families classified. Scrambled column pairing (header/date
    #      fragments, RTL cell reflow) manufactures label/number pairs that
    #      inflate «labeled_rows» while the statement stays unread; a real
    #      statement face names most account families, so thin coverage on
    #      a big table is the fingerprint of noise.
    thin_concepts = (
        best_score["labeled_rows"] >= 30 and len(best_score["concepts"]) <= 6
    )
    if (best_score["score"] < STRONG_SCORE
            or not best_score.get("spine")
            or thin_concepts):
        # OCR runs with its parallel worker cap lifted to the machine's
        # CPU count when a progress reader is attached (upload-time): the
        # request thread parks on the worker pool anyway, so the cap is
        # the only thing throttling recognition.
        progress_dict = progress
        o_tables, o_texts = _ocr_pdf_fallback(path, progress=progress_dict)
        o_score = score_extraction(o_tables, o_texts)
        if o_score["score"] > best_score["score"]:
            tables, texts, best_score = o_tables, o_texts, o_score
            ocr_used = True
        # a second opinion at a coarser scale: the engine downscales big
        # pages differently per DPI — a weak first read often recovers at
        # another one (shaded rows and small print flip readability)
        if best_score["score"] < STRONG_SCORE and o_tables:
            o2_tables, o2_texts = _ocr_pdf_fallback(
                path, dpi=300, progress=progress_dict)
            o2_score = score_extraction(o2_tables, o2_texts)
            if o2_score["score"] > best_score["score"]:
                tables, texts, best_score = o2_tables, o2_texts, o2_score
                ocr_used = True

    return {"tables": tables, "texts": texts, "ocr_used": ocr_used,
            "quality": best_score}


def _extract_pdfplumber(path: Path) -> tuple[list, list]:
    """Engine 1: pdfplumber lattice/stream tables + text, with the Arabic
    presentation-form restoration applied line by line."""
    tables = []
    texts = []
    collected = 0

    with pdfplumber.open(str(path)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for i, table in enumerate(page.extract_tables() or [], start=1):
                rows = [
                    [
                        _restore_visual_arabic(
                            "" if c is None else str(c).strip()
                        )
                        for c in row
                    ]
                    for row in table[:MAX_ROWS]
                ]
                if rows:
                    tables.append({"name": f"p{page_no}_table_{i}", "rows": rows})

            text = page.extract_text() or ""
            if text and collected < MAX_CHARS:
                # restore line by line — a whole page mixes columns; the
                # visual/logical flip is only well-defined per line
                fixed_lines = [
                    _restore_visual_arabic(line)
                    for line in text.splitlines()
                ]
                fixed = "\n".join(fixed_lines)
                texts.append(fixed)
                collected += len(fixed)
    return tables, texts


def _has_numeric_content(tables: list, texts: list) -> bool:
    """True when ANY extracted cell or text line carries a digit.

    Latin digits only: Arabic-Indic date digits («٣١ ديسمبر ٢٠٢٣» on a
    cover page) must NOT count — a scanned Almarai-style report whose only
    text layer is one such line would otherwise pass this gate and SKIP
    the PyMuPDF/OCR engines entirely, surfacing as «لا أرى أرقامًا مالية»
    downstream. The OCR path normalises Arabic-Indic → Latin anyway, so
    Latin digits are exactly what feeds the row parsers (NUM_RE)."""
    for t in tables:
        for row in t.get("rows") or []:
            for cell in row:
                if any("0" <= ch <= "9" for ch in str(cell)):
                    return True
    for text in texts:
        if any("0" <= ch <= "9" for ch in text):
            return True
    return False


def _parse_pdf_fallback(path: Path) -> tuple[list, list]:
    """PyMuPDF second engine: word boxes → grouped rows → tables.

    Rows are clustered by y-center (gap < 6pt); within a row, cells are
    split wherever the gap between consecutive words exceeds ~18pt (a
    column gutter). A page yields a TABLE only when at least 3 rows carry
    a number — prose-only pages become text lines. Returns ([], []) when
    the PDF has no text layer at all (scanned) — the OCR third engine then
    takes over.
    """
    try:
        import pymupdf
    except Exception:
        return [], []
    tables: list = []
    texts: list = []
    try:
        doc = pymupdf.open(str(path))
    except Exception:
        return [], []
    collected = 0
    try:
        for page_no, page in enumerate(doc, start=1):
            words = page.get_text("words") or []
            if not words:
                continue
            # keep (x0, y0, x1, y1, text): newer PyMuPDF versions append
            # (block, line, word) indices to each tuple — unpacking the raw
            # shape downstream would blow up with «too many values»
            words = [tuple(w)[:5] for w in words]
            rows: list[list[tuple[float, float, float, float, str]]] = []
            for w in sorted(words, key=lambda w: (round(w[1], 1), w[0])):
                placed = False
                for row in rows:
                    if abs(row[0][1] - w[1]) < 6.0:
                        row.append(w)
                        placed = True
                        break
                if not placed:
                    rows.append([w])
            grid: list[list[str]] = []
            numeric_rows = 0
            for row in rows:
                row.sort(key=lambda w: w[0])
                cells: list[str] = []
                prev = None
                for x0, y0, x1, y1, wtext in row:
                    if prev is not None and (x0 - prev) > 18.0:
                        cells.append("")  # column gutter
                    cells.append(wtext)
                    prev = x1
                grid.append(cells)
                if any(any(ch.isdigit() for ch in c) for c in cells):
                    numeric_rows += 1
            if numeric_rows >= 3 and len(grid) >= 3:
                # pad rows to the widest so downstream row-parsers see columns
                width = max(len(r) for r in grid)
                grid = [r + [""] * (width - len(r)) for r in grid]
                tables.append({"name": f"p{page_no}_words",
                               "rows": [[_restore_visual_arabic(c) for c in r]
                                        for r in grid[:MAX_ROWS]]})
            else:
                text = page.get_text("text") or ""
                if text and collected < MAX_CHARS:
                    fixed = "\n".join(_restore_visual_arabic(line)
                                      for line in text.splitlines())
                    texts.append(fixed)
                    collected += len(fixed)
    finally:
        doc.close()
    return tables, texts


def _has_arabic(text: str) -> bool:
    """True when the string carries at least one Arabic letter."""
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def _run_coro_blocking(coro):
    """Run a winsdk coroutine even when the caller thread already owns a
    running asyncio loop (the async /api/upload calls the parser directly)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# Windows OCR engines are NOT concurrency-safe (a shared engine silently
# drops every read beyond the first — measured: 3 parallel reads returned
# 223/0/0 words) but a fresh engine PER THREAD runs truly in parallel
# (measured 2.9x on one dense page, 223 words everywhere). The engine
# creation cost is ~0 (a WinRT object handle, not a model load), so a
# per-thread cache gives each worker its own engine once and reuses it.
_OCR_ENGINE_TLS = threading.local()


def _thread_ocr_engine():
    """This thread's own OCR engine (created once per thread)."""
    engine = getattr(_OCR_ENGINE_TLS, "engine", None)
    if engine is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language

        for tag in ("ar-SA", "en-US"):
            try:
                engine = OcrEngine.try_create_from_language(Language(tag))
            except Exception:
                engine = None
            if engine:
                break
        _OCR_ENGINE_TLS.engine = engine
    return engine


async def _ocr_png_files(png_paths: list[str], engine) -> list[list]:
    """OCR each PNG with the Windows engine; returns per file a flat list
    of (x, y, width, height, text, line_idx) word boxes in PIXEL
    coordinates — the line index is kept because the engine already
    grouped words into VISUAL rows, and rebuilding rows from boxes alone
    mis-aligns labels from their amounts at higher DPI."""
    from winsdk.windows.storage import StorageFile, FileAccessMode
    from winsdk.windows.graphics.imaging import BitmapDecoder

    out: list[list] = []
    for png in png_paths:
        words: list = []
        try:
            file = await StorageFile.get_file_from_path_async(png)
            stream = await file.open_async(FileAccessMode.READ)
            try:
                decoder = await BitmapDecoder.create_async(stream)
                bmp = await decoder.get_software_bitmap_async()
                res = await engine.recognize_async(bmp)
            finally:
                stream.close()
            for li, line in enumerate(res.lines or []):
                for w in line.words or []:
                    r = w.bounding_rect
                    txt = (w.text or "").strip()
                    if txt:
                        words.append((r.x, r.y, r.width, r.height, txt, li))
        except Exception:
            pass
        out.append(words)
    return out


def _normalize_digits(text: str) -> str:
    """Arabic-Indic (٠١٢) and Persian (۰۱۲) digits → Latin — the row
    parsers (NUM_RE) only read Latin digits, and Windows OCR emits both
    kinds depending on the source document."""
    table = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    )
    return text.translate(table)


# an amount cell: digits with optional thousands/decimal separators,
# accounting parentheses and a trailing % — NOT a date (has /) or a code
# that mixes letters.
_MONEY_RE = re.compile(r"^\(?[\d][\d,.\s]*[\d]\)?%?$")


def _money_cell(txt: str) -> bool:
    t = txt.strip()
    if not t or not _MONEY_RE.match(t):
        return False
    digits = sum(ch.isdigit() for ch in t)
    # 3+ digits, or an explicit separator — «250» and «150,000» are amounts,
    # «12» alone stays ambiguous-but-harmless (a real column needs 3 rows)
    return digits >= 3 or "," in t or "." in t


def _heal_ocr_amounts(txt: str) -> str:
    """Rejoin digit groups Windows OCR swallows the comma between: an
    amount is the ONLY long multi-group digit run in a cell, so
    «1872 2 2 58» (→ 18,722,258) heals to «18722258» while «31 ديسمبر
    2023م» (a date: 2-digit + 4-digit groups, mixed letters) stays apart.
    Applied to OCR text only — never to text-layer extractions."""
    groups = [g for g in txt.split(" ") if g]
    if len(groups) < 2:
        return txt
    # heal a group into its successor only when BOTH are pure digit runs,
    # the pair keeps 6..14 digits total (amount range), and the pair alone
    # fills the cell (no Arabic words riding along → not a date line)
    all_digit_like = all(g.isdigit() for g in groups)
    if not all_digit_like:
        return txt
    total_digits = sum(len(g) for g in groups)
    if not (6 <= total_digits <= 14):
        return txt
    # a pure digit run whose groups all have ≤2 digits is a fragmented
    # single number («19 575 585»); with one 3+ digit group it is a
    # swallowed-comma amount («1872 2 2 58» / «19 575585»)
    healed = "".join(groups)
    # dates survive as dates: they never reach here (letters present)
    return healed


def _variant_cells(words: list) -> list[list[list[tuple]]]:
    """One render's word boxes → ROWS of CELLS, geometry preserved.

    Same stages as the original single-pass assembler (engine-line
    grouping, merge of vertically-overlapping line bands, gutter cell
    split, swallowed-comma healing) but returns rows of cell-word-groups
    so several renders' rows can be merged while each keeps its own cell
    boundaries (see ``_ocr_grid_from_variants``).
    """
    if not words:
        return []
    words = [
        (w[0], w[1], w[2], w[3], _normalize_digits(w[4]),
         w[5] if len(w) > 5 else 0)
        for w in words
    ]
    # PRIMARY grouping: the engine's own lines (they ARE the visual rows —
    # rebuilding from boxes alone split «Revenue» from «19,575,585» at
    # higher render DPI)
    words.sort(key=lambda w: (w[5], w[1], w[0]))
    rows: list[list] = []
    for w in words:
        x, y, wd, ht, txt, li = w
        placed = False
        if rows and rows[-1][0][5] == li:
            r_top = min(m[1] for m in rows[-1])
            r_bot = max(m[1] + m[3] for m in rows[-1])
            overlap = min(y + ht, r_bot) - max(y, r_top)
            if overlap > 0.4 * min(ht, r_bot - r_top):
                rows[-1].append(w)
                placed = True
        if not placed:
            for row in reversed(rows):  # merge heavily-overlapping line bands
                r_top = min(m[1] for m in row)
                r_bot = max(m[1] + m[3] for m in row)
                overlap = min(y + ht, r_bot) - max(y, r_top)
                if overlap > 0.6 * min(ht, r_bot - r_top):
                    row.append(w)
                    placed = True
                    break
            if not placed:
                rows.append([w])
    rows.sort(key=lambda r: min(m[1] for m in r))
    # split each row into cells (x-ascending); a cell keeps its words
    split_rows: list[list[list]] = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        gaps = []
        for i in range(len(row) - 1):
            a, b = row[i], row[i + 1]
            left, right = (a, b) if a[0] < b[0] else (b, a)
            gaps.append((left[0] + left[2]) - right[0])
        positive = sorted(g for g in gaps if g > 0)
        median = positive[len(positive) // 2] if positive else 0.0
        gutter = max(2.5 * median, 22.0)
        cells: list[list] = []
        prev = None
        for w in row:
            x, y, wd, ht, txt = w[0], w[1], w[2], w[3], w[4]
            if prev is not None:
                gap = (x - (prev[0] + prev[1])) if x > prev[0] else (prev[0] - (x + wd))
                if gap > gutter:
                    cells.append([])
            if not cells:
                cells.append([])
            cells[-1].append(w)
            prev = (x, wd)
        split_rows.append(cells)
    out: list[list[list[tuple]]] = []
    for cells in split_rows:
        voted_cells: list[list[tuple]] = []
        for cw in cells:
            # heal the JOINED cell text — the swallowed-comma fragments are
            # separate WORDS inside one cell («1872 2 2 58»); per-word
            # healing would never see them together
            txt = " ".join(w[4] for w in cw)
            healed = _heal_ocr_amounts(txt)
            if healed != txt:
                w0 = cw[0]  # tuples are immutable: swap in the healed read
                cw = [(w0[0], w0[1], w0[2], w0[3], healed, w0[5])]
            voted_cells.append(cw)
        out.append(voted_cells)
    return out


def _merge_variant_rows(rows_flat: list) -> list[list[list[tuple]]]:
    """Rows (flat, from every render variant, page coordinates) → one set.

    The engine's line grouping is trusted WITHIN each variant (a variant's
    row is a real visual row); variants disagree on WHICH rows they saw,
    so rows are merged by vertical overlap: a merged row keeps every
    variant's own cell split (never re-split mixed word lists).
    """
    merged: list[dict] = []  # {top, bot, cells: [cell_word_groups]}
    for cells in rows_flat:
        top = min(w[1] for cw in cells for w in cw)
        bot = max(w[1] + w[3] for cw in cells for w in cw)
        yc = (top + bot) / 2
        hit = None
        for m in merged:
            overlap = min(bot, m["bot"]) - max(top, m["top"])
            same_row = overlap > 0.5 * min(bot - top, m["bot"] - m["top"])
            # binarization shifts a variant's row band by a dozen px — the
            # bbox-overlap test alone then SPLITS one visual row into two
            # merged rows (each with half the variant consensus, and the
            # poisoned fragment can outvote). Same row = overlapping bands
            # OR near-identical centers (statement rows sit ≥55px apart).
            near = abs(yc - (m["top"] + m["bot"]) / 2) < 38.0
            if same_row or near:
                hit = m
                break
        if hit is None:
            merged.append({"top": top, "bot": bot, "cells": [cw for cw in cells]})
        else:
            hit["top"] = min(hit["top"], top)
            hit["bot"] = max(hit["bot"], bot)
            hit["cells"].extend(cells)
    merged.sort(key=lambda m: m["top"])
    return [m["cells"] for m in merged]


def _ocr_grid_from_variants(variant_rows: list) -> list[list[str]]:
    """Per-variant rows (from bands, binarizations, the full page) → grid.

    Rows merge by y-overlap (``_merge_variant_rows``) keeping each
    variant's own cell boundaries; within a merged row, cells CLUSTER by
    x-center into SLOTS and each slot is VOTED: the read with the most
    digits wins (a complete «13524295» beats a truncated «1352 4295»),
    ties prefer the longer read (keeps accounting parens). Slots then
    become the row's amount columns (45px rule — real debit/credit
    gutters are far wider). Table direction comes from WHERE THE NUMBERS
    sit relative to the labels: an RTL Arabic statement keeps its amounts
    on the LEFT half. An empty slot of a row that DID read an amount pads
    as an explicit «0» — the blank side of a money row (the accounting-
    export convention the row parsers expect). A row with NO amount reads
    (page headers, company banners, dates, prose) pads with EMPTY cells:
    padding those with «0» fabricated phantom columns that drowned the
    row parsers (the المراعي scan classified «31 ديسمبر 2023» rows as
    zero-balance accounts), so zeros exist only where the row itself
    speaks money.
    """
    if not variant_rows:
        return []
    merged_rows = _merge_variant_rows(variant_rows)
    # page-wide amount columns from every voted money read (45px rule)
    all_amount_cells: list[tuple[float, str]] = []
    row_slots: list[list[list]] = []
    for cells in merged_rows:
        # slots cluster by x-INTERVAL overlap: a cell split by the engine
        # into two boxes («2051» + «529» of one amount) must land in the
        # same slot as the variant that read it whole («2051529»)
        slots: list[list] = []  # [x0, x1, x_mean, candidates]
        for cw in sorted(
            cells, key=lambda c: min(w[0] for w in c)
        ):
            x0 = min(w[0] for w in cw)
            x1 = max(w[0] + w[2] for w in cw)
            hit = None
            for s in slots:
                # a same-cell fragment may sit on EITHER side (binarized
                # reads split «6,051,290» as «562|4223» from the left) —
                # scan the whole span, not just the leftmost overlap
                if x1 > s[0] + 12 and x0 < s[1] - 12:
                    hit = s
                    break
            if hit is None:
                slots.append([x0, x1, (x0 + x1) / 2, [cw]])
            else:
                hit[0] = min(hit[0], x0)
                hit[1] = max(hit[1], x1)
                hit[2] = (hit[0] + hit[1]) / 2
                hit[3].append(cw)
        row_slots.append([(s[2], s[3]) for s in slots])
        for s_x, s_cands in [(s[2], s[3]) for s in slots]:
            txt = _slot_text(s_cands)
            if _slot_is_money(s_cands):
                all_amount_cells.append((s_x, txt))
    all_amount_cells.sort()
    col_centers: list[float] = []
    for x, _ in all_amount_cells:
        if not col_centers or x - col_centers[-1] > 45.0:
            col_centers.append(x)
    if not col_centers:
        # no amounts on the page — prose lines
        out = []
        for cells in merged_rows:
            words = [w for cw in cells for w in cw]
            ws = sorted(words, key=lambda w: -w[0] if _has_arabic("".join(w[4] for w in words)) else w[0])
            out.append(" ".join(w[4] for w in ws))
        return out
    def col_of(x: float) -> int:
        return min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - x))
    # direction: labels right of amounts → RTL
    label_xs: list[float] = []
    amount_xs: list[float] = []
    for slots in row_slots:
        for x, cands in slots:
            if _slot_is_money(cands):
                amount_xs.append(x)
            else:
                label_xs.append(x)
    rtl = bool(label_xs and amount_xs
               and (sum(label_xs) / len(label_xs)) > (sum(amount_xs) / len(amount_xs)))
    n_cols = len(col_centers)
    grid: list[list[str]] = []
    for slots in row_slots:
        label_slots: list[tuple[float, str]] = []
        amounts: dict[int, str] = {}
        for x, cands in slots:
            txt = _slot_text(cands)
            if _slot_is_money(cands):
                amounts[col_of(x)] = txt
            else:
                label_slots.append((x, txt))
        label_slots.sort(key=lambda w: -w[0] if rtl else w[0])
        label = " ".join(t for _, t in label_slots).strip()
        slot_order = list(range(n_cols - 1, -1, -1)) if rtl else list(range(n_cols))
        # money rows pad their unread sides with «0»; label-only rows pad
        # with empty cells (no fabricated zero columns — see docstring)
        empty_pad = "0" if amounts else ""
        grid.append([label] + [amounts.get(s, empty_pad) for s in slot_order])
    return grid


def _slot_is_money(cands: list) -> bool:
    """Money verdict on the VOTED text — with one date-trap guard.

    `_slot_text` votes digits by place value, which is what recovers an
    amount glued to its label by the OCR («المخزون 40000» votes to
    «40000») — judging the raw reads directly would throw those digits
    into the label and lose the row's number. The one trap the vote
    cannot see: a date year read as ONE word («2023م») votes to «2023»
    and passes `_money_cell`, so the year masquerades as an amount column
    and label-only rows get zero-padded into phantom accounts. A real
    amount is read PURE by at least one band variant; a year never is —
    every read carries the letters riding the digits. When every raw read
    has letters attached AND the voted digits alone are year-shaped
    (19xx/20xx), the slot is a label, not a column."""
    voted = _slot_text(cands)
    if not _money_cell(voted):
        return False
    raws = [" ".join(w[4] for w in cw).strip() for cw in cands]
    digit_reads = [r for r in raws if any(ch.isdigit() for ch in r)]
    if (
        digit_reads
        and all(
            re.search(r"[^\d\s,.()%]", r) for r in digit_reads
        )
        and re.fullmatch(r"(?:19|20)\d{2}", voted)
    ):
        return False
    return True


def _one_delete(a: str, b: str) -> bool:
    """True when deleting ONE digit from ``a`` yields ``b`` (len(a)==len(b)+1).

    A phantom-digit twin («10778138» carrying a ghost leading digit over
    the true «1778138») folds into its shorter sibling by exactly one
    deletion — real different amounts never do.
    """
    if len(a) != len(b) + 1:
        return False
    i = 0
    n = len(b)
    while i < n and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i:]


def _slot_text(cands: list) -> str:
    """Vote one slot's same-cell reads: families + per-place majority.

    Reads of one cell form a FAMILY when one digit string contains the
    other (fragments «2051»/«529» of «2051529», truncated «605129» of
    «6051290», a poisoned «10778138» carrying a phantom leading digit
    over the true «1778138"). The winning family = most reads. Within it
    the value is rebuilt by PLACE VALUE (digits aligned from the RIGHT —
    the units place is what every read agrees on):
    - short fragments («2051», «529», «1352») abstain: only reads within
      one digit of the family's longest vote (fragments would flip the
      low places toward their own truncation point);
    - a place carried by < 60% of the voters is dropped — that kills the
      phantom leading digit of «10778138» (supported only by the bin170/
      bin200 misreads) while keeping every place all scanners saw;
    - remaining thin leading places (support < 3/4 of the place below)
      are dropped too: real digits repeat across independent bands,
      phantom ones do not.
    Parens (negatives) ride any voter that matches the winner.
    LABEL cells are joined in READING order (Arabic words right-to-left)
    — the winning text of a label slot must read «تكلفة الإيرادات», not
    the x-ascending «الإيرادات تكلفة», or the classifier misfiles the
    whole row.
    """
    texts = []
    for cw in cands:
        joined = " ".join(w[4] for w in cw).strip()
        if _has_arabic(joined):
            cw = sorted(cw, key=lambda w: -w[0])  # Arabic reads right-to-left
        texts.append(" ".join(w[4] for w in cw).strip())
    dig = {t: re.sub(r"\D", "", t) for t in texts}
    families: list[dict] = []  # {digits, members}
    for t in sorted(texts, key=lambda t: len(dig[t])):
        d = dig[t]
        if not d:
            continue
        hit = None
        for f in families:
            # containment vs EVERY family digit seen (the stored maximum
            # misses: «10778138» contains «778138» but NOT the shorter
            # «1778138» that seeded the family — only member-wise does
            # the poisoned read join its true-read family)
            if any(d in fd or fd in d for fd in {f["digits"], *(dig[m] for m in f["members"])}):
                hit = f
                break
        if hit is None:
            families.append({"digits": d, "members": [t]})
        else:
            if len(d) > len(hit["digits"]):
                hit["digits"] = d
            hit["members"].append(t)
    if not families:
        return max(texts, key=len) if texts else ""
    # The family with the most reads wins, but its longest member must
    # be plausible FIRST: a poisoned read with a phantom leading digit
    # («10778138» over «1778138», «(207090538)» over two separate cells
    # that merged) seeds a too-long family. When the longest read's
    # HIGH place carries a thin majority (the phantom), prefer the
    # next-longest read instead — this recursion peels phantom digits.
    def place_votes(ds: list[str], width: int) -> list[tuple[str, int]]:
        out = []
        for k in range(width):
            votes: Counter[str] = Counter(
                d[len(d) - 1 - k] for d in ds if len(d) > k
            )
            if not votes:
                break
            digit, n = votes.most_common(1)[0]
            out.append((digit, n))
        return out

    def build(f: dict) -> str:
        members = f["members"]
        m_dig = {t: dig[t] for t in members}
        n_all = len(m_dig)
        order = sorted(set(m_dig.values()), key=len, reverse=True)
        longest = order[0]
        for cand_len in range(len(longest), max(3, len(longest) - 4) - 1, -1):
            voters = [d for d in m_dig.values() if len(d) >= cand_len]
            if not voters:
                continue
            width = max(len(d) for d in voters)
            places = place_votes(voters, width)
            if not places:
                continue
            # the top place must convince: a phantom leading digit is
            # backed by a minority of the readers
            if places[-1][1] < 0.6 * len(voters):
                continue
            # a truncated read keeps its own top place («605129» of
            # «6051290»): that place's majority is real even though the
            # longer read outnumbers it — drop only when it wins on a
            # minority of BOTH the full-length and all voters
            while len(places) > 1 and (
                places[-1][1] < places[-2][1] * 0.75
                and places[-1][1] < 0.6 * n_all
            ):
                places.pop()
            digits = "".join(d for d, _ in places)[::-1]
            tail = digits[-4:]
            for t in members:
                if "(" in t and dig[t].endswith(tail):
                    return f"({digits})"
            return digits
        # fall back to the family's most frequent exact read
        counts = Counter(members)
        return counts.most_common(1)[0][0]

    top_count = max(len(f["members"]) for f in families)
    tied = [f for f in families if len(f["members"]) == top_count]
    if len(tied) > 1:
        # Two families tie on read count and containment joined neither
        # («1778138» ×2 vs «10778138» ×2). A tied family that folds into
        # a shorter tied sibling by deleting ONE digit is its phantom twin
        # — the phantom is dropped and the shorter family wins the tie; on
        # an unexplained disagreement the longer read keeps winning.
        tied = [
            f for f in tied
            if not any(
                g is not f
                and len(g["digits"]) == len(f["digits"]) - 1
                and _one_delete(f["digits"], g["digits"])
                for g in tied
            )
        ]
    best = max(tied, key=lambda f: (len(f["members"]), len(f["digits"])))
    return build(best)


def _ocr_text_line(words: list) -> str:
    """One prose line with words back in reading order.

    Windows OCR emits each word's characters in logical order but the
    words of a line left-to-right (visual). Arabic reads right-to-left,
    so the word order is reversed when the line carries Arabic letters.
    """
    ordered = [w[4] for w in sorted(words, key=lambda w: w[0])]
    line = " ".join(ordered)
    if _has_arabic(line):
        line = " ".join(reversed(ordered))
    return _normalize_digits(line)


def _ocr_pdf_fallback(
    path: Path, dpi: int = 0, progress: dict | None = None
) -> tuple[list, list]:
    """Third engine: Windows OCR (winsdk) for scanned PDFs.

    Every page is rendered to PNG with PyMuPDF (≤ ~2500 px so the Windows
    OCR engine accepts it), recognised with the installed Arabic engine
    (falling back to English), and the word boxes are turned into the same
    table/text shape as the PyMuPDF fallback. Returns ([], []) when OCR is
    unavailable (no winsdk / no OCR language) — the upload layer then keeps
    reporting the scanned-file hint. ``dpi`` overrides the module default
    (the cascade's second-opinion attempt reads at a coarser scale).
    """
    try:
        import pymupdf
    except Exception:
        return [], []
    engine = _thread_ocr_engine()
    if not engine:
        return [], []
    try:
        doc = pymupdf.open(str(path))
    except Exception:
        return [], []
    tmp_paths: list[str] = []
    page_cells: list[list] = []  # pooled VARIANT CELLS per page
    try:
        # PAGES RUN IN PARALLEL: each worker thread gets its own OCR engine
        # (see _thread_ocr_engine — shared engines silently drop reads) and
        # renders its own page from its OWN document handle (pymupdf
        # documents are not thread-safe). Render scale, the full-page pass
        # and the banded variants are IDENTICAL to the sequential path —
        # only the wall-clock order changes, so recognition quality and the
        # voted output are unchanged. Pages beyond _OCR_MAX_PAGES are cut.
        pages = list(doc)[:_OCR_MAX_PAGES]
        # With a live progress reader (the upload path) the request thread
        # parks on the worker pool anyway, so the cap is the only thing
        # throttling recognition — lift it to the machine's CPU count.
        cap = _parallel_cap() if progress is not None else _OCR_PARALLEL_PAGES
        workers = max(1, min(cap, len(pages)))
        if workers > 1:
            import concurrent.futures

            def _read_page(i: int) -> list:
                """ALL variant cells of page ``i`` — full-page probe read
                AND its banded variants — on one worker thread with its own
                engine and its own document handle (pymupdf pages cannot be
                touched from two threads, so every worker opens the file
                itself; the render is cheap, OCR is the bottleneck)."""
                _progress_set(progress, "ocr", i + 1, len(pages))
                with pymupdf.open(str(path)) as wdoc:
                    scale, full_words, cleaned = _render_page_seq(wdoc[i], dpi)
                    return _ocr_page_variants(
                        wdoc, i, full_words, scale, engine, dpi,
                        cleaned=cleaned,
                    )

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                page_cells = list(ex.map(_read_page, range(len(pages))))
        else:
            page_cells = []
            for i in range(len(pages)):
                _progress_set(progress, "ocr", i + 1, len(pages))
                scale, full_words, cleaned = _render_page_seq(pages[i], dpi)
                page_cells.append(
                    _ocr_page_variants(doc, i, full_words, scale, engine,
                                       dpi, cleaned=cleaned)
                )
    except Exception:
        return [], []
    finally:
        doc.close()
        for tmp in tmp_paths:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    tables: list = []
    texts: list = []
    collected = 0
    for page_no, variant_rows in enumerate(page_cells, start=1):
        if not variant_rows:
            continue
        grid = _ocr_grid_from_variants(variant_rows)
        numeric_rows = sum(
            1 for r in grid if any(any(ch.isdigit() for ch in c) for c in r)
        )
        if numeric_rows >= 3 and len(grid) >= 3:
            width = max(len(r) for r in grid)
            grid = [r + [""] * (width - len(r)) for r in grid]
            tables.append({
                "name": f"p{page_no}_ocr",
                "rows": [[_restore_visual_arabic(c) for c in r]
                         for r in grid[:MAX_ROWS]],
            })
        else:
            # prose page: one text line per MERGED row — the variant rows
            # already merged (same line read 3x lands in one row), so emit
            # each merged row's words in reading order
            lines: list[str] = []
            for merged_cells in _merge_variant_rows(variant_rows):
                words = [w for cw in merged_cells for w in cw]
                joined = " ".join(w[4] for w in words)
                words.sort(
                    key=lambda w: -w[0] if _has_arabic(joined) else w[0]
                )
                lines.append(" ".join(w[4] for w in words))
            text = "\n".join(lines)
            if text and collected < MAX_CHARS:
                texts.append(_restore_visual_arabic(text))
                collected += len(text)
    return tables, texts


def _render_page_seq(page: "pymupdf.Page", dpi: int = 0) -> tuple:
    """Sequential-path density probe: render one page, PREPROCESS it
    (grayscale → deskew → local binarization — see .preprocess), read it
    full-page, and return ``(scale, full_words, cleaned_image_or_None)``.
    The cleaned image rides along so the band variants crop from the SAME
    deskewed pixels as the full-page read — band/local coordinates stay
    consistent with the page geometry the vote merges on. ``None`` (or the
    original path behaviour) when preprocessing finds nothing to fix."""
    rect = page.rect
    longest = max(rect.width, rect.height) or 1.0
    scale = min((dpi or _OCR_DPI) / 72.0, _OCR_MAX_DIM / longest)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ocr_p")
    os.close(fd)
    pix.save(tmp)
    cleaned = None
    try:
        from PIL import Image
        from .preprocess import deskew_page_for_ocr
        img = Image.open(tmp)
        out, _meta = deskew_page_for_ocr(img)
        if out is not None:
            out.save(tmp)            # the engine reads the DESKEWED page
            cleaned = out
    except Exception:
        cleaned = None               # engine reads the raw render
    try:
        engine = _thread_ocr_engine()
        if not engine:
            return scale, [], cleaned
        words = _run_coro_blocking(_ocr_png_files([tmp], engine))[0]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return scale, words, cleaned


def _ocr_page_variants(doc, page_no: int, full_words: list, scale: float,
                       engine, dpi: int = 0, cleaned=None) -> list:
    """All VARIANT CELLS of ONE page: the full-page probe read + the banded
    binarized variants for dense pages (identical geometry to the original
    sequential loop — the band shift, overlap and thresholds are unchanged).
    When ``cleaned`` (the preprocessed page image) is given, bands crop
    from IT — pixel-identical to what the full-page read saw, so band-local
    coordinates shift into the same page space. Runs on its own thread with
    its own engine when called from the parallel path; called inline (same
    thread) on the sequential path."""
    page = doc[page_no]
    rect = page.rect
    page_h_px = rect.height * scale
    variants: list[tuple[float, list]] = [(0.0, full_words)]
    dense = sum(
        sum(ch.isdigit() for ch in txt) for _, _, _, _, txt, _ in full_words
    )
    eng = _thread_ocr_engine() or engine
    if dense >= 30:
        y0 = 0.0
        while y0 < page_h_px - 10:
            y1 = min(y0 + _OCR_BAND_H, page_h_px)
            band_pngs: list[str] = []
            if cleaned is not None:
                # bands from the CLEANED page image (PIL crop) — same
                # deskewed pixels the full-page read used
                fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ocr_b")
                os.close(fd)
                cleaned.crop((0, int(y0), cleaned.width, int(y1))).save(tmp)
                band_pngs.append(tmp)
            else:
                clip = pymupdf.Rect(0, y0 / scale, rect.width, y1 / scale)
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False
                )
                fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ocr_b")
                os.close(fd)
                pix.save(tmp)
                band_pngs.append(tmp)
            try:
                from PIL import Image
                img = Image.open(tmp).convert("L")
                for thr in _OCR_BIN_THRESHOLDS:
                    b_tmp = f"{tmp}.{thr}.png"
                    img.point(lambda p: 255 if p > thr else 0).save(b_tmp)
                    band_pngs.append(b_tmp)
                # LOCAL binarization variant: pulls faint digits out of
                # shaded/zebra bands no single fixed threshold recovers —
                # one more candidate in the per-cell vote (the read with
                # the most digits wins, so a weak extra read never poisons
                # a strong consensus)
                lb_tmp = f"{tmp}.local.png"
                binarize_local(img).save(lb_tmp)
                band_pngs.append(lb_tmp)
            except Exception:
                pass  # grayscale variant only when PIL is unavailable
            try:
                band_words_all = _run_coro_blocking(
                    _ocr_png_files(band_pngs, eng)
                )
            finally:
                for t in band_pngs:
                    try:
                        os.unlink(t)
                    except OSError:
                        pass
            for ws in band_words_all:
                # shift band-local y into page coordinates
                variants.append((y0, ws))
            if y1 >= page_h_px - 10:
                break
            y0 = y1 - _OCR_BAND_OVERLAP
    variant_rows: list = []
    for y_off, ws in variants:
        # cell-split each variant on its own geometry so its reads stay
        # intact (word-joining across variants would multiply every word
        # inside a cell); band-local y shifts into page coordinates
        variant_rows.extend(
            [
                [
                    [(w[0], w[1] + y_off, w[2], w[3], w[4], w[5]) for w in cw]
                    for cw in cells
                ]
                for cells in _variant_cells(ws)
            ]
        )
    return variant_rows
