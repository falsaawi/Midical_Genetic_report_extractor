"""Adaptive parser for CENTOGENE genetic-testing reports.

Three template generations are recognised and normalised into the common
``GeneticReport`` schema:

* ``2016_legacy``  – "Final Report", slash-separated fields, can hold TWO
  patients (a couple) analysed together.  Split into one report per patient.
* ``2018_labeled`` – "Patient no.: N, First Name: ..., Last Name: ..." header,
  ``RESULT SUMMARY`` variant table.  Single patient.
* ``2024_labeled`` – newer "CENTOGENE GmbH" layout, ``MAIN FINDINGS`` /
  ``SEQUENCE VARIANTS`` table, plus secondary/carriership sections.  Single
  patient.

The parser is deliberately defensive: every field is best-effort and missing
data yields ``None`` rather than an exception.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .pdf import ExtractedDocument
from .schema import (
    ClinicalInformation,
    CoverageStatistics,
    Disorder,
    GeneticReport,
    Laboratory,
    OrderingProvider,
    Patient,
    Sample,
    Signatory,
    TestInfo,
    Variant,
)
from .text_utils import collapse_ws, first, norm_lines, section, strip_boilerplate

INHERITANCE_MAP = {
    "AR": "Autosomal recessive",
    "AD": "Autosomal dominant",
    "XL": "X-linked",
    "XLR": "X-linked recessive",
    "XLD": "X-linked dominant",
    "MT": "Mitochondrial",
    "YL": "Y-linked",
}

VARIANT_TYPE_KEYWORDS = [
    "Frame-shift, premature stop codon",
    "Frameshift",
    "Frame-shift",
    "Stop gain",
    "Stop loss",
    "Stop-gain",
    "Nonsense",
    "Missense",
    "Splice",
    "Splicing",
    "In-frame",
    "Synonymous",
    "Start loss",
    "Deletion",
    "Duplication",
]

ZYGOSITY_MAP = {
    "hem": "Hemizygous",
    "hemi": "Hemizygous",
    "hemizygous": "Hemizygous",
    "het": "Heterozygous",
    "het.": "Heterozygous",
    "heterozygous": "Heterozygous",
    "hom": "Homozygous",
    "hom.": "Homozygous",
    "homozygous": "Homozygous",
}

# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #
def detect_format(raw_text: str) -> str:
    if re.search(r"Patient name:.*/.*", raw_text) or "CentoXome PLATINUM" in raw_text:
        # slash-separated header ⇒ legacy layout (may be multi-patient)
        return "2016_legacy"
    if "CENTOGENE GmbH" in raw_text or "MAIN FINDINGS" in raw_text or "CentoXome® Solo" in raw_text:
        return "2024_labeled"
    if re.search(r"First Name:", raw_text) or "RESULT SUMMARY" in raw_text:
        return "2018_labeled"
    return "unknown"


# --------------------------------------------------------------------------- #
# Shared extractors
# --------------------------------------------------------------------------- #
def _laboratory(raw: str) -> Laboratory:
    lab = Laboratory()
    if "CENTOGENE GmbH" in raw:
        lab.name = "CENTOGENE GmbH"
    elif re.search(r"CENTOGENE AG", raw) or re.search(r"Centogene AG", raw):
        lab.name = "CENTOGENE AG"
    lab.address = first(r"(Am Strande 7\s*[•,].*?Germany|Schillingallee 68.*?Germany)", raw)
    lab.country = "Germany"
    lab.clia_registration = first(r"CLIA registration\s*([0-9A-Z]+)", raw)
    lab.cap_registration = first(r"CAP registration\s*([0-9A-Z]+)", raw)
    lab.phone = first(r"Tel\.?:\s*(\+49[0-9()\s]+)", raw)
    lab.fax = first(r"Fax:\s*(\+49[0-9()\s]+)", raw)
    lab.email = first(r"((?:office|support|dmqc|customer\.support)@centogene\.com)", raw)
    lab.website = "www.centogene.com"
    return lab


def _variant_type(text: str) -> Optional[str]:
    for kw in VARIANT_TYPE_KEYWORDS:
        if re.search(re.escape(kw), text, re.IGNORECASE):
            return kw
    return None


def _classification(text: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(
        r"(Pathogenic|Likely pathogenic|Variant of uncertain significance|Likely benign|Benign)"
        r"\s*\(?\s*(class\s*\d)\)?",
        text,
        re.IGNORECASE,
    )
    if m:
        return collapse_ws(m.group(1)), collapse_ws(m.group(2)).lower()
    return None, None


def _disorder_from_interpretation(text: str) -> Disorder:
    d = Disorder()
    omim = first(r"OMIM®?:?\s*(\d{6})", text)
    d.omim = omim
    # Inheritance
    inh = first(r"Mode of Inheritance:\s*([A-Za-z\- ]+?)(?:\s*\(|$)", text)
    if not inh:
        inh = first(r"\b(Autosomal (?:dominant|recessive)|X-linked(?: recessive| dominant)?)", text)
    d.inheritance = inh
    # Disorder name from "genetic diagnosis of <name> is (thus )?confirmed"
    name = first(
        r"genetic diagnosis of\s+(.+?)\s+is\s+(?:thus\s+)?confirmed",
        text,
    )
    d.name = name
    return d


def _coverage_single(raw: str) -> CoverageStatistics:
    cov = CoverageStatistics()
    # 2024: "≥ 20x 99.28%"
    m = re.search(r"≥\s*20x\s*([\d.]+%)", raw)
    if m:
        cov.pct_ge_20x = m.group(1)
        cov.raw = collapse_ws(m.group(0))
        return cov
    # 2018: a row of 7 numbers under the ANALYSIS STATISTICS heading
    m = re.search(
        r"COVERAGE \(X\)\s*0X\s*≥\s*1X\s*≥\s*5X\s*≥\s*10X\s*≥\s*20X\s*≥\s*50X\s*"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
        raw,
    )
    if m:
        (cov.average_coverage, cov.pct_0x, cov.pct_ge_1x, cov.pct_ge_5x,
         cov.pct_ge_10x, cov.pct_ge_20x, cov.pct_ge_50x) = m.groups()
        cov.raw = collapse_ws(m.group(0))
    return cov


_RECO_EXCLUDE = re.compile(
    r"(based on ACMG|ACMG recommendation|recommendations of|recommendations for reporting|"
    r"ACMG SF|Please feel free|several guidelines recommend)",
    re.IGNORECASE,
)


def _recommend_sentences(text: str) -> Optional[str]:
    """Collect genuine recommendation sentences (legacy layout has no heading)."""
    out = []
    for sent in re.split(r"(?<=[.])\s+", text):
        s = collapse_ws(sent)
        if not re.search(r"\b(we recommend|is recommended|are recommended|recommend a |recommend retrospective)", s, re.IGNORECASE):
            continue
        if _RECO_EXCLUDE.search(s):
            continue
        out.append(s)
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return " ".join(uniq) or None


_SIG_NAME_RE = re.compile(
    r"(?:(?:Prof|Dr)\.?\s+)*[A-ZÀ-Ý][\wÀ-ÿ'’-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]+)*,\s*(?:MD|PhD|MSc)\b"
)
_SIG_TITLES = [
    "Chief Medical and Genomic Officer",
    "Chief Medical Director",
    "Human Geneticist",
    "Clinical Geneticist",
    "Clinical Scientist",
    "Laboratory Director",
    "Medical Director",
    "Molecular Geneticist",
]
_SIG_TITLE_RE = re.compile("|".join(re.escape(t) for t in _SIG_TITLES))


def _signatories(text: str) -> List[Signatory]:
    """Extract sign-off name/title pairs, handling both layouts.

    We classify each *line* as a name, a title, or neither (names and titles sit
    on their own lines in the PDF, so working line-by-line avoids swallowing
    title words into an adjacent name).  Sign-offs appear either sequentially
    (name, its title(s), next name, ...) or in two columns (all names, then all
    titles); we detect which by comparing the first title's line index against
    the last name's.
    """
    names, titles = [], []  # each entry: (line_index, text)
    for idx, ln in enumerate(norm_lines(text)):
        if _SIG_NAME_RE.fullmatch(ln):
            names.append((idx, ln))
        elif _SIG_TITLE_RE.fullmatch(ln):
            titles.append((idx, ln))
    if not names:
        return []
    if not titles:
        return [Signatory(name=n) for _, n in names]

    columnar = titles[0][0] > names[-1][0]
    sigs: List[Signatory] = []
    if columnar:
        for i, (_, n) in enumerate(names):
            sigs.append(Signatory(name=n, title=titles[i][1] if i < len(titles) else None))
    else:
        bounds = [i for i, _ in names] + [10 ** 9]
        for i, (idx, n) in enumerate(names):
            owned = [t for ti, t in titles if idx < ti < bounds[i + 1]]
            sigs.append(Signatory(name=n, title=", ".join(owned) or None))
    return sigs


# --------------------------------------------------------------------------- #
# Format: 2016 legacy (couple / multi-patient)
# --------------------------------------------------------------------------- #
def _split_slash(value: Optional[str]) -> List[str]:
    """Split couple fields on ' / ' (space-slash-space).

    A bare '/' is *not* a separator because individual values can contain one
    (e.g. the reference 'R6508/16').  The two patients are always separated by a
    slash surrounded by whitespace.
    """
    if not value:
        return []
    return [collapse_ws(p) for p in re.split(r"\s+/\s+", value) if collapse_ws(p)]


_COUNTRY_RE = (
    r"(Saudi Arabia|United Arab Emirates|Kuwait|Qatar|Bahrain|Oman|Egypt|Jordan|"
    r"Lebanon|Iraq|Yemen|Germany|United Kingdom|United States|Turkey|India|Pakistan)"
)


def _legacy_ordering(header: str) -> OrderingProvider:
    """Addressee block on legacy page 1 sits between the physician line and the
    'Centogene AG' sender block that follows it."""
    op = OrderingProvider()
    pm = re.search(r"(Dr\.?|Prof\.?|Mrs\.?|Mr\.?|Ms\.?)\s*[A-Z][A-Za-z.\-]+", header)
    if not pm:
        return op
    tail = header[pm.start():]
    sender = re.search(r"\n\s*Centogene AG", tail, re.IGNORECASE)
    block = tail[: sender.start()] if sender else tail
    lines = norm_lines(block)
    if not lines:
        return op
    op.physician = lines[0]
    if len(lines) > 1:
        op.institution = lines[1]
    country_idx = next((i for i, ln in enumerate(lines) if re.fullmatch(_COUNTRY_RE, ln)), None)
    if country_idx is not None:
        op.country = lines[country_idx]
        middle = lines[2:country_idx]
    else:
        middle = lines[2:]
    if middle:
        # A short alphabetic first middle line reads as a department.
        if len(middle[0]) <= 24 and not re.search(r"\d", middle[0]):
            op.department = middle[0]
            middle = middle[1:]
        if middle:
            op.address = ", ".join(middle)
    return op


def _parse_2016(doc: ExtractedDocument, clean: str, raw: str) -> List[GeneticReport]:
    header = doc.page_texts[0]

    names = first(r"Patient name:\s*(.+?)\s*(?:\n|Your ref)", header, flags=re.IGNORECASE | re.DOTALL)
    refs = first(r"Your ref\.?:\s*(.+?)\s*(?:\n|Sex)", header, flags=re.IGNORECASE | re.DOTALL)
    sexes = first(r"Sex:\s*(.+?)\s*(?:\n|DOB)", header, flags=re.IGNORECASE | re.DOTALL)
    dobs = first(r"DOB[^:]*:\s*(.+?)\s*(?:\n|Patient no)", header, flags=re.IGNORECASE | re.DOTALL)
    pnos = first(r"Patient no\.?:\s*(.+?)\s*(?:\n|Sample)", header, flags=re.IGNORECASE | re.DOTALL)
    onos = first(r"Order no\.?:\s*(.+?)\s*(?:\n\s*\n|Whole Exome|$)", header, flags=re.IGNORECASE | re.DOTALL)

    name_list = _split_slash(names)
    ref_list = _split_slash(refs)
    sex_list = _split_slash(sexes)
    dob_list = _split_slash(dobs)
    pno_list = _split_slash(pnos)
    ono_list = _split_slash(onos)
    n = max(len(name_list), len(pno_list), 1)

    # Shared fields
    sample = Sample(
        sample_type=first(r"Sample type:\s*([^\n]+)", header),
        collection_date=first(r"Sample collection date[^:]*:\s*([0-9.]+)", header),
        order_received_date=first(r"Order received[^:]*:\s*([0-9.]+)", header),
    )
    ordering = _legacy_ordering(header)
    lab = _laboratory(raw)
    test = TestInfo(
        tests_requested=first(r"(Whole Exome Sequencing \(CentoXome[^)]*\)[^.\n]*)", raw),
        method_summary=section(clean, r"Methods", ["Sanger sequencing", "Limitations", "Additional information"]),
        genome_build=first(r"(GRCh3[78]/hg19|GRCh3[78])", raw),
        platform=first(r"(Illumina\s+\w[\w\s]*?)(?:platform|\.)", raw),
    )
    clinical = ClinicalInformation(
        free_text=section(clean, r"Clinical information:", ["Variants with possible", "Variants with", "Gene ", "Interpretation"]),
        consanguinity=first(r"(consanguineous)", raw),
        family_history=first(r"(negative family history|positive family history)", raw),
    )

    variant = _parse_2016_variant(header)
    interpretation = section(clean, r"Interpretation", ["Incidental findings", "Analysis statistics"])
    recommendations = _recommend_sentences(clean)
    incidental = section(clean, r"Incidental findings", ["If you have any", "Best regards", "Analysis statistics"])
    coverage_rows = _parse_2016_coverage(doc.page_texts[-1], name_list)
    sigs = _signatories("\n".join(doc.page_texts[1:]))
    # Legacy reports carry no one-line result banner; derive one from the variant.
    result_line = None
    if variant and variant.classification:
        result_line = f"{variant.classification} variant identified in {variant.gene}"

    reports = []
    for idx in range(n):
        p = Patient(
            patient_no=pno_list[idx] if idx < len(pno_list) else None,
            your_ref=ref_list[idx] if idx < len(ref_list) else (refs if n == 1 else None),
            sex=(sex_list[idx] if idx < len(sex_list) else (sex_list[0] if len(sex_list) == 1 else None)),
            date_of_birth=dob_list[idx] if idx < len(dob_list) else None,
            order_no=ono_list[idx] if idx < len(ono_list) else None,
        )
        if idx < len(name_list):
            _assign_name(p, name_list[idx])

        # Per-patient variant (copy, set zygosity for this patient)
        pvariants = []
        if variant:
            v = _copy_variant(variant)
            if variant.zygosity and "/" in variant.zygosity:
                zz = _split_slash(variant.zygosity)
                v.zygosity = _norm_zyg(zz[idx]) if idx < len(zz) else v.zygosity
            pvariants.append(v)

        cov = coverage_rows.get(idx, CoverageStatistics())

        reports.append(GeneticReport(
            source_file=doc.path,
            lab_name=lab.name,
            report_type=first(r"(Final Report)", header) or "Final Report",
            report_date=first(r"Date:\s*([0-9.]+)", header),
            template_generation="2016_legacy",
            patient=p,
            laboratory=lab,
            ordering_provider=ordering,
            sample=sample,
            test=test,
            clinical_information=clinical,
            overall_result=result_line,
            variants=pvariants,
            interpretation=interpretation,
            recommendations=recommendations,
            incidental_findings=incidental,
            coverage=cov,
            signatories=sigs,
            patient_index=idx,
            patients_in_source=n,
        ))
    for r in reports:
        r.result_summary = r.variant_summary()
    return reports


def _parse_2016_variant(header: str) -> Optional[Variant]:
    # Locate the variant block after the table header
    m = re.search(r"inheritance\)\s*(.*)", header, re.DOTALL)
    block = header[m.start():] if m else header
    gene = first(r"\n([A-Z][A-Z0-9]{1,9})\s*\n?\s*\(NM_", block)
    transcript = first(r"\((NM_[0-9.]+)\)", block)
    cdna = first(r"(c\.[0-9_A-Za-z>+\-]+(?:dup|del|ins|>[ACGT])?[0-9A-Za-z]*)", block)
    protein = first(r"\((p\.[A-Za-z0-9*_]+)\)", block)
    if not (gene or cdna):
        return None
    # Two zygosity tokens for the couple
    zygs = re.findall(r"\b(Het\.?|Hom\.?|Hemi?\.?)\b", block, re.IGNORECASE)
    zyg = " / ".join(zygs[:2]) if zygs else None
    cls, cls_class = _classification(block)
    pmid = first(r"PMID:\s*(\d+)", block)
    described = first(r"([A-Z][a-z]+,\s*\d{4})", block)
    # Disorder name / OMIM / inheritance — the table cell wraps across several
    # lines, so match on a whitespace-collapsed copy of the block.
    flat_block = collapse_ws(block)
    dm = re.search(
        r"([A-Z][A-Za-z0-9 ,'\-]+?(?:dysplasia|syndrome|disease|deficiency|disorder)"
        r"[^()]*?)\s*\((\d{6}),\s*([A-Z]{2,3})\)",
        flat_block,
    )
    disorder = None
    if dm:
        disorder = Disorder(
            name=collapse_ws(dm.group(1)),
            omim=dm.group(2),
            inheritance=INHERITANCE_MAP.get(dm.group(3), dm.group(3)),
        )
    return Variant(
        gene=gene,
        transcript=transcript,
        cdna_change=cdna,
        protein_change=protein,
        zygosity=zyg,
        variant_type=_variant_type(block),
        classification=cls,
        classification_class=cls_class,
        described_in=described,
        pmid=pmid,
        allele_frequency=first(r"(Not described)\s*\n?\s*(?:Pathogenic|Likely)", block),
        disorder=disorder,
    )


def _parse_2016_coverage(last_page: str, name_list: List[str]) -> dict:
    """Match each patient's coverage row: <name> avg 0x 1x 5x 10x 20x 50x."""
    rows = {}
    nums = r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
    for idx, name in enumerate(name_list):
        # name in report is "Last, First"; on stats page it may be reflowed
        parts = [p.strip() for p in name.split(",")]
        anchor = re.escape(parts[-1].split()[0]) if parts else None
        if not anchor:
            continue
        m = re.search(anchor + r"[A-Za-z,\s]*?" + nums, last_page)
        if m:
            g = m.groups()
            rows[idx] = CoverageStatistics(
                average_coverage=g[0], pct_0x=g[1], pct_ge_1x=g[2], pct_ge_5x=g[3],
                pct_ge_10x=g[4], pct_ge_20x=g[5], pct_ge_50x=g[6], raw=collapse_ws(m.group(0)),
            )
    return rows


