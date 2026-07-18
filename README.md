# Medical Genetic Report Extractor

**▶ Live app:** https://genetic-report-extractor.vercel.app — bulk-upload report
PDFs, browse extracted records, and export to Excel. Auto-deploys from this
branch on every push.

Extracts structured data from **CENTOGENE** genetic-testing report PDFs and emits
one clean JSON record **per patient**. Reports that contain two patients (for
example a consanguineous couple analysed together) are automatically **split**
into separate records that share the common report metadata.

The parser is adaptive: it recognises four CENTOGENE template generations that
differ substantially in layout, extracts **every** reported variant (not just the
first), and normalises all of them into a single schema.

| Generation      | Example              | Layout cues                              | Patients / variants |
|-----------------|----------------------|------------------------------------------|---------------------|
| `2016_couple`   | `1150124`            | "Final Report", slash-separated fields, inline variant table | 2 patients |
| `2017_legacy`   | `ER860827`           | "Final Report", `Patient name: Last, First`, "Detailed description" table | 1 patient, **N variants** |
| `2018_labeled`  | `1223557`            | `Patient no.: …, First Name: …`, `RESULT SUMMARY` | 1 |
| `2024_labeled`  | `1933708`, `ER3283421` | "CENTOGENE GmbH", `MAIN FINDINGS`, secondary/carriership sections | 1 |

Handled across formats: **multiple variants per report** (e.g. NAXE + DCHS1),
**mitochondrial variants** (`m.` notation, `NC_012920`, heteroplasmy), per-gene
disorder/OMIM/inheritance, all result banners (`POSITIVE` / `POTENTIALLY
RELEVANT` / `NEGATIVE`), and scanned PDFs via offline OCR.

## Install

```bash
pip install -r requirements.txt      # PyMuPDF only
```

## Usage

Command line:

```bash
# Write one <patient_no>.json per patient (plus all_reports.json, reports.csv,
# and reports_table.html) to ./output
python -m genetic_report_extractor examples/*.pdf -o output

# Print combined JSON to stdout instead
python -m genetic_report_extractor examples/report1_1150124_couple.pdf --stdout

# Choose explicit CSV / HTML / Excel output paths
python -m genetic_report_extractor examples/*.pdf --csv fields.csv --html matrix.html --xlsx book.xlsx
```

Alongside the per-patient JSON, every run also writes:

- **`reports.csv`** — a flat table, **one row per patient and every field in its own
  column** (75 columns; nested objects become dotted names like `patient.your_ref`,
  repeated variants are numbered `variant1.*`, `variant2.*`). Ready for a database load.
- **`reports.xlsx`** — a formatted Excel workbook with two sheets: **Records (flat)**
  (one row per patient, frozen header, auto-filter) and **Field matrix** (fields as
  rows grouped by section, one column per patient). Needs `openpyxl`.
- **`reports_table.html`** — the same matrix as a standalone web page with sticky
  headers, so you can scan any field across all patients at a glance.

## Batch processing at scale (offline / on-premise)

For large runs (tens of thousands of PDFs) use the **batch runner** — a parallel,
resumable, fault-tolerant pipeline that needs **no internet and no cloud**. On a
single workstation it processes ~26 ms/PDF/core, so 70,000 reports take roughly
**2–5 minutes on 16 cores** (plus the OCR cost for any scans).

```bash
python -m genetic_report_extractor.batch /path/to/pdfs \
    --db out/batch.db --workers 16 --ocr \
    --csv out/records.csv --xlsx out/records.xlsx \
    --review-csv out/review_queue.csv \
    --errors out/errors.csv --quarantine out/quarantine
```

- **Parallel** across all cores (`--workers`).
- **Resumable / idempotent** — every file is tracked by content hash; re-running
  skips finished files, so you can stop/restart or add new PDFs incrementally.
  Use `--retry-errors` to reprocess only the failures.
- **Fault-tolerant** — corrupt / encrypted / text-less files are logged as errors
  (and copied to `--quarantine`) instead of aborting the run.
- **Offline OCR** (`--ocr`) reads scanned/image-only PDFs with Tesseract. Install
  the system binary once: `apt-get install tesseract-ocr` (e.g. `--ocr-lang eng+ara`).
- **Confidence scoring** — each record gets `high`/`medium`/`low`; low-confidence
  and OCR-derived records are routed to `--review-csv` for a human to check.
- **Streaming exports** — CSV and a write-only Excel sheet that scale to 70k+ rows
  without loading everything into memory.

Everything is stored in a local SQLite file (`--db`); re-export any time with
`--export-only`. See [`docs/AT_SCALE.md`](docs/AT_SCALE.md) for a full on-premise
deployment and privacy checklist.

### Offline Docker image

A self-contained image (Python + Tesseract + deps + app) ships the whole thing
as one artifact that runs with **no network** (verified with `--network=none`):

```bash
./docker/build-offline.sh                          # build + self-test + save tarball
docker load -i genetic-report-extractor_1.0.0.tar.gz   # on the air-gapped host
docker run --rm --network=none -v /data:/data genetic-report-extractor:1.0.0 \
    batch /data/reports --db /data/out/batch.db --ocr --csv /data/out/records.csv
docker run --rm -p 8077:8077 -v /data:/data genetic-report-extractor:1.0.0 web
```

