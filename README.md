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
│   ├── fixtures/           # regression workbook (committed)
│   ├── data/               # local SQLite DB + uploads (dev only, gitignored)
│   ├── pyproject.toml
│   └── requirements.txt    # pinned production deps (Render)
├── frontend/               # Next.js 15 + Tailwind app
│   ├── app/                # App Router pages (login, upload, documents, analytics, search, jobs)
│   ├── components/         # shared UI, review editor, findings, sheets
│   └── lib/                # API client, types, format helpers
├── eval/                   # evaluation harness
│   ├── generate_fixtures.py    # synthetic labeled PDFs + ground truth
│   ├── run_eval.py             # writes results.json / report.md
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

## Spreadsheet fixes (6 bugs resolved)

The spreadsheet ingestion pipeline had six bugs across the parser, field
normalizer, validation engine, API, and sheet UI. All are fixed and covered by
regression tests using `backend/fixtures/invoice_test_suite_cross_verification.xlsx`.

### Bug 1 — Multi-sheet classification
**Before:** Every row in every worksheet was treated as a standalone top-level
invoice. The 20 line-item rows in `Line_Items_Detail` became 20 false invoices
with `—` for Date, Supplier, Customer, Subtotal, Tax, Total.

**After:** Each sheet is classified by header inspection:
- `INVOICE_LEDGER` → top-level invoice/PO records
- `LINE_ITEMS` → parsed as `line_number`, `sku`, `description`, `quantity`,
  `unit_price`, `line_total` and linked to the matching parent invoice by
  `invoice_number`
- `RECONCILIATION` (variance/comparison columns) → skipped for top-level
  extraction, never duplicated

Result on the cross-verification workbook: **14 invoice/PO records** (8 from
`Master_PO_Ledger` + 6 from `Dirty_Data_Stress_Test`) and **20 child line
items**, not 34 top-level rows.

### Bug 2 — Supplier / Customer dropped in normalized view
**Before:** `SUPPLIER` and `CUSTOMER` were `null` in the Normalized view
despite being present in Raw.

**After:** Header synonym map expanded (case-insensitive, trimmed, whitespace/
underscore collapsed) to include `supplier name`, `supplier`, `vendor`, `vendor
name`, `merchant`, `supplier_name`, `seller` and `customer name`, `customer`,
`client`, `buyer`, `bill to`, `customer_name` plus all required invoice
number/date, subtotal, tax, total, and currency aliases.

### Bug 3 — Summary / footer `TOTAL` rows not filtered
**Before:** `Master_PO_Ledger` row 10 (`TOTAL`, with `=SUM(...)` formulas) was
extracted as an invoice record.

**After:** Rows where the first non-empty cell or identifier column matches
`{TOTAL, SUBTOTAL, GRAND TOTAL, SUM}` (case-insensitive) are skipped. Rows with
only summary totals and no identifier/supplier/customer are also skipped.
`openpyxl` loads with `data_only=True` so formula cells evaluate to numbers
rather than raw `=SUM(G2:G9)` strings.

### Bug 4 — Silent currency coercion (`XYZ` → USD)
**Before:** Unknown currency `XYZ` was silently replaced with `USD` and formatted
as `US$4,000.00` with no warning.

**After:** `normalize_currency_cell()` validates against the active ISO 4217 code
set (`ISO_4217_CODES`, separate from the PDF text-scanning subset to avoid false
matches such as `ALL`, `TRY`, `TOP`). Recognized codes/symbols are canonicalized;
an explicit unknown value like `XYZ` is preserved and reported with an
`"invalid currency (XYZ)"` warning instead of being coerced to USD.

### Bug 5 — Missing validation warnings on dirty rows
**Before:** Only row 3 showed `"missing invoice number"`; rows with bad dates,
non-numeric subtotals, math mismatches, and duplicates had no warnings.

