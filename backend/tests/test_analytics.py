"""Tests for the sales analytics aggregation endpoint."""

from __future__ import annotations

import secrets

from app.models import Document, Extraction, Finding, Invoice
from app.utils import normalize_invoice_number, normalize_supplier


def _field(value: str | None) -> dict:
    return {"value": value, "confidence": 0.9, "evidence": None, "reason": None}


def _add_invoice(
    db,
    *,
    date_value: str | None,
    total: str | None,
    currency: str,
    supplier: str,
    invoice_number: str | None = None,
    approved: bool = True,
) -> Invoice:
    number = invoice_number or f"INV-{secrets.token_hex(3)}"
    document = Document(
        original_filename=f"{supplier}.pdf",
        storage_key=f"documents/{secrets.token_hex(4)}.pdf",
        mime_type="application/pdf",
        kind="pdf",
        sha256=secrets.token_hex(32),
        status="completed" if approved else "needs_review",
        stage="completed",
    )
    db.add(document)
    db.flush()

    invoice = Invoice(
        document_id=document.id,
        status="completed" if approved else "needs_review",
        invoice_number_norm=normalize_invoice_number(number),
        supplier_norm=normalize_supplier(supplier),
    )
    db.add(invoice)
    db.flush()

    extraction = Extraction(
        invoice_id=invoice.id,
        version=1,
        data={
            "invoice_number": _field(number),
            "invoice_date": _field(date_value),
            "supplier_name": _field(supplier),
            "currency": _field(currency),
            "total": _field(total),
        },
        confidence={"overall": 0.9},
        review_status="approved" if approved else "pending",
    )
    db.add(extraction)
    db.flush()
    invoice.current_extraction_id = extraction.id
    db.flush()
    return invoice


