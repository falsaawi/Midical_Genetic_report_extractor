"""PDF text extraction helpers.

We rely on PyMuPDF (``fitz``) for fast, layout-aware text extraction. Reports
that carry an embedded text layer (the common case) are read directly. For
scanned / image-only PDFs an **offline** OCR fallback is available via Tesseract
(``pytesseract`` + the ``tesseract`` binary) — no network, no cloud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import fitz  # PyMuPDF

# Non-breaking / exotic spaces that CENTOGENE PDFs use between words; normalising
# them to plain spaces is essential for the regex-based parser to work.
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\ufeff]")
_UNICODE_SPACE = re.compile("[\xa0\u2000-\u200a\u202f\u205f\u3000]")

# Below this many characters a page is treated as having no usable text layer.
_MIN_TEXT_CHARS = 50


def normalize_text(text: str) -> str:
    text = _ZERO_WIDTH.sub("", text)
    text = _UNICODE_SPACE.sub(" ", text)
    return text


@dataclass
class ExtractedDocument:
    path: str
    page_texts: List[str]
    ocr_used: bool = False

    @property
    def text(self) -> str:
        """Full document text, newline-separated between pages."""
        return "\n".join(self.page_texts)

    @property
    def num_pages(self) -> int:
        return len(self.page_texts)


class OCRUnavailable(RuntimeError):
    """Raised when a scan needs OCR but Tesseract/pytesseract are not installed."""


class NoTextLayer(ValueError):
    """Raised for an image-only PDF when OCR is disabled."""


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_pages(doc: "fitz.Document", dpi: int, lang: str) -> List[str]:
    import pytesseract
    from PIL import Image

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    out = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        out.append(normalize_text(pytesseract.image_to_string(img, lang=lang)))
    return out


def extract_document(
    path: str,
    ocr: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "eng",
    force_ocr: bool = False,
) -> ExtractedDocument:
    """Return the text of every page in ``path``.

    Parameters
    ----------
    ocr:
        When ``True``, image-only PDFs are OCR'd with Tesseract instead of
        raising. When ``False`` (default) a text-less PDF raises ``NoTextLayer``.
    force_ocr:
        OCR every page even if a text layer exists (useful for low-quality
        embedded text). Implies ``ocr``.
    """
    doc = fitz.open(path)
    try:
        pages = [normalize_text(page.get_text("text")) for page in doc]
        has_text = sum(len(p.strip()) for p in pages) >= _MIN_TEXT_CHARS

        if force_ocr or (not has_text and ocr):
            if not ocr_available():
                raise OCRUnavailable(
                    f"{path}: needs OCR but Tesseract is not available. Install the "
                    "'tesseract-ocr' package and 'pytesseract' (both run offline)."
                )
            pages = _ocr_pages(doc, ocr_dpi, ocr_lang)
            return ExtractedDocument(path=path, page_texts=pages, ocr_used=True)
    finally:
        doc.close()

    if sum(len(p.strip()) for p in pages) < _MIN_TEXT_CHARS:
        raise NoTextLayer(
            f"{path}: no extractable text layer found — the PDF is likely a scan. "
            "Re-run with ocr=True (offline Tesseract) to read it."
        )
    return ExtractedDocument(path=path, page_texts=pages, ocr_used=False)
