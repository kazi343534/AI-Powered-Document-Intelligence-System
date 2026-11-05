# Evaluation — DocIntel

## Methodology

The evaluation harness lives in `eval/`:

- `generate_fixtures.py` — builds a reproducible synthetic labeled dataset of
  invoices (ReportLab PDFs) with a matching `ground_truth.jsonl`. Every field
  is known exactly by construction, so the run is deterministic and fully
  offline.
- `run_eval.py` — uploads each fixture through the real API, processes it
  synchronously, reads back the extraction, and compares each field to ground
  truth. Writes `results.json`, `results.csv`, and `report.md`.
- `queries.json` — 15 search evaluation queries with expected document IDs and
  negative cases, for Recall@10 / MRR measurement.

## Metrics computed

| Metric | Definition |
|--------|------------|
| Overall field F1 | Micro-averaged F1 over all required fields (invoice number, date, supplier, customer, currency, subtotal, tax, total) |
| Precision / recall | Per field, treating a predicted non-null value where GT is null as a false positive (hallucination), and a missed GT value as false negative |
| Exact-document rate | Share of documents where every required field matches GT exactly |
| Null / abstention accuracy | Share of ground-truth-null fields the system correctly predicted as null |
| Line-item F1 | Set F1 over (description, amount) pairs |

## Measured baseline (deterministic fallback, no Groq key)

Run: `cd eval && python generate_fixtures.py && python run_eval.py`

Result (`eval/report.md`, 4 synthetic invoices):

- Overall field F1: **0.9524**
- Overall precision: **0.9375**
- Overall recall: **0.9677**
- Exact-document rate: **0.75** (3/4)
- Null/abstention accuracy: **0.0** (1 abstention opportunity, 1 false positive — the deterministic extractor read "Tax 0.00" where the label marks tax absent)
- Line-item F1: **1.0** (all 4 docs)

Per-field:

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

## Limitations (stated per PLAN §13.3)

- This run used the deterministic fallback extractor. **Re-run with**
  `GROQ_API_KEY` **set in `backend/.env` to measure the Groq path.**
- Dataset is small and synthetic (4 invoices). Real-world scanned/degraded
  invoices, image invoices (JPG/PNG/TIFF), multi-sheet spreadsheets, and
  near-duplicate pairs are not yet included.
- Search metrics (Recall@10, MRR) are defined in `eval/queries.json` but not
  yet executed against a populated index.

## Reproducibility

State recorded with each run in `results.json`: commit context, model name,
prompt version (`extract_invoice.v1` / deterministic fallback), hardware,
database backend, dataset size, and generated-at timestamp.
