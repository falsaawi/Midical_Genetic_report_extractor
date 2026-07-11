"""Structured data model for extracted genetic-testing reports.

The model is intentionally lab-agnostic even though the current parser targets
CENTOGENE reports.  Every field is optional: real-world reports differ widely in
which pieces of information they contain, so a missing value is represented as
``None`` (or an empty list) rather than causing extraction to fail.

Each top-level ``GeneticReport`` corresponds to a single *patient*.  A source
PDF that contains more than one patient (e.g. a consanguineous couple analysed
together) is split into one ``GeneticReport`` per patient, all sharing the same
``source`` metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import List, Optional


def _clean(value):
    """Recursively drop ``None`` / empty values so serialised output stays terse."""
    if isinstance(value, dict):
        cleaned = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, [], {}, "")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


@dataclass
class Laboratory:
    name: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    clia_registration: Optional[str] = None
    cap_registration: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None


@dataclass
class OrderingProvider:
    """The referring physician / institution the report was sent to."""
    physician: Optional[str] = None
    institution: Optional[str] = None
    department: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None


@dataclass
class Sample:
    sample_type: Optional[str] = None
    collection_date: Optional[str] = None
    order_no: Optional[str] = None
    order_received_date: Optional[str] = None


@dataclass
class TestInfo:
    tests_requested: Optional[str] = None
    method_summary: Optional[str] = None
    genome_build: Optional[str] = None
    platform: Optional[str] = None


@dataclass
class Disorder:
    name: Optional[str] = None
    omim: Optional[str] = None
    inheritance: Optional[str] = None


@dataclass
class Variant:
    gene: Optional[str] = None
    transcript: Optional[str] = None
    cdna_change: Optional[str] = None          # e.g. c.3783G>A
    protein_change: Optional[str] = None       # e.g. p.(Trp1261*)
    genomic_coordinate: Optional[str] = None   # e.g. ChrX(GRCh37):g.32503197G>C
    exon: Optional[str] = None
    zygosity: Optional[str] = None
    variant_type: Optional[str] = None         # e.g. Nonsense / Frame-shift
    classification: Optional[str] = None       # e.g. Pathogenic
    classification_class: Optional[str] = None  # e.g. class 1
    snp_identifier: Optional[str] = None
    described_in: Optional[str] = None
    pmid: Optional[str] = None
    in_silico: Optional[str] = None
    allele_frequency: Optional[str] = None
    disorder: Optional[Disorder] = None


@dataclass
class CoverageStatistics:
    average_coverage: Optional[str] = None
    pct_0x: Optional[str] = None
    pct_ge_1x: Optional[str] = None
    pct_ge_5x: Optional[str] = None
    pct_ge_10x: Optional[str] = None
    pct_ge_20x: Optional[str] = None
    pct_ge_50x: Optional[str] = None
    raw: Optional[str] = None


@dataclass
class ClinicalInformation:
    hpo_terms: List[str] = field(default_factory=list)
    diagnosed_conditions: Optional[str] = None
    age_of_manifestation: Optional[str] = None
    family_history: Optional[str] = None
    consanguinity: Optional[str] = None
    free_text: Optional[str] = None


@dataclass
class Signatory:
    name: Optional[str] = None
    title: Optional[str] = None


@dataclass
class Patient:
    patient_no: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    sex: Optional[str] = None
    date_of_birth: Optional[str] = None
    your_ref: Optional[str] = None
    order_no: Optional[str] = None


@dataclass
class GeneticReport:
    """One patient's worth of extracted, structured report data."""
    source_file: Optional[str] = None
    lab_name: Optional[str] = None
    report_type: Optional[str] = None
    report_date: Optional[str] = None
    template_generation: Optional[str] = None   # which parser profile matched

    patient: Patient = field(default_factory=Patient)
    laboratory: Laboratory = field(default_factory=Laboratory)
    ordering_provider: OrderingProvider = field(default_factory=OrderingProvider)
    sample: Sample = field(default_factory=Sample)
    test: TestInfo = field(default_factory=TestInfo)
    clinical_information: ClinicalInformation = field(default_factory=ClinicalInformation)

    overall_result: Optional[str] = None
    result_summary: Optional[str] = None
    variants: List[Variant] = field(default_factory=list)
    interpretation: Optional[str] = None
    recommendations: Optional[str] = None
    incidental_findings: Optional[str] = None
    secondary_findings: Optional[str] = None
    carriership_findings: Optional[str] = None
    coverage: CoverageStatistics = field(default_factory=CoverageStatistics)
    signatories: List[Signatory] = field(default_factory=list)

    # Bookkeeping for multi-patient PDFs
    patient_index: Optional[int] = None
    patients_in_source: Optional[int] = None
    ocr_used: Optional[bool] = None

    def variant_summary(self) -> Optional[str]:
        """One readable line per reported variant (the 'results summary')."""
        if not self.variants:
            return "No reportable variants identified."
        lines = []
        for v in self.variants:
            parts = [v.gene or "?"]
            if v.transcript:
                parts.append(v.transcript)
            if v.cdna_change:
                parts.append(v.cdna_change)
            if v.protein_change:
                parts.append(v.protein_change)
            tail = []
            if v.zygosity:
                tail.append(v.zygosity)
            if v.classification:
                cls = v.classification
                if v.classification_class:
                    cls += f" ({v.classification_class})"
                tail.append(cls)
            if v.disorder and v.disorder.name:
                dis = v.disorder.name
                if v.disorder.omim:
                    dis += f", OMIM {v.disorder.omim}"
                tail.append(dis)
            line = " ".join(parts)
            if tail:
                line += " — " + " — ".join(tail)
            lines.append(line)
        return " | ".join(lines)

    def key_fields(self) -> dict:
        """The commonly-requested headline fields, in one flat block."""
        ci = self.clinical_information
        clinical = ci.free_text or "; ".join(ci.hpo_terms) or None
        return {
            "your_ref": self.patient.your_ref,
            "doctor_name": self.ordering_provider.physician,
            "hospital_name": self.ordering_provider.institution,
            "patient_name": self.patient.full_name,
            "patient_no": self.patient.patient_no,
            "results": self.overall_result,
            "results_summary": self.result_summary or self.variant_summary(),
            "clinical_information": clinical,
        }

    def to_dict(self, prune: bool = True) -> dict:
        d = asdict(self)
        d["key_fields"] = self.key_fields()
        return _clean(d) if prune else d

    @staticmethod
    def from_dict(d: dict) -> "GeneticReport":
        """Rebuild a report from a (possibly pruned) dict — inverse of to_dict."""
        d = d or {}
        r = _fill(GeneticReport(), d)
        r.patient = _fill(Patient(), d.get("patient"))
        r.laboratory = _fill(Laboratory(), d.get("laboratory"))
        r.ordering_provider = _fill(OrderingProvider(), d.get("ordering_provider"))
        r.sample = _fill(Sample(), d.get("sample"))
        r.test = _fill(TestInfo(), d.get("test"))
        r.clinical_information = _fill(ClinicalInformation(), d.get("clinical_information"))
        r.coverage = _fill(CoverageStatistics(), d.get("coverage"))
        r.variants = []
        for vd in d.get("variants") or []:
            vd = dict(vd)
            dis = vd.pop("disorder", None)
            v = _fill(Variant(), vd)
            v.disorder = _fill(Disorder(), dis) if dis else None
            r.variants.append(v)
        r.signatories = [_fill(Signatory(), s) for s in d.get("signatories") or []]
        return r


def _fill(obj, data: Optional[dict]):
    """Copy known scalar fields from ``data`` onto dataclass instance ``obj``."""
    if not data:
        return obj
    names = {f.name for f in fields(obj)}
    nested = {"patient", "laboratory", "ordering_provider", "sample", "test",
              "clinical_information", "coverage", "variants", "signatories", "disorder"}
    for k, v in data.items():
        if k in names and k not in nested:
            setattr(obj, k, v)
    return obj
