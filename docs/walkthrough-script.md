# DocIntel walkthrough script (6–8 minutes)

Narrated, end-to-end demo from a clean local setup. Times are approximate.

## 0. Prerequisites (before recording)

- `backend/` dependencies installed (`uv sync --extra dev`)
- `frontend/` dependencies installed (`npm install`)
- Dev DB initialized and demo user seeded (`uv run python -m cli init-db`)
- Backend running: `uv run uvicorn app.main:app --reload --port 8000`
- Worker running: `uv run python -m app.worker`
- Frontend running: `npm run dev` (http://localhost:3000)
- Demo credentials: `admin@docintel.local` / `admin12345`
- Sample file: `backend/data/samples/acme_invoice.pdf`

---

## 1. Problem + architecture — 60 s

- Show README diagram: upload → validate/dedupe → store → background worker →
  parse/OCR → page grouping → deterministic + Groq extraction → validation
  → index → review/correct/approve.
- Emphasize the core bet: **evidence-backed extraction**. Every non-null value
  carries a verbatim source quote verified against the page; missing values are
  `null`, never invented.

## 2. Upload — 60 s

- Log in at http://localhost:3000/login with demo credentials.
- Upload together: a digital PDF (`acme_invoice.pdf`), a scanned JPG/PNG, an
  XLSX ledger, and deliberately a corrupt `.txt` renamed to `.pdf`.
- Show per-file progress on the Upload page; show the corrupt file rejected
  with a clear error code while the batch continues.

## 3. Live processing — 60 s

- Switch to Dashboard / Jobs. Show the document moving queued → parsing →
  extraction → validation → indexing, with per-file progress and auto-refresh
  every 3 s.
- Mention the DB-backed job queue (`FOR UPDATE SKIP LOCKED`) and retries with
  exponential backoff.

## 4. Review invoice — 120 s

- Open the processed invoice → Review tab.
- Show side-by-side: page image/preview on the left, extracted fields on the
  right.
- Show confidence chips and evidence quotes; click a quote's page button to
  jump to the source page.
- Point out a missing field marked `null` with a reason — no invention.
- Show validation findings (e.g., V005 line-item vs subtotal mismatch) that
  block auto-approval.

## 5. Validation + correction — 60 s

- Correct the total value in the editor → **Save as new version**.
- Show a new immutable extraction revision is created and validation re-runs.
- Resolve/dismiss a finding; then **Approve** the invoice.
- Show status move to completed.

## 6. Search — 60 s

- Go to Search. Run keyword (`"ACME"`), then hybrid/semantic
  (`"office supplies"` or the invoice number).
- Show result snippets, confidence/score, and the ability to jump to the
  matching document/page.

## 7. Failure + retry — 30 s

- Show a failed job (e.g., from a corrupt upload or a manually failed job)
  with a clear error code.
- Click **Retry** → job re-queued → worker picks it up → success.

## 8. Results + engineering — 60 s

- Show `eval/report.md`: measured baseline numbers (field F1 0.952, exact-doc
  0.75, line-item F1 1.0).
- Mention tests: 62 backend tests pass offline; frontend typechecks and builds.
- Mention security: magic-byte + extension validation, size/page caps, zip-bomb
  guards, path-traversal prevention, JWT + RBAC, audit events.
- State limitations: Groq path not measured (no key), synthetic dataset only.

## Close

- "Nothing is auto-approved. Everything is versioned, audited, and reviewable."
- Point to README for setup and docs/ for architecture, Supabase setup, and AI
  disclosure.
