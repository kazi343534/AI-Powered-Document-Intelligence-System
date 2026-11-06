# DocIntel — AI-Powered Document Intelligence

DocIntel extracts structured invoice data (number, date, supplier, customer,
subtotal, tax, total, currency, line items) from PDFs, images, and spreadsheets,
validates the arithmetic and duplicates, and lets humans review and correct the
results before approval.

Built for a 5-day assignment. Stack: **Python 3.12 + FastAPI + SQLAlchemy +
SQLite (dev) / Supabase Postgres + pgvector (prod)** + **Groq** for LLM
extraction + **Next.js 15** frontend.

```
upload → validate + SHA-256 dedupe → store → background worker
  → parse / OCR (RapidOCR) → page grouping
  → deterministic + Groq extraction (evidence quotes, null-when-absent)
  → validation V001–V017 + duplicates + PDF↔Excel reconciliation
  → hybrid keyword + vector search → review / correct / approve
```

## Repository layout

```
docintel/
├── README.md
├── PLAN.md                 # 5-day execution plan (authored up front)
├── Makefile                # convenience targets
├── render.yaml             # Render blueprint for API + web services
├── .env.example            # copy to .env and fill in secrets
├── backend/                # FastAPI app (Python 3.12, uv)
│   ├── app/                # models, API, pipeline, worker, search, OCR, parsers
│   ├── tests/              # pytest suite (85 tests, deterministic, offline)
│   ├── data/               # local SQLite DB + uploads (dev only, gitignored)
│   ├── pyproject.toml
│   └── requirements.txt    # pinned production deps (Render)
├── frontend/               # Next.js 15 + Tailwind app
│   ├── app/                # App Router pages (login, upload, documents, analytics, search, jobs)
│   ├── components/         # shared UI, review editor, findings, sheets
│   └── lib/                # API client, types, format helpers
├── eval/                   # evaluation harness
│   ├── generate_fixtures.py    # synthetic labeled invoices
│   ├── run_eval.py             # deterministic baseline metrics
│   ├── dataset/                # generated PDFs (gitignored if large)
│   ├── ground_truth.jsonl      # labels
│   ├── results.json / results.csv / report.md
│   └── queries.json            # search evaluation queries
├── prompts/
│   └── extract_invoice.v1.md   # Groq extraction prompt + schema
├── docs/
│   ├── architecture.md   # system design & divergences from PLAN.md
│   ├── database.md       # DB schema (SQLAlchemy models)
│   ├── supabase-setup.md # provisioning Supabase for production
│   ├── ai-disclosure.md  # AI-assisted development disclosure
│   ├── evaluation.md     # evaluation methodology & measured numbers
│   └── walkthrough-script.md
└── prompts/
```

## One-command local demo

### Prerequisites

- Python 3.12+ with [`uv`](https://github.com/astral-sh/uv)
- Node 18+ with npm

### Backend

```bash
cd backend

# 1. Install dependencies
uv sync --extra dev

# 2. Initialize the dev DB (SQLite) and seed the demo user
uv run python -m cli init-db

# 3. Start the API (port 8000)
uv run uvicorn app.main:app --reload --port 8000

# 4. In another terminal, start the background worker
uv run python -m app.worker
```

Demo login (seeded): `admin@docintel.local` / `admin12345`

OpenAPI docs: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api to localhost:8000)
```

### End-to-end smoke test

1. Log in at `http://localhost:3000/login` with the demo credentials.
2. Upload `backend/data/samples/acme_invoice.pdf` (or any PDF/JPG/PNG/TIFF/XLSX/XLS/CSV).
3. Watch the job progress on the Dashboard / Jobs pages.
4. Open the document → Review tab: inspect extracted fields, evidence quotes,
   confidence, and validation findings.
5. Correct a value → a new immutable extraction version is created and
   re-validated. Approve or reopen.
6. Open Analytics for monthly and yearly sales charts, currency mix, top
   suppliers, and review status. Totals use only current extractions, never sum
   across currencies, and count each invoice identity once.
7. Go to Search and try `"ACME"` or `"INV-2024-0042"` (keyword / semantic /
   hybrid).

## Backend API (summary)

