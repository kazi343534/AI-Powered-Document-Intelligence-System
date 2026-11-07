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


def test_deterministic_line_items_with_ocr_table_artifacts():
    # Tesseract often keeps table borders/bullets at the start of a row.
    pages = [
        (
            1,
            "| Palette Shrink Wrap (Rolls) 15 18.50 277.50\n"
            "- Delivery Surcharge 1 95.00 95.00\n",
        )
    ]
    data = deterministic_extract(pages)
    descriptions = [item.description for item in data.line_items]
    assert descriptions == ["Palette Shrink Wrap (Rolls)", "Delivery Surcharge"]
    assert data.line_items[0].amount == "277.50"
    assert data.line_items[1].amount == "95.00"


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


def test_multiline_supplier_name_keeps_evidence():
    pages = [
        (
            1,
            "INVOICE\nInvoice Number\nINV-2026-00101\n"
            "Supplier Name\nApex Cloud Infrastructure\nLtd.\n"
            "Invoice Date\n2026-10-01\nTotal Amount Due (USD)\n13,020.00\n",
        )
    ]
    data = deterministic_extract(pages)
    assert data.supplier_name.value == "Apex Cloud Infrastructure Ltd."
    assert data.supplier_name.confidence >= 0.85
    assert data.supplier_name.evidence is not None
    assert data.supplier_name.evidence.page == 1


def test_image_style_invoice_has_auto_approve_confidence():
    text = "\n".join(
        [
            "NEXUS INDUSTRIAL SOLUTIONS LTD",
            "14 Innovation Park, Bristol, BS1 6JX, UK",
            "INVOICE",
            "Invoice No: INV-2024-0087",
            "Invoice Date: 14/10/2026",
            "Bill To: Stark Logistics",
            "Description",
            "Qty",
            "Unit Price",
            "Amount",
            "Pneumatic Valve 1/2 in",
            "5",
            "215.00",
            "1,075.00",
            "High-Tensile Wire (100m)",
            "10",
            "45.00",
            "450.00",
            "Industrial Sensor Unit",
            "4",
            "340.00",
            "1,360.00",
            "Subtotal: GBP 2,885.00",
            "VAT 20%: GBP 577.00",
            "Total Due: GBP 3,462.00",
        ]
    )
    data = deterministic_extract([(1, text)])
    assert data.invoice_number.value == "INV-2024-0087"
    assert data.invoice_date.value == "2026-10-14"
    assert data.supplier_name.value == "NEXUS INDUSTRIAL SOLUTIONS LTD"
    assert data.currency.value == "GBP"
    assert data.subtotal.value == "2885.00"
    assert data.tax.value == "577.00"
    assert data.total.value == "3462.00"
    assert len(data.line_items) == 3
    assert data.line_items[0].description == "Pneumatic Valve 1/2 in"
    assert data.line_items[0].quantity == "5"
    assert data.line_items[0].unit_price == "215.00"
    assert data.line_items[0].amount == "1075.00"

    # Clean image OCR invoices should clear the auto-approval threshold instead
    # of being forced into manual review by a fixed low fallback confidence.
    required = {
        "invoice_number": data.invoice_number,
        "invoice_date": data.invoice_date,
        "supplier_name": data.supplier_name,
        "total": data.total,
        "currency": data.currency,
    }
    assert all(field.value is not None and field.confidence >= 0.85 for field in required.values())
