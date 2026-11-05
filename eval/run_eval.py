"""Deterministic evaluation harness for DocIntel extraction.

Runs the extraction pipeline over the synthetic labeled dataset produced by
``generate_fixtures.py`` and compares each extracted field to ground truth.

Designed to run without a live LLM provider (deterministic fallback only) so
CI and local demos stay fully offline. When a Groq key is configured the same
harness exercises the AI path; swap in the key and re-run to compare.

Usage:
    python -m eval.run_eval            # writes eval/results.json + eval/report.md
    PYTHONPATH=backend python -m eval.run_eval
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Make the backend package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Force test settings before importing the app.
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval/data/eval_docintel.db")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "eval-secret-do-not-use-in-production")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db, seed_db  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline import process_document  # noqa: E402

get_settings.cache_clear()
SETTINGS = get_settings()

EVAL_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVAL_DIR / "dataset"
LABELS_PATH = EVAL_DIR / "ground_truth.jsonl"
RESULTS_JSON = EVAL_DIR / "results.json"
RESULTS_CSV = EVAL_DIR / "results.csv"
REPORT_PATH = EVAL_DIR / "report.md"

FIELD_KEYS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "currency",
    "subtotal",
    "tax",
    "total",
]

MONEY_KEYS = {"subtotal", "tax", "total"}


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _field_value(extraction_data: dict, key: str) -> str | None:
    field = extraction_data.get(key) or {}
    return field.get("value")


def _line_items(extraction_data: dict) -> list[dict]:
    return extraction_data.get("line_items") or []


def _load_labels() -> list[dict]:
    labels = []
    with open(LABELS_PATH) as handle:
        for line in handle:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    return labels


def _setup_db() -> Any:
    """Initialize a fresh eval DB and return a session bound to it."""
    eval_db_path = SETTINGS.database_url.replace("sqlite:///", "", 1)
    Path(eval_db_path).parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(eval_db_path + suffix).unlink()
        except FileNotFoundError:
            pass
    init_db()
    seed_db()
    return SessionLocal()


def _process(doc_id: str, db: Any) -> None:
    process_document(doc_id, db=db)
    db.commit()


def run() -> dict:
    labels = _load_labels()
    if not labels:
        raise SystemExit("No ground-truth labels found; run generate_fixtures.py first")

    # Fresh DB per eval run so results are reproducible.
    db = _setup_db()

    # Import inside function so the TestClient picks up the fresh DB session.
    import app.database as database_module  # noqa: PLC0415

    def _override_get_db():
        yield db

    app.dependency_overrides[database_module.get_db] = _override_get_db
    client = TestClient(app)

    try:
        # Seed user must exist for auth.
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@docintel.local", "password": "admin12345"},
        )
        assert login_resp.status_code == 200, login_resp.text
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        per_doc = []
        for label in labels:
            pdf_path = DATASET_DIR / label["filename"]
            start = time.time()

            with open(pdf_path, "rb") as handle:
                upload_resp = client.post(
                    "/api/v1/documents",
                    files={"files": (label["filename"], handle, "application/pdf")},
                    headers=headers,
                )
            assert upload_resp.status_code == 202, upload_resp.text
            doc_id = upload_resp.json()["documents"][0]["id"]

            # Synchronous processing (deterministic, offline-safe).
            _process(doc_id, db)

            detail = client.get(f"/api/v1/documents/{doc_id}", headers=headers).json()
            elapsed = time.time() - start

            invoice = detail["invoices"][0] if detail["invoices"] else {}
            extraction = invoice.get("current_extraction") or {}
            ext_data = extraction.get("data") or {}
            findings = detail.get("findings", [])

            per_doc.append(
                {
                    "doc_id": doc_id,
                    "filename": label["filename"],
                    "label_id": label["id"],
                    "document_status": detail.get("status"),
                    "invoice_status": invoice.get("status"),
                    "elapsed_seconds": round(elapsed, 3),
                    "extraction_source": extraction.get("source"),
                    "extraction_version": extraction.get("version"),
                    "extracted": {
                        key: _field_value(ext_data, key) for key in FIELD_KEYS
                    },
                    "line_items": _line_items(ext_data),
                    "finding_count": len(findings),
                    "blocking_findings": [
                        f for f in findings if f.get("severity") in ("error", "warning")
                    ],
                    "ground_truth": label,
                }
            )
    finally:
        app.dependency_overrides.pop(database_module.get_db, None)
        db.close()

    metrics = _compute_metrics(per_doc)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings": {
            "database": "sqlite" if SETTINGS.is_sqlite else "postgres",
            "ai_enabled": SETTINGS.ai_enabled,
            "ocr_engine": SETTINGS.ocr_engine,
            "embedding_provider": SETTINGS.embedding_provider,
            "embedding_model": SETTINGS.embedding_model,
        },
        "document_count": len(per_doc),
        "metrics": metrics,
        "documents": per_doc,
    }

    RESULTS_JSON.write_text(json.dumps(report, indent=2))
    _write_csv(per_doc)
    _write_report(report)

    print(f"Evaluation complete: {len(per_doc)} documents")
    print(f"  Overall field F1: {metrics['overall_field_f1']:.3f}")
    print(f"  Exact-doc rate:   {metrics['exact_doc_rate']:.3f}")
    print(f"  Null accuracy:    {metrics['null_accuracy']:.3f}")
    print(f"  Results -> {RESULTS_JSON}")
    print(f"  Report   -> {REPORT_PATH}")
    return report


def _compute_metrics(per_doc: list[dict]) -> dict:
    field_tp = {key: 0 for key in FIELD_KEYS}
    field_fp = {key: 0 for key in FIELD_KEYS}
    field_fn = {key: 0 for key in FIELD_KEYS}

    null_tn = 0  # ground truth null AND predicted null
    null_total_gt = 0  # ground truth null (abstention opportunities)
    null_correct = 0  # ground truth null AND predicted null

    exact_docs = 0
    total_line_item_f1 = 0.0
    docs_with_items = 0

    for doc in per_doc:
        gt = doc["ground_truth"]
        pred = doc["extracted"]

        doc_exact = True
        for key in FIELD_KEYS:
            gt_val = gt.get(key)
            pred_val = pred.get(key)
            match = _values_equal(gt_val, pred_val)
            if match:
                field_tp[key] += 1
            else:
                if gt_val is None:
                    field_fp[key] += 1  # hallucinated a value
                elif pred_val is None:
                    field_fn[key] += 1  # missed a value
                else:
                    field_fp[key] += 1
                    field_fn[key] += 1
                doc_exact = False

            # Abstention / null accuracy.
            if gt_val is None:
                null_total_gt += 1
                if pred_val is None:
                    null_correct += 1
                    null_tn += 1

        if doc_exact:
            exact_docs += 1

        # Line-item F1 (description match, order-insensitive).
        gt_items = gt.get("line_items") or []
        pred_items = doc["line_items"] or []
        if gt_items or pred_items:
            docs_with_items += 1
            total_line_item_f1 += _set_f1(
                {(i["description"], i["amount"]) for i in gt_items},
                {(i["description"], i["amount"]) for i in pred_items},
            )

    field_metrics = {}
    for key in FIELD_KEYS:
        tp, fp, fn = field_tp[key], field_fp[key], field_fn[key]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        field_metrics[key] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    overall_tp = sum(field_tp.values())
    overall_fp = sum(field_fp.values())
    overall_fn = sum(field_fn.values())
    overall_precision = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) else 0.0
    overall_recall = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) else 0.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall)
        else 0.0
    )

    return {
        "overall_field_f1": round(overall_f1, 4),
        "overall_precision": round(overall_precision, 4),
        "overall_recall": round(overall_recall, 4),
        "exact_doc_rate": round(exact_docs / len(per_doc), 4) if per_doc else 0.0,
        "exact_docs": exact_docs,
        "null_accuracy": round(null_correct / null_total_gt, 4) if null_total_gt else 1.0,
        "null_total_gt": null_total_gt,
        "null_correct": null_correct,
        "line_item_f1": round(total_line_item_f1 / docs_with_items, 4) if docs_with_items else None,
        "docs_with_items": docs_with_items,
        "per_field": field_metrics,
    }


def _values_equal(gt: Any, pred: Any) -> bool:
    if gt is None and pred is None:
        return True
    if gt is None or pred is None:
        return False
    gt_s = str(gt).strip()
    pred_s = str(pred).strip()
    if gt_s == pred_s:
        return True
    try:
        return Decimal(gt_s) == Decimal(pred_s)
    except (InvalidOperation, ValueError):
        return False


def _set_f1(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    precision = inter / len(b)
    recall = inter / len(a)
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def _write_csv(per_doc: list[dict]) -> None:
    with open(RESULTS_CSV, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "filename",
                "label_id",
                "document_status",
                "invoice_status",
                "source",
                "version",
                "elapsed_s",
                "finding_count",
                "blocking_findings",
            ]
            + [f"pred_{k}" for k in FIELD_KEYS]
        )
        for doc in per_doc:
            writer.writerow(
                [
                    doc["filename"],
                    doc["label_id"],
                    doc["document_status"],
                    doc["invoice_status"],
                    doc["extraction_source"],
                    doc["extraction_version"],
                    doc["elapsed_seconds"],
                    doc["finding_count"],
                    ";".join(f["rule_code"] for f in doc["blocking_findings"]),
                ]
                + [doc["extracted"].get(k) for k in FIELD_KEYS]
            )


def _write_report(report: dict) -> None:
    m = report["metrics"]
    lines = [
        "# DocIntel Extraction Evaluation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Database: {report['settings']['database']}",
        f"AI enabled: {report['settings']['ai_enabled']}",
        f"OCR engine: {report['settings']['ocr_engine']}",
        f"Embedding provider: {report['settings']['embedding_provider']}",
        f"Embedding model: {report['settings']['embedding_model']}",
        f"Documents evaluated: {report['document_count']}",
        "",
        "## Headline metrics",
        "",
        f"- Overall field F1: {m['overall_field_f1']}",
        f"- Overall precision: {m['overall_precision']}",
        f"- Overall recall: {m['overall_recall']}",
        f"- Exact-document rate: {m['exact_doc_rate']} "
        f"({m['exact_docs']}/{report['document_count']})",
        f"- Null/abstention accuracy: {m['null_accuracy']} "
        f"({m['null_correct']}/{m['null_total_gt']})",
        f"- Line-item F1: {m['line_item_f1']} (on {m['docs_with_items']} docs)",
        "",
        "## Per-field metrics",
        "",
        "| Field | Precision | Recall | F1 | TP | FP | FN |",
        "|-------|-----------|--------|----|----|----|----|",
    ]
    for key, stats in m["per_field"].items():
        lines.append(
            f"| {key} | {stats['precision']} | {stats['recall']} | {stats['f1']} | "
            f"{stats['tp']} | {stats['fp']} | {stats['fn']} |"
        )
    lines += [
        "",
        "## Per-document results",
        "",
        "| Filename | Status | Source | Elapsed (s) | Findings | Blocking |",
        "|----------|--------|--------|-------------|----------|----------|",
    ]
    for doc in report["documents"]:
        lines.append(
            f"| {doc['filename']} | {doc['document_status']} | {doc['extraction_source']} | "
            f"{doc['elapsed_seconds']} | {doc['finding_count']} | "
            f"{len(doc['blocking_findings'])} |"
        )
    lines += [
        "",
        "## Limitations",
        "",
        "- This run used the deterministic fallback extractor (no Groq API key configured).",
        "- Re-run with `GROQ_API_KEY` set to measure the AI extraction path.",
        "- Dataset is synthetic; real-world scanned/degraded invoices are not yet included.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    run()
