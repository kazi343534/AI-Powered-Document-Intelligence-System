"""Tests for deterministic extraction and evidence verification."""

from app.extraction.deterministic import deterministic_extract
from app.extraction.service import extract_invoice


def test_deterministic_extracts_core_fields():
    pages = [
        (1, "INVOICE\nInvoice No: INV-2024-0042\nInvoice Date: 15 March 2024\n")
    ]
    data = deterministic_extract(pages)
    assert data.invoice_number.value == "INV-2024-0042"
    assert data.invoice_date.value == "2024-03-15"


def test_deterministic_currency_symbol():
    pages = [(1, "INVOICE\nInvoice No: INV-X\nTotal £1,650.00\n")]
    data = deterministic_extract(pages)
    assert data.currency.value == "GBP"


def test_deterministic_line_items():
    pages = [(1, "Hex bolt M8      10    12.50    125.00\n")]
    data = deterministic_extract(pages)
    assert len(data.line_items) >= 1
    assert data.line_items[0].description == "Hex bolt M8"
    assert data.line_items[0].quantity == "10"
    assert data.line_items[0].unit_price == "12.50"
    assert data.line_items[0].amount == "125.00"


def test_extract_invoice_never_invents_missing():
    pages = [(1, "just some unrelated text\n")]
    outcome = extract_invoice(pages)
    assert outcome.data.invoice_number.value is None
    assert outcome.data.total.value is None
    assert outcome.data.currency.value is None
    assert outcome.source == "fallback"


def test_extract_invoice_ai_flagged_when_disabled():
    pages = [(1, "INVOICE\nInvoice No: INV-1\nTotal 100.00\n")]
    outcome = extract_invoice(pages)
    assert outcome.model == "deterministic"
    assert "AI extraction not configured" in " ".join(outcome.data.warnings)


def test_evidence_quote_populated_when_present():
    pages = [(1, "INVOICE\nInvoice No: INV-999\nTotal 100.00\n")]
    data = deterministic_extract(pages)
    assert data.invoice_number.evidence is not None
    assert data.invoice_number.evidence.page == 1
    assert data.invoice_number.evidence.quote is not None
