"""Render extracted reports as a transposed HTML matrix.

Fields are rows (grouped into labelled sections); patients are columns.  This is
the readable counterpart to the wide CSV: every extracted field is split out and
lined up so you can scan one field across every patient.
"""

from __future__ import annotations

import html
from typing import List

from .flatten import flatten_report
from .schema import GeneticReport

# (Section title, [(row label, flat-key, is_long_text), ...])
_SECTIONS = [
    ("Report", [
        ("Template", "template_generation", False),
        ("Laboratory", "lab_name", False),
        ("Report type", "report_type", False),
        ("Report date", "report_date", False),
        ("Source PDF", "source_file", False),
        ("Patients in source PDF", "patients_in_source", False),
    ]),
    ("Patient", [
        ("Patient no.", "patient.patient_no", False),
        ("First name", "patient.first_name", False),
        ("Last name", "patient.last_name", False),
        ("Full name", "patient.full_name", False),
        ("Sex", "patient.sex", False),
        ("Date of birth", "patient.date_of_birth", False),
        ("Your ref.", "patient.your_ref", False),
        ("Order no.", "patient.order_no", False),
    ]),
    ("Doctor & Hospital (ordering provider)", [
        ("Doctor name", "ordering_provider.physician", False),
        ("Hospital name", "ordering_provider.institution", False),
        ("Department", "ordering_provider.department", False),
        ("Address", "ordering_provider.address", False),
        ("Country", "ordering_provider.country", False),
    ]),
    ("Laboratory", [
        ("Name", "laboratory.name", False),
        ("Address", "laboratory.address", False),
        ("CLIA registration", "laboratory.clia_registration", False),
        ("CAP registration", "laboratory.cap_registration", False),
        ("Phone", "laboratory.phone", False),
        ("Fax", "laboratory.fax", False),
        ("Email", "laboratory.email", False),
        ("Website", "laboratory.website", False),
    ]),
    ("Sample", [
        ("Sample type", "sample.sample_type", False),
        ("Collection date", "sample.collection_date", False),
        ("Order no.", "sample.order_no", False),
        ("Order received", "sample.order_received_date", False),
    ]),
    ("Test", [
        ("Test(s) requested", "test.tests_requested", False),
        ("Genome build", "test.genome_build", False),
        ("Platform", "test.platform", False),
        ("Method summary", "test.method_summary", True),
    ]),
    ("Clinical information", [
        ("HPO phenotype terms", "clinical.hpo_terms", True),
        ("Diagnosed condition(s)", "clinical.diagnosed_conditions", False),
        ("Age of manifestation", "clinical.age_of_manifestation", False),
        ("Family history", "clinical.family_history", False),
        ("Consanguinity", "clinical.consanguinity", False),
        ("Referral free text", "clinical.free_text", True),
    ]),
    ("Result", [
        ("Overall result", "overall_result", False),
        ("Result summary", "result_summary", True),
    ]),
    ("Variant", [
        ("Gene", "variant1.gene", False),
        ("Transcript", "variant1.transcript", False),
        ("cDNA change", "variant1.cdna_change", False),
        ("Protein change", "variant1.protein_change", False),
        ("Genomic coordinate", "variant1.genomic_coordinate", False),
        ("Exon", "variant1.exon", False),
        ("Zygosity", "variant1.zygosity", False),
        ("Variant type", "variant1.variant_type", False),
        ("Classification", "variant1.classification", False),
        ("Class", "variant1.classification_class", False),
        ("dbSNP", "variant1.snp_identifier", False),
        ("Described in", "variant1.described_in", False),
        ("PMID", "variant1.pmid", False),
        ("Allele frequency", "variant1.allele_frequency", False),
        ("Disorder", "variant1.disorder.name", False),
        ("Disorder OMIM", "variant1.disorder.omim", False),
        ("Inheritance", "variant1.disorder.inheritance", False),
    ]),
    ("Interpretation & findings", [
        ("Interpretation", "interpretation", True),
        ("Recommendations", "recommendations", True),
        ("Incidental findings", "incidental_findings", True),
        ("Secondary findings", "secondary_findings", True),
        ("Carriership findings", "carriership_findings", True),
    ]),
    ("Coverage statistics", [
        ("Average coverage (X)", "coverage.average_coverage", False),
        ("% at 0X", "coverage.pct_0x", False),
        ("% ≥ 1X", "coverage.pct_ge_1x", False),
        ("% ≥ 5X", "coverage.pct_ge_5x", False),
        ("% ≥ 10X", "coverage.pct_ge_10x", False),
        ("% ≥ 20X", "coverage.pct_ge_20x", False),
        ("% ≥ 50X", "coverage.pct_ge_50x", False),
    ]),
    ("Sign-off", [
        ("Signatories", "signatories", True),
    ]),
]

