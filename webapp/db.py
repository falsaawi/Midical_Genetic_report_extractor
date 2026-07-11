"""SQLite persistence for upload transactions and extracted patient records.

Two tables:

* ``transactions`` — one row per uploaded PDF (an audit log of every upload:
  filename, size, when, how many patients came out, status / error).
* ``records``      — one row per extracted patient, linked to its transaction,
  storing the full report JSON plus denormalised columns for quick listing.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, List, Optional

DB_PATH = os.environ.get(
    "GRE_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "app.db")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER,
    uploaded_at   TEXT NOT NULL,
    status        TEXT NOT NULL,          -- 'success' | 'error'
    num_patients  INTEGER DEFAULT 0,
    error         TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    patient_no      TEXT,
    patient_name    TEXT,
    sex             TEXT,
    your_ref        TEXT,
    doctor          TEXT,
    hospital        TEXT,
    gene            TEXT,
    variant         TEXT,
    classification  TEXT,
    overall_result  TEXT,
    template        TEXT,
    data_json       TEXT NOT NULL
);
"""


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def add_transaction(filename: str, size_bytes: int, uploaded_at: str,
                    status: str, num_patients: int = 0,
                    error: Optional[str] = None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (filename, size_bytes, uploaded_at, status, "
            "num_patients, error) VALUES (?,?,?,?,?,?)",
            (filename, size_bytes, uploaded_at, status, num_patients, error),
        )
        return cur.lastrowid


def add_record(transaction_id: int, created_at: str, report) -> int:
    kf = report.key_fields()
    v = report.variants[0] if report.variants else None
    variant_str = None
    if v:
        variant_str = " ".join(x for x in (v.gene, v.cdna_change, v.protein_change) if x)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO records (transaction_id, created_at, patient_no, patient_name, "
            "sex, your_ref, doctor, hospital, gene, variant, classification, overall_result, "
            "template, data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                transaction_id, created_at,
                report.patient.patient_no, report.patient.full_name, report.patient.sex,
                kf["your_ref"], kf["doctor_name"], kf["hospital_name"],
                v.gene if v else None, variant_str,
                (v.classification if v else None),
                report.overall_result, report.template_generation,
                json.dumps(report.to_dict(), ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def list_transactions(limit: int = 200) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_records(limit: int = 1000) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, transaction_id, created_at, patient_no, patient_name, sex, "
            "your_ref, doctor, hospital, gene, variant, classification, overall_result, "
            "template FROM records ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_record(record_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d.pop("data_json"))
        return d


def all_record_dicts(ids: Optional[Iterable[int]] = None) -> List[dict]:
    """Full report dicts for export (optionally filtered to specific record ids)."""
    with _conn() as conn:
        if ids:
            ids = list(ids)
            q = "SELECT data_json FROM records WHERE id IN (%s) ORDER BY id" % (
                ",".join("?" * len(ids))
            )
            rows = conn.execute(q, ids).fetchall()
        else:
            rows = conn.execute("SELECT data_json FROM records ORDER BY id").fetchall()
        return [json.loads(r["data_json"]) for r in rows]


def stats() -> dict:
    with _conn() as conn:
        t = conn.execute("SELECT COUNT(*) n, "
                         "COALESCE(SUM(status='success'),0) ok, "
                         "COALESCE(SUM(status='error'),0) err FROM transactions").fetchone()
        rec = conn.execute("SELECT COUNT(*) n, COUNT(DISTINCT patient_no) p FROM records").fetchone()
        pos = conn.execute(
            "SELECT COUNT(*) n FROM records WHERE lower(classification) LIKE '%pathogenic%'"
        ).fetchone()
        return {
            "uploads": t["n"], "uploads_ok": t["ok"], "uploads_error": t["err"],
            "records": rec["n"], "unique_patients": rec["p"],
            "pathogenic_records": pos["n"],
        }
