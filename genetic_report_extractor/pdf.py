"""PDF text extraction helpers.

We rely on PyMuPDF (``fitz``) for fast, layout-aware text extraction.  All three
sample reports carry an embedded text layer, so no OCR is required.  A helper is
provided to fall back to OCR-style guidance if a scanned PDF is ever supplied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

import fitz  # PyMuPDF

# Non-breaking / exotic spaces that CENTOGENE PDFs use between words; normalising
# them to plain spaces is essential for the regex-based parser to work.
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\ufeff]")
_UNICODE_SPACE = re.compile("[\xa0\u2000-\u200a\u202f\u205f\u3000]")


def normalize_text(text: str) -> str:
    text = _ZERO_WIDTH.sub("", text)
    text = _UNICODE_SPACE.sub(" ", text)
    return text


@dataclass
class ExtractedDocument:
    path: str
    page_texts: List[str]

    @property
    def text(self) -> str:
        """Full document text with form-feed separators between pages."""
        return "\n".join(self.page_texts)

    @property
    def num_pages(self) -> int:
        return len(self.page_texts)


def extract_document(path: str) -> ExtractedDocument:
    """Return the text of every page in ``path``.

    Raises ``ValueError`` if the document has effectively no text layer, which
    is the signal that OCR would be required.
    """
    doc = fitz.open(path)
    try:
        pages = [normalize_text(page.get_text("text")) for page in doc]
    finally:
        doc.close()

    if sum(len(p.strip()) for p in pages) < 50:
        raise ValueError(
            f"{path}: no extractable text layer found — the PDF is likely a "
            "scan and would need OCR (e.g. tesseract) before parsing."
        )
    return ExtractedDocument(path=path, page_texts=pages)
