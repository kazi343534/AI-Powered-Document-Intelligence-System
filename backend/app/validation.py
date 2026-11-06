from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Document, Extraction, Invoice, SheetRow
from .schemas import ExtractionData
from .utils import (
    money_str,
    normalize_invoice_number,
    normalize_supplier,
    parse_date_flexible,
    parse_decimal,
)

settings = get_settings()
MONEY_TOLERANCE = Decimal(str(settings.amount_tolerance))


@dataclass
class ValidationIssue:
    rule_code: str
    severity: str
    field_path: str
    message: str
    expected: str | None = None
    actual: str | None = None
    invoice_id: str | None = None


@dataclass
class ReconciliationDraft:
    invoice_id: str
    matched_invoice_id: str | None = None
    matched_document_id: str | None = None
    sheet_row_id: str | None = None
    match_type: str = "pdf_sheet"
    confidence: float = 0.0
    diffs: list[dict] = field(default_factory=list)
    status: str = "matched"


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    reconciliations: list[ReconciliationDraft] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(issue.severity in {"error", "warning"} for issue in self.issues)


def _value(data: ExtractionData, key: str) -> str | None:
    field = getattr(data, key, None)
    return getattr(field, "value", None)


def _confidence(data: ExtractionData, key: str) -> float:
    field = getattr(data, key, None)
    return float(getattr(field, "confidence", 0.0) or 0.0)


def _amount(data: ExtractionData | dict, key: str) -> Decimal | None:
    if isinstance(data, ExtractionData):
        return parse_decimal(_value(data, key))
    return parse_decimal((data or {}).get(key))


def _add(
    result: ValidationResult,
    code: str,
    severity: str,
    field_path: str,
    message: str,
    expected: str | None = None,
    actual: str | None = None,
    invoice_id: str | None = None,
) -> None:
    result.issues.append(
        ValidationIssue(
            rule_code=code,
            severity=severity,
            field_path=field_path,
            message=message,
            expected=expected,
            actual=actual,
            invoice_id=invoice_id,
        )
    )


def _diff(
    diffs: list[dict], field_name: str, left, right, severity: str = "warning"
) -> None:
    diffs.append(
        {
            "field": field_name,
            "invoice_value": None if left is None else str(left),
            "sheet_value": None if right is None else str(right),
            "severity": severity,
        }
    )


def _compare_sheet_row(row: SheetRow, data: ExtractionData) -> tuple[list[dict], list[ValidationIssue]]:
    diffs: list[dict] = []
    issues: list[ValidationIssue] = []
    normalized = row.normalized or {}
    for key in ("subtotal", "tax", "total"):
        invoice_amount = _amount(data, key)
        sheet_amount = parse_decimal(normalized.get(key))
        if invoice_amount is not None and sheet_amount is not None:
            if abs(invoice_amount - sheet_amount) > MONEY_TOLERANCE:
                severity = "error" if key == "total" else "warning"
                _diff(diffs, key, invoice_amount, sheet_amount, severity)
                issues.append(
                    ValidationIssue(
                        rule_code="V013",
                        severity=severity,
                        field_path=key,
                        message=f"{key.title()} differs between the PDF invoice and the spreadsheet ledger",
                        expected=str(invoice_amount),
                        actual=str(sheet_amount),
                    )
                )
    invoice_date = _value(data, "invoice_date")
    sheet_date = normalized.get("invoice_date")
    if invoice_date and sheet_date and invoice_date != sheet_date:
        _diff(diffs, "invoice_date", invoice_date, sheet_date, "warning")
        issues.append(
            ValidationIssue(
                rule_code="V013",
                severity="warning",
                field_path="invoice_date",
                message="Invoice date differs between the PDF invoice and the spreadsheet",
                expected=invoice_date,
                actual=str(sheet_date),
            )
        )
    invoice_currency = _value(data, "currency")
    sheet_currency = normalized.get("currency")
    if invoice_currency and sheet_currency and invoice_currency != sheet_currency:
        _diff(diffs, "currency", invoice_currency, sheet_currency, "warning")
        issues.append(
            ValidationIssue(
                rule_code="V013",
                severity="warning",
                field_path="currency",
                message="Currency differs between the PDF invoice and the spreadsheet",
                expected=invoice_currency,
                actual=str(sheet_currency),
            )
        )
    invoice_supplier = _value(data, "supplier_name")
    sheet_supplier = normalized.get("supplier_name")
    if invoice_supplier and sheet_supplier:
        score = fuzz.token_set_ratio(invoice_supplier.lower(), str(sheet_supplier).lower())
        if score < 80:
            _diff(diffs, "supplier_name", invoice_supplier, sheet_supplier, "warning")
            issues.append(
                ValidationIssue(
                    rule_code="V013",
                    severity="warning",
                    field_path="supplier_name",
                    message="Supplier name differs between the PDF invoice and the spreadsheet",
                    expected=invoice_supplier,
                    actual=str(sheet_supplier),
                )
            )
    return diffs, issues