_CSS = """
:root{
  --bg:#f7f9fb; --panel:#ffffff; --ink:#141a1f; --muted:#5b6b76;
  --line:#e2e8ee; --line-strong:#c9d5de; --accent:#0e7c86; --accent-weak:#e2f1f2;
  --zebra:#f2f6f9; --path:#b3261e; --likely:#b7791f; --vus:#5b6b76;
  --sticky-shadow:rgba(20,26,31,.08);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0e1418; --panel:#151d23; --ink:#e6edf2; --muted:#93a3ad;
    --line:#243139; --line-strong:#33454f; --accent:#4cc7d4; --accent-weak:#123037;
    --zebra:#111a20; --path:#f0736a; --likely:#e0aa4a; --vus:#93a3ad;
    --sticky-shadow:rgba(0,0,0,.45);
  }
}
:root[data-theme="light"]{
  --bg:#f7f9fb; --panel:#ffffff; --ink:#141a1f; --muted:#5b6b76;
  --line:#e2e8ee; --line-strong:#c9d5de; --accent:#0e7c86; --accent-weak:#e2f1f2;
  --zebra:#f2f6f9; --path:#b3261e; --likely:#b7791f; --vus:#5b6b76;
  --sticky-shadow:rgba(20,26,31,.08);
}
:root[data-theme="dark"]{
  --bg:#0e1418; --panel:#151d23; --ink:#e6edf2; --muted:#93a3ad;
  --line:#243139; --line-strong:#33454f; --accent:#4cc7d4; --accent-weak:#123037;
  --zebra:#111a20; --path:#f0736a; --likely:#e0aa4a; --vus:#93a3ad;
  --sticky-shadow:rgba(0,0,0,.45);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:14px;line-height:1.5;}
.wrap{max-width:1400px;margin:0 auto;padding:32px 20px 80px;}
header.page{margin-bottom:24px;}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);
  font-weight:700;margin:0 0 6px;}
h1{font-size:26px;line-height:1.2;margin:0 0 8px;text-wrap:balance;letter-spacing:-.01em;}
.sub{color:var(--muted);margin:0;max-width:70ch;}
.scroller{overflow-x:auto;border:1px solid var(--line-strong);border-radius:12px;
  background:var(--panel);box-shadow:0 1px 2px var(--sticky-shadow);}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:820px;}
th,td{text-align:left;vertical-align:top;padding:9px 14px;border-bottom:1px solid var(--line);}
thead th{position:sticky;top:0;z-index:3;background:var(--panel);border-bottom:2px solid var(--line-strong);
  padding-top:14px;padding-bottom:12px;}
thead .pname{font-size:14px;font-weight:700;letter-spacing:-.01em;}
thead .pmeta{font-size:12px;color:var(--muted);font-weight:500;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
thead .couple{display:inline-block;margin-top:3px;font-size:11px;color:var(--accent);
  background:var(--accent-weak);padding:1px 7px;border-radius:999px;font-weight:600;}
.field{position:sticky;left:0;z-index:2;background:var(--panel);color:var(--muted);
  font-weight:600;min-width:200px;box-shadow:1px 0 0 var(--line);}
thead th.field{z-index:4;color:var(--ink);}
tbody tr:nth-child(even) td{background:var(--zebra);}
tbody tr:nth-child(even) .field{background:var(--zebra);}
tr.sec td{position:sticky;left:0;background:var(--accent-weak);color:var(--accent);
  font-weight:700;font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  padding:8px 14px;border-bottom:1px solid var(--line-strong);border-top:1px solid var(--line-strong);}
td.val{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;
  color:var(--ink);min-width:150px;}
td.num{font-variant-numeric:tabular-nums;}
.longcell{max-height:8.5em;overflow-y:auto;white-space:pre-wrap;
  padding-right:6px;font-size:12.5px;line-height:1.55;}
.empty{color:var(--line-strong);}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;
  font-family:system-ui,sans-serif;border:1px solid currentColor;}
.pill.path{color:var(--path);} .pill.likely{color:var(--likely);} .pill.vus{color:var(--vus);}
footer{margin-top:22px;color:var(--muted);font-size:12px;}
"""


