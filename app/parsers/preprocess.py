# -*- coding: utf-8 -*-
"""OCR image preprocessing — المعالجة المسبقة قبل المحرك.

Phone photos and cheap scans of statements (تقارير المراعي class: shaded
zebra rows, weak toner, 1–3° camera tilt) break the OCR engine in ways
that more read attempts alone never recover: a skewed baseline smears each
row across two engine lines (the row band vote then splits every cost row
in half), and low-contrast shaded bands collapse into solid gray under
fixed-threshold binarization — the exact «تكلفة الإيرادات rows vanish»
failure the band+binarization methodology works around.

This module fixes the PAGE first so the existing read attempts (bands,
binarization variants, per-cell voting) run on clean input:

- grayscale + autocontrast: zebra shading flattens into background;
- global deskew (Radon-like projection profile over ±6°, numpy): text
  rows align with the engine's line detection — the vote stops tearing
  cost rows apart;
- Sauvola-style LOCAL binarization (mean+std window, PIL+numpy): pulls
  faint digits out of shaded bands where any single fixed threshold
  either washes the ink away or blacks the band out;
- guarded adaptive-contrast fallback (pass-through when the histogram is
  already wide): sharpens faded scans without touching healthy ones.

Everything degrades safely: on any internal failure the ORIGINAL image
falls through unchanged, and each stage is applied only when it measurably
changes the image — preprocessing can never make a page worse than the
engine's own no-op path. The winsdk Windows-OCR engine (OcrEngine.
max_image_dimension 2600) takes the CLEANED page as-is.
"""

from __future__ import annotations

import io

import numpy as np

# deskew search window: statements scanned level sit within ±2°; phone
# shots rarely exceed 6°. Angles beyond that belong to the crop-rotation
# problem (a different fix), not baseline tilt.
_SKEW_MAX_DEG = 6.0
_SKEW_STEP_DEG = 0.25
# a real tilt shows as a sharp projection peak; noise floor ≈ flat. The
# score gap demanded before rotating anything — without it, clean pages
# get 0.25° nudges that waste a render and can smear thin glyphs.
_SKEW_MIN_GAIN = 1.15

# Sauvola-ish local mean thresholding: window ~2 glyph heights, ink =
# pixel < mean − k·std, with a CONTRAST floor so near-blank windows keep
# their background white instead of speckling (std of the window's pixel
# VALUES must exceed this; a flat 250-level window has std ≈ 0).
_LOCAL_WIN = 25
_LOCAL_K = 0.34
_LOCAL_WHITE = 245.0         # scanner white; anything close stays background
_LOCAL_MIN_INK = 60.0        # a pixel must be ≥60 levels under white to count as ink
_LOCAL_TILE = 256            # process in tiles to bound memory


def _to_gray(img):
    """PIL Image → L-mode Image."""
    return img.convert("L")


def _projection_score(arr: np.ndarray, angle_deg: float) -> float:
    """Peakedness of the INK projection profile at ``angle_deg``: rotate,
    binarize to an ink mask, sum ink per row. Total ink is invariant under
    rotation, so a level page (rows concentrated in crisp bands) maximises
    the profile's std while a tilted page smears the same ink across more
    rows and scores lower — the aligning angle is the argmax."""
    if angle_deg:
        arr = np.asarray(_rot_pil(arr, angle_deg))
    ink = (arr < 160).astype(np.float64)
    prof = ink.sum(axis=1)
    mean = float(prof.mean())
    return (float(prof.std()) / mean) if mean > 1e-6 else 0.0


def _rot_pil(arr: np.ndarray, angle_deg: float):
    from PIL import Image
    im = Image.fromarray(arr)
    return np.asarray(im.rotate(angle_deg, resample=Image.BILINEAR,
                                fillcolor=255))