def _find_sheet_match(db: Session, invoice_number_norm: str | None) -> SheetRow | None:
    if not invoice_number_norm:
        return None
    stmt = (
        select(SheetRow)
        .where(SheetRow.normalized["invoice_number_key"].as_string() == invoice_number_norm)
        .limit(1)
    )
    return db.scalars(stmt).first()


def validate_invoice(
    db: Session, document: Document, invoice: Invoice, extraction: Extraction, data: ExtractionData
) -> ValidationResult:
    result = ValidationResult()
    invoice_number = _value(data, "invoice_number")
    supplier = _value(data, "supplier_name")
    total = _amount(data, "total")
    subtotal = _amount(data, "subtotal")
    tax = _amount(data, "tax")
    invoice_date = parse_date_flexible(_value(data, "invoice_date"))
    currency = _value(data, "currency")

    invoice.invoice_number_norm = normalize_invoice_number(invoice_number)
    invoice.supplier_norm = normalize_supplier(supplier)

    required = {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "supplier_name": supplier,
        "total": total,
        "currency": currency,
    }
    for key, value in required.items():
        if value is None or value == "":
            _add(
                result,
                "V001",
                "error",
                key,
                f"Required field '{key.replace('_', ' ')}' is missing",
                invoice_id=invoice.id,
            )

    if not _value(data, "customer_name"):
        _add(
            result,
            "V001",
            "warning",
            "customer_name",
            "Customer name is missing",
            invoice_id=invoice.id,
        )

    if invoice_date:
        today = date.today()
        if invoice_date > today + timedelta(days=1):
            _add(
                result,
                "V002",
                "error",
                "invoice_date",
                "Invoice date is in the future",
                expected=f"<= {today.isoformat()}",
                actual=invoice_date.isoformat(),
                invoice_id=invoice.id,
            )
        elif invoice_date < today - timedelta(days=365 * 15):
            _add(
                result,
                "V002",
                "warning",
                "invoice_date",
                "Invoice date is more than 15 years old",
                actual=invoice_date.isoformat(),
                invoice_id=invoice.id,
            )

    for key in ("subtotal", "tax", "total"):
        amount = _amount(data, key)
        if amount is not None and amount < 0:
            _add(
                result,
                "V003",
                "error",
                key,
                f"{key.title()} is negative; this system does not auto-handle credit notes",
                actual=str(amount),
                invoice_id=invoice.id,
            )

    if subtotal is not None and tax is not None and total is not None:
        computed = subtotal + tax
        if abs(computed - total) > MONEY_TOLERANCE:
            _add(
                result,
                "V004",
                "error",
                "total",
                "Subtotal + tax does not equal total",
                expected=str(computed),
                actual=str(total),
                invoice_id=invoice.id,
            )
    elif total is not None and (subtotal is None or tax is None):
        _add(
            result,
            "V004",
            "info",
            "subtotal" if subtotal is None else "tax",
            "Cannot verify subtotal + tax = total because a component is missing",
            invoice_id=invoice.id,
        )

    if data.line_items:
        complete_items = [
            item for item in data.line_items if parse_decimal(item.amount) is not None
        ]
        if subtotal is not None and complete_items:
            item_sum = sum((parse_decimal(item.amount) or Decimal("0")) for item in complete_items)
            tolerance = max(
                Decimal("0.02"),
                abs(subtotal) * Decimal(str(settings.line_item_tolerance_pct)),
            )
            if abs(item_sum - subtotal) > tolerance:
                _add(
                    result,
                    "V005",
                    "error",
                    "line_items",
                    "Sum of line item amounts does not equal subtotal",
                    expected=str(item_sum),
                    actual=str(subtotal),
                    invoice_id=invoice.id,
                )
        for index, item in enumerate(data.line_items[:20]):
            quantity = parse_decimal(item.quantity)
            unit_price = parse_decimal(item.unit_price)
            amount = parse_decimal(item.amount)
            if quantity is not None and unit_price is not None and amount is not None:
                computed = quantity * unit_price
                tolerance = max(Decimal("0.02"), abs(amount) * Decimal("0.01"))
                if abs(computed - amount) > tolerance:
                    _add(
                        result,
                        "V006",
                        "warning",
                        f"line_items[{index}].amount",
                        "Quantity × unit price does not equal line amount",
                        expected=str(computed),
                        actual=str(amount),
                        invoice_id=invoice.id,
                    )
            tax_rate = parse_decimal(item.tax_rate)
            if tax_rate is not None and (tax_rate < 0 or tax_rate > 35):
                _add(
                    result,
                    "V007",
                    "warning",
                    f"line_items[{index}].tax_rate",
                    "Tax rate is outside the plausible range (0–35%)",
                    actual=str(tax_rate),
                    invoice_id=invoice.id,
                )
    elif total is not None and total > 0:
        _add(
            result,
            "V009",
            "warning",
            "line_items",
            "No line items were extracted for an invoice with a non-zero total",
            invoice_id=invoice.id,
        )

    if subtotal is not None and tax is not None and subtotal > 0:
        effective_rate = tax / subtotal * 100
        if effective_rate > 35:
            _add(
                result,
                "V007",
                "warning",
                "tax",
                "Effective tax rate is above 35%; review the tax amount",
                expected="<= 35%",
                actual=f"{effective_rate:.2f}%",
                invoice_id=invoice.id,
            )

    threshold = settings.auto_approve_confidence
    for key in ("invoice_number", "invoice_date", "supplier_name", "total", "currency"):
        confidence = _confidence(data, key)
        if _value(data, key) is not None and confidence < threshold:
            _add(
                result,
                "V015",
                "warning",
                key,
                f"Low extraction confidence ({confidence:.2f}) for {key.replace('_', ' ')}",
                expected=f">= {threshold:.2f}",
                actual=f"{confidence:.2f}",
                invoice_id=invoice.id,
            )

    for warning in data.warnings:
        if warning.startswith("Unverified field:") or warning.startswith("Evidence quote not found"):
            _add(
                result,
                "V016",
                "warning",
                warning.split(":", 1)[-1].strip() if ":" in warning else "",
                warning,
                invoice_id=invoice.id,
            )

    # Exact duplicates by normalized identity.
    duplicates: list[Invoice] = []
    if invoice.invoice_number_norm and invoice.supplier_norm:
        stmt = (
            select(Invoice)
            .join(Document, Document.id == Invoice.document_id)
            .where(
                Invoice.id != invoice.id,
                Invoice.invoice_number_norm == invoice.invoice_number_norm,
                Invoice.supplier_norm == invoice.supplier_norm,
                Document.deleted_at.is_(None),
            )
            .limit(5)
        )
        duplicates = list(db.scalars(stmt))
        for duplicate in duplicates:
            _add(
                result,
                "V010",
                "error",
                "invoice_number",
                f"Duplicate invoice: {invoice_number} from {supplier} was already processed",
                expected=duplicate.id,
                actual=invoice.id,
                invoice_id=invoice.id,
            )
            diffs = _duplicate_diffs(db, duplicate, data)
            result.reconciliations.append(
                ReconciliationDraft(
                    invoice_id=invoice.id,
                    matched_invoice_id=duplicate.id,
                    matched_document_id=duplicate.document_id,
                    match_type="pdf_pdf",
                    confidence=1.0,
                    diffs=diffs,
                    status="mismatch" if diffs else "matched",
                )
            )

    # Near duplicates: supplier/date/total fingerprint.
    if invoice.supplier_norm and total is not None and invoice_date and not duplicates:
        stmt = (
            select(Invoice)
            .where(Invoice.id != invoice.id, Invoice.current_extraction_id.is_not(None))
            .order_by(Invoice.created_at.desc())
            .limit(500)
        )
        for other in db.scalars(stmt):
            other_data = _load_extraction_data(db, other)
            if other_data is None:
                continue
            other_total = _amount(other_data, "total")
            other_date = parse_date_flexible(_value(other_data, "invoice_date"))
            other_supplier = _value(other_data, "supplier_name")
            if other_total is None or other_date is None or not other_supplier:
                continue
            if abs(other_total - total) > MONEY_TOLERANCE:
                continue
            if abs((other_date - invoice_date).days) > 1:
                continue
            score = fuzz.token_set_ratio(supplier.lower(), other_supplier.lower())
            if score >= 90:
                _add(
                    result,
                    "V011",
                    "warning",
                    "invoice_number",
                    "Possible near-duplicate invoice (same supplier, date and total)",
                    expected=other.id,
                    actual=invoice.id,
                    invoice_id=invoice.id,
                )
                break

    # Cross-check against spreadsheet rows already in the system.
    sheet_row = _find_sheet_match(db, invoice.invoice_number_norm)
    if sheet_row:
        diffs, sheet_issues = _compare_sheet_row(sheet_row, data)
        for issue in sheet_issues:
            issue.invoice_id = invoice.id
            result.issues.append(issue)
        result.reconciliations.append(
            ReconciliationDraft(
                invoice_id=invoice.id,
                matched_document_id=sheet_row.document_id,
                sheet_row_id=sheet_row.id,
                match_type="pdf_sheet",
                confidence=0.95,
                diffs=diffs,
                status="mismatch" if diffs else "matched",
            )
        )

    return result


