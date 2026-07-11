#!/usr/bin/env bash
# Dispatch entrypoint for the genetic-report-extractor image.
set -euo pipefail

cmd="${1:-help}"
shift || true

case "$cmd" in
  batch)
    # Parallel batch runner. Pass its flags after `batch`, e.g.:
    #   docker run -v /data:/data IMAGE batch /data/reports --db /data/out/batch.db --ocr
    exec python -m genetic_report_extractor.batch "$@"
    ;;
  extract)
    # One-off extraction CLI (JSON/CSV/XLSX/HTML).
    exec python -m genetic_report_extractor "$@"
    ;;
  web)
    # Interactive review web app on port 8077 (bind a host port to reach it).
    exec uvicorn webapp.main:app --host 0.0.0.0 --port "${PORT:-8077}"
    ;;
  selftest)
    # Prove the image works end-to-end on the bundled sample reports.
    python -m genetic_report_extractor.batch examples --db /tmp/selftest.db \
      --ocr --csv /tmp/selftest.csv
    echo "selftest OK"
    ;;
  shell)
    exec /bin/bash
    ;;
  help|--help|-h|*)
    cat <<'USAGE'
genetic-report-extractor — offline container

Commands:
  batch  <dir> [flags]   Parallel, resumable batch extraction of a folder of PDFs
                         e.g. batch /data/reports --db /data/out/batch.db --ocr \
                                    --csv /data/out/records.csv --xlsx /data/out/records.xlsx \
                                    --review-csv /data/out/review.csv --quarantine /data/out/q
  extract <pdfs> [flags] One-off extraction CLI (JSON/CSV/XLSX/HTML)
  web                    Start the review web app on :8077 (set PORT to change)
  selftest               Run the bundled sample reports through the pipeline
  shell                  Drop into a shell

Mount a host directory at /data to read PDFs and persist output, e.g.:
  docker run --rm -v /path/on/host:/data IMAGE batch /data/reports --db /data/batch.db --ocr
USAGE
    ;;
esac
