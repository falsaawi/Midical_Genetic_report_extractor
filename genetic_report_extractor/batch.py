"""Offline, parallel, resumable batch runner for large report sets.

Designed for tens of thousands of CENTOGENE PDFs on a single on-premise machine
with no cloud involvement:

* **Parallel** — a multiprocessing pool saturates all cores.
* **Resumable / idempotent** — every file is tracked in a manifest by content
  hash; re-running skips already-processed files, so you can stop/restart or add
  new PDFs without redoing work.
* **Fault-tolerant** — corrupt / encrypted / text-less files are recorded as
  errors (and optionally moved to a quarantine folder) instead of aborting.
* **OCR fallback** — scanned/image-only PDFs are read with offline Tesseract.
* **Confidence-scored** — low-confidence records are flagged for human review.
* **Streaming exports** — CSV always, plus an optional write-only Excel sheet.

Usage::

    python -m genetic_report_extractor.batch /path/to/pdfs \\
        --db out/batch.db --workers 16 --ocr \\
        --csv out/records.csv --xlsx out/records.xlsx \\
        --quarantine out/quarantine --errors out/errors.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Iterator, List, Optional

from .extractor import extract_from_pdf
from .confidence import score_report
from .flatten import flatten_report, column_order
from .schema import GeneticReport

_MANIFEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path         TEXT PRIMARY KEY,
    sha256       TEXT,
    status       TEXT,            -- success | error | needs_ocr
    num_records  INTEGER DEFAULT 0,
    ocr_used     INTEGER DEFAULT 0,
    error        TEXT,
    processed_at TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path   TEXT,
    sha256        TEXT,
    patient_no    TEXT,
    patient_name  TEXT,
    gene          TEXT,
    classification TEXT,
    confidence    TEXT,
    conf_ratio    REAL,
    needs_review  INTEGER,
    ocr_used      INTEGER,
    flags         TEXT,
    data_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_review ON records(needs_review);
CREATE INDEX IF NOT EXISTS idx_records_conf ON records(confidence);
"""


# --------------------------------------------------------------------------- #
# Worker (must be module-level so it is picklable for the process pool)
# --------------------------------------------------------------------------- #
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def process_one(path: str, ocr: bool = True, ocr_lang: str = "eng") -> dict:
    """Extract + score a single PDF. Returns a JSON-serialisable result dict."""
    try:
        sha = _sha256(path)
    except Exception as exc:  # unreadable file
        return {"path": path, "sha256": None, "status": "error",
                "error": f"read failed: {exc}", "records": []}
    try:
        reports = extract_from_pdf(path, ocr=ocr, ocr_lang=ocr_lang)
        records = []
        ocr_used = False
        for r in reports:
            s = score_report(r)
            ocr_used = ocr_used or bool(r.ocr_used)
            records.append({"report": r.to_dict(), "score": s})
        return {"path": path, "sha256": sha, "status": "success",
                "ocr_used": ocr_used, "records": records, "error": None}
    except Exception as exc:
        status = "needs_ocr" if exc.__class__.__name__ == "NoTextLayer" else "error"
        return {"path": path, "sha256": sha, "status": status,
                "error": f"{exc.__class__.__name__}: {exc}", "records": []}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _discover(input_dir: str, pattern: str = "*.pdf") -> List[str]:
    import fnmatch
    found = []
    for root, _dirs, files in os.walk(input_dir):
        for name in files:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                found.append(os.path.join(root, name))
    return sorted(found)


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_MANIFEST_SCHEMA)
    return conn


def _done_paths(conn: sqlite3.Connection, retry_errors: bool) -> set:
    if retry_errors:
        rows = conn.execute("SELECT path FROM files WHERE status='success'").fetchall()
    else:
        rows = conn.execute("SELECT path FROM files").fetchall()
    return {r[0] for r in rows}


