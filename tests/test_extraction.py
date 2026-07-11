"""End-to-end extraction tests against the three sample reports.

Run with:  python -m pytest -q      (or:  python tests/test_extraction.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genetic_report_extractor import extract_from_pdf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(os.path.dirname(HERE), "examples")


def _by_no(reports):
    return {r.patient.patient_no: r for r in reports}


def test_multipatient_split():
    reports = extract_from_pdf(os.path.join(EX, "report1_1150124_couple.pdf"))
    assert len(reports) == 2
    assert all(r.patients_in_source == 2 for r in reports)
    by = _by_no(reports)
    assert set(by) == {"1150124", "1150130"}

    p1 = by["1150124"]
    assert p1.patient.full_name == "Amani Mustafa Ahmad"
    assert p1.patient.sex == "female"
    assert p1.patient.date_of_birth == "04.07.1992"
    assert p1.patient.your_ref == "064230"

    p2 = by["1150130"]
    assert p2.patient.full_name == "Abdulhamide Mohammed Almohammed"
    assert p2.patient.sex == "male"
    assert p2.patient.your_ref == "R6508/16"  # slash inside a value is preserved

    # Shared variant, per-patient zygosity + coverage
    for r in reports:
        v = r.variants[0]
        assert v.gene == "CANT1"
        assert v.cdna_change == "c.902_906dup"
        assert v.protein_change == "p.Ser303Alafs*21"
        assert v.zygosity == "Heterozygous"
        assert v.classification == "Pathogenic"
    assert p1.coverage.average_coverage == "157.93"
    assert p2.coverage.average_coverage == "169.916"


def test_2018_single():
    (r,) = extract_from_pdf(os.path.join(EX, "report2_1223557.pdf"))
    assert r.template_generation == "2018_labeled"
    assert r.patient.full_name == "Meshael Alsubaie"
    assert r.patient.sex == "male"
    v = r.variants[0]
    assert v.gene == "DMD"
    assert v.cdna_change == "c.2642C>G"
    assert v.protein_change == "p.(Ser881*)"
    assert v.genomic_coordinate == "ChrX(GRCh37):g.32503197G>C"
    assert v.zygosity == "Hemizygous"
    assert v.exon == "21"
    assert v.classification_class == "class 2"
    assert v.disorder.omim == "310200"
    assert "Chewing difficulties" in r.clinical_information.hpo_terms
    assert r.clinical_information.age_of_manifestation == "18 months"
    assert r.ordering_provider.physician == "Dr. Walaa Al Shuaibi"


def test_2024_single():
    (r,) = extract_from_pdf(os.path.join(EX, "report3_1933708.pdf"))
    assert r.template_generation == "2024_labeled"
    assert r.lab_name == "CENTOGENE GmbH"
    assert r.patient.patient_no == "1933708"
    v = r.variants[0]
    assert v.gene == "CHD2"
    assert v.cdna_change == "c.3783G>A"
    assert v.protein_change == "p.(Trp1261*)"
    assert v.zygosity == "Heterozygous"
    assert v.variant_type == "Nonsense"
    assert v.classification == "Pathogenic"
    assert v.disorder.omim == "615369"
    assert v.disorder.inheritance == "Autosomal dominant"
    assert "Intellectual disability, mild" in r.clinical_information.hpo_terms
    assert r.clinical_information.consanguinity.lower().startswith("no")
    assert r.secondary_findings and "secondary findings" in r.secondary_findings.lower()
    assert len(r.signatories) == 3


def test_key_fields():
    (r,) = extract_from_pdf(os.path.join(EX, "report2_1223557.pdf"))
    kf = r.key_fields()
    assert kf["your_ref"] == "01-20-89-66"
    assert kf["doctor_name"] == "Dr. Walaa Al Shuaibi"
    assert kf["hospital_name"] == "King Khalid University Hospital"
    assert "pathogenic" in kf["results"].lower()
    assert kf["results_summary"].startswith("DMD")
    assert "Chewing difficulties" in kf["clinical_information"]
    # result_summary is also persisted on the record itself
    assert r.result_summary == kf["results_summary"]
    # ...and exposed in the serialised JSON
    assert "key_fields" in r.to_dict()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
