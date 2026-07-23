"""FastAPI backend for the Genetic Report Extractor web app.

Bulk-upload PDF genetic reports, extract structured per-patient records with the
``genetic_report_extractor`` package, persist every upload as a transaction, and
export the accumulated records to Excel.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# Make the sibling package importable when run as `uvicorn webapp.main:app`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genetic_report_extractor.extractor import extract_from_pdf  # noqa: E402
from genetic_report_extractor.schema import GeneticReport  # noqa: E402
from genetic_report_extractor.excel_report import xlsx_bytes  # noqa: E402

from . import db  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

app = FastAPI(title="Genetic Report Extractor", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": _now()}


@app.get("/api/stats")
def stats() -> dict:
    return db.stats()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Accept one or more PDFs; extract, persist, and return a per-file summary."""
    import hashlib
    results = []
    for uf in files:
        data = await uf.read()
        size = len(data)
        if not uf.filename.lower().endswith(".pdf"):
            tx = db.add_transaction(uf.filename, size, _now(), "error", 0,
                                    "Not a PDF file")
            results.append({"transaction_id": tx, "filename": uf.filename,
                            "status": "error", "error": "Not a PDF file", "patients": []})
            continue

        sha = hashlib.sha256(data).hexdigest()
        if db.sha_exists(sha):
            results.append({"filename": uf.filename, "status": "duplicate",
                            "error": "Identical PDF already processed", "patients": []})
            continue

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            reports = extract_from_pdf(tmp_path)
            for r in reports:
                r.source_file = uf.filename            # keep the real filename
            status = "success" if reports else "no_records"
            err = None if reports else "No patient record could be extracted"
            tx = db.add_transaction(uf.filename, size, _now(), status, len(reports), err, sha)
            patients = []
            for r in reports:
                rec_id = db.add_record(tx, _now(), r, sha)
                patients.append({"record_id": rec_id, **r.key_fields()})
            results.append({"transaction_id": tx, "filename": uf.filename,
                            "status": status, "error": err, "patients": patients})
        except Exception as exc:  # noqa: BLE001
            tx = db.add_transaction(uf.filename, size, _now(), "error", 0, str(exc), sha)
            results.append({"transaction_id": tx, "filename": uf.filename,
                            "status": "error", "error": str(exc), "patients": []})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return JSONResponse({"uploaded": len(files), "results": results})


@app.get("/api/records")
def records(limit: int = 1000) -> dict:
    return {"records": db.list_records(limit)}


@app.get("/api/record/{record_id}")
def record(record_id: int) -> dict:
    rec = db.get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="record not found")
    return rec


@app.get("/api/transactions")
def transactions(limit: int = 200) -> dict:
    return {"transactions": db.list_transactions(limit)}


@app.get("/api/export/xlsx")
def export_xlsx() -> Response:
    dicts = db.all_record_dicts()
    if not dicts:
        raise HTTPException(status_code=404, detail="no records to export")
    reports = [GeneticReport.from_dict(d) for d in dicts]
    payload = xlsx_bytes(reports)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="genetic_reports_{stamp}.xlsx"'},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/genomics")
def genomics() -> FileResponse:
    """Interactive explainer of the genomics-powered drug discovery value chain."""
    return FileResponse(os.path.join(STATIC_DIR, "genomics.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
