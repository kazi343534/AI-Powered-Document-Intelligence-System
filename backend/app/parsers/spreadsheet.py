from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from charset_normalizer import from_bytes

from ..utils import (
    json_safe,
    normalize_currency,
    normalize_invoice_number,
    normalize_supplier,
    normalize_whitespace,
    parse_date_flexible,
    parse_decimal,
)

logger = logging.getLogger(__name__)

MAX_SHEET_ROWS = 20000
MAX_SHEETS = 25

HEADER_SYNONYMS: dict[str, list[str]] = {
    "invoice_number": [
        "invoice number",
        "invoice no",
        "invoice num",
        "invoice #",
        "inv no",
        "inv number",
        "inv #",
        "invoice id",
        "document number",
        "doc no",
        "bill no",
    ],
    "invoice_date": ["invoice date", "bill date", "date"],
    "supplier_name": ["supplier", "vendor", "seller", "bill from", "company"],
    "customer_name": ["customer", "buyer", "client", "bill to"],
    "subtotal": ["subtotal", "sub total", "net amount", "net", "taxable amount"],
    "tax": ["tax", "vat", "gst", "sales tax", "vat amount", "tax amount"],
    "total": ["total", "grand total", "total amount", "amount due", "gross", "invoice total"],
    "currency": ["currency", "ccy", "curr"],
    "description": ["description", "item", "product", "details", "particulars"],
    "quantity": ["quantity", "qty"],
    "unit_price": ["unit price", "rate", "price"],
}


