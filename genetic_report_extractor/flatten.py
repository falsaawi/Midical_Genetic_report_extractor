"""Flatten a ``GeneticReport`` into a single flat row of columns.

One patient == one row.  Nested objects become dotted column names
(``patient.full_name``); repeated variants are numbered
(``variant1.gene``, ``variant2.gene`` …).  This is the shape you want for a
spreadsheet / CSV / database load where every piece of information sits in its
own column.
"""

from __future__ import annotations

import csv
from typing import Dict, List

from .schema import GeneticReport

# Fixed leading column order (stable across reports); any extra keys are appended.
_COLUMN_ORDER = [
    "source_file", "template_generation", "lab_name", "report_type", "report_date",
    "patient.patient_no", "patient.first_name", "patient.last_name", "patient.full_name",
    "patient.sex", "patient.date_of_birth", "patient.your_ref", "patient.order_no",
    "ordering_provider.physician", "ordering_provider.institution",
    "ordering_provider.department", "ordering_provider.address", "ordering_provider.country",
    "laboratory.name", "laboratory.address", "laboratory.country",
    "laboratory.clia_registration", "laboratory.cap_registration",
    "laboratory.phone", "laboratory.fax", "laboratory.email", "laboratory.website",
    "sample.sample_type", "sample.collection_date", "sample.order_no",
    "sample.order_received_date",
    "test.tests_requested", "test.genome_build", "test.platform", "test.method_summary",
    "clinical.hpo_terms", "clinical.diagnosed_conditions", "clinical.age_of_manifestation",
    "clinical.family_history", "clinical.consanguinity", "clinical.free_text",
    "overall_result", "result_summary",
    "interpretation", "recommendations",
    "incidental_findings", "secondary_findings", "carriership_findings",
    "coverage.average_coverage", "coverage.pct_0x", "coverage.pct_ge_1x",
    "coverage.pct_ge_5x", "coverage.pct_ge_10x", "coverage.pct_ge_20x",
    "coverage.pct_ge_50x",
    "signatories",
    "patient_index", "patients_in_source",
]

_VARIANT_FIELDS = [
    "gene", "transcript", "cdna_change", "protein_change", "genomic_coordinate",
    "exon", "zygosity", "variant_type", "classification", "classification_class",
    "snp_identifier", "described_in", "pmid", "allele_frequency",
    "disorder.name", "disorder.omim", "disorder.inheritance", "disorder.additional",
]


