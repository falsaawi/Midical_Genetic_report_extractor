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
from .schema import GeneticReport


def _summarise(r: GeneticReport) -> str:
    name = r.patient.full_name or "(unknown patient)"
    variants = ", ".join(
        f"{v.gene} {v.cdna_change or ''} {v.protein_change or ''} [{v.classification or '?'}]".strip()
        for v in r.variants
    ) or "no reportable variants"
    tag = ""
    if r.patients_in_source and r.patients_in_source > 1:
        tag = f" (patient {r.patient_index + 1}/{r.patients_in_source})"
    return (
        f"  • {name}{tag} — no. {r.patient.patient_no or '?'} | "
        f"{r.overall_result or r.report_type or ''}\n"
        f"      variants: {variants}"
    )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="genetic_report_extractor", description=__doc__)
    ap.add_argument("pdfs", nargs="+", help="PDF report(s) to extract")
    ap.add_argument("-o", "--outdir", default="output", help="output directory for JSON (default: output)")
    ap.add_argument("--stdout", action="store_true", help="print JSON to stdout instead of writing files")
    ap.add_argument("--no-prune", action="store_true", help="keep empty/None fields in the JSON")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
