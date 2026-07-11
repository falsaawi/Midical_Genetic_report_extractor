# Genetic Report Extractor — Web App

A small full-stack app around the `genetic_report_extractor` package:

- **Frontend** (`webapp/static/`) — a single-page UI (vanilla JS, no build step):
  drag-and-drop **bulk PDF upload**, a live records table, an upload/transaction
  log, per-record detail view, KPI tiles, light/dark themes, and a one-click
  **Export to Excel** button.
- **Backend** (`webapp/main.py`) — FastAPI. Each uploaded PDF is extracted with
  the shared package, every upload is recorded as a **transaction**, and every
  extracted patient becomes a **record** in SQLite. Multi-patient reports are
  split automatically.
- **Store** (`webapp/db.py`) — SQLite (`webapp/data/app.db`), two tables:
  `transactions` (audit log of every upload) and `records` (one row per patient,
  full report JSON + denormalised columns).

## Run

```bash
pip install -r requirements.txt        # fastapi, uvicorn, python-multipart, openpyxl, PyMuPDF
python -m uvicorn webapp.main:app --reload --port 8077
# open http://127.0.0.1:8077
```

The database path can be overridden with `GRE_DB_PATH`.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/upload` | Multipart `files[]` — extract + persist, returns per-file summary |
| `GET`  | `/api/records` | List extracted patient records |
| `GET`  | `/api/record/{id}` | Full report JSON for one record |
| `GET`  | `/api/transactions` | Upload/transaction audit log |
| `GET`  | `/api/stats` | KPI counts |
| `GET`  | `/api/export/xlsx` | Download all records as a formatted Excel workbook |
| `GET`  | `/api/health` | Health check |

## Deploy to Vercel

The repo is Vercel-ready: `api/index.py` exposes the FastAPI app to the
`@vercel/python` runtime and `vercel.json` routes all traffic to it.

**Option A — one-click / dashboard**
1. Go to <https://vercel.com/new> and import
   `falsaawi/Midical_Genetic_report_extractor`.
2. In the import screen set the **production branch** to
   `claude/medical-report-extraction-picjms` (that's where this code lives until
   it is merged to the default branch).
3. Deploy. Vercel installs `requirements.txt` and serves the app; your link is
   `https://<project>.vercel.app`.

**Option B — CLI**
```bash
git clone -b claude/medical-report-extraction-picjms \
  https://github.com/falsaawi/Midical_Genetic_report_extractor.git
cd Midical_Genetic_report_extractor
npx vercel --prod        # prompts you to log in the first time
```

### ⚠️ Persistence on Vercel
Vercel functions are stateless with a read-only filesystem except ephemeral
`/tmp`, so the bundled SQLite DB **resets on cold starts** — fine for a demo, not
for durable transaction history. For production set `GRE_DB_PATH` to a mounted
volume, or point the store at a hosted database (e.g. Turso/libSQL or Vercel
Postgres). Hosts with a persistent disk (Render, Railway, Fly.io) keep the
SQLite file as-is.

## Notes

- `webapp/data/` holds the SQLite DB at runtime; it is git-ignored.
- Export reconstructs `GeneticReport` objects from stored JSON via
  `GeneticReport.from_dict`, then reuses the package's Excel writer, so the
  workbook is identical to the CLI's `--xlsx` output.
