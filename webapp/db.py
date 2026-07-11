"""Persistence for upload transactions and extracted patient records.

Two storage backends, chosen at runtime:

* **local SQLite** (default) — file at ``GRE_DB_PATH`` (or ``webapp/data/app.db``).
* **Turso / libSQL** (durable, serverless-friendly) — used automatically when
  ``TURSO_DATABASE_URL`` is set (with ``TURSO_AUTH_TOKEN``). This lets the app
  keep a permanent transaction history even on Vercel, whose local filesystem is
  ephemeral.

The two tables are identical across backends:

* ``transactions`` — one row per uploaded PDF (audit log).
* ``records``      — one row per extracted patient, full report JSON + columns.
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
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER,
    uploaded_at   TEXT NOT NULL,
    status        TEXT NOT NULL,
    num_patients  INTEGER DEFAULT 0,
    error         TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  INTEGER NOT NULL,
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

_initialized = False


def using_turso() -> bool:
    return bool(TURSO_URL)


def _raw_connect():
    if using_turso():
        import libsql_experimental as libsql
        return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _conn():
    conn = _raw_connect()
    global _initialized
    if not _initialized:
        conn.executescript(_SCHEMA)  # idempotent (CREATE TABLE IF NOT EXISTS)
        conn.commit()
        _initialized = True
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _rows(cursor) -> List[dict]:
    """Backend-agnostic row->dict mapping (libSQL has no ``row_factory``)."""
    cols = [c[0] for c in cursor.description] if cursor.description else []
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def init_db() -> None:
    with _conn():
        pass  # _conn() ensures the schema on first use


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
        return _rows(conn.execute(
            "SELECT id, filename, size_bytes, uploaded_at, status, num_patients, error "
            "FROM transactions ORDER BY id DESC LIMIT ?", (limit,)))


def list_records(limit: int = 1000) -> List[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT id, transaction_id, created_at, patient_no, patient_name, sex, "
            "your_ref, doctor, hospital, gene, variant, classification, overall_result, "
            "template FROM records ORDER BY id DESC LIMIT ?", (limit,)))


def get_record(record_id: int) -> Optional[dict]:
    with _conn() as conn:
        rows = _rows(conn.execute("SELECT * FROM records WHERE id=?", (record_id,)))
        if not rows:
            return None
        d = rows[0]
        d["data"] = json.loads(d.pop("data_json"))
        return d


def all_record_dicts(ids: Optional[Iterable[int]] = None) -> List[dict]:
    with _conn() as conn:
        if ids:
            ids = list(ids)
            q = "SELECT data_json FROM records WHERE id IN (%s) ORDER BY id" % (
                ",".join("?" * len(ids)))
            rows = _rows(conn.execute(q, ids))
        else:
            rows = _rows(conn.execute("SELECT data_json FROM records ORDER BY id"))
        return [json.loads(r["data_json"]) for r in rows]


def stats() -> dict:
    with _conn() as conn:
        t = _rows(conn.execute(
            "SELECT COUNT(*) n, "
            "COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),0) ok, "
            "COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END),0) err "
            "FROM transactions"))[0]
        rec = _rows(conn.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT patient_no) p FROM records"))[0]
        pos = _rows(conn.execute(
            "SELECT COUNT(*) n FROM records WHERE lower(classification) LIKE '%pathogenic%'"))[0]
        return {
            "uploads": t["n"], "uploads_ok": t["ok"], "uploads_error": t["err"],
            "records": rec["n"], "unique_patients": rec["p"],
            "pathogenic_records": pos["n"],
            "backend": "turso" if using_turso() else "sqlite",
        }