def estimate_skew(img, probe_width: int = 700) -> float:
    """Global text-line tilt in degrees (−6..+6), 0.0 when effectively
    level. Downsamples to ``probe_width`` first — skew is a page property,
    a 700px probe measures it just as well and ~20× faster."""
    try:
        from PIL import Image
        g = _to_gray(img)
        w, h = g.size
        if max(w, h) < 64:
            return 0.0
        scale = probe_width / max(w, h)
        if scale < 1.0:
            g = g.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.BILINEAR)
        arr = np.asarray(g, dtype=np.uint8)
        base = _projection_score(arr, 0.0)
        best_angle, best_score = 0.0, base
        lo, hi = -_SKEW_MAX_DEG, _SKEW_MAX_DEG
        # coarse-to-fine: 0.5° steps then 0.25° refinement around the best
        for step in (0.5, 0.25):
            angles = np.arange(lo, hi + 1e-9, step)
            for a in angles:
                sc = _projection_score(arr, float(a))
                if sc > best_score:
                    best_angle, best_score = float(a), sc
            lo, hi = best_angle - step * 2, best_angle + step * 2
        # a REAL tilt: the best angle's profile is decisively more peaked
        # than the level one. Noise floor ≈ 1.0; demand a clear margin.
        if base > 1e-6 and best_score / base >= _SKEW_MIN_GAIN:
            return round(best_angle, 2)
        return 0.0
    except Exception:
        return 0.0


def deskew(img, angle_deg: float) -> object:
    """Rotate by ``angle_deg`` (the estimator's correction angle) on a
    white background, cropping-free. The fill colour must match the image
    mode — a tuple fill on an L-mode image raises and would silently skip
    the rotation."""
    if not angle_deg:
        return img
    try:
        from PIL import Image
        fill = 255 if img.mode in ("L", "1", "I", "F", "LA") \
            else (255, 255, 255)
        return img.rotate(angle_deg, resample=Image.BICUBIC, fillcolor=fill)
    except Exception:
        return img


def binarize_local(img) -> object:
    """Sauvola-style local binarization: threshold each pixel at its
    window's mean − k·std (window ~2 glyph heights, edge-padded), and keep
    near-blank windows as pure background. Outperforms every fixed
    threshold on shaded/gradient bands and faded toner."""
    try:
        from PIL import Image
        g = np.asarray(_to_gray(img), dtype=np.uint8)
        h, w = g.shape
        out = np.full((h, w), 255, dtype=np.uint8)
        win, k = _LOCAL_WIN, _LOCAL_K
        f = g.astype(np.float32)
        for y0 in range(0, h, _LOCAL_TILE):
            for x0 in range(0, w, _LOCAL_TILE):
                tile = f[y0:y0 + _LOCAL_TILE, x0:x0 + _LOCAL_TILE]
                # integral-image mean + std over the window (vectorised
                # per tile — cheap and exact enough for OCR ink)
                m = _box_mean(tile, win)
                s = np.sqrt(np.maximum(
                    _box_mean(tile * tile, win) - m * m, 0.0))
                # ink pixels must (a) sit below the LOCAL mean by k·std AND
                # (b) be meaningfully darker than the page white (local
                # contrast ≥ _LOCAL_MIN_INK) — without (b) the mean inside
                # a fully-inked window drifts down and the flood fills it
                mask = (tile < m - k * s) & (tile < _LOCAL_WHITE - _LOCAL_MIN_INK)
                sub = out[y0:y0 + _LOCAL_TILE, x0:x0 + _LOCAL_TILE]
                sub[mask] = 0
        return Image.fromarray(out, mode="L")
    except Exception:
        return img