def _persist(conn: sqlite3.Connection, res: dict, quarantine: Optional[str]) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    # Replace any prior manifest + record rows for this path (idempotent re-run)
    conn.execute("DELETE FROM files WHERE path=?", (res["path"],))
    conn.execute("DELETE FROM records WHERE source_path=?", (res["path"],))
    conn.execute(
        "INSERT INTO files (path, sha256, status, num_records, ocr_used, error, processed_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (res["path"], res.get("sha256"), res["status"], len(res["records"]),
         int(bool(res.get("ocr_used"))), res.get("error"), now),
    )
    for item in res["records"]:
        rep, s = item["report"], item["score"]
        p = rep.get("patient", {})
        v = (rep.get("variants") or [{}])[0]
        conn.execute(
            "INSERT INTO records (source_path, sha256, patient_no, patient_name, gene, "
            "classification, confidence, conf_ratio, needs_review, ocr_used, flags, data_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (res["path"], res.get("sha256"), p.get("patient_no"), p.get("full_name"),
             v.get("gene"), v.get("classification"), s["level"], s["ratio"],
             int(s["needs_review"]), int(bool(rep.get("ocr_used"))),
             ",".join(s["flags"]), json.dumps(rep, ensure_ascii=False)),
        )
    conn.commit()
    if quarantine and res["status"] in ("error", "needs_ocr"):
        try:
            os.makedirs(quarantine, exist_ok=True)
            shutil.copy2(res["path"], os.path.join(quarantine, os.path.basename(res["path"])))
        except Exception:
            pass


def run_batch(input_dir: str, db_path: str, workers: int = 0, ocr: bool = True,
              ocr_lang: str = "eng", pattern: str = "*.pdf", retry_errors: bool = False,
              quarantine: Optional[str] = None, limit: int = 0,
              progress_every: int = 200) -> dict:
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    conn = _connect(db_path)
    all_files = _discover(input_dir, pattern)
    done = _done_paths(conn, retry_errors)
    todo = [f for f in all_files if f not in done]
    if limit:
        todo = todo[:limit]

    print(f"Discovered {len(all_files)} PDF(s); {len(done)} already processed; "
          f"{len(todo)} to do; workers={workers}; ocr={ocr}")
    if not todo:
        conn.close()
        return summary(db_path)

    t0 = time.perf_counter()
    counts = {"success": 0, "error": 0, "needs_ocr": 0, "records": 0}
    n = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_one, f, ocr, ocr_lang): f for f in todo}
        for fut in as_completed(futures):
            res = fut.result()
            _persist(conn, res, quarantine)
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            counts["records"] += len(res["records"])
            n += 1
            if n % progress_every == 0 or n == len(todo):
                rate = n / (time.perf_counter() - t0)
                eta = (len(todo) - n) / rate if rate else 0
                print(f"  {n}/{len(todo)}  ({rate:.0f}/s)  "
                      f"ok={counts['success']} err={counts['error']} "
                      f"scan={counts['needs_ocr']} rec={counts['records']}  ETA {eta/60:.1f}m")
    conn.close()
    dt = time.perf_counter() - t0
    print(f"Done in {dt/60:.1f} min ({len(todo)/dt:.0f} files/s).")
    return summary(db_path)


