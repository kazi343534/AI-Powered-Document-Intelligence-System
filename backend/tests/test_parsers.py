"""Tests for spreadsheet parsing (XLSX/XLS/CSV)."""

from pathlib import Path

import pytest

from app.parsers.spreadsheet import (
    SHEET_INVOICE_LEDGER,
    SHEET_LINE_ITEMS,
    SHEET_RECONCILIATION,
    SpreadsheetError,
    parse_spreadsheet,
)

CROSS_VERIFICATION_WORKBOOK = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "invoice_test_suite_cross_verification.xlsx"
)


def _sheet(sheets, name):
    return next(sheet for sheet in sheets if sheet.name == name)


def _row(sheet, row_number):
    return next(row for row in [*sheet.rows, *sheet.line_items] if row["row_number"] == row_number)


def test_csv_parsing(tmp_path):
    path = tmp_path / "invoices.csv"
    path.write_text(
        "invoice number,invoice date,supplier,total\nINV-CSV-001,2024-01-10,Acme Corp,123.45\n"
    )
    sheets = parse_spreadsheet(path, ".csv")
    assert len(sheets) == 1
    assert len(sheets[0].rows) == 1
    row = sheets[0].rows[0]
    assert row["normalized"]["invoice_number"] == "INV-CSV-001"
    assert row["normalized"]["total"] == "123.45"


def test_xlsx_parsing(tmp_path):
    import openpyxl

    path = tmp_path / "invoices.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Invoices"
    sheet.append(["Invoice #", "Date", "Supplier", "Total"])
    sheet.append(["INV-XLSX-001", "2024-02-01", "Acme Corp", 250.00])
    workbook.save(str(path))

    sheets = parse_spreadsheet(path, ".xlsx")
    assert len(sheets) == 1
    assert len(sheets[0].rows) == 1
    row = sheets[0].rows[0]
    assert row["normalized"]["invoice_number"] == "INV-XLSX-001"
    assert row["normalized"]["total"] == "250"


def test_unsupported_type_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(SpreadsheetError):
        parse_spreadsheet(path, ".txt")


def test_cross_verification_sheet_classification_and_counts():
    sheets = parse_spreadsheet(CROSS_VERIFICATION_WORKBOOK, ".xlsx")

    assert [sheet.name for sheet in sheets] == [
        "Master_PO_Ledger",
        "PDF_vs_Excel_Comparison",
        "Line_Items_Detail",
        "Dirty_Data_Stress_Test",
    ]
    assert _sheet(sheets, "Master_PO_Ledger").kind == SHEET_INVOICE_LEDGER
    assert _sheet(sheets, "PDF_vs_Excel_Comparison").kind == SHEET_RECONCILIATION
    assert _sheet(sheets, "Line_Items_Detail").kind == SHEET_LINE_ITEMS
    assert _sheet(sheets, "Dirty_Data_Stress_Test").kind == SHEET_INVOICE_LEDGER

    # Only the two invoice/PO ledgers produce top-level records.
    assert sum(len(sheet.rows) for sheet in sheets) == 14
    assert sum(len(sheet.line_items) for sheet in sheets) == 20

    master = _sheet(sheets, "Master_PO_Ledger")
    dirty = _sheet(sheets, "Dirty_Data_Stress_Test")
    comparison = _sheet(sheets, "PDF_vs_Excel_Comparison")

    assert len(master.rows) == 8
    assert len(dirty.rows) == 6
    assert len(comparison.rows) == 0
    assert len(comparison.line_items) == 0

    # The formula-only TOTAL footer and the Record ID-only row are not invoices.
    assert [row["row_number"] for row in master.rows] == list(range(2, 10))
    assert [row["row_number"] for row in dirty.rows] == [2, 3, 4, 5, 7, 8]


def test_cross_verification_header_aliases_and_unknown_currency():
    master = _sheet(
        parse_spreadsheet(CROSS_VERIFICATION_WORKBOOK, ".xlsx"), "Master_PO_Ledger"
    )
    first = _row(master, 2)["normalized"]
    assert first["invoice_number"] == "INV-2026-00101"
    assert first["invoice_date"] == "2026-10-05"
    assert first["supplier_name"] == "Apex Cloud Solutions Inc."
    assert first["customer_name"] == "Global FinTech Corp"
    assert first["subtotal"] == "14250"
    assert first["tax"] == "1140"
    assert first["total"] == "15390"
    assert first["currency"] == "USD"

    dirty = _sheet(
        parse_spreadsheet(CROSS_VERIFICATION_WORKBOOK, ".xlsx"),
        "Dirty_Data_Stress_Test",
    )
    unknown_currency = _row(dirty, 7)
    assert unknown_currency["normalized"]["supplier_name"] == "Epsilon Security"
    assert unknown_currency["normalized"]["customer_name"] == "Global FinTech Corp"
    assert unknown_currency["normalized"]["currency"] == "XYZ"
    assert "invalid currency (XYZ)" in unknown_currency["warnings"]
    assert unknown_currency["normalized"]["total"] == "4100"


def test_cross_verification_dirty_row_warnings():
    dirty = _sheet(
        parse_spreadsheet(CROSS_VERIFICATION_WORKBOOK, ".xlsx"),
        "Dirty_Data_Stress_Test",
    )

    assert "missing invoice number" in _row(dirty, 3)["warnings"]
    assert "invalid date format" in _row(dirty, 4)["warnings"]
    assert _row(dirty, 4)["normalized"]["invoice_date"] is None
    assert "invalid or missing subtotal" in _row(dirty, 5)["warnings"]
    assert _row(dirty, 5)["normalized"]["subtotal"] is None
    assert _row(dirty, 7)["normalized"]["currency"] == "XYZ"
    assert "invalid currency (XYZ)" in _row(dirty, 7)["warnings"]


def test_cross_verification_line_items_link_to_parent_invoices():
    sheets = parse_spreadsheet(CROSS_VERIFICATION_WORKBOOK, ".xlsx")
    line_items_sheet = _sheet(sheets, "Line_Items_Detail")
    master = _sheet(sheets, "Master_PO_Ledger")

    assert len(line_items_sheet.line_items) == 20
    linked = [item for item in line_items_sheet.line_items if item["normalized"].get("linked")]
    unlinked = [
        item for item in line_items_sheet.line_items if not item["normalized"].get("linked")
    ]
    assert len(linked) == 17
    assert len(unlinked) == 3
    assert {item["normalized"]["invoice_number"] for item in unlinked} == {None}
    assert all(
        "missing parent invoice number" in item["warnings"] for item in unlinked
    )

    first = _row(master, 2)["normalized"]
    assert first["line_item_count"] == 6
    assert len(first["line_items"]) == 6
    assert first["line_items"][0] == {
        "line_number": "1",
        "sku": "CLD-ENT-01",
        "description": "Enterprise Kubernetes Cluster (Annual)",
        "quantity": "2",
        "unit_price": "3200",
        "line_total": "6400",
    }

    assert _row(master, 3)["normalized"]["line_item_count"] == 4
    assert _row(master, 4)["normalized"]["line_item_count"] == 4
    assert _row(master, 6)["normalized"].get("line_item_count") is None
    assert _row(master, 7)["normalized"].get("line_item_count") is None
    assert _row(master, 8)["normalized"]["line_item_count"] == 3
    assert _row(master, 9)["normalized"].get("line_item_count") is None