def _load_extraction_data(db: Session, invoice: Invoice) -> ExtractionData | None:
    if not invoice.current_extraction_id:
        return None
    extraction = db.get(Extraction, invoice.current_extraction_id)
    if not extraction:
        return None
    try:
        return ExtractionData.model_validate(extraction.data)
    except Exception:
        return None


def _duplicate_diffs(db: Session, duplicate: Invoice, data: ExtractionData) -> list[dict]:
    other_data = _load_extraction_data(db, duplicate)
    if other_data is None:
        return []
    diffs: list[dict] = []
    for key in ("subtotal", "tax", "total"):
        left = _amount(data, key)
        right = _amount(other_data, key)
        if left is not None and right is not None and abs(left - right) > MONEY_TOLERANCE:
            _diff(diffs, key, left, right, "error")
    left_date = _value(data, "invoice_date")
    right_date = _value(other_data, "invoice_date")
    if left_date and right_date and left_date != right_date:
        _diff(diffs, "invoice_date", left_date, right_date, "warning")
    return diffs


def _add_row_warning(row: SheetRow, warning: str) -> None:
    warnings = list(row.warnings or [])
    if warning not in warnings:
        warnings.append(warning)
    row.warnings = warnings


def validate_sheet_document(
    db: Session, document: Document, rows: list[SheetRow]
) -> ValidationResult:
    result = ValidationResult()
    seen_numbers: dict[str, SheetRow] = {}
    invoice_rows = [
        row
        for row in rows
        if str((row.normalized or {}).get("row_type") or "invoice") == "invoice"
    ]
    for index, row in enumerate(invoice_rows):
        if index >= 100:
            break
        normalized = row.normalized or {}
        invoice_number = normalized.get("invoice_number")
        invoice_key = normalized.get("invoice_number_key")
        total = parse_decimal(normalized.get("total"))
        subtotal = parse_decimal(normalized.get("subtotal"))
        tax = parse_decimal(normalized.get("tax"))
        location = f"sheet[{row.sheet_name}!{row.row_number}]"

        if not invoice_number:
            _add(
                result,
                "V001",
                "warning",
                f"{location}.invoice_number",
                f"Row {row.row_number} in '{row.sheet_name}' has no invoice number",
            )
        else:
            if invoice_key and invoice_key in seen_numbers:
                first_row = seen_numbers[invoice_key]
                _add_row_warning(first_row, "duplicate invoice number")
                _add_row_warning(row, "duplicate invoice number")
                _add(
                    result,
                    "V014",
                    "error",
                    f"{location}.invoice_number",
                    f"Duplicate invoice number inside spreadsheet: {invoice_number}",
                    expected=f"row {first_row.row_number}",
                    actual=f"row {row.row_number}",
                )
            elif invoice_key:
                seen_numbers[invoice_key] = row

        if total is None:
            _add(
                result,
                "V001",
                "warning",
                f"{location}.total",
                f"Row {row.row_number} in '{row.sheet_name}' has no total",
            )
        if subtotal is None and tax is not None and total is not None:
            _add_row_warning(row, "invalid or missing subtotal")
        if subtotal is not None and tax is not None and total is not None:
            if abs(subtotal + tax - total) > MONEY_TOLERANCE:
                expected_total = subtotal + tax
                _add_row_warning(
                    row,
                    f"math mismatch: subtotal + tax ({money_str(expected_total)}) "
                    f"!= total ({money_str(total)})",
                )
                _add(
                    result,
                    "V014",
                    "error",
                    f"{location}.total",
                    "Spreadsheet row subtotal + tax does not equal total",
                    expected=str(expected_total),
                    actual=str(total),
                )

        if invoice_key:
            stmt = (
                select(Invoice)
                .where(Invoice.invoice_number_norm == invoice_key)
                .order_by(Invoice.created_at.desc())
                .limit(5)
            )
            for invoice in db.scalars(stmt):
                extraction = db.get(Extraction, invoice.current_extraction_id) if invoice.current_extraction_id else None
                if not extraction:
                    continue
                try:
                    data = ExtractionData.model_validate(extraction.data)
                except Exception:
                    continue
                diffs, issues = _compare_sheet_row(row, data)
                if issues:
                    for issue in issues:
                        issue.invoice_id = invoice.id
                        issue.field_path = f"{location}.{issue.field_path}"
                        result.issues.append(issue)
                    result.reconciliations.append(
                        ReconciliationDraft(
                            invoice_id=invoice.id,
                            matched_document_id=document.id,
                            sheet_row_id=row.id,
                            match_type="pdf_sheet",
                            confidence=0.95,
                            diffs=diffs,
                            status="mismatch",
                        )
                    )
                    invoice.status = "needs_review"
                    if invoice.document_id != document.id:
                        source_document = db.get(Document, invoice.document_id)
                        if source_document:
                            source_document.status = "needs_review"
    return result
