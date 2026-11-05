from pathlib import Path

from .csv_parser import parse_csv
from .excel import parse_excel
from .image_parser import parse_image
from .pdf_parser import parse_pdf
from .pptx_parser import parse_pptx
from .word import parse_word

PARSERS = {
    ".xlsx": parse_excel,
    ".xlsm": parse_excel,
    ".csv": parse_csv,
    ".docx": parse_word,
    ".pdf": parse_pdf,
    ".pptx": parse_pptx,
    ".png": parse_image,
    ".jpg": parse_image,
    ".jpeg": parse_image,
}


def parse_file(path: Path, progress: dict | None = None) -> dict:
    """Return {"tables": [...], "texts": [...]} for ``path``.

    ``progress`` (optional) is a shared dict the PDF parser ticks with the
    live OCR stage ("pdf" → "ocr" with page N of total) so a concurrent
    reader can drive the frontend's progress indicator. Other parsers
    ignore it.
    """
    parser = PARSERS.get(path.suffix.lower())
    if not parser:
        raise ValueError(f"unsupported file type: {path.suffix}")
    if progress is not None and path.suffix.lower() == ".pdf":
        return parser(path, progress=progress)
    return parser(path)