class SpreadsheetError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParsedSheet:
    name: str
    header_row: int
    headers: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_header(value: Any) -> str:
    text = normalize_whitespace(str(value or "")).lower()
    text = text.replace("#", " number ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_headers(headers: list[Any]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    used: set[str] = set()
    normalized = [normalize_header(header) for header in headers]
    synonym_lookup: dict[str, str] = {}
    for canonical, synonyms in HEADER_SYNONYMS.items():
        for synonym in synonyms:
            synonym_lookup[normalize_header(synonym)] = canonical
    for index, header in enumerate(normalized):
        canonical = synonym_lookup.get(header)
        if canonical and canonical not in used:
            mapping[index] = canonical
            used.add(canonical)
    return mapping


def _find_header_row(rows: list[list[Any]]) -> tuple[int, list[str], dict[int, str]]:
    best: tuple[int, int, dict[int, str]] | None = None
    for index, row in enumerate(rows[:20]):
        if not row or not any(cell not in (None, "") for cell in row):
            continue
        mapping = canonical_headers(row)
        if best is None or len(mapping) > best[1]:
            best = (index, len(mapping), mapping)
    if best and best[1] >= 2:
        index, _score, mapping = best
        headers = [normalize_whitespace(str(cell or "")) or f"column_{i + 1}" for i, cell in enumerate(rows[index])]
        return index, headers, mapping
    # Fallback: first non-empty row as headers, raw values only.
    for index, row in enumerate(rows):
        if row and any(cell not in (None, "") for cell in row):
            headers = [normalize_whitespace(str(cell or "")) or f"column_{i + 1}" for i, cell in enumerate(row)]
            return index, headers, {}
    return 0, [], {}


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for header in headers:
        base = header or "column"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def _normalize_row(
    raw: dict[str, Any], mapping: dict[int, str], header_names: list[str], text_blob: str
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for index, key in mapping.items():
        if index >= len(header_names):
            continue
        value = raw.get(header_names[index])
        if value in (None, ""):
            continue
        if key in {"subtotal", "tax", "total", "quantity", "unit_price"}:
            parsed = parse_decimal(value)
            normalized[key] = str(parsed) if parsed is not None else None
        elif key == "invoice_date":
            parsed_date = parse_date_flexible(value)
            normalized[key] = parsed_date.isoformat() if parsed_date else None
        elif key == "currency":
            normalized[key] = normalize_currency(str(value), text_blob)
        elif key == "invoice_number":
            normalized[key] = normalize_whitespace(str(value))
        else:
            normalized[key] = normalize_whitespace(str(value))
    if normalized.get("invoice_number"):
        normalized["invoice_number_key"] = normalize_invoice_number(
            str(normalized["invoice_number"])
        )
    if normalized.get("supplier_name"):
        normalized["supplier_key"] = normalize_supplier(str(normalized["supplier_name"]))
    return normalized


def _rows_to_sheet(
    name: str, rows: list[list[Any]], warnings: list[str] | None = None
) -> ParsedSheet:
    warnings = list(warnings or [])
    if len(rows) > MAX_SHEET_ROWS:
        warnings.append(f"Sheet truncated to {MAX_SHEET_ROWS} rows (safety limit)")
        rows = rows[:MAX_SHEET_ROWS]
    header_index, raw_headers, mapping = _find_header_row(rows)
    header_names = _dedupe_headers(raw_headers)
    parsed = ParsedSheet(
        name=name,
        header_row=header_index + 1,
        headers=header_names,
        warnings=warnings,
    )
    if not mapping:
        parsed.warnings.append("No recognizable invoice columns were detected in this sheet")

    text_blob = " ".join(str(cell) for row in rows[:5] for cell in row if cell is not None)
    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not row or not any(cell not in (None, "") for cell in row):
            continue
        raw = {
            header_names[index] if index < len(header_names) else f"column_{index + 1}": json_safe(value)
            for index, value in enumerate(row)
        }
        normalized = _normalize_row(raw, mapping, header_names, text_blob)
        if not normalized:
            continue
        row_warnings: list[str] = []
        if not normalized.get("invoice_number"):
            row_warnings.append("missing invoice number")
        if not normalized.get("total"):
            row_warnings.append("missing total")
        parsed.rows.append(
            {
                "row_number": offset,
                "data": raw,
                "normalized": normalized,
                "warnings": row_warnings,
            }
        )
    return parsed


def _read_xlsx(path: Path) -> list[ParsedSheet]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise SpreadsheetError("INVALID_XLSX", f"Could not open XLSX: {exc}") from exc
    sheets: list[ParsedSheet] = []
    try:
        for index, sheet in enumerate(workbook.worksheets):
            if index >= MAX_SHEETS:
                break
            rows = []
            for row in sheet.iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) > MAX_SHEET_ROWS:
                    break
            sheets.append(_rows_to_sheet(sheet.title, rows))
    finally:
        workbook.close()
    return sheets


def _read_xls(path: Path) -> list[ParsedSheet]:
    try:
        workbook = xlrd.open_workbook(path, on_demand=True)
    except Exception as exc:
        raise SpreadsheetError("INVALID_XLS", f"Could not open XLS: {exc}") from exc
    sheets: list[ParsedSheet] = []
    try:
        for index in range(min(workbook.nsheets, MAX_SHEETS)):
            sheet = workbook.sheet_by_index(index)
            rows: list[list[Any]] = []
            for row_index in range(min(sheet.nrows, MAX_SHEET_ROWS + 1)):
                row: list[Any] = []
                for cell in sheet.row(row_index):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(
                                xlrd.xldate_as_datetime(cell.value, workbook.datemode).date()
                            )
                        except Exception:
                            row.append(cell.value)
                    else:
                        row.append(cell.value)
                rows.append(row)
            sheets.append(_rows_to_sheet(sheet.name, rows))
    finally:
        workbook.release_resources()
    return sheets


def _read_csv(path: Path) -> list[ParsedSheet]:
    raw = path.read_bytes()
    decoded = from_bytes(raw).best()
    if decoded is None:
        raise SpreadsheetError("INVALID_CSV", "Could not decode CSV file")
    text = str(decoded)
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    return [_rows_to_sheet(path.stem, rows)]


def parse_spreadsheet(path: Path, suffix: str) -> list[ParsedSheet]:
    suffix = suffix.lower()
    if suffix == ".xlsx":
        return _read_xlsx(path)
    if suffix == ".xls":
        return _read_xls(path)
    if suffix == ".csv":
        return _read_csv(path)
    raise SpreadsheetError("UNSUPPORTED_TYPE", f"Unsupported spreadsheet type {suffix}")


def sheets_summary(sheets: list[ParsedSheet]) -> str:
    parts: list[str] = []
    for sheet in sheets:
        parts.append(f"Sheet: {sheet.name}")
        if sheet.headers:
            parts.append(" | ".join(sheet.headers))
        for row in sheet.rows[:2000]:
            values = [str(value) for value in row["data"].values() if value not in (None, "")]
            if values:
                parts.append(" | ".join(values))
    return "\n".join(parts)
