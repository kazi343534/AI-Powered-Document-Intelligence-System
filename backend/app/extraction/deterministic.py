from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..schemas import Evidence, ExtractionData, ExtractionLineItem, FieldValue
from ..utils import (
    line_containing,
    money_str,
    normalize_currency,
    normalize_whitespace,
    parse_date_flexible,
    parse_decimal,
)
from ..parsers.grouping import detect_invoice_number, detect_supplier

MONEY_RE = re.compile(
    r"(?<![\w])(?:[£$€₹¥]\s*)?-?\(?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,4})?\)?(?:\s*(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY))?",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b")

LABELS = {
    "invoice_number": [
        r"invoice\s*(?:no\.?|number|num|#|id)",
        r"inv\s*(?:no\.?|number|#)",
        r"bill\s*(?:no\.?|number)",
    ],
    "invoice_date": [r"invoice\s*date", r"date\s*of\s*invoice", r"bill\s*date", r"\bdate\b"],
    "customer_name": [r"bill\s*to", r"customer", r"buyer", r"client"],
    "supplier_name": [r"supplier", r"vendor", r"seller", r"bill\s*from", r"from"],
    "subtotal": [r"sub\s*total", r"net\s*amount", r"taxable\s*amount"],
    "tax": [r"\btax\b", r"\bvat\b", r"\bgst\b", r"sales\s*tax"],
    "total": [r"grand\s*total", r"total\s*due", r"amount\s*due", r"balance\s*due", r"\btotal\b"],
    "currency": [r"currency", r"ccy"],
}

CURRENCY_HINTS = ["USD", "EUR", "GBP", "INR", "JPY", "CAD", "AUD", "CHF", "CNY", "£", "€", "₹", "¥", "$"]


def _find_label_line(text: str, patterns: list[str]) -> str | None:
    for line in (text or "").splitlines():
        candidate = normalize_whitespace(line)
        if not candidate:
            continue
        for pattern in patterns:
            if re.search(pattern, candidate, re.IGNORECASE):
                return line.strip()
    return None


def _line_value(text: str, patterns: list[str]) -> tuple[str | None, str | None]:
    for line in (text or "").splitlines():
        candidate = normalize_whitespace(line)
        if not candidate:
            continue
        if any(re.search(pattern, candidate, re.IGNORECASE) for pattern in patterns):
            # Remove the label portion, then take the first meaningful value.
            remainder = candidate
            for pattern in patterns:
                remainder = re.sub(pattern, " ", remainder, count=1, flags=re.IGNORECASE)
            remainder = re.sub(r"^[\s:#.\-]+", "", remainder).strip()
            if remainder:
                return remainder[:200], line.strip()
    return None, None


def _amount_from_line(line: str | None) -> Decimal | None:
    if not line:
        return None
    amounts: list[Decimal] = []
    for match in MONEY_RE.finditer(line):
        parsed = parse_decimal(match.group(0))
        if parsed is not None:
            amounts.append(parsed)
    if not amounts:
        return None
    # The rightmost amount is normally the monetary value after labels.
    return amounts[-1]


def _parse_amount_field(text: str, key: str) -> tuple[Decimal | None, str | None, float]:
    labels = LABELS[key]
    candidates: list[tuple[Decimal, str]] = []
    for line in (text or "").splitlines():
        cleaned = normalize_whitespace(line)
        if not cleaned:
            continue
        if not any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in labels):
            continue
        if key == "total" and re.search(r"sub\s*total", cleaned, re.IGNORECASE):
            continue
        if key == "tax" and re.search(r"(?:sub\s*total|total)", cleaned, re.IGNORECASE):
            continue
        amount = _amount_from_line(cleaned)
        if amount is not None:
            candidates.append((amount, line.strip()))
    if not candidates:
        return None, None, 0.0
    # Prefer the last labelled match (usually the final payable total).
    amount, quote = candidates[-1]
    return amount, quote, 0.86


