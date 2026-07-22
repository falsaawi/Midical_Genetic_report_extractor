"""Variant-table extraction shared across CENTOGENE template generations.

The 2017 "Detailed description of the detected variants" table, the 2018
"RESULT SUMMARY" table, and the 2024 "MAIN FINDINGS / SEQUENCE VARIANTS" table
all encode one or more variants with the same essential columns (gene, genomic
coordinate, transcript:cDNA, protein change, zygosity, in-silico, allele
frequency, type + ACMG class). This module extracts *all* of them and enriches
each with its gene-specific disorder / OMIM / inheritance from the prose.

The 2016 "couple" report uses a different inline layout (transcript in
parentheses, no colon, per-patient zygosity columns) and keeps its own parser.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .schema import Disorder, Variant
from .text_utils import collapse_ws

INHERITANCE_MAP = {
    "AR": "Autosomal recessive", "AD": "Autosomal dominant", "XL": "X-linked",
    "XLR": "X-linked recessive", "XLD": "X-linked dominant", "MT": "Mitochondrial",
}

VARIANT_TYPE_KEYWORDS = [
    "Frame-shift, premature stop codon", "Frameshift", "Frame-shift", "Stop gain",
    "Stop loss", "Stop-gain", "Nonsense", "Missense", "Splice", "Splicing",
    "In-frame", "Synonymous", "Start loss", "Alteration", "Deletion", "Duplication",
]

# transcript:cDNA/mtDNA — the one token every table row contains exactly once.
_TX_CDNA = re.compile(r"(N[MCR]_\d+\.\d+)\s*:\s*([cmn]\.[0-9_A-Za-z>+\-]+)")
# A gene symbol sitting immediately before a genomic or transcript coordinate.
_GENE_COORD = re.compile(
    r"\b([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?)\s+(?=Chr[0-9XYMT]+\(GRCh|N[CM]_\d)")
_GENOMIC = re.compile(r"((?:Chr[0-9XYMT]+|NC_\d+\.\d+)\([^)]*\):[gm]\.[0-9A-Za-z>+\-_]+"
                      r"|Chr[0-9XYMT]+\(GRCh3[78]\):g\.[0-9A-Za-z>+\-_]+)")
_PROTEIN = re.compile(r"(p\.\(?[A-Za-z0-9*_=]+\)?)")
_CLASS_NUM = re.compile(r"\(\s*class\s*([1-6])\s*\)", re.IGNORECASE)
_CLASS_LABEL = re.compile(
    r"(Likely pathogenic|Pathogenic|Variant of uncertain significance|"
    r"Uncertain significance|Likely benign|Benign|Disease-associated)", re.IGNORECASE)
# The class number maps deterministically to the label (CENTOGENE/ACMG scheme).
_CLASS_BY_NUM = {"1": "Pathogenic", "2": "Likely pathogenic",
                 "3": "Variant of uncertain significance", "4": "Likely benign",
                 "5": "Benign", "6": "Disease-associated variant"}
_ZYG_TABLE = re.compile(
    r"(Heteroplasmy[^)]*\)|Homoplasmy|Homozygous|Heterozygous|Hemizygous|Hom\.?|Het\.?|Hem\.?)",
    re.IGNORECASE)
_ZYG_PROSE = re.compile(r"(homozygous|heterozygous|hemizygous|heteroplasmic|homoplasmic)",
                        re.IGNORECASE)
_ZYG_NORM = {"hom": "Homozygous", "het": "Heterozygous", "hem": "Hemizygous",
             "homozygous": "Homozygous", "heterozygous": "Heterozygous",
             "hemizygous": "Hemizygous", "heteroplasmic": "Heteroplasmy",
             "homoplasmic": "Homoplasmy"}


def _prep(region: str) -> str:
    r = collapse_ws(region)
    r = re.sub(r">\s+([ACGTacgt])", r">\1", r)          # join 'A> G' -> 'A>G'
    r = re.sub(r"([A-Z0-9])-\s+([A-Z0-9])", r"\1-\2", r)  # join 'MT- TL1' -> 'MT-TL1'
    return r


def _norm_class(label: str) -> str:
    low = label.lower()
    if "uncertain" in low:
        return "Variant of uncertain significance"
    return label.strip().capitalize() if low in ("pathogenic", "benign") else label.strip()


def _classify(window: str):
    """Return (label, 'class N'). Label and number may be far apart in the text
    (they sit in one column but the extractor interleaves other columns), so we
    read them independently and fall back to the number->label mapping."""
    num_m = _CLASS_NUM.search(window)
    if num_m:
        # The class number is authoritative; label text in the window can be
        # contaminated by in-silico results (e.g. "PolyPhen: Benign").
        return _CLASS_BY_NUM.get(num_m.group(1)), f"class {num_m.group(1)}"
    lbl_m = _CLASS_LABEL.search(window)
    return (_norm_class(lbl_m.group(1)) if lbl_m else None), None


def _variant_type(text: str) -> Optional[str]:
    for kw in VARIANT_TYPE_KEYWORDS:
        if re.search(re.escape(kw), text, re.IGNORECASE):
            return kw
    return None


def _cdna_core(cdna: str) -> str:
    return re.sub(r"\s+", "", cdna)


def gene_by_cdna(clean: str) -> Dict[str, str]:
    """Map each cDNA/mtDNA change to its gene using the report prose.

    Prose reliably ties the two together, e.g. 'The NAXE variant c.262G>T',
    'the homozygous DCHS1 variant c.391G>T', 'MT-TL1, m.3243A>G', 'DMD, c.2642C>G'.
    """
    out: Dict[str, str] = {}
    patterns = [
        r"\b([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?)\s*,\s*\(?([cmn]\.[0-9_A-Za-z>+\-]+)",
        r"\b([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?)\s+(?:gene\s+)?variant\s+\(?([cmn]\.[0-9_A-Za-z>+\-]+)",
        r"\b([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?)\s+\(N[MCR]_\d+\.\d+[^)]*\)[^c]*?([cmn]\.[0-9_A-Za-z>+\-]+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, clean):
            core = _cdna_core(m.group(2))
            out.setdefault(core, m.group(1))
    return out


def _clean_disname(name: str) -> Optional[str]:
    name = collapse_ws(name).strip(" .,;:")
    name = re.sub(r"^The\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r",?\s+also\s+(?:referred|known)\s+as\b.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\([A-Z][A-Za-z0-9]*\)\s*$", "", name)   # drop trailing "(HPE)" abbrev
    return name or None


def _disorder_name_before(window: str) -> Optional[str]:
    """The disorder name is the subject of the paragraph preceding its OMIM."""
    w = collapse_ws(window)
    for pat in (r"(?:^|\. )The\s+([A-Z].+?),\s+also\s+(?:referred|known)",
                r"(?:^|\. )([A-Z][A-Za-z0-9 ()\-/,']{3,}?)\s+is\s+(?:characterized|the most|a genetically|an?\s|associated)",
                r"(?:^|\. )([A-Z][A-Za-z0-9 \-/,']{3,}?)\s*\([A-Z0-9]+\)\s+is\b"):
        matches = list(re.finditer(pat, w))
        if matches:
            name = _clean_disname(matches[-1].group(1))
            if name and len(name) < 90:
                return name
    return None


def _norm_inh(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = collapse_ws(value)
    return v[0].upper() + v[1:] if v else None


def _moi_disorders(clean: str) -> List[Disorder]:
    """Disorders written in the 2024 style: 'Mode of Inheritance: X (OMIM®: N)'."""
    out, prev = [], 0
    for m in re.finditer(
        r"Mode\s+of\s+Inheritance:\s*([A-Za-z /\-]+?)\s*\.?\s*\(\s*OMIM®?:?\s*(\d{5,6})\s*\)",
        clean, re.IGNORECASE):
        out.append(Disorder(name=_disorder_name_before(clean[prev:m.start()]),
                            omim=m.group(2), inheritance=_norm_inh(m.group(1))))
        prev = m.end()
    return out


def gene_disorders(gene: str, clean: str) -> List[Disorder]:
    """All disorders associated with ``gene`` (primary first)."""
    found: List[Disorder] = []
    seen = set()

    def add(d):
        key = d.omim or (d.name or "").lower()
        if d and (d.name or d.omim) and key not in seen:
            seen.add(key)
            found.append(d)

    if gene:
        g = re.escape(gene)
        m = re.search(
            rf"Pathogenic variants?\s+in\s+(?:the\s+)?{g}\s+(?:gene\s+)?(?:is|are)\s+associated\s+with\s+(.+?)"
            rf"(?:\.\s|\s*\(|,\s+an?\s)", clean, re.IGNORECASE | re.DOTALL)
        if m:
            tail = clean[m.start():m.start() + 900]
            om = re.search(r"OMIM®?:?\s*(\d{5,6})", tail)
            im = re.search(r"\b(?:an?\s+)?(autosomal (?:recessive|dominant)|X-linked(?: recessive| dominant)?|"
                           r"mitochondrial|Y-linked)\s+(?:disorder|inheritance|manner|trait|condition|pattern)",
                           tail, re.IGNORECASE)
            add(Disorder(name=_clean_disname(m.group(1)),
                         omim=om.group(1) if om else None,
                         inheritance=_norm_inh(im.group(1)) if im else None))
    for d in _moi_disorders(clean):
        add(d)
    return found


def disorder_for_gene(gene: str, clean: str) -> Optional[Disorder]:
    ds = gene_disorders(gene, clean)
    return ds[0] if ds else None


def extract_variants(region: str, clean: str) -> List[Variant]:
    """Extract every variant row from a variant-table ``region``."""
    region = _prep(region)
    prose_gene = gene_by_cdna(clean)
    table_genes = [(m.start(), m.group(1)) for m in _GENE_COORD.finditer(region)]
    tx = list(_TX_CDNA.finditer(region))
    variants: List[Variant] = []

    for i, m in enumerate(tx):
        start = tx[i - 1].end() if i else 0
        end = tx[i + 1].start() if i + 1 < len(tx) else len(region)
        window = region[start:end]
        cdna = m.group(2)
        core = _cdna_core(cdna)

        # gene: prose map first (most reliable), else nearest table gene before this row
        gene = prose_gene.get(core)
        if not gene:
            before = [g for pos, g in table_genes if pos < m.start()]
            gene = before[-1] if before else None

        protein = None
        pm = _PROTEIN.search(window[window.find(cdna) + len(cdna):] if cdna in window else window)
        if pm:
            protein = pm.group(1)
        genomic = None
        gm = _GENOMIC.search(window)
        if gm and ":m." not in gm.group(1):  # mito genomic == transcript; skip dup
            genomic = gm.group(1)
        cls_label, cls_class = _classify(window)

        zyg = None
        zm = _ZYG_TABLE.search(window)
        if zm:
            raw = zm.group(1)
            zyg = raw if raw.lower().startswith("heteroplasmy") else \
                _ZYG_NORM.get(raw.lower().rstrip("."), raw)

        af = None
        for src in ("gnomAD", "ExAC", "ExAc", "ESP", "MitoMap"):
            am = re.search(rf"{src}:\s*([0-9]+\.[0-9]+(?:[eE]-?\d+)?%?)", window)
            if am:
                af = am.group(1)
                break
        snp = None
        sm = re.search(r"\b(rs\d+)\b", window)
        if sm:
            snp = sm.group(1)

        dis = gene_disorders(gene, clean) if gene else []
        variants.append(Variant(
            gene=gene, transcript=m.group(1), cdna_change=core, protein_change=protein,
            genomic_coordinate=genomic, zygosity=zyg, allele_frequency=af, snp_identifier=snp,
            variant_type=_variant_type(window),
            classification=cls_label, classification_class=cls_class,
            disorder=dis[0] if dis else None,
            additional_disorders=dis[1:],
        ))
    return variants


def apply_prose_zygosity(variants: List[Variant], clean: str) -> None:
    """Fill missing zygosity from prose like 'homozygous variant c.262G>T'."""
    for v in variants:
        if v.zygosity or not v.cdna_change:
            continue
        core = re.escape(v.cdna_change)
        m = (re.search(rf"({_ZYG_PROSE.pattern})\s+variant\s+\(?{core}", clean, re.IGNORECASE)
             or re.search(rf"({_ZYG_PROSE.pattern})\b[^.]{{0,50}}?{core}", clean, re.IGNORECASE)
             or re.search(rf"{core}[^.]*?\b({_ZYG_PROSE.pattern})\b", clean, re.IGNORECASE))
        if m:
            v.zygosity = _ZYG_NORM.get(m.group(1).lower(), m.group(1).capitalize())
