# Offline, self-contained image: extractor + batch runner + OCR + web app.
# Everything needed at runtime is baked in, so it runs on an air-gapped host
# with no internet access. Build once, `docker save`, load on the target host.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRE_DB_PATH=/data/app.db

# System dependency: Tesseract OCR engine (for scanned/image-only PDFs).
# Add language packs here if needed, e.g. tesseract-ocr-ara for Arabic.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
# PIP_ARGS is an escape hatch for building behind a TLS-intercepting proxy or
# from a local wheelhouse; leave empty for a normal connected build, e.g.:
#   --build-arg PIP_ARGS="--trusted-host pypi.org --trusted-host files.pythonhosted.org"
#   --build-arg PIP_ARGS="--no-index --find-links /wheels"   (fully offline build)
ARG PIP_ARGS=""
COPY requirements.txt .
RUN pip install ${PIP_ARGS} -r requirements.txt

# Application code (see .dockerignore for what is intentionally excluded).
COPY genetic_report_extractor/ genetic_report_extractor/
COPY webapp/ webapp/
COPY examples/ examples/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data

# Local, on-prem data lives here; mount a host directory to persist it.
VOLUME ["/data"]
EXPOSE 8077

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["help"]
