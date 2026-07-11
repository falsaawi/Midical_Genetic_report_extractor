"""Top-level orchestration: PDF -> list of structured per-patient reports."""

from __future__ import annotations

from typing import List

from .pdf import extract_document
from .parser import parse_document
from .schema import GeneticReport


def extract_from_pdf(path: str, ocr: bool = False, ocr_lang: str = "eng") -> List[GeneticReport]:
    """Extract one ``GeneticReport`` per patient from a single PDF.

    Set ``ocr=True`` to fall back to offline Tesseract OCR for scanned/image-only
    PDFs. Each returned report carries ``ocr_used`` so callers can flag it.
    """
    doc = extract_document(path, ocr=ocr, ocr_lang=ocr_lang)
    reports = parse_document(doc)
    for r in reports:
        r.ocr_used = doc.ocr_used
    return reports


def extract_reports(paths: List[str]) -> List[GeneticReport]:
    """Extract structured reports from many PDFs (flattened)."""
    out: List[GeneticReport] = []
    for p in paths:
        out.extend(extract_from_pdf(p))
    return out