def flatten_report(r: GeneticReport) -> Dict[str, str]:
    ci = r.clinical_information
    row: Dict[str, str] = {
        "source_file": r.source_file,
        "template_generation": r.template_generation,
        "lab_name": r.lab_name,
        "report_type": r.report_type,
        "report_date": r.report_date,
        "patient.patient_no": r.patient.patient_no,
        "patient.first_name": r.patient.first_name,
        "patient.last_name": r.patient.last_name,
        "patient.full_name": r.patient.full_name,
        "patient.sex": r.patient.sex,
        "patient.date_of_birth": r.patient.date_of_birth,
        "patient.your_ref": r.patient.your_ref,
        "patient.order_no": r.patient.order_no,
        "ordering_provider.physician": r.ordering_provider.physician,
        "ordering_provider.institution": r.ordering_provider.institution,
        "ordering_provider.department": r.ordering_provider.department,
        "ordering_provider.address": r.ordering_provider.address,
        "ordering_provider.country": r.ordering_provider.country,
        "laboratory.name": r.laboratory.name,
        "laboratory.address": r.laboratory.address,
        "laboratory.country": r.laboratory.country,
        "laboratory.clia_registration": r.laboratory.clia_registration,
        "laboratory.cap_registration": r.laboratory.cap_registration,
        "laboratory.phone": r.laboratory.phone,
        "laboratory.fax": r.laboratory.fax,
        "laboratory.email": r.laboratory.email,
        "laboratory.website": r.laboratory.website,
        "sample.sample_type": r.sample.sample_type,
        "sample.collection_date": r.sample.collection_date,
        "sample.order_no": r.sample.order_no,
        "sample.order_received_date": r.sample.order_received_date,
        "test.tests_requested": r.test.tests_requested,
        "test.genome_build": r.test.genome_build,
        "test.platform": r.test.platform,
        "test.method_summary": r.test.method_summary,
        "clinical.hpo_terms": "; ".join(ci.hpo_terms) if ci.hpo_terms else None,
        "clinical.diagnosed_conditions": ci.diagnosed_conditions,
        "clinical.age_of_manifestation": ci.age_of_manifestation,
        "clinical.family_history": ci.family_history,
        "clinical.consanguinity": ci.consanguinity,
        "clinical.free_text": ci.free_text,
        "overall_result": r.overall_result,
        "result_summary": r.result_summary,
        "interpretation": r.interpretation,
        "recommendations": r.recommendations,
        "incidental_findings": r.incidental_findings,
        "secondary_findings": r.secondary_findings,
        "carriership_findings": r.carriership_findings,
        "coverage.average_coverage": r.coverage.average_coverage,
        "coverage.pct_0x": r.coverage.pct_0x,
        "coverage.pct_ge_1x": r.coverage.pct_ge_1x,
        "coverage.pct_ge_5x": r.coverage.pct_ge_5x,
        "coverage.pct_ge_10x": r.coverage.pct_ge_10x,
        "coverage.pct_ge_20x": r.coverage.pct_ge_20x,
        "coverage.pct_ge_50x": r.coverage.pct_ge_50x,
        "signatories": " | ".join(
            f"{s.name}" + (f" ({s.title})" if s.title else "") for s in r.signatories
        ) if r.signatories else None,
        "patient_index": r.patient_index,
        "patients_in_source": r.patients_in_source,
    }
    for i, v in enumerate(r.variants, start=1):
        d = v.disorder
        extra_dis = "; ".join(
            f"{x.name or '?'} (OMIM {x.omim or '?'}, {x.inheritance or '?'})"
            for x in (v.additional_disorders or [])
        ) or None
        values = {
            "gene": v.gene, "transcript": v.transcript, "cdna_change": v.cdna_change,
            "protein_change": v.protein_change, "genomic_coordinate": v.genomic_coordinate,
            "exon": v.exon, "zygosity": v.zygosity, "variant_type": v.variant_type,
            "classification": v.classification, "classification_class": v.classification_class,
            "snp_identifier": v.snp_identifier, "described_in": v.described_in,
            "pmid": v.pmid, "allele_frequency": v.allele_frequency,
            "disorder.name": d.name if d else None,
            "disorder.omim": d.omim if d else None,
            "disorder.inheritance": d.inheritance if d else None,
            "disorder.additional": extra_dis,
        }
        for f in _VARIANT_FIELDS:
            row[f"variant{i}.{f}"] = values[f]
    return row


def column_order(rows: List[Dict[str, str]]) -> List[str]:
    """Stable column order: fixed leading columns, then variant/extra columns."""
    seen = set(_COLUMN_ORDER)
    variant_cols = sorted(
        {k for row in rows for k in row if k.startswith("variant")},
        key=lambda k: (int(k.split(".")[0][7:]), _VARIANT_FIELDS.index(k.split(".", 1)[1])),
    )
    extra = [k for row in rows for k in row if k not in seen and not k.startswith("variant")]
    # Insert variant columns right after result_summary
    cols = []
    for c in _COLUMN_ORDER:
        cols.append(c)
        if c == "result_summary":
            cols.extend(variant_cols)
    # de-dup extras preserving order
    for e in extra:
        if e not in cols:
            cols.append(e)
    return cols


def write_csv(reports: List[GeneticReport], path: str) -> List[str]:
    rows = [flatten_report(r) for r in reports]
    cols = column_order(rows)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") if row.get(c) is not None else "" for c in cols})
    return cols