def _fmt(value: str, is_long: bool, is_num: bool, field_key: str) -> str:
    if value in (None, ""):
        return '<span class="empty">—</span>'
    safe = html.escape(str(value))
    if field_key == "variant1.classification":
        low = str(value).lower()
        cls = "path" if "pathogenic" in low and "likely" not in low else \
              "likely" if "likely" in low else "vus"
        return f'<span class="pill {cls}">{safe}</span>'
    if is_long:
        return f'<div class="longcell">{safe}</div>'
    return safe


def render_html(reports: List[GeneticReport]) -> str:
    flat = [flatten_report(r) for r in reports]

    head_cells = ['<th class="field">Field</th>']
    for r in reports:
        name = html.escape(r.patient.full_name or "(unknown)")
        meta = html.escape(f"no. {r.patient.patient_no or '?'} · {r.patient.sex or '?'}")
        couple = ""
        if r.patients_in_source and r.patients_in_source > 1:
            couple = f'<div class="couple">split {r.patient_index + 1} of {r.patients_in_source}</div>'
        head_cells.append(
            f'<th><div class="pname">{name}</div>'
            f'<div class="pmeta">{meta}</div>{couple}</th>'
        )
    thead = "<thead><tr>" + "".join(head_cells) + "</tr></thead>"

    body_rows = []
    ncol = len(reports) + 1
    for title, rows in _SECTIONS:
        body_rows.append(f'<tr class="sec"><td colspan="{ncol}">{html.escape(title)}</td></tr>')
        for label, key, is_long in rows:
            cells = [f'<td class="field">{html.escape(label)}</td>']
            is_num = key.startswith("coverage.") or key in ("variant1.pmid", "variant1.disorder.omim")
            for row in flat:
                val = row.get(key)
                numcls = " num" if is_num else ""
                cells.append(f'<td class="val{numcls}">{_fmt(val, is_long, is_num, key)}</td>')
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
    tbody = "<tbody>" + "".join(body_rows) + "</tbody>"

    n_src = len({r.source_file for r in reports})
    return f"""<title>Extracted genetic report fields</title>
<style>{_CSS}</style>
<div class="wrap">
  <header class="page">
    <p class="eyebrow">CENTOGENE · extraction matrix</p>
    <h1>Extracted report fields, split by patient</h1>
    <p class="sub">Every field the extractor pulled from {n_src} report PDF(s), transposed so
    each row is one field and each column is one patient. The couple report is split into two
    patient columns. Empty cells (—) mean the field was absent from that report's layout.</p>
  </header>
  <div class="scroller">
    <table>{thead}{tbody}</table>
  </div>
  <footer>{len(reports)} patient records · one column each · {sum(len(s[1]) for s in _SECTIONS)} fields per patient.</footer>
</div>"""


def write_html(reports: List[GeneticReport], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(reports))