# --------------------------------------------------------------------------- #
# Format: 2018 / 2024 labeled (single patient)
# --------------------------------------------------------------------------- #
def _parse_labeled(doc: ExtractedDocument, clean: str, raw: str, generation: str) -> List[GeneticReport]:
    header = doc.page_texts[0]

    p = Patient(
        patient_no=first(r"Patient no\.?:?\s*(\d+)", raw),
        first_name=first(r"First Name:\s*([^,\n]+?)\s*(?:,\s*Last Name|$|\n)", raw),
        last_name=first(r"Last Name:\s*([^,\n]+?)\s*(?:\n|DOB|$)", raw),
        sex=first(r"Sex:\s*([A-Za-z]+)", raw),
        date_of_birth=first(r"DOB:\s*([0-9]{1,2}\s*[A-Za-z]{3}\.?\s*[0-9]{4})", raw),
        your_ref=first(r"Your ref\.?:\s*([^\n,]+)", raw),
        order_no=first(r"Order no\.?:\s*(\d+)", raw),
    )
    if p.first_name and p.last_name:
        p.full_name = f"{p.first_name} {p.last_name}"

    ordering = _ordering_labeled(header)
    lab = _laboratory(raw)

    sample = Sample(
        sample_type=first(r"Sample type(?:\s*/\s*Sample collection date)?:\s*([^\n/]+)", raw),
        collection_date=first(r"Sample collection date:\s*([0-9]{1,2}\s*[A-Za-z]{3}\.?\s*[0-9]{4})", raw)
        or first(r"Sample type\s*/\s*Sample collection date:\s*[^/\n]*/\s*([0-9]{1,2}\s*[A-Za-z]{3}\.?\s*[0-9]{4})", raw),
        order_no=first(r"Order no\.?:\s*(\d+)", raw),
        order_received_date=first(r"Order received:\s*([0-9]{1,2}\s*[A-Za-z]{3}\.?\s*[0-9]{4})", raw),
    )

    test = TestInfo(
        tests_requested=first(r"Test\(s\) requested:\s*([^\n]+)", raw),
        method_summary=section(clean, r"METHODS", ["LIMITATIONS", "ANALYSIS STATISTICS", "ADDITIONAL INFORMATION"]),
        genome_build=first(r"(GRCh3[78]/hg19|GRCh3[78])", raw),
        platform=first(r"(Illumina platform|Illumina NextSeq|Illumina HiSeq[^.\n]*)", raw),
    )

    clinical = _clinical_labeled(clean, raw)

    overall = section(clean, r"(?:POSITIVE RESULT|NEGATIVE RESULT|NO PATHOGENIC)", ["INTERPRETATION"]) \
        or first(r"(POSITIVE RESULT|NEGATIVE RESULT)", raw)
    interpretation = section(clean, r"\bINTERPRETATION\b", ["RECOMMENDATIONS", "RESULT SUMMARY", "MAIN FINDINGS"])
    recommendations = section(clean, r"\bRECOMMENDATIONS\b", ["RESULT SUMMARY", "MAIN FINDINGS", "GENE ", "SEQUENCE VARIANTS", "Patient no"])
    incidental = section(clean, r"INCIDENTAL FINDINGS", ["ANALYSIS STATISTICS", "CENTOGENE VARIANT", "METHODS", "SECONDARY"])
    secondary = section(clean, r"SECONDARY FINDINGS", ["CARRIERSHIP FINDINGS", "CENTOGENE VARIANT", "METHODS", "Patient no"])
    carriership = section(clean, r"CARRIERSHIP FINDINGS", ["CENTOGENE VARIANT", "METHODS", "ANALYSIS STATISTICS"])

    variant = _parse_labeled_variant(clean, raw)
    coverage = _coverage_single(raw)
    sigs = _signatories("\n".join(doc.page_texts[-2:]))

    report = GeneticReport(
        source_file=doc.path,
        lab_name=lab.name,
        report_type=first(r"Report type:\s*([^\n]+)", raw),
        report_date=first(r"Report date:\s*([0-9]{1,2}\s*[A-Za-z]{3}\.?\s*[0-9]{4})", raw),
        template_generation=generation,
        patient=p,
        laboratory=lab,
        ordering_provider=ordering,
        sample=sample,
        test=test,
        clinical_information=clinical,
        overall_result=overall,
        variants=[variant] if variant else [],
        interpretation=interpretation,
        recommendations=recommendations,
        incidental_findings=incidental,
        secondary_findings=secondary,
        carriership_findings=carriership,
        coverage=coverage,
        signatories=sigs,
        patient_index=0,
        patients_in_source=1,
    )
    report.result_summary = report.variant_summary()
    return [report]


