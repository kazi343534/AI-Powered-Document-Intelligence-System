"""Tests for spreadsheet parsing (XLSX/XLS/CSV)."""


import pytest

from app.parsers.spreadsheet import SpreadsheetError, parse_spreadsheet


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
