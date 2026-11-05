"""Tests for validation rules (V001–V017), duplicates and reconciliation."""

from datetime import date, timedelta

from app.schemas import ExtractionData, ExtractionLineItem, FieldValue
from app.validation import validate_invoice


def _build_data(**overrides):
    data = ExtractionData()
    for key, value in overrides.items():
        field = FieldValue(value=value, confidence=1.0)
        setattr(data, key, field)
    return data


def test_v001_required_missing(db):
    invoice = type("Invoice", (), {"id": "inv-1"})()
    data = _build_data()
    result = validate_invoice(db, None, invoice, None, data)
    codes = [i.rule_code for i in result.issues]
    assert "V001" in codes


def test_v004_arithmetic_mismatch(db):
    invoice = type("Invoice", (), {"id": "inv-2"})()
    data = _build_data(subtotal="100.00", tax="20.00", total="200.00")
    result = validate_invoice(db, None, invoice, None, data)
    assert any(i.rule_code == "V004" for i in result.issues)


def test_v004_arithmetic_ok(db):
    invoice = type("Invoice", (), {"id": "inv-3"})()
    data = _build_data(subtotal="100.00", tax="20.00", total="120.00")
    result = validate_invoice(db, None, invoice, None, data)
    assert not any(i.rule_code == "V004" for i in result.issues)


def test_v005_line_item_sum_mismatch(db):
    invoice = type("Invoice", (), {"id": "inv-4"})()
    data = _build_data(subtotal="100.00", total="100.00")
    data.line_items = [
        ExtractionLineItem(description="A", amount="60.00"),
        ExtractionLineItem(description="B", amount="30.00"),
    ]
    result = validate_invoice(db, None, invoice, None, data)
    assert any(i.rule_code == "V005" for i in result.issues)


def test_v015_low_confidence(db):
    invoice = type("Invoice", (), {"id": "inv-5"})()
    data = _build_data(total="100.00")
    data.total.confidence = 0.1
    result = validate_invoice(db, None, invoice, None, data)
    assert any(i.rule_code == "V015" for i in result.issues)


def test_v009_no_line_items_with_total(db):
    invoice = type("Invoice", (), {"id": "inv-6"})()
    data = _build_data(total="100.00")
    result = validate_invoice(db, None, invoice, None, data)
    assert any(i.rule_code == "V009" for i in result.issues)


def test_v002_future_date(db):
    invoice = type("Invoice", (), {"id": "inv-7"})()
    data = _build_data(invoice_date=(date.today() + timedelta(days=5)).isoformat())
    result = validate_invoice(db, None, invoice, None, data)
    assert any(i.rule_code == "V002" for i in result.issues)