def _parse_line_items(text: str) -> list[ExtractionLineItem]:
    items: list[ExtractionLineItem] = []
    item_re = re.compile(
        r"^(?P<desc>[A-Za-z][A-Za-z0-9 ,&()/._'#-]{2,80}?)\s+"
        r"(?P<qty>\d{1,5}(?:[.,]\d{1,2})?)\s+"
        r"(?P<unit>\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,4})?)\s+"
        r"(?P<amount>\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,4})?)\s*$"
    )
    for line in (text or "").splitlines():
        cleaned = normalize_whitespace(line)
        if len(cleaned) < 8 or re.search(r"\b(sub\s*total|tax|vat|total)\b", cleaned, re.I):
            continue
        match = item_re.match(cleaned)
        if not match:
            continue
        qty = parse_decimal(match.group("qty"))
        unit = parse_decimal(match.group("unit"))
        amount = parse_decimal(match.group("amount"))
        if qty is None or unit is None or amount is None:
            continue
        if abs(qty * unit - amount) > max(Decimal("0.05"), abs(amount) * Decimal("0.02")):
            continue
        items.append(
            ExtractionLineItem(
                description=match.group("desc").strip(),
                quantity=str(qty),
                unit_price=str(unit),
                amount=str(amount),
                confidence=0.55,
            )
        )
        if len(items) >= 200:
            break
    return items


def deterministic_extract(pages: list[tuple[int, str]]) -> ExtractionData:
    """Best-effort extraction without an LLM. Conservative by design."""
    full_text = "\n".join(text for _page, text in pages)
    data = ExtractionData()

    number = detect_invoice_number(full_text)
    if number:
        # Keep a display version from the label line where possible.
        raw, quote = _line_value(full_text, LABELS["invoice_number"])
        display = raw
        if display:
            display = re.split(r"\s{2,}|\s+(?:date|invoice\s*date|due\s*date)\b", display, 1)[0]
            display = display.strip(" :#-")
        if not display:
            display = number
        data.invoice_number = FieldValue(
            value=display[:80],
            confidence=0.86 if quote else 0.7,
            evidence=Evidence(page=1, quote=quote) if quote else None,
        )

    date_raw, date_quote = _line_value(full_text, LABELS["invoice_date"])
    parsed_date: date | None = None
    if date_raw:
        match = DATE_RE.search(date_raw)
        parsed_date = parse_date_flexible(match.group(0) if match else date_raw)
    if not parsed_date:
        match = DATE_RE.search(full_text)
        if match:
            parsed_date = parse_date_flexible(match.group(0))
            date_quote = match.group(0)
    if parsed_date:
        data.invoice_date = FieldValue(
            value=parsed_date.isoformat(),
            confidence=0.84 if date_quote else 0.65,
            evidence=Evidence(page=1, quote=date_quote) if date_quote else None,
        )

    supplier = detect_supplier(full_text)
    if supplier:
        quote = line_containing(full_text, supplier)
        data.supplier_name = FieldValue(
            value=supplier,
            confidence=0.7 if quote else 0.55,
            evidence=Evidence(page=1, quote=quote) if quote else None,
        )

    customer_raw, customer_quote = _line_value(full_text, LABELS["customer_name"])
    if customer_raw:
        customer = normalize_whitespace(customer_raw).strip(" :-#")
        if customer and len(customer) <= 120:
            data.customer_name = FieldValue(
                value=customer,
                confidence=0.8,
                evidence=Evidence(page=1, quote=customer_quote) if customer_quote else None,
            )

    currency = normalize_currency(None, full_text)
    if currency:
        hint = next((hint for hint in CURRENCY_HINTS if hint in full_text), currency)
        data.currency = FieldValue(
            value=currency,
            confidence=0.8,
            evidence=Evidence(page=1, quote=hint) if hint else None,
        )

    for key, setter in (
        ("subtotal", "subtotal"),
        ("tax", "tax"),
        ("total", "total"),
    ):
        amount, quote, confidence = _parse_amount_field(full_text, key)
        if amount is not None:
            setattr(
                data,
                setter,
                FieldValue(
                    value=money_str(amount),
                    confidence=confidence,
                    evidence=Evidence(page=1, quote=quote) if quote else None,
                ),
            )

    data.line_items = _parse_line_items(full_text)
    return data