Base path `/api/v1`. Auth: JWT via `Authorization: Bearer` token or HttpOnly
cookie; demo login `admin@docintel.local` / `admin12345`.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/auth/login` | Session token |
| `GET` | `/auth/me` | Current user |
| `POST` | `/documents` | Multi-file upload (202, queued) |
| `GET` | `/documents` | List / filter / paginate |
| `GET` | `/documents/{id}` | Detail: pages, invoices, findings, jobs |
| `GET` | `/documents/{id}/text` | Page text (digital or OCR) |
| `GET` | `/documents/{id}/sheet-rows?row_type=` | Invoice/PO records (default) or child line items |
| `POST` | `/documents/{id}/reprocess` | Re-queue processing |
| `POST` | `/documents/{id}/approve` | Approve invoices or a spreadsheet |
| `GET` | `/invoices/{id}/extractions` | Revision history |
| `PATCH` | `/invoices/{id}/extractions/{eid}` | Correct → new immutable revision |
| `POST` | `/invoices/{id}/review` | Approve / reopen |
| `GET` | `/findings` | Validation findings |
| `PATCH` | `/findings/{id}` | Resolve / dismiss |
| `GET` | `/reconciliations` | Cross-document matches |
| `PATCH` | `/reconciliations/{id}` | Accept or dismiss a mismatch |
| `GET` | `/analytics/sales?currency=&months=&years=` | Monthly/yearly totals, currency mix, top suppliers, review status |
| `GET` | `/search?q=&mode=` | keyword / semantic / hybrid |
| `GET` | `/jobs` | Job queue + retry failed |
| `GET` | `/meta` | Engine/runtime status |
| `GET` | `/health/ready` | Readiness |

## Supported file types

PDF, JPG, JPEG, PNG, TIFF, XLSX, XLS, CSV. Multi-page PDFs are grouped into
logical invoices. Spreadsheet sheets are classified as invoice/PO ledgers,
line-item detail, or reconciliation sheets: only ledgers create top-level
records, while line items are linked to their parent invoice and surfaced
separately. Summary/footer rows are skipped. Corrupt or unsupported files are
rejected with a stable error code and never crash the batch.

## Background processing

Jobs live in a `processing_jobs` table. A separate `app.worker` process claims
jobs with `FOR UPDATE SKIP LOCKED` (Postgres) or a polling claim (SQLite),
runs them with retries and exponential backoff, and recovers stale jobs after
`job_stale_seconds` (default 30 min). Workers scale horizontally in Postgres.

## Evaluation

Run the deterministic baseline (no API key required):

```bash
cd eval
python generate_fixtures.py   # synthetic labeled PDFs + ground truth
python run_eval.py            # writes results.json / report.md
```

Measured baseline (deterministic extractor, 4 synthetic invoices):

- Overall field F1: **0.952**
- Exact-document rate: **0.75** (3/4)
- Null/abstention accuracy: **0.0** (1 abstention opportunity, 1 FP)
- Line-item F1: **1.0**

Re-run with `GROQ_API_KEY` set in `backend/.env` to measure the Groq path.

## Production: Supabase

See `docs/supabase-setup.md` for provisioning Postgres + pgvector + Storage and
pointing the backend at it via `DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, and `STORAGE_BACKEND=supabase`.

## Deploy on Render

The repository includes `render.yaml`, which defines two free web services:

- `docintel-api` — FastAPI; installs `backend/requirements.txt`, runs the API
  with the in-process worker (`AUTO_WORKER=true`), and health-checks
  `/health/ready`.
- `docintel-web` — Next.js; proxies `/api/*` and `/health/*` to `BACKEND_URL`.

1. In Render, choose **New → Blueprint**, connect this GitHub repository, and
   apply the blueprint.
2. Fill the `sync: false` secrets when prompted:
   - API: `DATABASE_URL` (Supabase pooler URL; transaction mode on port 6543
     or session mode on 5432), `SUPABASE_URL`,
     `SUPABASE_SERVICE_KEY`, `FRONTEND_ORIGIN` (the web service URL), and
     `GROQ_API_KEY` (optional; deterministic extraction works without it).
   - Web: `BACKEND_URL` (the API service URL, no trailing slash).
3. Deploy the API first, then the web app, and set each service's URL in the
   other service's environment.

`backend/.python-version` and `PYTHON_VERSION=3.12.7` keep Render on Python
3.12 (the project supports `>=3.12,<3.14`). The blueprint uses the `hash`
embedding provider to fit Render's free 512 MB instance; switch
`EMBEDDING_PROVIDER` to `fastembed` on a larger plan for model embeddings.

## Tests

```bash
cd backend
uv run pytest tests/ -q   # 85 tests, fully offline (no live LLM)
```

Tests cover normalization, page grouping, deterministic extraction, validation
rules (V001–V017), spreadsheet parsing, uploads, corrections, auth, search,
findings, job retries, duplicate detection, and duplicate-safe sales analytics.

## Docs

- `docs/architecture.md` — system design, pipeline, divergences from PLAN.md
- `docs/database.md` — SQLAlchemy schema & indexes
- `docs/supabase-setup.md` — production provisioning
- `docs/ai-disclosure.md` — AI-assisted development disclosure
- `docs/evaluation.md` — methodology & measured results
- `docs/walkthrough-script.md` — 6–8 minute demo script

## Security notes

- Uploads are validated by extension **and magic bytes**; size (200 MB) and
  page (1,500) caps; XLSX zip-bomb guards.
- Extracted text is treated as untrusted; the Groq prompt is schema-constrained
  and delimited so it cannot issue commands.
- Values are never invented: missing fields are `null` with a reason, every
  non-null value carries a verbatim evidence quote verified against the source.

## AI assistance

Code was drafted with AI assistance and reviewed/tested by hand. See
`docs/ai-disclosure.md`.
