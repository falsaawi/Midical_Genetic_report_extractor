"""Medical genetic-report extractor.

Turns CENTOGENE genetic-testing report PDFs into structured records, one per
patient (multi-patient reports are automatically split).
"""

from .extractor import extract_reports, extract_from_pdf
from .schema import GeneticReport

__all__ = ["extract_reports", "extract_from_pdf", "GeneticReport"]
__version__ = "0.1.0"
