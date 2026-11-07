# DocIntel — AI-Powered Document Intelligence

DocIntel turns invoices, scans, and spreadsheets into **reviewed, validated,
searchable data**. Upload a PDF, image, or ledger; DocIntel extracts the invoice
fields and line items, verifies arithmetic and duplicates, reconciles invoices
against spreadsheets or other invoices, and gives reviewers an evidence-backed
workflow to correct and approve the result.

**Live demo**

| Service | URL |
|---------|-----|
| Web app | https://docintel-web.onrender.com |
| API | https://ai-powered-document-intelligence-system-5.onrender.com |
| Interactive API docs | https://ai-powered-document-intelligence-system-5.onrender.com/docs |
| Readiness check | https://ai-powered-document-intelligence-system-5.onrender.com/health/ready |

**Demo login:** `admin@docintel.local` / `admin12345`

> The demo runs on Render's free tier. After ~15 minutes of inactivity the API
> spins down; the first request can take 30–60 seconds while it wakes up. The
> frontend retries cold-start `502/503/504` responses automatically.

---

## Table of contents

1. [What DocIntel does](#what-docintel-does)
2. [Feature tour](#feature-tour)
3. [How to use DocIntel (step by step)](#how-to-use-docintel-step-by-step)
4. [Architecture](#architecture)
5. [Repository layout](#repository-layout)
6. [Tech stack](#tech-stack)
7. [Local development setup](#local-development-setup)
8. [Configuration reference](#configuration-reference)
9. [Supported formats, limits, and upload errors](#supported-formats-limits-and-upload-errors)
10. [How processing works](#how-processing-works)
11. [Spreadsheet ingestion and the six fixes](#spreadsheet-ingestion-and-the-six-fixes)
12. [API reference](#api-reference)
13. [Analytics](#analytics)
14. [Search](#search)
15. [Background processing](#background-processing)
16. [Evaluation](#evaluation)
17. [Tests](#tests)
18. [Production: Supabase](#production-supabase)
19. [Deploy on Render](#deploy-on-render)
20. [OCR, memory, and embedding notes](#ocr-memory-and-embedding-notes)
21. [Troubleshooting](#troubleshooting)
22. [Security](#security)
23. [Known limitations](#known-limitations)
24. [Documentation](#documentation)
25. [AI assistance](#ai-assistance)

---

## What DocIntel does

- **Ingests PDFs, images, and spreadsheets.** Digital PDFs are read from their
  text layer; scanned PDFs and images fall back to OCR. XLSX/XLS/CSV files are
  classified into invoice ledgers, line-item detail, or reconciliation sheets.
- **Extracts invoice data.** Invoice number, invoice date, supplier, customer,
  currency, subtotal, tax, total, and line items (description, quantity, unit
  price, amount, tax rate).
- **Never invents values.** Missing fields are stored as `null` with a reason.
  Extracted non-null values are checked against the source page; unverified
  values are flagged and their confidence is reduced.
- **Validates the result.** Required fields, date sanity, negative amounts,
  arithmetic, line-item sums, tax plausibility, duplicates, near-duplicates,
  cross-document differences, and low-confidence fields are written as findings.
- **Reconciles documents.** PDF↔spreadsheet and PDF↔PDF comparisons store
  field-level differences and block approval until a reviewer accepts or
  dismisses them.
- **Versioned corrections.** Editing a field creates a new immutable extraction
  revision with a full correction audit trail, then re-runs validation.
- **Approval workflow.** Clean extractions with every required field at or above
  `AUTO_APPROVE_CONFIDENCE` can auto-approve; otherwise reviewers approve
  invoices or whole documents after blocking findings and reconciliation
  mismatches are cleared.
- **Search and analytics.** Keyword, semantic, and hybrid search across page
  text and invoice summaries; monthly/yearly analytics that never mix currencies
  or double-count duplicates.
- **Durable processing.** A database-backed queue with retries, exponential
  backoff, stale-job recovery, and an in-process worker option for
  single-service deployments.

---

## Feature tour

| Area | What you get |
|------|--------------|
| Upload | Drag-and-drop or file picker, up to 20 files per batch, per-file progress, duplicate detection by SHA-256, stable rejection codes |
| Processing | Digital text extraction, OCR fallback, page grouping into logical invoices, deterministic + optional Groq extraction, validation, indexing |
| Review | Side-by-side page preview and field editor, confidence badges, clickable evidence quotes, multi-invoice tabs, line-item editor |
| Findings | Severity-coded review queue (`info`, `warning`, `error`), resolve/dismiss actions, audit trail |
| Reconciliation | PDF↔spreadsheet and PDF↔PDF diffs, per-field values, accept/dismiss, automatically synced with linked findings |
| Approval | Auto-approval for clean, high-confidence extractions; invoice- and document-level approval otherwise; spreadsheets approved directly |
| Analytics | Monthly/yearly sales, currency mix, top suppliers, approved vs pending totals, duplicate exclusion |
| Search | Keyword (`websearch_to_tsquery` / `ILIKE`), semantic (FastEmbed or hash fallback), hybrid reciprocal-rank fusion, filters |
| Jobs | Live queue status, attempts, timings, error codes, retry button |
| Audit | Uploads, corrections, reviews, approvals, reprocesses, finding updates, reconciliation updates, job retries, logins |
| Security | JWT (HttpOnly cookie or Bearer), roles, CORS allowlist, magic-byte validation, path-traversal prevention, login rate limiting |

---

## How to use DocIntel (step by step)

This section is the complete user guide for the web app.

### 1. Sign in

1. Open the web app: https://docintel-web.onrender.com (or
   `http://localhost:3000` locally).
2. The login form is pre-filled with the demo credentials:
   `admin@docintel.local` / `admin12345`.
3. Click **Sign in**.

The frontend stores the JWT in `localStorage` under `docintel_token` and also
sends it as a Bearer token. The API additionally sets an HttpOnly cookie.
Ten login attempts for the same IP + email within five minutes are rate-limited
with HTTP `429`.

### 2. Dashboard

The dashboard is the workspace overview. It shows:

- **Total documents**, completed, processing/queued, needs-review, and failed.
- **Document kinds:** PDF, image/scan, spreadsheet.
- **Queue depth** and **average processing time**.
- **Open findings** by severity.
- **Recent documents** with status and links.
- The processing pipeline: Upload → Parse/OCR → AI extraction → Validation →
  Index.

The page polls every four seconds while any document is busy or the queue is
non-empty. Click a metric card to jump to the filtered document archive.

### 3. Upload documents

1. Open **Upload** in the sidebar.
2. Drag files onto the drop zone, or click to choose files.
3. Review the queue. Each item shows its name, type, size, and status.
4. Click the upload button (for example, **Upload 3 files**).

Rules enforced by the UI and API:

- Allowed extensions: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`,
  `.xlsx`, `.xls`, `.csv`.
- Maximum 20 files per upload.
- Maximum 200 MB per file.
- Duplicate files (same SHA-256) are not stored again; the existing document is
  returned with `duplicate: true`.
- A rejected file never cancels the rest of the batch. Each rejection includes a
  stable error code and a human-readable message.

After upload, each accepted document is queued and the page polls its status
every three seconds. When processing finishes, click the document to review it.

### 4. Monitor processing

The **Jobs** page lists every processing job with:

- Status: `queued`, `running`, `completed`, `failed`, `cancelled` (and
  `retry_wait` is represented on the document stage).
- Attempts out of the maximum (default 3).
- Progress bar, start/finish timestamps, duration, error code, and message.
- **Retry** for failed or cancelled jobs.

The dashboard, documents list, and document detail pages auto-refresh while
work is active.

### 5. Browse the document archive

Open **Documents**. You can:

- Search by filename, invoice number, or supplier.
- Filter by status (`completed`, `needs_review`, `processing`, `queued`,
  `failed`) and kind (`pdf`, `image`, `spreadsheet`).
- Sort by newest, oldest, recently updated, or filename.
- Page through results (25 per page).
- Open a document or use its row actions.

### 6. Review a document

Click a document to open its detail page. The available tabs depend on the kind.

#### Review tab (PDF / image)

- Choose an invoice when a PDF contains multiple logical invoices.
- See the source page preview on the left and extracted fields on the right.
- Every field shows its value, confidence, and (when available) an evidence
  quote. Click the quote/page badge to jump to the source page.
- `null` values are shown as **Not found**, never fabricated.
- Line items are listed with description, quantity, unit price, amount, tax
  rate, and confidence.

#### Correct a field or line item

1. Click **Correct** in the Review tab.
2. Edit any of the invoice fields: invoice number, date, supplier, customer,
   currency, subtotal, tax, total.
3. Add, remove, or edit line-item rows.
4. Optionally add a reason/note.
5. Click **Save as new version**.

What happens next:

- A new immutable extraction revision is created; the previous revision is kept.
- The field-level correction is written to the correction audit trail.
- Validation and reconciliation are re-run against the new values.
- The invoice returns to `needs_review`.
- The Review header shows the current version (for example, `v2`); earlier
  revisions are available through `GET /invoices/{id}/extractions`.

Corrections use the API's optimistic concurrency check: if another revision was
saved first, the request returns HTTP `409` and asks you to reload.

#### Findings tab

Findings are validation results. Each finding shows its rule code, severity,
field path, message, expected/actual values, status, and creation time.

- **Resolve** means the issue was fixed.
- **Dismiss** means the difference is accepted/expected.
- Both require a role of `admin` or `reviewer`.
- `info` findings never block approval.
- `warning` and `error` findings block approval while they are `open`.

The Findings tab header shows open findings versus total (`N open / M total`);
the tab badge shows the open count.

#### Reconciliation tab

This tab lists cross-document matches:

- **PDF↔spreadsheet** matches by normalized invoice number.
- **PDF↔PDF** matches for duplicate invoice identities.
- Each row shows the match type, confidence, status, and a field-by-field diff
  table (`invoice_value` vs `sheet_value`, severity).
- **Dismiss mismatch** accepts the difference and unblocks approval.
- The API also accepts `status: "matched"` to confirm that a pair is consistent;
  the web UI exposes **Dismiss mismatch** for mismatches and links to the
  matched document.

Reconciliation and findings are two views of the same cross-document
differences. DocIntel keeps them in sync:

- When the last linked `V013`/`V010` finding is resolved or dismissed, the
  corresponding reconciliation is automatically dismissed.
- When a reconciliation is dismissed or marked matched, its linked findings are
  automatically dismissed.
- Both actions are recorded in the audit trail.

This means you can work from **either** tab and approval unblocks correctly.

#### Pages tab

Shows every page with:

- Text source: digital text layer, OCR, or none.
- OCR confidence (when available).
- Page dimensions.
- Full extracted text.
- **Show on page** to open the page preview.

Use this tab to diagnose missing fields, poor scans, or unexpected grouping.

#### History tab

Shows every processing attempt and state transition for the document: job type,
status, attempt count, timestamps, progress, and error details. Failed or
cancelled jobs can be retried here.

#### Sheet rows tab (spreadsheets)

Spreadsheets use a dedicated table view instead of the invoice Review tab.

- **Invoice / PO records** and **Child line items** are separate tabs with
  independent counts.
- Toggle **Normalized** vs **Raw** columns.
- Invoice rows show invoice number, date, supplier, customer, subtotal, tax,
  total, currency, and the number of linked line items.
- Line-item rows show invoice number, line number, SKU, description, quantity,
  unit price, and line total.
- Row warnings (invalid date, invalid/missing subtotal, math mismatch, duplicate
  invoice number, missing parent) are displayed with the row.
- Pagination is 50 rows per page.

### 7. Approve a document or invoice

Approval is blocker-aware. During processing, an extraction auto-approves when
every required field is present at or above `AUTO_APPROVE_CONFIDENCE` (default
`0.85`) and there are no blocking findings or mismatches. Otherwise it stays
`needs_review` for explicit approval.

**Invoice approval** (Review tab, or API `POST /invoices/{id}/review` with
`action: "approve"`) succeeds only when:

- There are no open `error`/`warning` findings for that invoice, including
  document-level findings with no invoice attached.
- There are no `mismatch` reconciliations where the invoice is either side of
  the match.

**Document approval** (header button, or API `POST /documents/{id}/approve`):

- For PDFs/images, every reviewable invoice is approved using the same rules.
- For spreadsheets, document-level open `error`/`warning` findings and
  reconciliation mismatches are checked directly.
- The document becomes `completed` when all invoices are approved.

If approval is blocked, the API returns HTTP `409` with a message such as:

```text
Cannot approve: 0 open finding(s) and 1 reconciliation mismatch(es) must be resolved first
```

Resolve/dismiss the findings or the mismatch (either tab works), then approve
again.

### 8. Reopen an approved invoice

Use **Reopen** in the Review tab (or `POST /invoices/{id}/review` with
`action: "reopen"`). The extraction returns to `pending`, the invoice and
document return to `needs_review`, and the previous approval remains in the
audit trail.

### 9. Reprocess a document

Use **Reprocess** on the document detail page. This:

- Cancels any queued/running job for the document.
- Clears derived results: pages, invoices, extractions, line items, correction
  rows, findings, reconciliations, sheet rows, and search chunks.
- Re-queues the original file for a fresh processing run.

Reprocessing clears extraction revisions and their correction rows. Audit
events remain in the audit log, but reapply any manual corrections after the
fresh extraction completes.

### 10. Analytics

Open **Analytics** to see:

- Monthly and yearly sales totals, invoice counts, approved totals, and approved
  counts.
- Currency mix.
- Top suppliers by total and invoice count.
- Approved vs pending review status.
- Summary metrics: total, average invoice, dated/undated, missing totals, and
  excluded duplicates.

Analytics read only the **current extraction** of each invoice. They never sum
across currencies; choose a currency in the filter. Invoices with an open `V010`
duplicate finding are excluded, and duplicate identities are counted once.

### 11. Search

Open **Search** and choose a mode:

- **Hybrid** — keyword + semantic results fused with reciprocal rank fusion
  (default).
- **Keyword** — PostgreSQL full-text search; falls back to `ILIKE` on SQLite.
- **Semantic** — vector similarity using FastEmbed `bge-small-en-v1.5` when
  available, otherwise the deterministic hash embedder.

Try a supplier name, invoice number, filename, or phrase such as
`"office supplies"`. Results show the matching snippet, document status, kind,
page number, invoice summary, score, and match type. Click a result to open the
document.

Additional API filters: status, kind, supplier, currency, date range, min/max
total, and `has_findings`.

### 12. Recommended end-to-end workflow

1. Upload the invoice PDF/image and its spreadsheet ledger together (or upload
   the spreadsheet first).
2. Wait for both documents to reach `needs_review` or `completed`.
3. Open the invoice. Review fields, confidence, and evidence quotes.
4. Open **Findings**. Resolve real extraction errors; dismiss expected
   differences. The API also accepts an optional note for either action.
5. Open **Reconciliation**. Check every field diff; dismiss or mark matched.
6. Correct fields when the source value is wrong; save a new version and let
   validation re-run.
7. Approve the document.
8. Check **Analytics** and **Search** to confirm the data is visible and
   correctly counted.

---

## Architecture

### High-level flow

```text
Browser (Next.js 15)
        │  REST /api/v1
        ▼
FastAPI (Python 3.12)
        │
        ├── SQLAlchemy ──> SQLite (dev) / Supabase Postgres + pgvector (prod)
        ├── Storage ─────> local filesystem (dev) / Supabase Storage (prod)
        ├── Queue ───────> processing_jobs table
        │                       │
        │                       ▼
        │                 app.worker (separate process or in-process on Render)
        ├── Extraction ──> deterministic parser + optional Groq LLM
        └── Search ──────> PostgreSQL FTS + pgvector / SQLite fallbacks
```

### Processing stages

```text
upload
  → extension + magic-byte validation
  → SHA-256 dedupe
  → store original
  → queued job
  → downloading
  → parsing (PDF text layer / spreadsheet / image)
  → OCR fallback when needed
  → page grouping into logical invoices
  → extraction (deterministic + optional Groq)
  → validation (rules, duplicates, reconciliation)
  → indexing (page chunks + invoice summaries + embeddings)
  → completed or needs_review
```

### Components

| Component | Responsibility |
|-----------|----------------|
| `backend/app/main.py` | FastAPI app, CORS, security headers, lifespan startup, in-process worker |
| `backend/app/api/` | Auth, documents, invoices, findings, reconciliations, analytics, search, system routes |
| `backend/app/pipeline.py` | End-to-end document processing, persistence, reprocessing |
| `backend/app/worker.py` | Durable job claim, retry/backoff, stale-job recovery, graceful shutdown |
| `backend/app/parsers/` | PDF text/page rendering, spreadsheet parsing/classification, invoice grouping |
| `backend/app/ocr.py` | OCR engine selection, image preprocessing, RapidOCR/tesserocr/Tesseract |
| `backend/app/extraction/` | Deterministic extractor, Groq client, evidence verification/merge |
| `backend/app/validation.py` | Rule engine, duplicate/near-duplicate detection, reconciliation diffs |
| `backend/app/reconciliation_sync.py` | Two-way sync between reconciliation rows and findings |
| `backend/app/search.py` | Chunking, indexing, keyword/semantic/hybrid search, filters |
| `backend/app/embeddings.py` | FastEmbed provider and deterministic hash fallback |
| `backend/app/storage.py` | Local and Supabase Storage backends with signed URLs |
| `frontend/` | Next.js App Router UI: login, dashboard, upload, documents, review, analytics, search, jobs |

---

## Repository layout

```text
docintel/
├── README.md
├── PLAN.md                     # 5-day execution plan (authored up front)
├── Makefile                    # convenience targets
├── render.yaml                 # Render blueprint for API + web services
├── backend/
│   ├── app/
│   │   ├── api/                # auth, documents, invoices, findings, reconciliations,
│   │   │                       # analytics, search, system
│   │   ├── extraction/         # deterministic.py, groq.py, service.py
│   │   ├── parsers/            # pdf.py, spreadsheet.py, grouping.py
│   │   ├── tessdata/           # bundled eng.traineddata for tesserocr
│   │   ├── cli.py              # init-db / seed helpers
│   │   ├── config.py           # pydantic-settings configuration
│   │   ├── database.py         # engine, sessions, schema/index init, demo seed
│   │   ├── embeddings.py       # FastEmbed + hash fallback
│   │   ├── ingest_validation.py# extension/magic-byte/zip-bomb validation
│   │   ├── main.py             # FastAPI entry point
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── ocr.py              # OCR engine selection and preprocessing
│   │   ├── pipeline.py         # processing orchestration
│   │   ├── reconciliation_sync.py
│   │   ├── schemas.py          # Pydantic request/response models
│   │   ├── search.py           # chunking + search
│   │   ├── storage.py          # local/Supabase storage
│   │   ├── utils.py            # normalization/parsing helpers
│   │   ├── validation.py       # validation rules and reconciliation drafts
│   │   └── worker.py           # background worker
│   ├── tests/                  # 88 deterministic, offline pytest tests
│   ├── tests/fixtures/         # committed regression workbook
│   ├── data/                   # local SQLite DB + uploads (dev only, gitignored)
│   ├── .env.example            # copy to .env and fill in secrets
│   ├── .python-version         # 3.12
│   ├── pyproject.toml
│   └── requirements.txt        # pinned production deps (Render)
├── frontend/
│   ├── app/                    # App Router: login, (app)/dashboard, upload,
│   │                           # documents, documents/[id], analytics, search, jobs
│   ├── components/             # AppShell, AuthProvider, DocumentTable, DocumentPreview,
│   │                           # ExtractionReview, FindingsList, SheetView, SalesCharts, ui
│   ├── lib/                    # API client, types, format helpers
│   ├── next.config.ts          # proxies /api/* and /health/* to BACKEND_URL
│   └── package.json
├── eval/
│   ├── generate_fixtures.py    # synthetic labeled PDFs + ground truth
│   ├── run_eval.py             # writes results.json / results.csv / report.md
│   ├── dataset/                # generated PDFs (gitignored if large)
│   ├── ground_truth.jsonl      # labels
│   ├── queries.json            # search evaluation queries
│   └── results.json / results.csv / report.md
├── prompts/
│   └── extract_invoice.v1.md   # Groq extraction prompt + schema
└── docs/
    ├── architecture.md         # system design & divergences from PLAN.md
    ├── database.md             # DB schema (SQLAlchemy models)
    ├── supabase-setup.md       # provisioning Supabase for production
    ├── ai-disclosure.md        # AI-assisted development disclosure
    ├── evaluation.md           # evaluation methodology & measured numbers
    └── walkthrough-script.md   # 6–8 minute demo script
```

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic 2, Uvicorn |
| Database | SQLite (dev), Supabase Postgres 16 + pgvector (prod) |
| Storage | Local filesystem (dev), Supabase Storage (prod) |
| Queue | `processing_jobs` table + `app.worker` (no Redis/Celery) |
| PDF parsing | PyMuPDF (`fitz`) |
| OCR | RapidOCR (local default), tesserocr (Render default, bundled tessdata), Tesseract/pytesseract, or none |
| Extraction | Conservative deterministic regex/layout parser + optional Groq `llama-3.3-70b-versatile` |
| Embeddings | FastEmbed `BAAI/bge-small-en-v1.5` (384 dims) or deterministic hash fallback |
| Search | PostgreSQL full-text + pgvector HNSW; SQLite `ILIKE`/cosine fallbacks |
| Frontend | Next.js 15 (App Router), React 19, Tailwind CSS 3, lucide-react |
| Auth | JWT (PyJWT), bcrypt password hashes, HttpOnly cookie or Bearer token |
| Testing | pytest, pytest-asyncio, httpx, ReportLab fixtures, ruff |
| Deployment | Render (two free web services: FastAPI API + Next.js web) |

---

## Local development setup

### Prerequisites

- Python **3.12** (project supports `>=3.12,<3.14`)
- [`uv`](https://github.com/astral-sh/uv)
- Node.js **18+** and npm
- Optional: Tesseract if you want the `tesseract` OCR engine instead of the
  bundled `tesserocr`/RapidOCR options

No Supabase account is needed for local development. The default database is
SQLite and the default storage backend is the local filesystem.

### Backend

```bash
cd backend

# 1. Install dependencies (includes dev/test extras)
uv sync --extra dev

# 2. Initialize the dev database and seed the demo user
uv run python -m app.cli init-db

# 3. Start the API on port 8000
uv run uvicorn app.main:app --reload --port 8000

# 4. In a second terminal, start the background worker
uv run python -m app.worker
```

Useful URLs:

- API: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- Readiness: `http://localhost:8000/health/ready`
- Runtime metadata: `http://localhost:8000/api/v1/meta`

The worker is optional if you set `AUTO_WORKER=true` in `backend/.env`; in that
case the API starts an in-process worker. A separate worker process is
recommended for development because it isolates processing from API reloads.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The Next.js rewrite proxies `/api/*` and
`/health/*` to `BACKEND_URL` (default `http://localhost:8000`).

To point the frontend at another backend:

```bash
BACKEND_URL=https://your-api.example.com npm run dev
```

### Demo credentials

The demo user is seeded on startup if it does not already exist:

```text
Email:    admin@docintel.local
Password: admin12345
Role:     admin
```

Change `DEMO_EMAIL` / `DEMO_PASSWORD` and rotate the demo user before exposing a
production instance publicly.

### Make targets

```bash
make help              # list targets
make backend-install   # uv sync --extra dev
make backend-init      # init SQLite DB + demo user
make backend-api       # uvicorn app.main:app --reload --port 8000
make backend-worker    # python -m app.worker
make backend-test      # pytest tests/
make backend-lint      # ruff check app tests
make frontend-install  # npm install
make frontend-dev      # npm run dev
make frontend-build    # npm run build
make frontend-typecheck # tsc --noEmit
make eval-fixtures     # generate synthetic evaluation PDFs
make eval-run          # run deterministic evaluation
make clean             # remove local DB, uploads, eval outputs
```

### Sample file

A sample invoice is committed at:

```text
backend/data/samples/acme_invoice.pdf
```

Upload it together with any spreadsheet ledger to exercise reconciliation.

### End-to-end smoke test (local)

1. Log in at `http://localhost:3000/login` with the demo credentials.
2. Upload `backend/data/samples/acme_invoice.pdf` (or any supported PDF, image,
   XLSX, XLS, or CSV).
3. Watch the progress on the Dashboard, Documents, and Jobs pages.
4. Open the document → **Review** tab. Inspect fields, confidence, evidence
   quotes, and line items.
5. Correct a value → **Save as new version**. Confirm the new version badge and
   re-run findings in **Review**.
6. Resolve or dismiss findings; dismiss any reconciliation mismatch.
7. Approve the document. Confirm status `completed`.
8. Open **Analytics** and **Search** to confirm the data appears.

### Reset local data

```bash
make clean
cd backend && uv run python -m app.cli init-db
```

This removes the SQLite database and local uploads. It does not touch Supabase.

---

## Configuration reference

The backend reads `backend/.env` (copy from `backend/.env.example`). All
variables are optional for local development; the defaults below are shown.
Environment variable names are case-insensitive.

### Core

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_NAME` | `DocIntel` | Display name in metadata |
| `ENVIRONMENT` | `development` | Free-form environment label (`production` on Render) |
| `API_PREFIX` | `/api/v1` | API route prefix |

### Database and auth

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./data/docintel.db` | SQLAlchemy URL. `postgres://` and `postgresql://` are normalized to `postgresql+psycopg://` |
| `SECRET_KEY` | `change-this-to-a-long-random-string` | JWT signing key; **change in production** |
| `ACCESS_TOKEN_MINUTES` | `720` | Token lifetime (12 hours) |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS so the auth cookie is `Secure` |
| `DEMO_EMAIL` | `admin@docintel.local` | Seeded demo user email |
| `DEMO_PASSWORD` | `admin12345` | Seeded demo user password |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS allowlist origin |

### Storage

| Variable | Default | Purpose |
|----------|---------|---------|
| `STORAGE_BACKEND` | `local` | `local` or `supabase` |
| `LOCAL_STORAGE_DIR` | `./data/uploads` | Local upload root |
| `SUPABASE_URL` | empty | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | empty | Service-role key; **backend only, never expose to the browser** |
| `SUPABASE_BUCKET` | `documents` | Storage bucket name |

### Extraction and AI

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` | empty | Optional Groq key. Without it, the deterministic extractor is used |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model name |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq-compatible endpoint |
| `LLM_TIMEOUT_SECONDS` | `90` | Per-request LLM timeout |
| `AUTO_APPROVE_CONFIDENCE` | `0.85` | Required-field confidence threshold for auto-approval |
| `AMOUNT_TOLERANCE` | `0.01` | Money comparison tolerance |
| `LINE_ITEM_TOLERANCE_PCT` | `0.005` | Line-item sum tolerance (0.5%) |

### OCR

| Variable | Default | Purpose |
|----------|---------|---------|
| `OCR_ENGINE` | `auto` | `auto`, `rapidocr`, `tesserocr`, `tesseract`, or `none` |
| `TESSERACT_CMD` | empty | Path to the Tesseract binary for `pytesseract` |
| `TESSDATA_PREFIX` | empty | Directory containing `eng.traineddata`; empty uses the bundled `backend/app/tessdata` |

Engine selection for `auto`:

1. RapidOCR if importable.
2. tesserocr if importable (uses the bundled tessdata).
3. Tesseract via pytesseract if the binary is available.
4. No OCR.

On Render (`RENDER=true`), `auto` becomes `tesserocr` unless `OCR_ENGINE` is set
explicitly.

### Embeddings

| Variable | Default | Purpose |
|----------|---------|---------|
| `EMBEDDING_PROVIDER` | `auto` | `auto`, `fastembed`, or `hash` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed model |
| `EMBEDDING_DIM` | `384` | Hash-embedding dimension |

`auto` uses FastEmbed when it can initialize, otherwise the deterministic hash
embedder. On Render, `auto` becomes `hash` unless explicitly set.

### Limits and validation

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_FILE_MB` | `200` | Maximum size per uploaded file |
| `MAX_FILES_PER_UPLOAD` | `20` | Maximum files in one request |
| `MAX_PDF_PAGES` | `1500` | Maximum PDF pages per document |
| `WORKER_POLL_SECONDS` | `1.0` | Idle worker poll interval |
| `WORKER_CONCURRENCY` | `2` | Worker threads on Postgres (SQLite always uses 1) |
| `JOB_STALE_SECONDS` | `1800` | Requeue running jobs whose worker heartbeat is older than this |
| `AUTO_WORKER` | `false` | Start an in-process worker with the API |

Render automatically starts the in-process worker even if `AUTO_WORKER` is not
set, because Render sets `RENDER=true`.

### Frontend environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKEND_URL` | `http://localhost:8000` | Public API base URL used by the Next.js proxy; no trailing slash |
| `NODE_VERSION` | Render-managed | Node version for Render (blueprint uses `22.12.0`) |

---

## Supported formats, limits, and upload errors

### Supported extensions

| Kind | Extensions |
|------|------------|
| PDF | `.pdf` |
| Images | `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff` |
| Spreadsheets | `.xlsx`, `.xls`, `.csv` |

### Limits

| Limit | Value |
|-------|-------|
| File size | 200 MB (`MAX_FILE_MB`) |
| Files per upload | 20 (`MAX_FILES_PER_UPLOAD`) |
| PDF pages | 1,500 (`MAX_PDF_PAGES`) |
| Spreadsheet sheets | 25 per workbook |
| Spreadsheet rows | 20,000 per sheet (truncated with a warning) |
| XLSX uncompressed size | 1 GB guard |
| XLSX compression ratio | 200× guard (zip-bomb protection) |
| Login rate limit | 10 attempts / 5 minutes / IP + email |

### Upload rejection codes

| Code | Meaning |
|------|---------|
| `UNSUPPORTED_TYPE` | Extension not in the allowlist |
| `FILE_TOO_LARGE` | Exceeds `MAX_FILE_MB` |
| `EMPTY_FILE` | Zero-byte upload |
| `INVALID_PDF` | Missing `%PDF-` header |
| `INVALID_IMAGE` | JPEG/PNG/TIFF content does not match its extension |
| `INVALID_XLSX` | Not a valid XLSX workbook |
| `INVALID_XLS` | Not a valid legacy XLS workbook |
| `INVALID_CSV` | Binary content or undecodable CSV |
| `EMPTY_CSV` | No data rows |
| `MIME_MISMATCH` | Detected content type contradicts the extension |
| `ZIP_BOMB` | Unsafe XLSX expansion size or compression ratio |
| `STORAGE_ERROR` | Storage backend rejected the upload |
| `UPLOAD_ERROR` | Unexpected per-file failure |

Processing failures use additional codes such as `INVALID_PDF`,
`ENCRYPTED_PDF`, `EMPTY_PDF`, `TOO_MANY_PAGES`, `SPREADSHEET_ERROR`,
`EXTRACTION_ERROR`, `PROCESSING_ERROR`, and `WORKER_LOST`.

---

## How processing works

### 1. Upload and dedupe

`POST /api/v1/documents` performs these steps per file:

1. Sanitize the filename.
2. Validate the extension.
3. Stream the file to a temporary path while enforcing the size cap.
4. Validate magic bytes (and XLSX zip-bomb guards).
5. Compute SHA-256.
6. If an active document with the same hash exists, return it with
   `duplicate: true` instead of storing a second copy.
7. Store the original under `documents/<first-2-hex>/<sha><ext>`.
8. Create a `Document` and a queued `ProcessingJob`.
9. Write a `document.upload` audit event.
10. Return HTTP `202` with accepted and rejected files.

### 2. PDF and image text extraction

- PDF pages are opened with PyMuPDF.
- If the digital text layer has at least ~40 non-whitespace characters, it is
  used directly.
- Otherwise the page is rendered at 250 DPI and sent to the selected OCR engine.
- Encrypted PDFs are rejected with `ENCRYPTED_PDF`.
- Empty PDFs are rejected with `EMPTY_PDF`.
- Pages beyond `MAX_PDF_PAGES` are rejected with `TOO_MANY_PAGES`.
- Images are normalized (EXIF orientation, RGB/grayscale, max dimension 3200)
  before OCR.
- Each page stores its text, source (`digital` / `ocr` / `none`), OCR
  confidence, dimensions, and any page-level error.

### 3. Page grouping

`backend/app/parsers/grouping.py` splits page text into logical invoices using:

- Invoice-number label lines and inline values.
- Record headings such as `COMMERCIAL TAX INVOICE — RECORD 03`.
- Continuation markers (`page 2 of 3`, `continued`).
- Supplier/date/total fingerprints.
- Non-invoice headings (internal procurement, appendix, terms, notes) are
  excluded.

A single page can contain multiple invoices; grouping keeps each invoice's text
separate so values do not leak across records. Every invoice stores a
`page_start`, `page_end`, and `grouping_confidence`.

### 4. Extraction

Extraction combines two sources:

1. **Deterministic parser** (`extraction/deterministic.py`) — conservative regex
   and layout rules. It runs without any API key and never invents values.
2. **Groq LLM** (`extraction/groq.py`) — enabled only when `GROQ_API_KEY` is
   set. The prompt is schema-constrained, JSON-output oriented, and delimited so
   document text is treated as untrusted content.

`extraction/service.py` merges the results:

- Every non-null extracted value is checked against the source page. If the
  quoted evidence cannot be found, confidence is reduced and a `V016` warning is
  recorded; if the value cannot be located at all, confidence drops to `0.25`.
- Missing values stay `null` with a reason.
- Manual corrections are normalized, marked with source `manual`, stored with
  confidence `1.0`, and carry no evidence quote.

Each extraction stores a version, schema version, prompt version, model, source
(`ai`, `fallback`, or `manual`), field confidences, and overall confidence.

### 5. Validation rules

Findings are persisted with `rule_code`, `severity` (`info` / `warning` /
`error`), `field_path`, `message`, `expected`, `actual`, and `status`
(`open` / `resolved` / `dismissed`).

| Code | Check | Severity |
|------|-------|----------|
| `V001` | Required fields: invoice number, date, supplier, total, currency; missing customer is a warning | error / warning |
| `V002` | Invoice date is not in the future and not more than 15 years old | error / warning |
| `V003` | Subtotal, tax, and total are not negative (credit notes are not auto-handled) | error |
| `V004` | `subtotal + tax = total` within `AMOUNT_TOLERANCE`; missing components produce an info finding | error / info |
| `V005` | Sum of line-item amounts equals subtotal within max(0.02, 0.5%) | error |
| `V006` | `quantity × unit_price = amount` per line item within max(0.02, 1%) | warning |
| `V007` | Line-item tax rate is within 0–35%; invoice effective tax rate is at most 35% | warning |
| `V009` | Invoice has a non-zero total but no line items | warning |
| `V010` | Exact duplicate: normalized supplier + invoice number already exists | error |
| `V011` | Near duplicate: same supplier, date ±1 day, total within tolerance, fuzzy supplier score ≥ 90 | warning |
| `V013` | PDF↔spreadsheet difference in subtotal, tax, total, date, currency, or supplier | error / warning |
| `V014` | Spreadsheet-internal duplicate invoice number or `subtotal + tax ≠ total` | error |
| `V015` | Required-field confidence is below `AUTO_APPROVE_CONFIDENCE` | warning |
| `V016` | A non-null value's evidence quote could not be verified | warning |

The per-line-item checks `V006` and `V007` inspect the first 20 line items;
`V005` sums all extracted line items.

Rule IDs `V008` (currency ISO check), `V012` (PDF↔PDF conflict as a separate
finding), and `V017` (prompt-injection detection) are reserved in the product
catalog. The current build handles currency normalization in the parser,
PDF↔PDF conflicts through reconciliation + `V010`, and prompt-injection defense
through schema-constrained prompts rather than a separate finding.

Spreadsheet validation additionally writes row-level warnings to
`SheetRow.warnings`:

- `invalid date format`
- `invalid or missing subtotal`
- `invalid currency (XYZ)`
- `math mismatch: subtotal + tax (4500.00) != total (4100.00)`
- `duplicate invoice number`
- `missing invoice number`, `missing total`, `missing parent invoice number`

### 6. Duplicate and near-duplicate detection

- **Exact duplicates (`V010`):** same normalized invoice number and supplier.
  A `pdf_pdf` reconciliation is created for the pair.
- **Near duplicates (`V011`):** same supplier (fuzzy token-set ratio ≥ 90),
  invoice date within one day, and total within `AMOUNT_TOLERANCE`.
- Duplicate documents uploaded byte-for-byte are caught earlier by SHA-256 and
  are not processed twice.

### 7. Reconciliation

Two match types are produced:

**PDF↔spreadsheet (`pdf_sheet`)**

- Find a sheet row by normalized invoice number.
- Compare `subtotal`, `tax`, `total`, `invoice_date`, `currency`, and
  `supplier_name` (fuzzy threshold 80).
- `total` differences are errors; other differences are warnings.
- Store a reconciliation row with field diffs and status `matched` or `mismatch`.

**PDF↔PDF (`pdf_pdf`)**

- Created for exact duplicate invoice identities.
- Compare subtotal, tax, total, and invoice date.
- Store `matched_document_id` / `matched_invoice_id` and the diff list.

Reconciliation rows and findings are linked by invoice and field. The
`reconciliation_sync.py` module implements:

- `dismiss_linked_findings()` — dismissing a reconciliation dismisses its
  `V013`/`V010` findings.
- `auto_dismiss_acknowledged_reconciliations()` — once every linked finding is
  resolved/dismissed, the reconciliation is dismissed automatically.

This prevents the same difference from blocking approval twice.

### 8. Approval rules

Approval is blocked by:

- Open `warning` or `error` findings attached to the invoice (including
  document-level findings with `invoice_id = null`).
- `mismatch` reconciliations where the invoice is either side of the match.
- For spreadsheet documents: any open `warning`/`error` finding on the document
  or any `mismatch` reconciliation matched to that document.

Approval succeeds when all of those are cleared. `info` findings do not block.
Explicitly approved extractions store `review_status = approved`, reviewer,
timestamp, and note; auto-approved extractions are marked approved without a
reviewer. The document becomes `completed` when all its invoices are approved.

### 9. Indexing and search

After extraction:

- Page text is split into overlapping chunks (~1,400 characters, 150-character
  overlap).
- Each invoice gets a summary chunk: invoice number, supplier, date, total, and
  up to 20 line items.
- Spreadsheet sheets get summary chunks.
- Embeddings are generated in batches (up to 500 semantic chunks per document).
- Chunks are searchable by keyword, vector similarity, or hybrid reciprocal-rank
  fusion.

### 10. Background worker

Jobs live in the `processing_jobs` table.

- **Postgres:** atomic claim with `FOR UPDATE SKIP LOCKED`.
- **SQLite:** polling claim of the earliest due job; one worker thread.
- **Retries:** retryable failures are re-queued with exponential backoff
  `min(300s, 15s × 2^(attempt − 1))` (15s, 30s, 60s, …) up to `max_attempts`
  (default 3, so two retries).
- **Stale recovery:** a `running` job whose heartbeat is older than
  `JOB_STALE_SECONDS` is requeued with `WORKER_LOST`.
- **Graceful shutdown:** SIGTERM/SIGINT stop the worker between jobs.
- **Scale-out:** on Postgres, run multiple worker processes/threads; the claim
  query prevents double-processing.

On Render, `AUTO_WORKER=true` runs one in-process worker inside the API service.

---

## Spreadsheet ingestion and the six fixes

The spreadsheet pipeline had six bugs across the parser, field normalizer,
validation engine, API, and sheet UI. All are fixed and covered by regression
tests using
`backend/tests/fixtures/invoice_test_suite_cross_verification.xlsx`.

### Bug 1 — Multi-sheet classification

**Before:** every row in every worksheet became a standalone invoice. The 20
line-item rows in `Line_Items_Detail` became 20 false invoices with `—` for
date, supplier, customer, subtotal, tax, and total.

**After:** each sheet is classified by header inspection:

- `INVOICE_LEDGER` → top-level invoice/PO records.
- `LINE_ITEMS` → parsed as `line_number`, `sku`, `description`, `quantity`,
  `unit_price`, `line_total`, and linked to the parent invoice by
  `invoice_number`.
- `RECONCILIATION` (variance/comparison columns) → skipped for top-level
  extraction and never duplicated.

Result on the cross-verification workbook: **14 invoice/PO records** (8 from
`Master_PO_Ledger` + 6 from `Dirty_Data_Stress_Test`) and **20 child line
items**, not 34 top-level rows.

### Bug 2 — Supplier / customer dropped in the normalized view

**Before:** `SUPPLIER` and `CUSTOMER` were `null` in the Normalized view even
though they existed in Raw.

**After:** the case-insensitive header synonym map includes:

- Supplier: `supplier name`, `supplier`, `vendor`, `vendor name`, `merchant`,
  `supplier_name`, `seller`, `bill from`, `company`.
- Customer: `customer name`, `customer`, `client`, `buyer`, `bill to`,
  `customer_name`.
- Plus invoice number/date, subtotal, tax, total, and currency aliases.

Headers are trimmed, lowercased, and have whitespace/underscores collapsed.

### Bug 3 — Summary/footer `TOTAL` rows not filtered

**Before:** `Master_PO_Ledger` row 10 (`TOTAL`, with `=SUM(...)` formulas) was
extracted as an invoice.

**After:** rows where the first non-empty cell or identifier column matches
`TOTAL`, `SUBTOTAL`, `GRAND TOTAL`, or `SUM` (case-insensitive) are skipped.
Rows with only summary totals and no identifier/supplier/customer are also
skipped. `openpyxl` loads with `data_only=True`, so formula cells evaluate to
numbers instead of raw `=SUM(G2:G9)` strings.

### Bug 4 — Silent currency coercion (`XYZ` → `USD`)

**Before:** unknown currency `XYZ` was silently replaced with `USD` and
formatted as `US$4,000.00` with no warning.

**After:** `normalize_currency_cell()` validates against the active ISO 4217
code set (`ISO_4217_CODES`, kept separate from the PDF text-scanning subset to
avoid false matches such as `ALL`, `TRY`, `TOP`). Recognized codes/symbols are
canonicalized; an explicit unknown value like `XYZ` is preserved and reported
with an `invalid currency (XYZ)` warning instead of being coerced to USD.

### Bug 5 — Missing validation warnings on dirty rows

**Before:** only row 3 showed `missing invoice number`; rows with bad dates,
non-numeric subtotals, math mismatches, and duplicates had no warnings.

**After:** row-level validation populates `warnings` for:

- Unparseable date → `invalid date format`
- Non-numeric subtotal → `invalid or missing subtotal`
- Math mismatch →
  `math mismatch: subtotal + tax (4500.00) != total (4100.00)`
- Duplicate invoice number → `duplicate invoice number` on both rows
- Unknown currency → `invalid currency (XYZ)`

Warnings are stored on `SheetRow.warnings`, exposed through `/sheet-rows`, and
shown in the Normalized sheet UI.

### Bug 6 — Raw vs normalized row-count consistency

**Before:** the UI showed 34 extracted rows, mixing invoices, line items, and
comparison rows.

**After:** `SheetView` separates **Invoice / PO records** (14) from **Child line
items** (20) with dedicated tabs and counts. `/sheet-rows?row_type=` supports
`invoice` (default), `line_item`, and `all`. Responses include `invoice_total`,
`line_item_total`, `row_type`, `parent_invoice_number`, and `line_item_count`.
Line items are merged into the parent invoice row's `normalized.line_items`.

**Expected workbook result:** 14 invoice/PO records + 20 child line items.

Parent attachment:

| Parent invoice | Linked line items |
|----------------|-------------------|
| `INV-2026-00101` | 6 |
| `INV-2026-00102` | 4 |
| `INV-2026-00103` | 4 |
| `INV-2026-00107` | 3 |
| Unlinked (`MISSING`) | 3 |

### Regression workbook sheets

`backend/tests/fixtures/invoice_test_suite_cross_verification.xlsx` contains:

| Sheet | Classification | Invoice rows | Line items | Purpose |
|-------|----------------|--------------|------------|---------|
| `Master_PO_Ledger` | `INVOICE_LEDGER` | 8 | — | Clean baseline, multi-currency, math error, duplicate |
| `PDF_vs_Excel_Comparison` | `RECONCILIATION` | 0 | — | Skipped for top-level extraction |
| `Line_Items_Detail` | `LINE_ITEMS` | 0 | 20 | Linked to parent invoices by invoice number |
| `Dirty_Data_Stress_Test` | `INVOICE_LEDGER` | 6 | — | Missing invoice number, invalid date, non-numeric subtotal, unknown currency, math mismatch, duplicate |

Dirty-row expected warnings:

| Row | Issue | Expected warning |
|-----|-------|------------------|
| `ROW-003` (`INV-2026-00203`) | `INVALID_DATE_STR` | `invalid date format` |
| `ROW-004` (`INV-2026-00204`) | Subtotal `N/A` | `invalid or missing subtotal` |
| `ROW-006` (`INV-2026-00206`) | Currency `XYZ`; subtotal + tax ≠ total | `invalid currency (XYZ)`, `math mismatch: ...` |
| `ROW-001` / `ROW-007` (`INV-2026-00201`) | Duplicate invoice number | `duplicate invoice number` on both rows |

---

## API reference

Base path: `/api/v1`. Auth: `Authorization: Bearer <token>` or the HttpOnly
cookie set by login. Read endpoints require any authenticated user; mutations
require the `admin` or `reviewer` role.

### Conventions

- JSON request/response bodies unless noted.
- Timestamps are ISO 8601 UTC.
- Errors use FastAPI's `{ "detail": "..." }` shape.
- `409` means a workflow conflict (approval blocked, stale extraction, active
  job).
- Upload returns `202 Accepted` because processing is asynchronous.

### Auth

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/auth/login` | Log in; returns `{token, user}` and sets an HttpOnly cookie |
| `POST` | `/auth/logout` | Clear the auth cookie |
| `GET` | `/auth/me` | Current user |

### Documents

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/documents` | Multi-file upload; `202` with accepted/rejected files |
| `GET` | `/documents` | List/filter/paginate (`q`, `status`, `kind`, `supplier`, `date_from`, `date_to`, `sort`, `limit`, `offset`) |
| `GET` | `/documents/{id}` | Detail: pages, invoices, current extractions, findings, reconciliations, jobs |
| `GET` | `/documents/{id}/status` | Lightweight status/progress/job summary |
| `GET` | `/documents/{id}/file` | Original file (signed URL or stream) |
| `GET` | `/documents/{id}/pages/{n}/preview` | Rendered page/image preview |
| `GET` | `/documents/{id}/text` | Page text (`page_from`, `page_to`) |
| `GET` | `/documents/{id}/invoices` | Invoices for the document |
| `GET` | `/documents/{id}/findings` | Findings for the document |
| `GET` | `/documents/{id}/sheet-rows` | Spreadsheet rows (`sheet`, `row_type`, `limit`, `offset`) |
| `POST` | `/documents/{id}/reprocess` | Clear results and re-queue (`{"stage": "all"}`) |
| `POST` | `/documents/{id}/approve` | Approve all invoices / a spreadsheet document |

### Invoices

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/invoices/{id}` | Invoice detail with current extraction |
| `GET` | `/invoices/{id}/extractions` | Every extraction revision |
| `GET` | `/invoices/{id}/corrections` | Correction audit trail |
| `PATCH` | `/invoices/{id}/extractions/{extraction_id}` | Save a correction as a new immutable version |
| `POST` | `/invoices/{id}/review` | `{"action": "approve"}` or `{"action": "reopen"}` |

Correction body:

```json
{
  "changes": {
    "invoice_number": "INV-2024-0042",
    "total": "10800.00",
    "line_items": [
      {
        "description": "Freight",
        "quantity": "1",
        "unit_price": "9000.00",
        "amount": "9000.00",
        "tax_rate": "20"
      }
    ]
  },
  "reason": "Corrected total against the source PDF"
}
```

Optional `If-Match: <version>` provides optimistic concurrency.

### Findings and reconciliations

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/findings` | List/filter by `status`, `document_id`, `invoice_id`, `limit` |
| `PATCH` | `/findings/{id}` | `{"status": "resolved"}` or `{"status": "dismissed"}`, optional note |
| `GET` | `/reconciliations` | List/filter by `document_id`, `invoice_id`, `status` |
| `PATCH` | `/reconciliations/{id}` | `{"status": "matched"}` or `{"status": "dismissed"}`, optional note |

### Analytics, search, and system

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/analytics/sales` | Sales analytics (`currency`, `months` 1–60, `years` 1–10) |
| `GET` | `/search` | Search (`q`, `mode`, filters, `limit`) |
| `GET` | `/search/status/embedding` | Embedding provider availability |
| `GET` | `/meta` | Runtime metadata: environment, AI, OCR, embeddings, storage, extensions |
| `GET` | `/health/live` | Liveness |
| `GET` | `/health/ready` | Readiness (checks the database) |
| `GET` | `/dashboard/stats` | Dashboard counts and queue depth |
| `GET` | `/jobs` | List jobs (`status_filter`, `document_id`, `limit`) |
| `GET` | `/jobs/{id}` | Job detail |
| `POST` | `/jobs/{id}/retry` | Retry a failed/cancelled job |

The root paths `/health/live` and `/health/ready` are also exposed outside the
API prefix.

### Search parameters

`GET /search` supports:

- `q` — query text (empty query returns filter-only results).
- `mode` — `keyword`, `semantic`, `hybrid` (default).
- `status`, `kind`, `supplier`, `currency`.
- `date_from`, `date_to` (YYYY-MM-DD).
- `min_total`, `max_total`.
- `has_findings` (boolean).
- `limit` 1–100 (default 20).

### Example: log in and upload with curl

```bash
API=http://localhost:8000

# Log in and capture the token
TOKEN=$(curl -s -X POST "$API/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@docintel.local","password":"admin12345"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

# Upload an invoice and a ledger together
curl -s -X POST "$API/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@backend/data/samples/acme_invoice.pdf" \
  -F "files=@backend/tests/fixtures/invoice_test_suite_cross_verification.xlsx"

# Poll status
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/api/v1/documents/<document-id>/status"

# Approve once blockers are cleared
curl -s -X POST "$API/api/v1/documents/<document-id>/approve" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"note":"approved after review"}'
```

---

## Analytics

`GET /api/v1/analytics/sales` returns:

- `summary`: invoice count, total, average invoice, supplier count, approved
  count, pending count, dated/undated count, missing-total count, excluded
  duplicates.
- `currencies`: count and total per currency.
- `monthly`: a continuous month series ending at the latest invoice date (or
  today), with total, invoice count, approved total, and approved count.
- `yearly`: a continuous year series.
- `top_suppliers`: top six by total.
- `statuses`: approved vs pending counts and totals.

Counting rules:

- Only the **current extraction** of each invoice contributes.
- Invoices with an open `V010` duplicate finding are excluded.
- Duplicate identities are counted once, preferring the clean, approved, then
  earliest copy.
- Amounts are **never summed across currencies**. The response selects the
  requested currency, or the currency with the most invoices, and reports the
  rest separately.
- Missing dates are excluded from monthly/yearly buckets but still counted in
  the summary.
- Missing totals contribute to counts but not to monetary totals.

No FX conversion is performed.

---

## Search

### Modes

- **Keyword:**
  - Postgres: `to_tsvector('english', content)` + `websearch_to_tsquery`,
    ranked with `ts_rank_cd` and a GIN index.
  - SQLite: `ILIKE` on content and invoice-number metadata.
- **Semantic:**
  - FastEmbed `BAAI/bge-small-en-v1.5` (384 dimensions) when available.
  - Deterministic hash embedder otherwise (lexical, not truly semantic).
  - Postgres uses pgvector cosine distance with an HNSW index; SQLite computes
    cosine similarity in Python over up to 500 chunks.
- **Hybrid:** reciprocal-rank fusion of keyword and semantic results
  (`1 / (60 + rank)`), with filters applied afterward.

### Indexed content

- Page text chunks with page numbers and text source.
- Invoice summary chunks with invoice number, supplier, date, total, currency,
  and up to 20 line items.
- Spreadsheet sheet summaries and row text.

Results include the document summary, snippet, page number, invoice ID, score,
and match type. An empty query returns the latest documents matching the
selected filters.

---

## Background processing

Jobs live in a `processing_jobs` table. A separate `app.worker` process claims
jobs with `FOR UPDATE SKIP LOCKED` on Postgres or a polling claim on SQLite,
runs them with retries and exponential backoff, and recovers stale jobs after
`JOB_STALE_SECONDS` (default 30 minutes). Workers scale horizontally on
Postgres.

Run a standalone worker:

```bash
cd backend
uv run python -m app.worker
```

Run an in-process worker with the API:

```bash
AUTO_WORKER=true uv run uvicorn app.main:app --port 8000
```

Render starts the in-process worker automatically.

Job lifecycle:

```text
queued → running → completed
              ↘ retry_wait → running → ...
              ↘ failed
              ↘ cancelled (reprocess/reset)
```

---

## Evaluation

The evaluation harness lives in `eval/`.

```bash
cd eval
python generate_fixtures.py   # synthetic labeled PDFs + ground truth
python run_eval.py            # writes results.json / results.csv / report.md
```

`generate_fixtures.py` builds a reproducible synthetic dataset of ReportLab
PDFs with matching `ground_truth.jsonl`, so every field is known by
construction and the run is deterministic and offline. `run_eval.py` uploads
each fixture through the real API, processes it synchronously, reads back the
extraction, and compares each field to ground truth.

### Metrics computed

| Metric | Definition |
|--------|------------|
| Overall field F1 | Micro-averaged F1 over all required fields (invoice number, date, supplier, customer, currency, subtotal, tax, total) |
| Precision / recall | Per field; a predicted non-null value where ground truth is null is a false positive (hallucination); a missed value is a false negative |
| Exact-document rate | Share of documents where every required field matches ground truth exactly |
| Null / abstention accuracy | Share of ground-truth-null fields correctly predicted as null |
| Line-item F1 | Set F1 over (description, amount) pairs |

### Measured baseline (deterministic fallback, no Groq key)

Run: `cd eval && python generate_fixtures.py && python run_eval.py`

Result (`eval/report.md`, 4 synthetic invoices):

- Overall field F1: **0.9524**
- Overall precision: **0.9375**
- Overall recall: **0.9677**
- Exact-document rate: **0.75** (3/4)
- Null/abstention accuracy: **0.0** (1 abstention opportunity, 1 false positive)
- Line-item F1: **1.0** (all 4 documents)

### Per-field evaluation matrix

| Field | Precision | Recall | F1 |
|-------|-----------|--------|----|
| `invoice_number` | 1.0 | 1.0 | 1.0 |
| `invoice_date` | 1.0 | 1.0 | 1.0 |
| `supplier_name` | 1.0 | 1.0 | 1.0 |
| `customer_name` | 0.75 | 0.75 | 0.75 |
| `currency` | 1.0 | 1.0 | 1.0 |
| `subtotal` | 1.0 | 1.0 | 1.0 |
| `tax` | 0.75 | 1.0 | 0.8571 |
| `total` | 1.0 | 1.0 | 1.0 |

Re-run with `GROQ_API_KEY` set in `backend/.env` to measure the Groq path.

### Limitations

- The baseline above uses the deterministic extractor, not Groq.
- The dataset is small and synthetic (4 invoices). Scanned/degraded invoices,
  image invoices, multi-sheet spreadsheets, and near-duplicate pairs are not yet
  included in the evaluation set.
- `eval/queries.json` defines 15 search queries with expected document IDs and
  negative cases for Recall@10/MRR, but those metrics are not yet executed
  against a populated index.

---

## Tests

The backend suite contains **88 deterministic, offline tests** across 7 test
modules. No live LLM, network, Supabase, or Tesseract install is required.

```bash
cd backend
uv run pytest tests/ -q      # 88 passed
uv run ruff check app tests  # lint
```

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

### Test suite matrix

| Test module | Tests | Coverage |
|-------------|-------|----------|
| `test_utils.py` | 21 | Decimal parsing (plain, integer, negative parentheses, European/thousand separators, currency symbols, empty, garbage), invoice-number normalization, supplier normalization, currency code/symbol/unknown handling, flexible date parsing, constants |
| `test_parsers.py` | 7 | CSV/XLSX parsing, unsupported types, cross-verification sheet classification and counts (14 invoices + 20 line items), header aliases and unknown currency, dirty-row warnings, line-item parent linking |
| `test_validation.py` | 7 | V001 required fields, V002 future date, V004 arithmetic mismatch/OK, V005 line-item sum, V009 missing line items, V015 low confidence |
| `test_grouping.py` | 9 | Single page → one invoice, continuation pages, new invoice numbers, missing numbers, confidence bounds, record headings within/across pages, inline invoice numbers, empty input |
| `test_extraction.py` | 9 | Core-field extraction, currency symbols, line items, OCR table artifacts (`|`/`-` rows), never inventing missing fields, AI-disabled behavior, evidence quotes, multiline suppliers, image-style auto-approve confidence |
| `test_analytics.py` | 5 | Monthly/yearly totals + currency filter, default currency and duplicate exclusion, duplicate identity counted once, missing date/total reporting, authentication |
| `test_api.py` | 30 | Auth (4), upload (4), document list/detail (3), findings (1), search (2), reprocess/jobs (2), meta (1), corrections (1), worker retry (1), approval (2), reconciliation dismissal (4), spreadsheet approval (3), cross-verification workbook (2) |

The approval and reconciliation tests in `test_api.py` cover:

- Dismissing the last linked finding automatically dismisses the reconciliation
  and unblocks approval.
- Dismissing a reconciliation automatically dismisses its linked `V013`/`V010`
  findings.
- Spreadsheet approval blocks on open findings/mismatches, then succeeds after
  dismissal.
- Cross-document findings do not block an unrelated invoice in another
  document.

### Regression workbook

`backend/tests/fixtures/invoice_test_suite_cross_verification.xlsx` is the committed
4-sheet workbook used by `test_parsers.py`, `test_api.py`, and the spreadsheet
UI checks. Its expected result is **14 invoice/PO records + 20 child line
items**, with the parent attachments and dirty-row warnings described in
[Spreadsheet ingestion and the six fixes](#spreadsheet-ingestion-and-the-six-fixes).

---

## Production: Supabase

See `docs/supabase-setup.md` for the full provisioning walkthrough.

### 1. Create the project

Create a project at https://supabase.com. From **Settings → API**, note:

- **Project URL** → `SUPABASE_URL`
- **Service role key** → `SUPABASE_SERVICE_KEY` (backend only; never expose it
  to the browser)

From **Settings → Database**, copy the connection string:

```text
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

Use the `+psycopg` driver in the URL (the backend normalizes plain
`postgresql://` too):

```ini
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

The transaction pooler on port `6543` works. The backend disables psycopg
server-side prepared statements (`prepare_threshold=None`) because PgBouncer
transaction mode does not support them.

### 2. Enable pgvector

The backend runs this automatically on startup:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

You can also run it once in the Supabase SQL Editor.

### 3. Create the Storage bucket

In **Storage → Create a bucket**:

- Name: `documents` (or set `SUPABASE_BUCKET`)
- Public: **false**
- Enable RLS: **true**

The service role bypasses RLS, so no extra policy is required for the backend.
Add user-scoped policies only if you expose direct browser access.

### 4. Configure the backend

```ini
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
ENVIRONMENT=production

STORAGE_BACKEND=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=<service-role-key>
SUPABASE_BUCKET=documents

SECRET_KEY=<long-random-string>
COOKIE_SECURE=true
ACCESS_TOKEN_MINUTES=720
FRONTEND_ORIGIN=https://your-web-app.example.com

# Optional; deterministic extraction works without it
GROQ_API_KEY=<your-groq-key>
```

### 5. Initialize the schema and demo user

```bash
cd backend
uv sync --extra dev
uv run python -m app.cli init-db
```

This creates all tables, the pgvector extension, the GIN full-text index, the
HNSW vector index, the sheet-rows GIN index, and seeds the demo user. Change the
demo password or disable the user in production.

### 6. Run

```bash
# API
uv run uvicorn app.main:app --port 8000

# Worker (separate process; scale horizontally on Postgres)
uv run python -m app.worker
```

Set `AUTO_WORKER=true` only for single-service deployments.

### 7. Verify

```bash
curl https://<your-api>/health/ready
curl https://<your-api>/api/v1/meta
```

`meta.storage_backend` should be `supabase`; `meta.ai_enabled` is `true` when
`GROQ_API_KEY` is set.

### Supabase production checklist

- [ ] Rotate `SECRET_KEY` away from the default.
- [ ] Set `COOKIE_SECURE=true` and serve the API over HTTPS.
- [ ] Keep `SUPABASE_SERVICE_KEY` in backend-only environments.
- [ ] Change the demo password or disable the seeded user.
- [ ] Review `FRONTEND_ORIGIN` and login rate limits.
- [ ] Enable Supabase backups and point-in-time recovery.
- [ ] Use the pooler URL on port `6543` for serverless/free-tier deployments.

---

## Deploy on Render

The repository includes `render.yaml`, which defines two free web services.

### Blueprint services

| Service | Runtime | Root | Build | Start |
|---------|---------|------|-------|-------|
| `docintel-api` | Python 3.12.7 | `backend` | `pip install --upgrade pip && pip install -r requirements.txt` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `docintel-web` | Node 22.12.0 | `frontend` | `npm ci && npm run build` | `npm start -- -p $PORT` |

> When a Render service uses `rootDir: backend`, build/start commands run from
> that directory and must not include the `backend/` prefix. If you configure
> the API service from the repository root instead, use
> `pip install -r backend/requirements.txt` and
> `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

### Deploy steps

1. In Render, choose **New → Blueprint** and connect the GitHub repository.
2. Apply the blueprint.
3. Fill the `sync: false` secrets:
   - API: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
     `FRONTEND_ORIGIN`, and optionally `GROQ_API_KEY`.
   - Web: `BACKEND_URL` (the API URL, no trailing slash).
4. Deploy the API first, then the web app.
5. Set each service's public URL in the other service's environment:
   - API `FRONTEND_ORIGIN` = web URL.
   - Web `BACKEND_URL` = API URL.
6. Confirm the health check passes at `/health/ready`.

### Blueprint environment

`docintel-api` sets:

| Variable | Value |
|----------|-------|
| `PYTHON_VERSION` | `3.12.7` |
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | generated by Render |
| `STORAGE_BACKEND` | `supabase` |
| `SUPABASE_BUCKET` | `documents` |
| `AUTO_WORKER` | `true` |
| `COOKIE_SECURE` | `true` |
| `EMBEDDING_PROVIDER` | `hash` |
| `OCR_ENGINE` | `tesserocr` |
| `WORKER_CONCURRENCY` | `1` |

`backend/.python-version` (`3.12`) and `PYTHON_VERSION=3.12.7` keep Render on a
supported Python version (`>=3.12,<3.14`).

### Live deployment

The current deployment is:

- Web: https://docintel-web.onrender.com
- API: https://ai-powered-document-intelligence-system-5.onrender.com
- Storage: Supabase (`documents` bucket)
- Database: Supabase Postgres + pgvector
- Runtime metadata: `environment=production`, `storage_backend=supabase`,
  `embedding_provider=hash`, `ocr_engine=tesserocr`

### Render free-tier notes

- 512 MB RAM, 0.1 CPU.
- Spins down after ~15 minutes idle; cold start is ~43 seconds (occasionally
  30–60 seconds).
- The frontend retries cold-start `502/503/504` responses for GET requests and
  login up to 12 times at 5-second intervals.
- Keep `WORKER_CONCURRENCY=1`; the in-process worker is already single-threaded
  on the free plan.
- Keep `EMBEDDING_PROVIDER=hash` to avoid downloading/loading FastEmbed weights.
- Keep `OCR_ENGINE=tesserocr` with the bundled `eng.traineddata` to stay near
  ~90 MB peak OCR memory instead of RapidOCR's ~400 MB.
- Free instances are not suitable for large batches or heavy concurrent OCR.
  Upgrade the plan and switch to FastEmbed/RapidOCR when memory allows.

---

## OCR, memory, and embedding notes

### OCR engines

| Engine | Memory | Quality | When to use |
|--------|--------|---------|-------------|
| `rapidocr` | ~400 MB peak | Strong general OCR | Local development / larger instances |
| `tesserocr` | ~90 MB peak | Good for printed invoices | Render free tier (default there) |
| `tesseract` | External binary | Good | When Tesseract is installed and you prefer pytesseract |
| `none` | Minimal | No OCR | Digital PDFs only |

`auto` prefers RapidOCR locally, then tesserocr, then pytesseract, then none. On
Render it prefers tesserocr. The bundled
`backend/app/tessdata/eng.traineddata` means Render needs no system package or
runtime model download for tesserocr. Set `TESSDATA_PREFIX` to override it.

OCR preprocessing includes EXIF orientation, grayscale conversion, denoising,
contrast enhancement, and a maximum dimension of 3200 px.

### Embeddings

| Provider | Behaviour | Notes |
|----------|-----------|-------|
| `fastembed` | Loads `BAAI/bge-small-en-v1.5` (384 dims) | Best semantic quality; downloads weights on first use; needs memory |
| `hash` | Deterministic feature hashing (blake2b) | Zero download; lexical rather than truly semantic; used on Render free tier |
| `auto` | FastEmbed if it initializes, otherwise hash | Falls back with a warning |

On Render, `auto` becomes `hash` unless `EMBEDDING_PROVIDER` is explicit. Search
still works in keyword and hybrid modes because hybrid fuses keyword and
semantic ranks.

### Memory guidance

- One OCR page at a time; pages are rendered at 250 DPI for OCR and 150 DPI for
  previews.
- Embedding batches are 32 chunks; semantic indexing is capped at 500 chunks per
  document.
- On 512 MB, avoid concurrent large image uploads. If an instance restarts
  during OCR, confirm `OCR_ENGINE=tesserocr` and `WORKER_CONCURRENCY=1`.
- The in-process worker shares memory with the API; a separate worker on a
  larger plan is preferable.

---

## Troubleshooting

### "Cannot approve: N open finding(s) and M reconciliation mismatch(es)"

This means approval is correctly blocked. Fix it by either route:

1. **Findings tab:** resolve or dismiss every open `warning`/`error` finding.
   Once the last linked `V013`/`V010` finding is closed, the reconciliation is
   dismissed automatically.
2. **Reconciliation tab:** dismiss the mismatch or mark it matched. Linked
   findings are dismissed automatically.

Then refresh and approve. `info` findings never block. If a mismatch has no
linked findings (for example, a manually created row), dismiss it explicitly
from the Reconciliation tab.

### The Approve button is disabled

Possible causes:

- The document is still processing (`queued`, `processing`).
- It has open `warning`/`error` findings.
- It has a `mismatch` reconciliation.
- It has no reviewable extraction ("Document has no reviewable invoices").
- You are not signed in as `admin` or `reviewer`.

Check the Findings and Reconciliation tabs and the Jobs page.

### Render returns 502/503/504 on the first request

The free API instance is waking up. Wait 30–60 seconds. The frontend retries
GET/login requests up to 12 times. If it persists, check the Render logs and the
`/health/ready` endpoint.

### Render restarts or runs out of memory during OCR

- Confirm `OCR_ENGINE=tesserocr` and `WORKER_CONCURRENCY=1`.
- Confirm `EMBEDDING_PROVIDER=hash`.
- Avoid uploading multiple large images at once.
- Use a larger Render plan for RapidOCR/FastEmbed, or run OCR locally and upload
  the resulting PDF/spreadsheet.

### OCR engine unavailable

`tesserocr` needs the bundled `backend/app/tessdata/eng.traineddata` (committed)
or a valid `TESSDATA_PREFIX`. `tesseract` needs the Tesseract binary installed:

```bash
brew install tesseract   # macOS
```

For a quick diagnostic:

```bash
curl http://localhost:8000/api/v1/meta
```

`ocr_engine` shows the active engine. If it is `none`, digital PDFs still work
but scanned images/pages will have no text.

### A scanned PDF has no text

- Open the **Pages** tab: `text_source` should be `ocr`, not `none`.
- Check OCR confidence and the page preview.
- Try `OCR_ENGINE=rapidocr` locally for difficult scans.
- Confirm the PDF is not encrypted (`ENCRYPTED_PDF`).

### Upload rejected

Use the error code table in
[Supported formats, limits, and upload errors](#supported-formats-limits-and-upload-errors).
Common causes: wrong extension, magic bytes do not match (renamed file), CSV
with binary content, or an XLSX zip-bomb guard.

### Duplicate upload returns an existing document

This is expected. Deduplication is by SHA-256. The existing document is returned
with `duplicate: true`; it is not processed again. Rename/modify the file or
delete the old document if you truly need a new copy.

### Spreadsheet shows fewer rows than expected

- Some sheets are intentionally skipped: `RECONCILIATION` comparison sheets are
  not top-level invoices.
- Summary/footer `TOTAL` rows are skipped.
- Only invoice ledgers create top-level records; line-item sheets attach to
  parent invoices.
- The cross-verification workbook should show **14 invoice/PO records + 20
  child line items**.
- Check the **Raw** view and row warnings for header-mapping problems.
- The sheet-rows API paginates with a default limit of 100 rows (max 500); use the offset/page controls to see more.

### Correcting a field returns 409

The extraction changed since you loaded it. Reload the document and reapply the
correction. The API uses `If-Match`/version checks to prevent overwriting newer
revisions.

### Search returns no results

- Try **Keyword** mode first.
- On Render, semantic search uses the hash embedder (lexical), so results are
  weaker than FastEmbed.
- Confirm the document finished indexing (`completed` or `needs_review`).
- Check `/api/v1/search/status/embedding`.
- Empty queries return filter-only results, not semantic matches.

### Analytics totals look low

- Analytics uses only the current extraction of each invoice.
- Open `V010` duplicate invoices are excluded, and duplicate identities are
  counted once.
- Only one currency is shown at a time; check the currency filter/mix.
- Invoices without dates are excluded from monthly/yearly buckets.
- Invoices without totals count toward invoice counts but not monetary totals.

### Login succeeds but API calls return 401

- The frontend stores the token in `localStorage`; clearing site data requires
  signing in again.
- If using cookies, `COOKIE_SECURE=true` requires HTTPS.
- Confirm `FRONTEND_ORIGIN` matches the web origin exactly (scheme, host, port).

### Supabase connection errors

- Use the pooler host and port (`6543` for transaction mode).
- Include `+psycopg` or let the backend normalize `postgresql://`.
- Prepared statements are disabled for PgBouncer compatibility.
- Confirm the project is not paused (free projects pause when idle).
- Confirm the `documents` bucket exists and RLS allows the service role.

### Worker is not processing jobs

- Start `uv run python -m app.worker`, or set `AUTO_WORKER=true`.
- Check `/api/v1/jobs` for queued jobs and error messages.
- A stale `running` job is requeued after `JOB_STALE_SECONDS` (30 minutes).
- Retry failed jobs from the Jobs page.

### Reprocessing removed my corrections

Reprocessing clears extraction revisions and their correction rows and creates
a fresh extraction. Audit events remain in the audit log. Reapply manual
corrections after the fresh extraction completes.

---

## Security

- **Upload validation:** extension allowlist + magic-byte checks, 200 MB/file,
  20 files/request, 1,500 PDF pages, XLSX zip-bomb guards, CSV binary checks.
- **Filename handling:** sanitized; storage keys are resolved under the storage
  root with `Path.is_relative_to` to prevent path traversal.
- **Auth:** JWT with `ACCESS_TOKEN_MINUTES` lifetime, bcrypt password hashes,
  HttpOnly cookie or Bearer token. Roles: `admin`, `reviewer`, `viewer`.
  Mutations require `admin` or `reviewer`.
- **Login rate limiting:** 10 attempts per 5 minutes per IP + email.
- **CORS:** only `FRONTEND_ORIGIN` is allowed, with credentials.
- **Security headers:** `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
  `X-Request-ID`.
- **Prompt safety:** extracted text is untrusted. The Groq prompt is
  schema-constrained and delimited; values are verified against source quotes.
- **Storage:** Supabase bucket is private; the backend uses the service role key
  and issues signed URLs / streams files. The service role key is never sent to
  the frontend.
- **Audit trail:** uploads, logins, corrections, reviews, approvals,
  reprocesses, finding updates, reconciliation updates, and job retries.
- **Data integrity:** immutable extraction revisions, optimistic concurrency,
  UTC timestamps.

---

## Known limitations

- **No Alembic migrations.** Schema is created with
  `Base.metadata.create_all` plus explicit Postgres indexes. Add migrations
  before evolving production schemas.
- **Single worker on SQLite.** SQLite deployments cannot scale workers; Postgres
  supports `FOR UPDATE SKIP LOCKED` scale-out.
- **Reserved rule IDs.** `V008`, `V012`, and `V017` are catalog placeholders, not
  emitted findings in the current build.
- **Hash embeddings on Render.** Semantic search is lexical unless you switch to
  FastEmbed on a larger plan.
- **No FX conversion.** Analytics reports one currency at a time.
- **Credit notes are not auto-handled.** Negative amounts produce `V003`.
- **Evaluation is small and synthetic.** Real scanned/image/multi-sheet
  evaluation is future work.
- **Search metrics are defined but not executed.** `eval/queries.json` is ready
  for Recall@10/MRR runs.
- **PDF↔spreadsheet matching is invoice-number based.** There is no fuzzy
  fallback for unmatched rows.
- **No user-management UI.** Users/roles are managed directly in the database.
- **Free-tier cold starts.** The public demo can take ~30–60 seconds to wake.

---

## Documentation

- `docs/architecture.md` — system design, pipeline, divergences from `PLAN.md`
- `docs/database.md` — SQLAlchemy schema, indexes, data rules
- `docs/supabase-setup.md` — production Postgres + pgvector + Storage
- `docs/evaluation.md` — evaluation methodology and measured results
- `docs/ai-disclosure.md` — AI-assisted development disclosure
- `docs/walkthrough-script.md` — 6–8 minute demo script

---

## AI assistance

Code was drafted with AI assistance and reviewed/tested by hand. See
`docs/ai-disclosure.md` for the full disclosure.
