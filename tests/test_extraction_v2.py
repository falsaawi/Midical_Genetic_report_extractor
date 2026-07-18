"""Regression tests for the additional CENTOGENE formats (examples_v2).

Covers the 2017 single-patient "Final Report" legacy layout (with a multi-variant
"Detailed description" table), mitochondrial variants, and the 2024
"POTENTIALLY RELEVANT RESULT" banner.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genetic_report_extractor import extract_from_pdf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(os.path.dirname(HERE), "examples_v2")


def _vars(reports):
    return {v.gene: v for r in reports for v in r.variants}


def test_2017_legacy_multivariant():
    (r,) = extract_from_pdf(os.path.join(EX, "new1_ER860827.pdf"))
    assert r.template_generation == "2017_legacy"
    assert r.patient.full_name == "Eleen Talal Al Otaibi"
    assert r.patient.patient_no == "1256164"
    v = _vars([r])
    assert set(v) == {"NAXE", "DCHS1"}                       # two variants captured
    assert v["NAXE"].cdna_change == "c.262G>T"
    assert v["NAXE"].protein_change == "p.(Gly88Trp)"
    assert v["NAXE"].zygosity == "Homozygous"
    assert v["NAXE"].classification_class == "class 3"
    assert v["NAXE"].classification == "Variant of uncertain significance"
    assert v["DCHS1"].zygosity == "Homozygous"
    assert v["DCHS1"].protein_change == "p.(Val131Leu)"
    assert v["DCHS1"].disorder.omim == "601390"


def test_2017_legacy_class_not_from_insilico():
    # F9 is class 3 (VUS); the in-silico column says 'PolyPhen: Benign' — the
    # extractor must not mistake that for the variant classification.
    (r,) = extract_from_pdf(os.path.join(EX, "new3_ER741968.pdf"))
    assert r.template_generation == "2017_legacy"
    v = _vars([r])["F9"]
    assert v.cdna_change == "c.855G>C"
    assert v.classification_class == "class 3"
    assert v.classification == "Variant of uncertain significance"
    assert v.disorder.inheritance and "X-linked" in v.disorder.inheritance


def test_mitochondrial_variant_and_banner():
    (r,) = extract_from_pdf(os.path.join(EX, "new2_ER3283421.pdf"))
    assert r.template_generation == "2024_labeled"
    v = _vars([r])["MT-TL1"]
    assert v.cdna_change == "m.3243A>G"                      # mtDNA notation
    assert v.transcript == "NC_012920.1"
    assert v.classification_class == "class 1"
    assert v.zygosity.lower().startswith("heteroplasmy")
    assert v.disorder.omim == "540000"
    assert r.overall_result and "pathogenic" in r.overall_result.lower()


def test_2024_single_variants_still_work():
    for name, gene in [("new4_ER3112271.pdf", "ALDH1A3"), ("new5_ER3407788.pdf", "PTCH1")]:
        (r,) = extract_from_pdf(os.path.join(EX, name))
        v = _vars([r])
        assert gene in v
        assert v[gene].classification_class == "class 2"
        assert v[gene].disorder and v[gene].disorder.omim


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {n}")
    print("All v2 tests passed.")