def summary(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        f = dict(zip(("total", "success", "error", "needs_ocr"), conn.execute(
            "SELECT COUNT(*), "
            "SUM(status='success'), SUM(status='error'), SUM(status='needs_ocr') "
            "FROM files").fetchone()))
        rec = conn.execute("SELECT COUNT(*), SUM(needs_review), SUM(ocr_used) FROM records").fetchone()
        conf = dict(conn.execute(
            "SELECT confidence, COUNT(*) FROM records GROUP BY confidence").fetchall())
    finally:
        conn.close()
    return {
        "files_total": f["total"], "files_success": f["success"] or 0,
        "files_error": f["error"] or 0, "files_needs_ocr": f["needs_ocr"] or 0,
        "records": rec[0] or 0, "records_needs_review": rec[1] or 0,
        "records_ocr": rec[2] or 0, "confidence": conf,
    }


# --------------------------------------------------------------------------- #
# Exports (stream from the DB — memory-flat for 70k+ rows)
# --------------------------------------------------------------------------- #
def _iter_reports(db_path: str, review_only: bool = False) -> Iterator[GeneticReport]:
    conn = sqlite3.connect(db_path)
    q = "SELECT data_json, needs_review, confidence, source_path FROM records"
    if review_only:
        q += " WHERE needs_review=1"
    q += " ORDER BY id"
    try:
        for data_json, needs_review, conf, src in conn.execute(q):
            yield GeneticReport.from_dict(json.loads(data_json)), needs_review, conf, src
    finally:
        conn.close()


_META_COLS = ["confidence", "needs_review", "source_file"]


def _collect(db_path: str, review_only: bool):
    """Return (flattened_rows_with_meta, base_columns)."""
    rows = []
    base = []
    for rep, needs_review, conf, src in _iter_reports(db_path, review_only):
        flat = flatten_report(rep)
        base.append(flat)
        rows.append({**flat, "confidence": conf,
                     "needs_review": needs_review, "source_file": src})
    cols = (column_order(base) if base else []) + _META_COLS
    return rows, cols


def export_csv(db_path: str, path: str, review_only: bool = False) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    rows, cols = _collect(db_path, review_only)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in cols})
    return len(rows)


def export_xlsx(db_path: str, path: str, review_only: bool = False) -> int:
    from .excel_report import write_xlsx_streaming
    rows, cols = _collect(db_path, review_only)
    write_xlsx_streaming(rows, cols, path)
    return len(rows)


def export_errors(db_path: str, path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT path, status, error, processed_at FROM files "
            "WHERE status!='success' ORDER BY path").fetchall()
    finally:
        conn.close()
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "status", "error", "processed_at"])
        w.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="genetic_report_extractor.batch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_dir", nargs="?", help="directory to scan recursively for PDFs")
    ap.add_argument("--db", default="out/batch.db", help="SQLite manifest+records DB (default: out/batch.db)")
    ap.add_argument("--workers", type=int, default=0, help="parallel workers (default: cores-1)")
    ap.add_argument("--ocr", action="store_true", default=True, help="OCR scanned PDFs (default on)")
    ap.add_argument("--no-ocr", dest="ocr", action="store_false", help="disable OCR (scans -> needs_ocr)")
    ap.add_argument("--ocr-lang", default="eng", help="Tesseract language(s), e.g. eng+ara")
    ap.add_argument("--pattern", default="*.pdf", help="filename glob (default: *.pdf)")
    ap.add_argument("--retry-errors", action="store_true", help="reprocess files not marked success")
    ap.add_argument("--quarantine", help="copy failed/scan files into this folder")
    ap.add_argument("--limit", type=int, default=0, help="process at most N new files (for calibration)")
    ap.add_argument("--csv", help="export all records to this CSV after the run")
    ap.add_argument("--xlsx", help="export all records to this Excel file after the run")
    ap.add_argument("--errors", help="write an errors/quarantine report CSV")
    ap.add_argument("--review-csv", help="export only records that need human review")
    ap.add_argument("--export-only", action="store_true", help="skip processing; just export from --db")
    args = ap.parse_args(argv)

    if not args.export_only:
        if not args.input_dir or not os.path.isdir(args.input_dir):
            ap.error("input_dir must be an existing directory (or use --export-only)")
        stats = run_batch(args.input_dir, args.db, workers=args.workers, ocr=args.ocr,
                          ocr_lang=args.ocr_lang, pattern=args.pattern,
                          retry_errors=args.retry_errors, quarantine=args.quarantine,
                          limit=args.limit)
    else:
        stats = summary(args.db)

    print("\n=== Summary ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if args.csv:
        print(f"CSV: {export_csv(args.db, args.csv)} records -> {args.csv}")
    if args.xlsx:
        print(f"Excel: {export_xlsx(args.db, args.xlsx)} records -> {args.xlsx}")
    if args.review_csv:
        print(f"Review queue: {export_csv(args.db, args.review_csv, review_only=True)} records -> {args.review_csv}")
    if args.errors:
        print(f"Errors report: {export_errors(args.db, args.errors)} rows -> {args.errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
