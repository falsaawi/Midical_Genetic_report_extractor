"""Command-line interface.

Usage::

    python -m genetic_report_extractor REPORT.pdf [MORE.pdf ...] [-o OUTDIR]
    python -m genetic_report_extractor REPORT.pdf --stdout    # print JSON

Each patient in each PDF is written to ``OUTDIR/<patient_no>.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List

from .extractor import extract_from_pdf
from .flatten import write_csv
from .html_report import write_html
from .schema import GeneticReport


def _summarise(r: GeneticReport) -> str:
    kf = r.key_fields()
    tag = ""
    if r.patients_in_source and r.patients_in_source > 1:
        tag = f" (patient {r.patient_index + 1}/{r.patients_in_source})"
    clinical = kf["clinical_information"] or ""
    if len(clinical) > 160:
        clinical = clinical[:157] + "..."
    rows = [
        f"  • {kf['patient_name'] or '(unknown)'}{tag}  [patient no. {kf['patient_no'] or '?'}]",
        f"      Your Ref            : {kf['your_ref'] or '-'}",
        f"      Doctor name         : {kf['doctor_name'] or '-'}",
        f"      Hospital name       : {kf['hospital_name'] or '-'}",
        f"      Results             : {kf['results'] or '-'}",
        f"      Results summary     : {kf['results_summary'] or '-'}",
        f"      Clinical information: {clinical or '-'}",
    ]
    return "\n".join(rows)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="genetic_report_extractor", description=__doc__)
    ap.add_argument("pdfs", nargs="+", help="PDF report(s) to extract")
    ap.add_argument("-o", "--outdir", default="output", help="output directory for JSON (default: output)")
    ap.add_argument("--stdout", action="store_true", help="print JSON to stdout instead of writing files")
    ap.add_argument("--no-prune", action="store_true", help="keep empty/None fields in the JSON")
    ap.add_argument("--csv", metavar="PATH", help="also write a flat one-row-per-patient CSV")
    ap.add_argument("--html", metavar="PATH", help="also write a transposed HTML field matrix")
    args = ap.parse_args(argv)

    all_reports: List[GeneticReport] = []
    for pdf in args.pdfs:
        if not os.path.exists(pdf):
            print(f"! skipping missing file: {pdf}", file=sys.stderr)
            continue
        try:
            reports = extract_from_pdf(pdf)
        except Exception as exc:  # noqa: BLE001 — surface any parse failure clearly
            print(f"! failed to parse {pdf}: {exc}", file=sys.stderr)
            continue

        print(f"\n{os.path.basename(pdf)} -> {len(reports)} patient record(s)")
        for r in reports:
            print(_summarise(r))
        all_reports.extend(reports)

    payload = [r.to_dict(prune=not args.no_prune) for r in all_reports]

    if args.stdout:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    os.makedirs(args.outdir, exist_ok=True)
    for r in all_reports:
        stem = r.patient.patient_no or f"{os.path.basename(r.source_file)}_{r.patient_index}"
        out_path = os.path.join(args.outdir, f"{stem}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(r.to_dict(prune=not args.no_prune), fh, indent=2, ensure_ascii=False)
    combined = os.path.join(args.outdir, "all_reports.json")
    with open(combined, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(all_reports)} record(s) to {args.outdir}/ (+ all_reports.json)")

    csv_path = args.csv or os.path.join(args.outdir, "reports.csv")
    cols = write_csv(all_reports, csv_path)
    print(f"Wrote flat CSV ({len(cols)} columns x {len(all_reports)} rows): {csv_path}")

    html_path = args.html or os.path.join(args.outdir, "reports_table.html")
    write_html(all_reports, html_path)
    print(f"Wrote HTML field matrix: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
