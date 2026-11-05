from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

MAX_TEXTS = 500


def _walk_shapes(shapes, texts: list, slide_no: int) -> None:
    for shape in shapes:
        if len(texts) >= MAX_TEXTS:
            return
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            _walk_shapes(shape.shapes, texts, slide_no)
            continue
        if shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                texts.append(f"[slide {slide_no}] {text}")
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = []
            for row in shape.table.rows:
                rows.append([cell.text.strip() for cell in row.cells])
            texts.append(f"[slide {slide_no}] __TABLE__{rows!r}")


def parse_pptx(path: Path) -> dict:
    prs = Presentation(str(path))
    texts: list = []
    for slide_no, slide in enumerate(prs.slides, start=1):
        _walk_shapes(slide.shapes, texts, slide_no)
    return {"tables": [], "texts": texts}
