# AI-assisted development disclosure

This project (DocIntel) was developed with AI assistance throughout a 5-day
assignment. This disclosure documents how AI was used, consistent with the
requirement in `PLAN.md` (§5.3, deliverable 9).

## Tools used

- **OpenCode** (this agent) — scaffolding, code generation, debugging,
  test authoring, documentation, and build verification.
- **Nemotron model** — the underlying chat model powering OpenCode.

## What AI helped with

- Backend scaffold: FastAPI app, SQLAlchemy models, Pydantic schemas, auth
  (JWT + cookie), upload validation, storage adapters (local/Supabase), OCR
  wiring (RapidOCR/Tesseract), PDF/image/spreadsheet parsers, page grouping,
  deterministic extraction, validation rules (V001–V017), reconciliation,
  search (keyword + FastEmbed + vector fallback), DB-backed worker, REST API
  routers, CLI.
- Hardening fixes: closed file-handle leak in `validate_file`, storage path
  traversal prevention (`is_relative_to`), worker multi-worker shutdown loop,
  removed dead `mark_failure`, Postgres UTC date filtering, `/findings` router.
- Frontend: Next.js 15 + Tailwind design system, auth provider, app shell,
  login, dashboard, upload queue with per-file progress/polling, documents list
  with filters/pagination, search page, jobs page, document detail page,
  extraction editor (field editing, line items, approval), findings list,
  sheet viewer, preview component.
- Tests: 62-case pytest suite covering normalization, grouping, extraction,
  validation, duplicates, spreadsheet parsing, uploads, corrections, auth,
  search, findings, job retries, duplicates.
- Evaluation harness: `eval/generate_fixtures.py` and `eval/run_eval.py`
  producing measured baseline metrics (overall field F1 0.952, exact-doc rate
  0.75, line-item F1 1.0).
- Documentation: README, architecture, database schema, Supabase setup guide,
  this disclosure, evaluation report, walkthrough script.

## Review and testing statement

All AI-generated code was reviewed, adjusted, and tested by hand before being
considered complete:

- Backend tests pass (`uv run pytest tests/ -q` → 62 passed).
- Frontend typechecks and builds (`npm run typecheck`, `npm run build`).
- The full auth → upload → process → review → correct → search flow was
  exercised against a running backend + worker + frontend.
- The evaluation harness was executed end-to-end and produced real measured
  numbers in `eval/report.md`.

## Secrets and data

- No API keys, real invoices, or personal data are committed.
- `backend/.env.example` documents required variables without values.
- The Groq extraction path is **disabled by default** (`GROQ_API_KEY=""`);
  the deterministic fallback extractor handles everything offline.
- Evaluation fixtures are synthetic (generated with ReportLab) and labeled by
  construction.

## Prompts

- Production prompt: `prompts/extract_invoice.v1.md` (Groq structured JSON
  schema with evidence-quote verification and null-when-absent rules).
- The prompt version is stored with every extraction for reproducibility.
