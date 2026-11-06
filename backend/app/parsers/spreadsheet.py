from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from charset_normalizer import from_bytes

from ..utils import (
    json_safe,
    normalize_currency_cell,
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
        "invoice #",
        "invoice no",
        "expected invoice no",
        "invoice_number",
        "inv no",
        "invoice number (pdf)",
        "invoice num",
        "inv number",
        "inv #",
        "invoice id",
        "document number",
        "doc no",
        "bill no",
    ],
    "invoice_date": [
        "invoice date",
        "date",
        "expected date",
        "bill date",
        "invoice_date",
    ],
    "supplier_name": [
        "supplier name",
        "supplier",
        "vendor",
        "vendor name",
        "merchant",
        "supplier_name",
        "seller",
        "bill from",
        "company",
    ],
    "customer_name": [
        "customer name",
        "customer",
        "client",
        "buyer",
        "bill to",
        "customer_name",
    ],
    "subtotal": [
        "subtotal",
        "sub total",
        "expected subtotal",
        "pdf subtotal",
        "net amount",
        "net",
        "taxable amount",
    ],
    "tax": [
        "tax",
        "vat",
        "gst",
        "hst",
        "expected tax",
        "pdf tax",
        "tax amount",
        "sales tax",
        "vat amount",
    ],
    "total": [
        "total",
        "grand total",
        "expected total",
        "pdf total",
        "total amount",
        "amount due",
        "gross",
        "invoice total",
    ],
    "currency": ["currency", "curr", "ccy", "currency code"],
    "description": ["description", "item", "product", "details", "particulars"],
    "quantity": ["quantity", "qty"],
    "unit_price": ["unit price", "rate", "price"],
    "line_number": ["line #", "line number", "line no", "line"],
    "sku": ["sku", "sku / item code", "item code", "item code / sku", "part number"],
    "line_total": [
        "pdf line total",
        "line total",
        "calculated line total",
        "line amount",
    ],
    "po_number": ["po number", "po #", "po no", "purchase order number", "purchase order"],
    "record_id": ["record id", "record_id"],
}

SHEET_INVOICE_LEDGER = "INVOICE_LEDGER"
SHEET_LINE_ITEMS = "LINE_ITEMS"
SHEET_RECONCILIATION = "RECONCILIATION"

SUMMARY_LABELS = {"total", "subtotal", "grand total", "sum"}
IDENTIFIER_HEADERS = {
    "invoice number",
    "invoice no",
    "expected invoice no",
    "invoice number pdf",
    "po number",
    "po no",
    "record id",
}
RECONCILIATION_HEADERS = {
    "subtotal variance",
    "total variance",
    "formula math check",
    "excel po total",
    "excel po subtotal",
    "excel po tax",
}
LINE_ITEM_STRONG_HEADERS = {
    "sku",
    "sku item code",
    "item code",
    "line number",
    "line no",
    "pdf line total",
    "calculated line total",
}
LINE_ITEM_BROAD_HEADERS = {"quantity", "qty", "unit price"}


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
    kind: str = SHEET_INVOICE_LEDGER
    rows: list[dict[str, Any]] = field(default_factory=list)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_header(value: Any) -> str:
    text = normalize_whitespace(str(value or "")).lower()
    text = text.replace("#", " number ")
    text = text.replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_sheet(headers: list[Any]) -> str:
    """Classify a worksheet from its normalized headers."""
    normalized = {normalize_header(header) for header in headers if header not in (None, "")}
    if normalized & RECONCILIATION_HEADERS:
        return SHEET_RECONCILIATION
    if normalized & LINE_ITEM_STRONG_HEADERS:
        return SHEET_LINE_ITEMS
    if len(normalized & LINE_ITEM_BROAD_HEADERS) >= 2:
        return SHEET_LINE_ITEMS
    return SHEET_INVOICE_LEDGER


def _is_summary_label(value: Any) -> bool:
    return normalize_header(value) in SUMMARY_LABELS


def _is_missing_token(value: Any) -> bool:
    return normalize_header(value) in {"missing", "n a", "na", "none", "null"}


def _is_summary_row(raw: dict[str, Any]) -> bool:
    values = [value for value in raw.values() if value not in (None, "")]
    if not values:
        return False
    if _is_summary_label(values[0]):
        return True
    for header, value in raw.items():
        if normalize_header(header) in IDENTIFIER_HEADERS and _is_summary_label(value):
            return True
    return False


def _row_type(row: dict[str, Any]) -> str:
    return str((row.get("normalized") or {}).get("row_type") or "invoice")


def _append_warning(row: dict[str, Any], warning: str) -> None:
    warnings = list(row.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    row["warnings"] = warnings


def _line_item_payload(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "line_number": normalized.get("line_number"),
        "sku": normalized.get("sku"),
        "description": normalized.get("description"),
        "quantity": normalized.get("quantity"),
        "unit_price": normalized.get("unit_price"),
        "line_total": normalized.get("line_total"),
    }


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
    raw: dict[str, Any], mapping: dict[int, str], header_names: list[str]
) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    warnings: list[str] = []
    for index, key in mapping.items():
        if index >= len(header_names):
            continue
        value = raw.get(header_names[index])
        if value in (None, ""):
            continue
        if key in {"subtotal", "tax", "total", "quantity", "unit_price", "line_total"}:
            parsed = parse_decimal(value)
            normalized[key] = str(parsed) if parsed is not None else None
            if parsed is None:
                label = key.replace("_", " ")
                if key == "subtotal":
                    warnings.append("invalid or missing subtotal")
                elif key == "total":
                    warnings.append("invalid or missing total")
                elif key == "line_total":
                    warnings.append("invalid or missing line total")
                else:
                    warnings.append(f"invalid {label}")
        elif key == "invoice_date":
            parsed_date = parse_date_flexible(value)
            normalized[key] = parsed_date.isoformat() if parsed_date else None
            if parsed_date is None:
                warnings.append("invalid date format")
        elif key == "currency":
            currency, valid = normalize_currency_cell(value)
            normalized[key] = currency
            if not valid:
                warnings.append(f"invalid currency ({currency})")
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
    return normalized, warnings


