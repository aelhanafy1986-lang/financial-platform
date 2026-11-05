"""Image parser: client-uploaded photos/scans (JPG/PNG) of financial
statements.

A phone photo of a statement has no text layer — the image IS the page —
so the Windows-OCR pipeline the scanned-PDF fallback uses runs directly
on the pixels. Methodology (same referee as the PDF cascade): several
READ ATTEMPTS (native scale + an upsampled pass for small images, each
with the binarization variants) are scored by ``.quality.score_extraction``
and the STRONGEST wins — small thumbnails read weakly at native size and
recover at 1.6×, while big photos are already inside the engine's range.
"""

from pathlib import Path

import os
import tempfile

MAX_ROWS = 300
MAX_CHARS = 60_000

# same render-size budget the PDF OCR path uses (Windows OCR accepts up
# to 10,000 px; 400 dpi of an A4 page ≈ 3300 px, phone shots are larger)
_OCR_MAX_DIM = 10_000
_OCR_BIN_THRESHOLDS = (128, 170)
# images smaller than this read weakly (the engine has too few pixels per
# glyph) — an upsampled second attempt recovers them
_UPSCALE_TRIGGER = 1800
_UPSCALE_FACTOR = 1.6


def _normalize_digits(text: str) -> str:
    from .pdf_parser import _normalize_digits as _n
    return _n(text)


def _make_engine():
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language

    for tag in ("ar-SA", "en-US"):
        try:
            engine = OcrEngine.try_create_from_language(Language(tag))
        except Exception:
            engine = None
        if engine:
            return engine
    return None


def _ocr_pass(img, engine) -> dict:
    """One read attempt: OCR the (already-sized) image — a full pass plus
    binarized variants — and build the voted grid/table shape."""
    from .pdf_parser import (
        _restore_visual_arabic,
        _variant_cells,
        _merge_variant_rows,
        _ocr_grid_from_variants,
        _run_coro_blocking,
        _ocr_png_files,
        _has_arabic,
    )
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="img_ocr")
    os.close(fd)
    try:
        img.save(tmp)
        variants: list[list] = []  # (y_offset, words) — one full pass + bins
        try:
            full = _run_coro_blocking(_ocr_png_files([tmp], engine))[0]
        except Exception:
            full = []
        variants.append((0.0, full))
        try:
            from PIL import Image as _I

            gray = _I.open(tmp).convert("L")
            for thr in _OCR_BIN_THRESHOLDS:
                b_tmp = f"{tmp}.{thr}.png"
                gray.point(lambda p: 255 if p > thr else 0).save(b_tmp)
                try:
                    words = _run_coro_blocking(_ocr_png_files([b_tmp], engine))[0]
                except Exception:
                    words = []
                variants.append((0.0, words))
                try:
                    os.unlink(b_tmp)
                except OSError:
                    pass
        except Exception:
            pass  # grayscale-only when PIL variants are unavailable
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    variant_rows: list = []
    for y_off, ws in variants:
        if not ws:
            continue
        variant_rows.extend(
            [
                [[(w[0], w[1] + y_off, w[2], w[3], w[4], w[5]) for w in cw]
                 for cw in cells]
                for cells in _variant_cells(ws)
            ]
        )
    if not variant_rows:
        return {"tables": [], "texts": []}

    grid = _ocr_grid_from_variants(variant_rows)
    numeric_rows = sum(
        1 for r in grid if any(any(ch.isdigit() for ch in c) for c in r)
    )
    if numeric_rows >= 3 and len(grid) >= 3:
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]
        return {"tables": [{
            "name": "image_ocr",
            "rows": [[_restore_visual_arabic(c) for c in r]
                     for r in grid[:MAX_ROWS]],
        }], "texts": []}
    # prose image: one text line per merged row in reading order
    texts: list = []
    collected = 0
    for merged_cells in _merge_variant_rows(variant_rows):
        words = [w for cw in merged_cells for w in cw]
        if not words:
            continue
        joined = " ".join(w[4] for w in words)
        words.sort(key=lambda w: -w[0] if _has_arabic(joined) else w[0])
        line = " ".join(w[4] for w in words)
        if line and collected < MAX_CHARS:
            texts.append(_restore_visual_arabic(line))
            collected += len(line)
    return {"tables": [], "texts": texts}


def parse_image(path: Path) -> dict:
    """OCR an uploaded image into the standard tables/texts shape — the
    strongest of the read attempts wins (scored by .quality)."""
    from PIL import Image

    try:
        from winsdk.windows.media.ocr import OcrEngine  # noqa: F401
    except Exception:
        return {"tables": [], "texts": [], "ocr_used": False,
                "quality": {"score": 0.0, "labeled_rows": 0,
                            "numeric_rows": 0, "concepts": [], "spine": False}}

    engine = _make_engine()
    if not engine:
        return {"tables": [], "texts": [], "ocr_used": False,
                "quality": {"score": 0.0, "labeled_rows": 0,
                            "numeric_rows": 0, "concepts": [], "spine": False}}

    try:
        img = Image.open(str(path))
        img.load()
    except Exception:
        return {"tables": [], "texts": [], "ocr_used": False,
                "quality": {"score": 0.0, "labeled_rows": 0,
                            "numeric_rows": 0, "concepts": [], "spine": False}}

    # downscale into the engine's accepted range, keep colour (binarization
    # variants are generated per attempt below, like the PDF path)
    w, h = img.size
    longest = max(w, h) or 1
    if longest > _OCR_MAX_DIM:
        scale = _OCR_MAX_DIM / longest
        img = img.resize((int(w * scale), int(h * scale)))
        w, h = img.size
        longest = max(w, h) or 1

    # ---- PREPROCESS as an EXTRA CANDIDATE: deskew + local binarization
    # repair tilted / shaded pages (a skewed baseline smears rows across
    # two engine lines — the vote tears cost rows apart), but the ORIGINAL
    # always competes too: the score referee (.quality) picks the strongest
    # read, so preprocessing can only ADD a winner, never lose one.
    pre_meta: dict | None = None
    attempts: list = [img]
    try:
        from .preprocess import preprocess_for_ocr

        cleaned, pre_meta = preprocess_for_ocr(img)
        if cleaned is not None:
            attempts.insert(0, cleaned)
    except Exception:
        pre_meta = None

    if longest < _UPSCALE_TRIGGER:
        # small thumbnail: an upsampled pass gives the engine enough
        # pixels per glyph to read the amounts
        attempts.append(img.resize(
            (int(w * _UPSCALE_FACTOR), int(h * _UPSCALE_FACTOR)),
            Image.LANCZOS,
        ))

    from .quality import score_extraction

    best: dict | None = None
    best_score: dict | None = None
    for attempt in attempts:
        cand = _ocr_pass(attempt, engine)
        sc = score_extraction(cand["tables"], cand["texts"])
        if best_score is None or sc["score"] > best_score["score"]:
            best, best_score = cand, sc

    best["ocr_used"] = True
    best["quality"] = best_score
    if pre_meta:
        # transparency: what preprocessing actually did to the page
        best["preprocess"] = pre_meta
    return best
