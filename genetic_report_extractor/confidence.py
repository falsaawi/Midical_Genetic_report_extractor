"""Confidence scoring for extracted records.

At 70k-report scale you cannot eyeball every record, so each one gets a cheap,
deterministic confidence score. Low-confidence records are routed to a review
queue instead of being trusted blindly. The score rewards the presence of the
fields that matter and that a correct CENTOGENE extraction should always yield.
"""

from __future__ import annotations

from typing import List, Tuple

from .schema import GeneticReport

# (weight, label, predicate)
_CHECKS = [
    (2, "template recognised", lambda r: r.template_generation not in (None, "unknown")),
    (1, "patient number", lambda r: bool(r.patient.patient_no)),
    (1, "patient name", lambda r: bool(r.patient.full_name)),
    (1, "sex", lambda r: bool(r.patient.sex)),
    (1, "date of birth", lambda r: bool(r.patient.date_of_birth)),
    (1, "ordering doctor", lambda r: bool(r.ordering_provider.physician)),
    (2, "at least one variant", lambda r: len(r.variants) > 0),
    (2, "variant gene", lambda r: bool(r.variants and r.variants[0].gene)),
    (2, "variant cDNA change", lambda r: bool(r.variants and r.variants[0].cdna_change)),
    (1, "variant classification", lambda r: bool(r.variants and r.variants[0].classification)),
    (1, "overall result", lambda r: bool(r.overall_result)),
]
_MAX = sum(w for w, _, _ in _CHECKS)

# A negative-result report legitimately has no variant; don't penalise it.
_NEGATIVE_MARKERS = ("no pathogenic", "negative", "no clinically relevant",
                     "no reportable", "no relevant variant")


def score_report(report: GeneticReport) -> dict:
    """Return ``{score, max, ratio, level, missing, flags}`` for one record."""
    negative = bool(report.overall_result) and any(
        m in report.overall_result.lower() for m in _NEGATIVE_MARKERS
    )
    earned, missing = 0, []
    max_score = _MAX
    for weight, label, ok in _CHECKS:
        # Variant-related checks don't count against a genuine negative report.
        variant_check = label.startswith("variant") or label == "at least one variant"
        if negative and variant_check:
            max_score -= weight
            continue
        if ok(report):
            earned += weight
        else:
            missing.append(label)

    ratio = earned / max_score if max_score else 0.0
    level = "high" if ratio >= 0.85 else "medium" if ratio >= 0.6 else "low"

    flags = []
    if report.ocr_used:
        flags.append("ocr")           # OCR text is noisier — worth a human glance
    if negative:
        flags.append("negative-result")
    if report.patients_in_source and report.patients_in_source > 1:
        flags.append("multi-patient-split")

    return {
        "score": earned,
        "max": max_score,
        "ratio": round(ratio, 3),
        "level": level,
        "missing": missing,
        "flags": flags,
        "needs_review": level != "high" or bool(report.ocr_used),
    }


def summarise(scores: List[dict]) -> dict:
    """Aggregate counts across many score dicts."""
    out = {"high": 0, "medium": 0, "low": 0, "needs_review": 0, "ocr": 0}
    for s in scores:
        out[s["level"]] += 1
        if s["needs_review"]:
            out["needs_review"] += 1
        if "ocr" in s["flags"]:
            out["ocr"] += 1
    return out
