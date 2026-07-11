"""Top-level orchestration: PDF -> list of structured per-patient reports."""

from __future__ import annotations

from typing import List

from .pdf import extract_document
from .parser import parse_document
from .schema import GeneticReport


def extract_from_pdf(path: str) -> List[GeneticReport]:
    """Extract one ``GeneticReport`` per patient from a single PDF."""
    doc = extract_document(path)
    return parse_document(doc)


def extract_reports(paths: List[str]) -> List[GeneticReport]:
    """Extract structured reports from many PDFs (flattened)."""
    out: List[GeneticReport] = []
    for p in paths:
        out.extend(extract_from_pdf(p))
    return out
