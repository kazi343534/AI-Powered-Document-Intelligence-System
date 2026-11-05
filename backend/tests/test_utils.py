"""Tests for shared normalization / utility helpers."""

from decimal import Decimal

from app.utils import (
    CURRENCY_CODES,
    CURRENCY_SYMBOLS,
    normalize_currency,
    normalize_for_match,
    normalize_invoice_number,
    normalize_supplier,
    parse_date_flexible,
    parse_decimal,
)


class TestParseDecimal:
    def test_plain_number(self):
        assert parse_decimal("125.00") == Decimal("125.00")

    def test_integer(self):
        assert parse_decimal("10") == Decimal("10")

    def test_negative_parentheses(self):
        assert parse_decimal("(100.00)") == Decimal("-100.00")

    def test_european_separators(self):
        assert parse_decimal("1.250,00") == Decimal("1250.00")

    def test_thousand_comma(self):
        assert parse_decimal("1,250.00") == Decimal("1250.00")

    def test_currency_symbol_stripped(self):
        assert parse_decimal("£1,650.00") == Decimal("1650.00")

    def test_empty_and_none(self):
        assert parse_decimal("") is None
        assert parse_decimal(None) is None

    def test_garbage(self):
        assert parse_decimal("not a number") is None


class TestNormalizeInvoiceNumber:
    def test_strips_prefix(self):
        assert normalize_invoice_number("Invoice No: INV-2024-0042") == "INV20240042"

    def test_none(self):
        assert normalize_invoice_number(None) is None
        assert normalize_invoice_number("") is None


class TestNormalizeSupplier:
    def test_strips_legal_suffixes(self):
        assert normalize_supplier("ACME COMPONENTS LTD") == "acme components"

    def test_none(self):
        assert normalize_supplier(None) is None


class TestNormalizeCurrency:
    def test_code_returned(self):
        assert normalize_currency("GBP", "") == "GBP"

    def test_symbol_returned(self):
        assert normalize_currency(None, "£1,650.00") == "GBP"

    def test_unknown_returns_none(self):
        assert normalize_currency("ZZZ", "") is None


class TestParseDateFlexible:
    def test_iso(self):
        assert parse_date_flexible("2024-03-15").isoformat() == "2024-03-15"

    def test_long_form(self):
        assert parse_date_flexible("15 March 2024").isoformat() == "2024-03-15"

    def test_none(self):
        assert parse_date_flexible(None) is None

    def test_garbage_returns_none(self):
        assert parse_date_flexible("not-a-real-date") is None


class TestConstants:
    def test_known_currencies(self):
        assert "GBP" in CURRENCY_CODES
        assert "£" in CURRENCY_SYMBOLS

    def test_normalize_for_match_compacts(self):
        assert normalize_for_match("INV-2024/0042!") == "inv20240042"
