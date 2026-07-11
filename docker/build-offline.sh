#!/usr/bin/env bash
# Build the image and export it as a portable tarball for air-gapped hosts.
#
#   ./docker/build-offline.sh [image:tag] [output.tar]
#
# On the target (offline) host:
#   docker load -i genetic-report-extractor_1.0.0.tar.gz
#   docker run --rm -v /data:/data genetic-report-extractor:1.0.0 \
#       batch /data/reports --db /data/out/batch.db --ocr --csv /data/out/records.csv
set -euo pipefail

IMAGE="${1:-genetic-report-extractor:1.0.0}"
OUT="${2:-genetic-report-extractor_1.0.0.tar}"

cd "$(dirname "$0")/.."

echo ">> Building $IMAGE"
docker build -t "$IMAGE" .

echo ">> Self-test"
docker run --rm "$IMAGE" selftest

echo ">> Saving to ${OUT}.gz"
docker save "$IMAGE" | gzip > "${OUT}.gz"

echo ">> Done: ${OUT}.gz ($(du -h "${OUT}.gz" | cut -f1))"
echo "   Load on target host with:  docker load -i ${OUT}.gz"
