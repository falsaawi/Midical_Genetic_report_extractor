# Running at scale, on-premise (70,000+ reports)

This guide covers processing a large corpus of genetic-report PDFs on your own
hardware, with **no cloud** and strong privacy controls — appropriate for
sensitive genetic / PHI data.

## 1. Why this is a small job

The extractor is pure Python (PyMuPDF + regex + openpyxl) and makes **zero
network calls**. Measured throughput on the sample reports is **~26 ms per PDF
per core**:

| Cores | 70,000 PDFs (extraction only) |
|------:|-------------------------------|
|     1 | ~30 min |
|     8 | ~4 min  |
|    16 | ~2 min  |

Scanned PDFs add OCR time (~0.5–2 s/page) but only for the image-only fraction.
A single 8–16 core workstation with 32–64 GB RAM and an encrypted disk is more
than enough. Budget ~35 GB of storage for 70k PDFs at ~500 KB each.

## 2. One-time setup (air-gapped friendly)

```bash
# System OCR engine (only needed if any PDFs are scans)
apt-get install -y tesseract-ocr            # add language packs e.g. tesseract-ocr-ara

# Python deps — vendor the wheels for a truly offline install:
pip download -r requirements.txt -d wheels/           # on a connected machine
pip install --no-index --find-links wheels/ -r requirements.txt   # on the air-gapped host
```

Pin versions and keep the `wheels/` directory under change control so the
offline environment is reproducible. None of the dependencies phone home.

## 3. Run it

```bash
python -m genetic_report_extractor.batch /data/reports \
    --db /data/out/batch.db --workers 16 --ocr \
    --csv /data/out/records.csv --xlsx /data/out/records.xlsx \
    --review-csv /data/out/review_queue.csv \
    --errors /data/out/errors.csv --quarantine /data/out/quarantine
```

What you get:

| Output | Contents |
|--------|----------|
| `batch.db` | SQLite manifest (every file + status + hash) and all records with full JSON |
| `records.csv` / `.xlsx` | one row per patient, every field in its own column |
| `review_queue.csv` | only the records flagged `medium`/`low` confidence or OCR-derived |
| `errors.csv` | corrupt / encrypted / text-less files, with the reason |
| `quarantine/` | copies of the failed files for manual handling |

Re-run the same command any time — finished files are skipped (tracked by content
hash), so you can stop/restart or drip-feed new PDFs. `--export-only` regenerates
the CSV/Excel from the DB without reprocessing.

## 4. Calibrate before trusting the full batch

The parser is tuned to **CENTOGENE** templates. Even within one lab, formats
drift over the years, so start with a sample:

```bash
python -m genetic_report_extractor.batch /data/reports --db /tmp/cal.db \
    --limit 500 --review-csv /tmp/cal_review.csv
```

Inspect the confidence distribution in the run summary and spot-check
`cal_review.csv`. Each record is scored on the presence of the fields a correct
extraction must have (template recognised, patient id, gene, cDNA change,
classification, …); `medium`/`low` records are the ones worth a human glance.
OCR-derived records are always flagged even when they score `high`, because OCR
text is noisier.

## 5. Privacy & security checklist (genetic / PHI data)

- **No egress.** The pipeline needs no internet; run it on an isolated host or
  VLAN. (The optional Vercel/Turso web deployment is for non-sensitive demos only
  — do **not** use it for real patient data.)
- **Encryption at rest.** Full-disk encryption (LUKS/BitLocker); keep `batch.db`,
  exports, and the PDFs on the encrypted volume.
- **Access control & audit.** Restrict the host to authorised staff; the manifest
  records what was processed and when. Extend with an operator id if you need a
  fuller audit trail.
- **Minimise copies.** `--quarantine` copies failed files; point it at the same
  protected volume and purge it after triage.
- **Retention & deletion.** Define how long `batch.db` and exports live, and
  delete securely (`shred`/crypto-erase) when done.
- **Reproducible, vendored dependencies.** Install from pinned local wheels; the
  libraries carry no telemetry.
- **Optional containerisation.** Package as an offline Docker image for a
  reproducible, isolated run — build once on a connected machine, `docker save`
  the image, and load it on the air-gapped host (see below).

## 7. Offline Docker image (air-gapped)

The bundled `Dockerfile` produces a self-contained image (Python + Tesseract +
all dependencies + the app). It needs internet only to **build**; at **runtime**
it needs nothing — verified with `docker run --network=none`.

**Build once on a connected machine and export a portable tarball:**
```bash
./docker/build-offline.sh                       # builds + self-tests + saves .tar.gz
# -> genetic-report-extractor_1.0.0.tar.gz  (~130 MB compressed, 511 MB image)
```

**Move the tarball to the air-gapped host and load it:**
```bash
docker load -i genetic-report-extractor_1.0.0.tar.gz
```

**Run — batch mode (mount a host dir at `/data`):**
```bash
docker run --rm --network=none -v /data:/data genetic-report-extractor:1.0.0 \
    batch /data/reports --db /data/out/batch.db --ocr \
    --csv /data/out/records.csv --xlsx /data/out/records.xlsx \
    --review-csv /data/out/review.csv --quarantine /data/out/quarantine
```

**Run — review web app (local only):**
```bash
docker run --rm -p 8077:8077 -v /data:/data genetic-report-extractor:1.0.0 web
# http://localhost:8077
```

Other entrypoint commands: `extract` (one-off CLI), `selftest` (runs the bundled
samples), `shell`. Add OCR language packs by editing the `apt-get` line in the
`Dockerfile` (e.g. `tesseract-ocr-ara`).

**Fully offline build** (no internet even at build time) — vendor the wheels and
`.deb`s on a connected machine, then:
```bash
docker build --build-arg PIP_ARGS="--no-index --find-links /wheels" -t genetic-report-extractor:1.0.0 .
```

## 6. Interactive review UI (optional, local only)

The bundled web app (`webapp/`) can run on the same host, bound to localhost or
an internal address, for humans to eyeball flagged records. Keep it off the
public internet and behind authentication when it holds real data.
