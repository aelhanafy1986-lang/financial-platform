"""Render frontend/public/logo.svg to logo.png for embedding in Excel/PDF.

Uses cairosvg when available; falls back to a hand-drawn PIL render that
mirrors the SVG (teal rounded square, white bars + arrow + dot).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "frontend" / "public" / "logo.svg"
PNG = ROOT / "frontend" / "public" / "logo.png"


def _via_cairosvg() -> bool:
    try:
        import cairosvg

        cairosvg.svg2png(url=str(SVG), write_to=str(PNG), output_width=256, output_height=256)
        return True
    except Exception:
        return False


def _via_svglib() -> bool:
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM

        drawing = svg2rlg(str(SVG))
        drawing.scale(2, 2)
        drawing.width, drawing.height = drawing.width * 2, drawing.height * 2
        renderPM.drawToFile(drawing, str(PNG), fmt="PNG")
        return True
    except Exception:
        return False


def _via_pil() -> bool:
    from PIL import Image, ImageDraw

    S = 4  # supersample
    W = H = 128 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def lerp(a, b, t):
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

    top, bottom = (20, 184, 166), (15, 118, 110)
    # vertical gradient inside a rounded rect
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([4 * S, 4 * S, 124 * S, 124 * S], radius=28 * S, fill=255)
    grad = Image.new("RGBA", (W, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        gd.line([(0, y), (W, y)], fill=lerp(top, bottom, y / H) + (255,))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    def rect(x, y, w, h, alpha, r=3 * S):
        d.rounded_rectangle(
            [x * S, y * S, (x + w) * S, (y + h) * S],
            radius=r, fill=(255, 255, 255, int(255 * alpha)),
        )

    # ascending bars
    rect(30, 78, 12, 20, 0.85)
    rect(48, 66, 12, 32, 0.92)
    rect(66, 54, 12, 44, 1.0)
    # upward arrow (two triangles approximating the SVG path)
    d.polygon([(84 * S, 66 * S), (96 * S, 40 * S), (104 * S, 60 * S), (94 * S, 52 * S)],
              fill=(255, 255, 255, int(255 * 0.95)))
    d.polygon([(94 * S, 52 * S), (104 * S, 60 * S), (108 * S, 34 * S), (88 * S, 30 * S)],
              fill=(255, 255, 255, int(255 * 0.75)))
    # dot
    d.ellipse([28 * S, 36 * S, 40 * S, 48 * S], fill=(255, 255, 255, int(255 * 0.9)))

    img.resize((128, 128), Image.LANCZOS).save(PNG)
    return True


if __name__ == "__main__":
    ok = _via_cairosvg() or _via_svglib() or _via_pil()
    print("logo.png:", "written" if ok and PNG.exists() else "FAILED")
    raise SystemExit(0 if ok else 1)
