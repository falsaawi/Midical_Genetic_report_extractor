"""Text-cleaning helpers shared by the parsers."""

from __future__ import annotations

import re
from typing import List, Optional


def collapse_ws(text: str) -> str:
    """Collapse runs of whitespace (incl. newlines) into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def norm_lines(text: str) -> List[str]:
    """Return non-empty, stripped lines."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# Repeated header / footer boilerplate that CENTOGENE stamps on every page.
_BOILERPLATE_PATTERNS = [
    # Legacy continuation-page header echo: a repeated "Patient name: ..." block
    # immediately followed by the CLIA footer on pages 2+.  Must precede the
    # standalone CLIA pattern below (it consumes the CLIA text it depends on).
    re.compile(
        r"Patient name:(?:(?!Patient name:)[\s\S])*?CLIA registration[\s\S]*?centogene\.com\.",
        re.IGNORECASE,
    ),
    # Contact-details / CLIA block (spans many lines, ends on a centogene.com email)
    re.compile(
        r">?\s*Contact Details.*?(?:support|dmqc|customer\.support)@cen\s*togene\.com\.",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"CLIA registration.*?(?:support|dmqc|customer\.support)@cen\s*togene\.com\.",
        re.IGNORECASE | re.DOTALL,
    ),
    # Lab address strap-lines
    re.compile(r"CENTOGENE\s*(?:AG|GmbH)\s*[••].*?Germany", re.IGNORECASE | re.DOTALL),
    re.compile(r"Centogene AG\s*[••]\s*Schillingallee.*?Germany", re.IGNORECASE | re.DOTALL),
    # Page markers
    re.compile(r"Page:\s*\d+\s*of\s*\d+", re.IGNORECASE),
]


def strip_boilerplate(text: str) -> str:
    """Remove repeated page headers/footers so section slicing is reliable."""
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
    # Standalone "n / m" or bare page-number lines
    cleaned = []
    for ln in text.splitlines():
        s = ln.strip()
        if re.fullmatch(r"\d+\s*/\s*\d+", s):
            continue
        if re.fullmatch(r"\d{1,2}", s):
            continue
        cleaned.append(ln)
    return "\n".join(cleaned)


def first(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    try:
        val = m.group(group)
    except IndexError:
        return None
    return collapse_ws(val) if val else None


def section(text: str, start: str, stops: List[str], flags: int = re.IGNORECASE) -> Optional[str]:
    """Return the text between heading ``start`` and the earliest of ``stops``."""
    m = re.search(start, text, flags)
    if not m:
        return None
    body = text[m.end():]
    end = len(body)
    for stop in stops:
        sm = re.search(stop, body, flags)
        if sm and sm.start() < end:
            end = sm.start()
    result = collapse_ws(body[:end])
    return result or None