def _rows_to_sheet(
    name: str, rows: list[list[Any]], warnings: list[str] | None = None
) -> ParsedSheet:
    warnings = list(warnings or [])
    if len(rows) > MAX_SHEET_ROWS:
        warnings.append(f"Sheet truncated to {MAX_SHEET_ROWS} rows (safety limit)")
        rows = rows[:MAX_SHEET_ROWS]
    header_index, raw_headers, mapping = _find_header_row(rows)
    header_names = _dedupe_headers(raw_headers)
    kind = classify_sheet(raw_headers)
    parsed = ParsedSheet(
        name=name,
        header_row=header_index + 1,
        headers=header_names,
        kind=kind,
        warnings=warnings,
    )
    if not mapping:
        parsed.warnings.append("No recognizable invoice columns were detected in this sheet")
    if kind == SHEET_RECONCILIATION:
        parsed.warnings.append(
            "Reconciliation/comparison sheet skipped for top-level invoice extraction"
        )
        return parsed

    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not row or not any(cell not in (None, "") for cell in row):
            continue
        raw = {}
        for index, value in enumerate(row):
            key = header_names[index] if index < len(header_names) else f"column_{index + 1}"
            raw[key] = json_safe(value)
        if kind == SHEET_INVOICE_LEDGER and _is_summary_row(raw):
            continue
        normalized, row_warnings = _normalize_row(raw, mapping, header_names)
        if not normalized:
            continue

        if kind == SHEET_LINE_ITEMS:
            payload = _line_item_payload(normalized)
            if not any(value not in (None, "") for value in payload.values()):
                continue
            parent_number = normalized.get("invoice_number")
            if (
                not parent_number
                or _is_summary_label(parent_number)
                or _is_missing_token(parent_number)
            ):
                parent_number = None
                normalized["invoice_number"] = None
                normalized.pop("invoice_number_key", None)
                row_warnings.append("missing parent invoice number")
            normalized["row_type"] = "line_item"
            normalized["parent_invoice_number"] = parent_number
            parsed.line_items.append(
                {
                    "row_number": offset,
                    "data": raw,
                    "normalized": normalized,
                    "warnings": row_warnings,
                }
            )
            continue

        business_fields = (
            "invoice_number",
            "invoice_date",
            "supplier_name",
            "customer_name",
            "currency",
            "subtotal",
            "tax",
            "total",
        )
        if not any(normalized.get(field) not in (None, "") for field in business_fields):
            continue
        if (
            not any(
                normalized.get(field)
                for field in ("invoice_number", "supplier_name", "customer_name")
            )
            and any(
                normalized.get(field) is not None
                for field in ("subtotal", "tax", "total")
            )
        ):
            continue
        normalized["row_type"] = "invoice"
        if not normalized.get("invoice_number"):
            row_warnings.append("missing invoice number")
        if normalized.get("total") is None:
            if "invalid or missing total" not in row_warnings:
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


def _link_line_items(sheets: list[ParsedSheet]) -> None:
    parents: dict[str, dict[str, Any]] = {}
    for sheet in sheets:
        if sheet.kind != SHEET_INVOICE_LEDGER:
            continue
        for row in sheet.rows:
            key = (row.get("normalized") or {}).get("invoice_number_key")
            if key:
                parents.setdefault(str(key), row)

    for sheet in sheets:
        if sheet.kind != SHEET_LINE_ITEMS:
            continue
        for item in sheet.line_items:
            normalized = item.get("normalized") or {}
            key = normalized.get("invoice_number_key")
            if not key:
                normalized["linked"] = False
                continue
            parent = parents.get(str(key))
            if parent is None:
                normalized["linked"] = False
                _append_warning(item, "no matching parent invoice")
                continue
            payload = _line_item_payload(normalized)
            parent_normalized = parent.setdefault("normalized", {})
            line_items = list(parent_normalized.get("line_items") or [])
            line_items.append(payload)
            parent_normalized["line_items"] = line_items
            parent_normalized["line_item_count"] = len(line_items)
            normalized["linked"] = True
            normalized["parent_invoice_id"] = parent_normalized.get("invoice_number")
            normalized["parent_row_number"] = parent.get("row_number")


def parse_spreadsheet(path: Path, suffix: str) -> list[ParsedSheet]:
    suffix = suffix.lower()
    if suffix == ".xlsx":
        sheets = _read_xlsx(path)
    elif suffix == ".xls":
        sheets = _read_xls(path)
    elif suffix == ".csv":
        sheets = _read_csv(path)
    else:
        raise SpreadsheetError("UNSUPPORTED_TYPE", f"Unsupported spreadsheet type {suffix}")
    _link_line_items(sheets)
    return sheets


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