**After:** Row-level validation populates `warnings` for:
- **Unparseable date** → `"invalid date format"`
- **Non-numeric subtotal** → `"invalid or missing subtotal"`
- **Math mismatch** → `"math mismatch: subtotal + tax (4500.00) != total (4100.00)"`
- **Duplicate invoice number** → `"duplicate invoice number"` (flagged on both
  duplicate rows)

Warnings are written back to `SheetRow.warnings` and exposed through `/sheet-rows`
and the Normalized sheet UI.

### Bug 6 — Raw vs Normalized row count consistency
**Before:** UI showed 34 extracted rows, mixing invoices, line items, and
comparison rows.

**After:** `SheetView` separates **Invoice / PO records** (14) from **Child line
items** (20) with dedicated tabs and counts. `/sheet-rows?row_type=invoice`
(default), `row_type=line_item`, or `row_type=all`. Response includes
`invoice_total`, `line_item_total`, `row_type`, `parent_invoice_number`, and
`line_item_count`. Line items are merged into the parent invoice row's
`normalized.line_items` and exposed via `line_item_count`.

**Expected workbook result:** 14 invoice/PO records + 20 child line items
(parent attachment: `INV-2026-00101` → 6, `INV-2026-00102` → 4,
`INV-2026-00103` → 4, `INV-2026-00107` → 3; 3 `"MISSING"` items unlinked).

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

### Evaluation metrics computed

| Metric | Definition |
|--------|------------|
| Overall field F1 | Micro-averaged F1 over all required fields (invoice number, date, supplier, customer, currency, subtotal, tax, total) |
| Precision / recall | Per field; predicted non-null where GT is null = false positive (hallucination); missed GT value = false negative |
| Exact-document rate | Share of documents where every required field matches GT exactly |
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
- Line-item F1: **1.0** (all 4 docs)

### Per-field evaluation matrix

| Field | Precision | Recall | F1 |
|-------|-----------|--------|----|
| invoice_number | 1.0 | 1.0 | 1.0 |
| invoice_date | 1.0 | 1.0 | 1.0 |
| supplier_name | 1.0 | 1.0 | 1.0 |
| customer_name | 0.75 | 0.75 | 0.75 |
| currency | 1.0 | 1.0 | 1.0 |
| subtotal | 1.0 | 1.0 | 1.0 |
| tax | 0.75 | 1.0 | 0.8571 |
| total | 1.0 | 1.0 | 1.0 |

Re-run with `GROQ_API_KEY` set in `backend/.env` to measure the Groq path.

### Test suite matrix

The backend test suite contains **85 deterministic, offline tests** across
9 test modules:

| Test module | Test cases | Coverage |
|-------------|------------|----------|
| `test_parsers.py` | `test_csv_parsing`, `test_xlsx_parsing`, `test_unsupported_type_raises`, `test_cross_verification_sheet_classification_and_counts`, `test_cross_verification_header_aliases_and_unknown_currency`, `test_cross_verification_dirty_row_warnings`, `test_cross_verification_line_items_link_to_parent_invoices` | Sheet classification (INVOICE_LEDGER / LINE_ITEMS / RECONCILIATION), header aliases, footer/summary skipping, unknown currency preservation, row warnings (invalid date / missing subtotal / math mismatch / duplicate invoice), line-item linking (17 linked / 3 unmatched), counts (14 invoices + 20 line items) |
| `test_utils.py` | `TestParseDecimal` (8), `TestNormalizeInvoiceNumber` (2), `TestNormalizeSupplier` (2), `TestNormalizeCurrency` (3), `TestParseDateFlexible` (4), `TestConstants` (2) | Decimal parsing (plain, integer, negative parentheses, European/thousand separators, currency symbols, empty, garbage), invoice number normalization, supplier normalization, currency code/symbol/unknown handling, date parsing (ISO, long form, garbage) |
| `test_validation.py` | `test_v001_required_missing`, `test_v002_future_date`, `test_v004_arithmetic_mismatch`, `test_v004_arithmetic_ok`, `test_v005_line_item_sum_mismatch`, `test_v009_no_line_items_with_total`, `test_v015_low_confidence` | Validation rules V001–V017, required fields, future dates, arithmetic mismatch/OK, line-item sum mismatch, missing totals, low confidence |
| `test_api.py` | `TestAuth` (4), `TestUpload` (4), `TestDocumentsListAndDetail` (4), `TestFindings` (2), `TestSearch` (2), `TestReprocessAndJobs` (2), `TestMeta` (1), `TestCorrections` (1), `TestWorkerRetry` (1), `TestApprove` (2), `TestReconciliationDismissal` (3), `TestSpreadsheetApproval` (3), `TestCrossVerificationWorkbook` (2) | Auth, upload/reject/duplicate, document list/detail/text, findings CRUD, search, reprocess/jobs, meta, corrections, worker retry, approve blocks/completes, spreadsheet approval (no invoices / blocking findings / mismatch dismissed), cross-verification upload → process_jobs → /sheet-rows (invoice_total=14, line_item_total=20, row_type filtering, parent links, warnings) |
| `test_analytics.py` | `TestSalesAnalytics` (5) | Monthly/yearly totals + currency filter, default currency + duplicate exclusion, duplicate identity counted once, missing date/total reporting, authentication |
| `test_grouping.py` | 9 tests | Single page → one group, continuation page joins, new invoice number → new group, no number → single group, confidence bounds, record headings split invoices within/across pages, inline invoice numbers, empty input |
| `test_extraction.py` | 7 tests | Deterministic extraction of core fields, currency symbol, line items, never invents missing, AI flagged when disabled, evidence quote populated, multiline supplier, image-style invoice auto-approve |

Run all tests:

```bash
cd backend
uv run pytest tests/ -q   # 85 tests, fully offline (no live LLM)
```

### Regression workbook (committed fixture)

`backend/fixtures/invoice_test_suite_cross_verification.xlsx` — the exact 4-sheet
workbook used for regression testing:

| Sheet | Classification | Rows (invoice) | Line items | Purpose |
|-------|---------------|----------------|------------|---------|
| `Master_PO_Ledger` | `INVOICE_LEDGER` | 8 | — | Clean baseline + multi-currency + math error + duplicate |
| `PDF_vs_Excel_Comparison` | `RECONCILIATION` | 0 | — | Skipped for top-level extraction |
| `Line_Items_Detail` | `LINE_ITEMS` | 0 | 20 | Linked to parent invoices by invoice_number |
| `Dirty_Data_Stress_Test` | `INVOICE_LEDGER` | 6 | — | Missing invoice #, invalid date, non-numeric subtotal, unknown currency XYZ, math mismatch, duplicate |

Dirty-row expected warnings:

| Row | Field issue | Expected warning |
|-----|-------------|------------------|
| ROW-003 (INV-2026-00203) | `INVALID_DATE_STR` | `"invalid date format"` |
| ROW-004 (INV-2026-00204) | Subtotal `"N/A"` | `"invalid or missing subtotal"` |
| ROW-006 (INV-2026-00206) | Currency `XYZ`; subtotal+tax ≠ total | `"invalid currency (XYZ)"`, `"math mismatch: subtotal + tax (4500.00) != total (4100.00)"` |
| ROW-001 / ROW-007 (INV-2026-00201) | Duplicate invoice number | `"duplicate invoice number"` (both rows) |

## Background processing

Jobs live in a `processing_jobs` table. A separate `app.worker` process claims
jobs with `FOR UPDATE SKIP LOCKED` (Postgres) or a polling claim (SQLite),
runs them with retries and exponential backoff, and recovers stale jobs after
`job_stale_seconds` (default 30 min). Workers scale horizontally in Postgres.

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
4. **Build command** (set in the Render dashboard for `docintel-api`):
   `pip install --upgrade pip && pip install -r backend/requirements.txt`
   (also reflected in `render.yaml`).

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