_META_LABEL_RE = re.compile(
    r"^(Order no|Order received|Sample type|Sample collection|Report date|Report type|"
    r"Patient no|Test\(s\)|DOB|Sex|Your ref|CLINICAL|POSITIVE|NEGATIVE|>)",
    re.IGNORECASE,
)
_COUNTRY_RE = re.compile(
    r"(Saudi Arabia|Germany|United Arab Emirates|Emirates|Kuwait|Qatar|Bahrain|Oman|Egypt|Jordan|Lebanon)",
    re.IGNORECASE,
)


def _ordering_labeled(header: str) -> OrderingProvider:
    """Extract the addressee block.

    In these layouts the addressee lines are interleaved with (or precede) the
    order-metadata lines.  We strip boilerplate, find the first title line
    (Dr./Mrs./Mr./Prof./Ms.) and collect the non-label lines that follow, up to
    the patient/test section.
    """
    lines = norm_lines(strip_boilerplate(header))
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"(Dr|Mrs|Mr|Ms|Prof)\.?\s+[A-Z]", ln) and not _META_LABEL_RE.match(ln):
            start = i
            break
    op = OrderingProvider()
    if start is None:
        return op
    block: List[str] = []
    country = None
    for ln in lines[start:]:
        if re.match(r"(Patient no|Test\(s\)|CLINICAL|DOB:)", ln, re.IGNORECASE):
            break
        if _META_LABEL_RE.match(ln):
            continue
        block.append(ln)
        if _COUNTRY_RE.search(ln):
            country = ln  # the addressee block ends at the country line
            break

    if block:
        op.physician = block[0]
    if len(block) > 1:
        op.institution = block[1]
    if country:
        op.country = country
    middle = block[2:-1] if country else block[2:]
    if middle:
        # A short alphabetic first middle line reads as a department
        if not re.search(r"\d", middle[0]) and len(middle[0]) <= 30:
            op.department = middle[0]
            middle = middle[1:]
    if middle:
        op.address = ", ".join(middle)
    return op


