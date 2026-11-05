"""Reproducible synthetic invoice fixture generator + ground-truth labels.

Generates a small, deterministic labeled dataset (ReportLab) with a matching
ground-truth JSONL. All values are known exactly, which makes the evaluation
harness deterministic and runnable without a live LLM provider.

Usage:
    python -m eval.generate_fixtures        # write dataset/ + ground_truth.jsonl
    PYTHONPATH=backend python -m eval.generate_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Resolve the eval directory relative to this file so it works from any CWD.
EVAL_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVAL_DIR / "dataset"
LABELS_PATH = EVAL_DIR / "ground_truth.jsonl"

# Fixed seed-ish determinism: we build documents by hand so labels are exact.


def _money(value: float) -> str:
    return f"{value:.2f}"


def _draw_invoice(
    c: canvas.Canvas,
    *,
    invoice_number: str,
    invoice_date: str,
    supplier: str,
    customer: str,
    currency: str,
    subtotal: float,
    tax: float,
    total: float,
    line_items: list[tuple[str, int, float, float]],
    y: float = 720,
) -> None:
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, y, "INVOICE")
    c.setFont("Helvetica", 11)
    y -= 30
    c.drawString(72, y, f"Invoice No: {invoice_number}")
    y -= 18
    c.drawString(72, y, f"Invoice Date: {invoice_date}")
    y -= 18
    c.drawString(72, y, f"Supplier: {supplier}")
    y -= 18
    c.drawString(72, y, f"Customer: {customer}")
    y -= 24
    c.setFont("Helvetica-Bold", 11)
    c.drawString(72, y, "Description          Qty   Unit Price   Amount")
    c.setFont("Helvetica", 11)
    y -= 18
    for description, qty, unit_price, amount in line_items:
        c.drawString(72, y, f"{description:<20} {qty:<5} {unit_price:<11.2f} {amount:.2f}")
        y -= 18
    y -= 6
    c.drawString(72, y, f"Subtotal      {_money(subtotal)}")
    y -= 18
    c.drawString(72, y, f"Tax           {_money(tax)}")
    y -= 18
    c.drawString(72, y, f"Total         {_money(total)}")
    y -= 18
    c.drawString(72, y, f"{currency}")


DOCUMENTS: list[dict] = [
    {
        "id": "inv-clean-digital-01",
        "filename": "clean_digital_invoice_01.pdf",
        "invoice_number": "INV-2024-0101",
        "invoice_date": "2024-03-15",
        "supplier": "ACME COMPONENTS LTD",
        "customer": "TEST CUSTOMER ONE",
        "currency": "GBP",
        "subtotal": 125.00,
        "tax": 25.00,
        "total": 150.00,
        "line_items": [
            ("Hex bolt M8", 10, 12.50, 125.00),
        ],
        "notes": "Clean single-page digital invoice; all fields present.",
    },
    {
        "id": "inv-clean-digital-02",
        "filename": "clean_digital_invoice_02.pdf",
        "invoice_number": "INV-2024-0207",
        "invoice_date": "2024-01-22",
        "supplier": "GLOBAL DISTRIBUTORS INC",
        "customer": "NORTHWIND TRADERS",
        "currency": "USD",
        "subtotal": 840.00,
        "tax": 84.00,
        "total": 924.00,
        "line_items": [
            ("Steel bracket A2", 2, 400.00, 800.00),
            ("USB-C cable", 4, 10.00, 40.00),
        ],
        "notes": "Multi-line invoice, USD currency.",
    },
    {
        "id": "inv-missing-tax",
        "filename": "missing_tax_invoice.pdf",
        "invoice_number": "INV-2024-0303",
        "invoice_date": "2024-05-02",
        "supplier": "PLAIN SUPPLIES",
        "customer": "WALK-IN CLIENT",
        "currency": "EUR",
        "subtotal": 200.00,
        "tax": 0.00,
        "total": 200.00,
        "line_items": [
            ("Notebook A5", 20, 10.00, 200.00),
        ],
        "notes": "Tax is genuinely zero/absent; system should not invent a tax value.",
    },
    {
        "id": "inv-multi-line",
        "filename": "multi_line_invoice.pdf",
        "invoice_number": "INV-2024-0410",
        "invoice_date": "2024-06-10",
        "supplier": "INDUSTRIAL FASTENERS GMBH",
        "customer": "EUROPEAN MFG",
        "currency": "EUR",
        "subtotal": 315.00,
        "tax": 63.00,
        "total": 378.00,
        "line_items": [
            ("Washer M6", 50, 1.50, 75.00),
            ("Nut M6", 100, 0.80, 80.00),
            ("Screw M8", 40, 4.00, 160.00),
        ],
        "notes": "Three line items that reconcile exactly with subtotal.",
    },
]


def generate() -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for doc in DOCUMENTS:
        path = DATASET_DIR / doc["filename"]
        c = canvas.Canvas(str(path), pagesize=letter)
        _draw_invoice(
            c,
            invoice_number=doc["invoice_number"],
            invoice_date=doc["invoice_date"],
            supplier=doc["supplier"],
            customer=doc["customer"],
            currency=doc["currency"],
            subtotal=doc["subtotal"],
            tax=doc["tax"],
            total=doc["total"],
            line_items=doc["line_items"],
        )
        c.save()

        total_amounts = sum(i[3] for i in doc["line_items"])
        rows.append(
            {
                "id": doc["id"],
                "filename": doc["filename"],
                "document_type": "invoice",
                "invoice_number": doc["invoice_number"],
                "invoice_date": doc["invoice_date"],
                "supplier_name": doc["supplier"],
                "customer_name": doc["customer"],
                "currency": doc["currency"],
                "subtotal": _money(doc["subtotal"]),
                "tax": _money(doc["tax"]) if doc["tax"] else None,
                "total": _money(doc["total"]),
                "line_items": [
                    {
                        "description": desc,
                        "quantity": str(qty),
                        "unit_price": _money(up),
                        "amount": _money(amt),
                    }
                    for desc, qty, up, amt in doc["line_items"]
                ],
                "line_item_amount_sum": _money(total_amounts),
                "notes": doc["notes"],
            }
        )

    with open(LABELS_PATH, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    print(f"Wrote {len(DOCUMENTS)} PDFs to {DATASET_DIR}")
    print(f"Wrote {len(rows)} ground-truth labels to {LABELS_PATH}")


if __name__ == "__main__":
    generate()