As a library:

```python
from genetic_report_extractor import extract_from_pdf

for report in extract_from_pdf("examples/report1_1150124_couple.pdf"):
    print(report.patient.full_name, report.variants[0].gene)
    data = report.to_dict()          # dict ready for json.dumps
```

## What gets extracted

Each `GeneticReport` (one per patient) captures:

- **Patient** — patient no., first/last/full name, sex, DOB, your-ref, order no.
- **Laboratory** — name, address, CLIA/CAP registration, phone/fax/email/website.
- **Ordering provider** — referring physician, institution, department, address, country.
- **Sample** — type, collection date, order no., order-received date.
- **Test** — test(s) requested, method summary, genome build, sequencing platform.
- **Clinical information** — HPO phenotype terms (split into a list), diagnosed
  conditions, age of manifestation, family history, consanguinity, free text.
- **Result** — overall result banner + one or more **variants**, each with gene,
  transcript, cDNA / protein / genomic change, exon, zygosity, variant type,
  ACMG classification (label + class), dbSNP id, PMID, and the associated
  **disorder** (name, OMIM, inheritance).
- **Interpretation**, **recommendations**, **incidental / secondary /
  carriership findings**.
- **Coverage statistics** (per patient), and report **signatories** (name + title).

Missing fields are simply omitted from the JSON rather than causing a failure.

### Headline `key_fields` block

For convenience, every serialised record also carries a flat `key_fields` block
that surfaces the most commonly requested values in one place (also available
programmatically via `report.key_fields()`):

| key | source |
|-----|--------|
| `your_ref` | patient's "Your ref." |
| `doctor_name` | referring physician the report is addressed to |
| `hospital_name` | referring institution |
| `patient_name` / `patient_no` | patient identity |
| `results` | overall result banner (e.g. *POSITIVE RESULT — Likely pathogenic variant identified*) |
| `results_summary` | readable one-liner per reported variant (gene, transcript, cDNA/protein, zygosity, classification, disorder) |
| `clinical_information` | referral clinical text / HPO terms |

```json
"key_fields": {
  "your_ref": "01-20-89-66",
  "doctor_name": "Dr. Walaa Al Shuaibi",
  "hospital_name": "King Khalid University Hospital",
  "patient_name": "Meshael Alsubaie",
  "patient_no": "1223557",
  "results": "Likely pathogenic variant identified",
  "results_summary": "DMD NM_004006.2 c.2642C>G p.(Ser881*) — Hemizygous — likely pathogenic (class 2) — Duchenne Muscular Dystrophy, OMIM 310200",
  "clinical_information": "Chewing difficulties, Delayed gross motor development, ..."
}
```

## Example: multi-patient split

`report1_1150124_couple.pdf` is a single PDF describing both parents. It becomes
two records:

```
report1_1150124_couple.pdf -> 2 patient record(s)
  • Amani Mustafa Ahmad (patient 1/2) — no. 1150124 | Pathogenic variant identified in CANT1
      variants: CANT1 c.902_906dup p.Ser303Alafs*21 [Pathogenic]
  • Abdulhamide Mohammed Almohammed (patient 2/2) — no. 1150130 | Pathogenic variant identified in CANT1
      variants: CANT1 c.902_906dup p.Ser303Alafs*21 [Pathogenic]
```

Both share the CANT1 variant but each keeps its own patient identity, reference,
zygosity, and coverage statistics. Sample structured output for all three
reports lives in [`output/`](output/).

## Design notes

- **Text layer only.** All three samples carry an embedded text layer, so no OCR
  is needed. Scanned PDFs raise a clear error pointing at OCR.
- **Whitespace normalisation.** CENTOGENE PDFs use non-breaking / exotic spaces
  between words; these are normalised to plain spaces at extraction time so the
  regex parser works reliably.
- **Boilerplate stripping.** Repeated per-page headers/footers (contact block,
  CLIA notice, page markers, legacy continuation-page header echoes) are removed
  before section slicing.
- **Layout-aware sign-off parsing.** Signatories are read line-by-line and the
  two common layouts (sequential vs. two-column) are auto-detected.

## Project layout

```
genetic_report_extractor/
  pdf.py          PDF text extraction + unicode normalisation
  text_utils.py   boilerplate stripping, section slicing, regex helpers
  schema.py       dataclasses for the structured model
  parser.py       adaptive CENTOGENE parser + multi-patient splitting
  extractor.py    top-level orchestration (PDF -> [GeneticReport])
  flatten.py      GeneticReport -> flat one-row-per-patient dict / CSV
  html_report.py  transposed HTML field matrix
  excel_report.py formatted .xlsx workbook (+ streaming writer for big sets)
  confidence.py   per-record confidence score + review flags
  batch.py        parallel, resumable, offline batch runner (70k+ PDFs)
  cli.py          command-line interface
examples/         the three sample PDFs
output/           example output (JSON per patient + reports.csv/.xlsx + reports_table.html)
tests/            end-to-end extraction tests
```

## Tests

```bash
python tests/test_extraction.py     # or: python -m pytest -q
```

## Scope & disclaimer

Currently targets CENTOGENE reports; the schema is lab-agnostic so additional
labs can be added as new parser profiles. Extraction is best-effort and intended
to assist data entry — **always verify against the source report before clinical
use**.