class TestSalesAnalytics:
    def test_monthly_yearly_totals_and_currency_filter(self, client, auth_headers, db):
        _add_invoice(
            db, date_value="2025-12-15", total="100.00", currency="USD", supplier="ACME"
        )
        _add_invoice(
            db, date_value="2026-01-10", total="200.00", currency="USD", supplier="Beta"
        )
        _add_invoice(
            db, date_value="2026-01-20", total="300.00", currency="EUR", supplier="Gamma"
        )
        _add_invoice(
            db,
            date_value="2026-02-05",
            total="50.00",
            currency="USD",
            supplier="ACME",
            approved=False,
        )

        response = client.get(
            "/api/v1/analytics/sales?currency=USD&months=6&years=3",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["currency"] == "USD"
        summary = body["summary"]
        assert summary["invoice_count"] == 3
        assert summary["total"] == 350.0
        assert summary["average_invoice"] == 116.67
        assert summary["supplier_count"] == 2
        assert summary["approved_count"] == 2
        assert summary["pending_count"] == 1
        assert summary["dated_count"] == 3
        assert summary["undated_count"] == 0
        assert summary["missing_total_count"] == 0
        assert summary["excluded_duplicates"] == 0

        assert [point["period"] for point in body["monthly"]] == [
            "2025-09",
            "2025-10",
            "2025-11",
            "2025-12",
            "2026-01",
            "2026-02",
        ]
        monthly = {point["period"]: point for point in body["monthly"]}
        assert monthly["2025-12"]["total"] == 100.0
        assert monthly["2026-01"]["total"] == 200.0
        assert monthly["2026-01"]["approved_total"] == 200.0
        assert monthly["2026-02"]["total"] == 50.0
        assert monthly["2026-02"]["approved_total"] == 0.0
        assert monthly["2025-09"]["invoice_count"] == 0

        yearly = {point["period"]: point for point in body["yearly"]}
        assert len(body["yearly"]) == 3
        assert yearly["2025"]["total"] == 100.0
        assert yearly["2026"]["total"] == 250.0

        currencies = {item["currency"]: item for item in body["currencies"]}
        assert currencies["USD"]["invoice_count"] == 3
        assert currencies["USD"]["total"] == 350.0
        assert currencies["EUR"]["invoice_count"] == 1
        assert currencies["EUR"]["total"] == 300.0

        assert [item["supplier_name"] for item in body["top_suppliers"]] == [
            "Beta",
            "ACME",
        ]
        assert body["top_suppliers"][0]["total"] == 200.0

        statuses = {item["status"]: item for item in body["statuses"]}
        assert statuses["approved"]["count"] == 2
        assert statuses["approved"]["total"] == 300.0
        assert statuses["pending"]["count"] == 1
        assert statuses["pending"]["total"] == 50.0

    def test_default_currency_and_open_duplicate_exclusion(self, client, auth_headers, db):
        _add_invoice(
            db, date_value="2026-01-05", total="100.00", currency="USD", supplier="ACME"
        )
        _add_invoice(
            db, date_value="2026-02-05", total="200.00", currency="USD", supplier="Beta"
        )
        _add_invoice(
            db, date_value="2026-03-05", total="300.00", currency="USD", supplier="Gamma"
        )
        _add_invoice(
            db, date_value="2026-03-06", total="1000.00", currency="EUR", supplier="Delta"
        )
        duplicate = _add_invoice(
            db, date_value="2026-03-07", total="999.00", currency="USD", supplier="ACME"
        )
        db.add(
            Finding(
                document_id=duplicate.document_id,
                invoice_id=duplicate.id,
                rule_code="V010",
                severity="error",
                field_path="invoice_number",
                message="Duplicate invoice",
            )
        )
        db.flush()

        response = client.get("/api/v1/analytics/sales", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()

        # USD has three non-duplicate invoices versus one EUR invoice.
        assert body["currency"] == "USD"
        assert body["summary"]["invoice_count"] == 3
        assert body["summary"]["total"] == 600.0
        assert body["summary"]["excluded_duplicates"] == 1

        currencies = {item["currency"]: item for item in body["currencies"]}
        assert currencies["USD"]["total"] == 600.0
        assert currencies["EUR"]["total"] == 1000.0

    def test_duplicate_identity_counted_once_and_prefers_clean_copy(
        self, client, auth_headers, db
    ):
        first = _add_invoice(
            db,
            invoice_number="INV-100",
            date_value="2026-01-05",
            total="100.00",
            currency="USD",
            supplier="ACME",
        )
        _add_invoice(
            db,
            invoice_number="INV-100",
            date_value="2026-01-05",
            total="120.00",
            currency="USD",
            supplier="ACME",
        )
        _add_invoice(
            db,
            invoice_number="INV-200",
            date_value="2026-02-05",
            total="250.00",
            currency="USD",
            supplier="ACME",
        )
        db.add(
            Finding(
                document_id=first.document_id,
                invoice_id=first.id,
                rule_code="V010",
                severity="error",
                field_path="invoice_number",
                message="Duplicate invoice",
            )
        )
        db.flush()

        response = client.get("/api/v1/analytics/sales", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["summary"]["invoice_count"] == 2
        assert body["summary"]["total"] == 370.0
        assert body["summary"]["excluded_duplicates"] == 1

    def test_missing_date_and_total_are_reported(self, client, auth_headers, db):
        _add_invoice(
            db,
            date_value=None,
            total=None,
            currency="USD",
            supplier="No Date Ltd",
            approved=False,
        )

        response = client.get("/api/v1/analytics/sales", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["summary"]["invoice_count"] == 1
        assert body["summary"]["undated_count"] == 1
        assert body["summary"]["missing_total_count"] == 1
        assert body["summary"]["total"] == 0.0
        assert len(body["monthly"]) == 12
        assert all(point["invoice_count"] == 0 for point in body["monthly"])

    def test_requires_authentication(self, client):
        response = client.get("/api/v1/analytics/sales")
        assert response.status_code == 401