def _box_mean(a: np.ndarray, win: int) -> np.ndarray:
    """Box filter (uniform, radius win//2) via a padded integral image —
    edge-padded, so every output pixel averages the same win×win window
    (the naive pad-then-average definition, verified against it)."""
    h, w = a.shape
    r = win // 2
    pad = np.pad(a, r, mode="edge")
    ii = pad.cumsum(0, dtype=np.float64).cumsum(1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    win2 = float(win * win)
    return ((ii[win:win + h, win:win + w]
             - ii[0:h, win:win + w]
             - ii[win:win + h, 0:w]
             + ii[0:h, 0:w]) / win2).astype(a.dtype)


def adaptive_contrast(img) -> object:
    """Contrast stretch for FADED scans — a page whose DARK INK (darkest
    1% of pixels) never drops meaningfully under the white point: toner-
    starved scans keep their whole ink mass above ~200 levels and the OCR
    engine's fixed thresholds miss it. Healthy pages (ink < 200) return
    ``(original, False)`` untouched — a white page WITH black text is the
    normal case, never «low contrast»."""
    try:
        from PIL import Image
        g = np.asarray(_to_gray(img), dtype=np.uint8)
        ink = np.percentile(g, 1)
        if ink <= 200.0:
            return img, False              # real ink exists: no-op
        lo, hi = float(g.min()), float(g.max())
        if hi - lo < 10.0:
            return img, False              # blank page: nothing to stretch
        lut = np.clip((g.astype(np.float32) - lo)
                      * (255.0 / (hi - lo or 1)), 0, 255).astype(np.uint8)
        return Image.fromarray(lut, mode="L"), True
    except Exception:
        return img, False


def deskew_page_for_ocr(img, skew_threshold_deg: float = 0.6):
    """The PDF path's entry point: DESKEW ONLY. Returns
    ``(deskewed_gray_image_or_None, meta)`` — ``None`` when the page is
    level (the engine then reads the raw render exactly as the proven
    band+threshold pipeline always has).

    Deliberately NOT binarizing here: the PDF cascade's fixed-threshold
    band variants were tuned against real scans, and replacing the engine's
    input pixels wholesale changed reads on healthy pages (a 2× upscaled
    render looks statistically «faded» though it reads perfectly). Tilt is
    a pure GEOMETRY defect — correcting it aligns rows without altering
    the read style; contrast defects are handled per-band instead (a local
    binarization VARIANT joins the fixed-threshold ones in the vote).
    """
    meta = {"skew": 0.0, "deskewed": False}
    try:
        if img is None:
            return None, meta
        angle = estimate_skew(img)
        meta["skew"] = angle
        if abs(angle) >= skew_threshold_deg:
            meta["deskewed"] = True
            # the estimate IS the correction angle: the search returns the
            # probe rotation that re-aligns the ink rows, and rotating the
            # page by the same amount is the same operation
            return deskew(_to_gray(img), angle), meta
        return None, meta
    except Exception:
        return None, meta


def preprocess_for_ocr(img, skew_threshold_deg: float = 0.6):
    """The IMAGE path's pipeline: grayscale → deskew → local binarization
    → adaptive contrast (guarded). Returns ``(preprocessed_image_or_None,
    meta)`` — the result competes as an EXTRA read attempt against the
    original (the score referee picks), never silently replacing it."""
    meta = {"skew": 0.0, "deskewed": False, "binarized": False,
            "contrast": False}
    try:
        if img is None:
            return None, meta
        angle = estimate_skew(img)
        meta["skew"] = angle
        work = img
        if abs(angle) >= skew_threshold_deg:
            work = deskew(_to_gray(work), angle)
            meta["deskewed"] = True
        else:
            work = _to_gray(work)
        work, stretched = adaptive_contrast(work)
        meta["contrast"] = stretched
        work = binarize_local(work)
        meta["binarized"] = True
        return work, meta
    except Exception:
        return None, meta


def preprocess_bytes(data: bytes):
    """Convenience wrapper for raw image bytes → (preprocessed PNG bytes
    or None, meta)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        out, meta = preprocess_for_ocr(img)
        if out is None:
            return None, meta
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue(), meta
    except Exception:
        return None, {"skew": 0.0, "deskewed": False, "binarized": False,
                      "contrast": False}