def _clinical_labeled(clean: str, raw: str) -> ClinicalInformation:
    ci_text = section(
        clean, r"CLINICAL INFORMATION\*?",
        ["POSITIVE RESULT", "NEGATIVE RESULT", "INTERPRETATION", "Age of manifestation"],
    )
    hpo = []
    if ci_text:
        # Cut off the "follows HPO nomenclature" footnote and anything after it.
        head = ci_text
        for cut in (r"\(?\s*Clinical information indicated above", r"Diagnosed Condition",
                    r"Age of manifestation", r"Previous ", r"EEG ", r"MRI "):
            head = re.split(cut, head)[0]
        head = re.sub(r"[\s*:(]+$", "", head)  # drop trailing footnote markers (* : ( )
        # Newer reports separate terms with ';', older ones with ','.  Only split
        # on ',' when there are no semicolons, so terms like "Intellectual
        # disability, mild" stay intact.
        sep = r";" if ";" in head else r","
        for term in re.split(sep, head):
            t = collapse_ws(term).strip(" (")
            if t and not t.lower().startswith("clinical information") and len(t) > 1:
                hpo.append(t)
    return ClinicalInformation(
        hpo_terms=hpo,
        diagnosed_conditions=first(r"Diagnosed Condition\(s\):\s*([^\n.]+)", raw),
        age_of_manifestation=first(r"Age of manifestation:\s*([^\n]+)", raw),
        family_history=first(r"Family history:\s*([^\n]+)", raw),
        consanguinity=first(r"Consanguineous parents:\s*([^\n.]+)", raw),
        free_text=ci_text,
    )


