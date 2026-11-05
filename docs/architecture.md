# Architecture — DocIntel

This document describes the system **as implemented**, which is a pragmatic
subset of the vision in `PLAN.md` (Celery/Redis/MinIO were swapped for a
database-backed job queue and local/Supabase Storage to keep the 5-day scope
shippable).

## High-level flow

```
Browser (Next.js) ──REST──> FastAPI ──SQLAlchemy──> Postgres (dev: SQLite)
                               │                    └─ pgvector + FTS (prod)
                               │
                               └─ Storage: local FS (dev) / Supabase Storage (prod)
                               └─ Worker: app.worker (claims jobs from processing_jobs)
                               └─ Groq LLM (optional; deterministic fallback otherwise)
```

## Components

### API (`backend/app/main.py`)
FastAPI application. Registers routers:
- `auth` — login/logout/me, JWT (HttpOnly cookie or Bearer)
- `documents` — upload, list, detail, text, sheet rows, download, reprocess
- `invoices` — detail, extraction revisions, corrections, review (approve/reopen)
- `findings` — list and resolve/dismiss validation findings
- `search_api` — keyword / semantic / hybrid search
- `system` — health, meta, dashboard stats, jobs, reconciliations

### Background worker (`backend/app/worker.py`)
A `Worker` process claims jobs from `processing_jobs`:
- **Postgres:** `UPDATE ... WHERE id = (SELECT id ... FOR UPDATE SKIP LOCKED)`
- **SQLite:** polling claim of the earliest due job
- Retries with exponential backoff (`15s, 30s, 60s ...`, capped 300s)
- Stale jobs (heartbeat older than `job_stale_seconds`, default 30 min) are
  requeued with `WORKER_LOST`
- Graceful shutdown: stop flag polled between jobs

Run with `uv run python -m app.worker`.

### Pipeline (`backend/app/pipeline.py`)
`process_document` runs the full ETL for one document:
1. `downloading` — materialize original from storage to a temp file
2. `parsing` — PDF text layer (PyMuPDF), OCR fallback (RapidOCR/Tesseract),
   spreadsheet parsing (openpyxl/xlrd/csv)
3. Page grouping into logical invoices (`backend/app/parsers/grouping.py`)
4. `extracting` — deterministic regex extractor + Groq (when `GROQ_API_KEY` is
   set); evidence quotes verified against page text; null-when-absent
5. `validating` — rules V001–V017, duplicates, PDF↔Excel reconciliation
6. `indexing` — page chunks + invoice summary chunk stored for search
7. `completed` / `needs_review`

### Extraction (`backend/app/extraction/`)
- `deterministic.py` — conservative regex/layout parser, never invents values
- `groq.py` — Groq client with structured JSON output and evidence verification
- `service.py` — merges AI + deterministic, verifies every non-null value has a
  source quote on the cited page; unsupported fields are flagged and
  confidence reduced

### Search (`backend/app/search.py`, `backend/app/embeddings.py`)
- Keyword: PostgreSQL full-text (`to_tsvector` GIN index on Postgres) /
  `ILIKE` fallback on SQLite
- Semantic: FastEmbed `BAAI/bge-small-en-v1.5` (384 dims), deterministic hash
  embedder fallback; pgvector HNSW index on Postgres
- Hybrid: reciprocal rank fusion of keyword + semantic, then filters

### Storage (`backend/app/storage.py`)
`Storage` interface with `LocalStorage` (dev) and `SupabaseStorage` (prod).
Path-traversal prevention via `Path.is_relative_to(root)`.

## Data flow for one upload

1. `POST /documents` — validate magic bytes + size, compute SHA-256, dedupe
   against existing documents, store original, create `Document` + `ProcessingJob`
   (`status=queued`), return `202`
2. Worker claims job → `process_document` → populates `DocumentPage`,
   `Invoice`, `Extraction`, `LineItem`, `Finding`, `Reconciliation`, `Chunk`
3. Document reaches `completed` or `needs_review`; frontend polls every 3s

## Divergences from PLAN.md

| Area | PLAN.md | Implemented |
|------|---------|-------------|
| Job queue | Celery + Redis | DB-backed `processing_jobs` + `app.worker` |
| Object storage | MinIO / S3 | Local FS (dev) + Supabase Storage (prod) |
| Database | Postgres 16 + pgvector | SQLite (dev) + Postgres + pgvector (prod) |
| Embeddings | pgvector 1536 dims | FastEmbed 384 dims / hash fallback |
| Search | websearch_to_tsquery + pgvector | Same where supported; SQLite ILIKE fallback |
| Frontend state | TanStack Query | React hooks + polling |
| Migrations | Alembic | `Base.metadata.create_all` (dev-friendly) |

## Security

- Upload allowlist by extension **and magic bytes**; 200 MB/file, 20 files/request,
  1,500 PDF pages, XLSX zip-bomb ratio guard
- Filenames sanitized; storage keys resolved under `root` with
  `is_relative_to` (no path traversal)
- Extracted text treated as untrusted; Groq prompt is schema-constrained and
  delimited against prompt injection
- JWT auth; roles `admin` / `reviewer` / `viewer`; mutations require admin or
  reviewer
- Audit events written for upload, correction, review, reprocess, finding update