def _parse_labeled_variant(clean: str, raw: str) -> Optional[Variant]:
    # Gene + cDNA + protein reliably appear together in VARIANT INTERPRETATION
    gv = re.search(
        r"\b([A-Z][A-Z0-9]{1,9}),\s*(c\.[0-9_A-Za-z>+\-]+)\s*(p\.\(?[A-Za-z0-9*_=]+\)?)",
        clean,
    )
    gene = gv.group(1) if gv else None
    cdna = gv.group(2) if gv else first(r"(c\.[0-9_A-Za-z>+\-]+)", raw)
    protein = gv.group(3) if gv else first(r"(p\.\(?[A-Za-z0-9*_=]+\)?)", raw)
    transcript = first(r"(NM_[0-9]+\.[0-9]+):c\.", raw)
    if not gene:
        gene = first(r"(?:RESULT SUMMARY|SEQUENCE VARIANTS).*?\b([A-Z][A-Z0-9]{2,9})\b", raw, flags=re.DOTALL)
    genomic = first(r"(Chr[0-9XYM]+\([^)]+\):g\.[0-9A-Za-z>+\-]+)", raw)
    exon = first(r"Exon\s*([0-9]+)", raw) or first(r"exon\(s\)\s*no\.\s*([0-9]+)", raw)
    zyg = _norm_zyg(first(r"\b(Hemizygous|Heterozygous|Homozygous|Hem|Het|Hom)\b", raw))
    cls, cls_class = _classification(clean)
    disorder = _disorder_from_interpretation(clean)
    pmid = first(r"PMID:\s*(\d+)", raw)
    snp = first(r"(rs\d+)", raw)
    return Variant(
        gene=gene,
        transcript=transcript,
        cdna_change=cdna,
        protein_change=protein,
        genomic_coordinate=genomic,
        exon=exon,
        zygosity=zyg,
        variant_type=_variant_type(clean),
        classification=cls,
        classification_class=cls_class,
        snp_identifier=snp,
        pmid=pmid,
        disorder=disorder if (disorder.name or disorder.omim or disorder.inheritance) else None,
    )


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _assign_name(p: Patient, display_name: str):
    """CENTOGENE writes names as 'Last, First Middle'."""
    if "," in display_name:
        last, first_ = [collapse_ws(x) for x in display_name.split(",", 1)]
        p.last_name = last
        p.first_name = first_
        p.full_name = f"{first_} {last}"
    else:
        p.full_name = display_name


def _norm_zyg(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return ZYGOSITY_MAP.get(value.strip().lower().rstrip("."), value.strip())


def _copy_variant(v: Variant) -> Variant:
    d = Disorder(**vars(v.disorder)) if v.disorder else None
    nv = Variant(**{k: val for k, val in vars(v).items() if k != "disorder"})
    nv.disorder = d
    return nv


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def parse_document(doc: ExtractedDocument) -> List[GeneticReport]:
    raw = doc.text
    clean = strip_boilerplate(raw)
    fmt = detect_format(raw)
    if fmt == "2016_legacy":
        return _parse_2016(doc, clean, raw)
    if fmt == "2024_labeled":
        return _parse_labeled(doc, clean, raw, "2024_labeled")
    if fmt == "2018_labeled":
        return _parse_labeled(doc, clean, raw, "2018_labeled")
    # Fallback: try labeled parser
    return _parse_labeled(doc, clean, raw, "unknown")
