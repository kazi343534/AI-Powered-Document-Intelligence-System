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
from ..parsers.grouping import (
    detect_invoice_number_evidence,
    detect_supplier,
)

MONEY_RE = re.compile(
    r"(?<![\w])(?:[£$€₹¥]\s*)?-?\(?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,4})?\)?(?:\s*(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY))?",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b"
)
DATE_ONLY_RE = re.compile(
    r"^(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})$"
)
PERCENT_RE = re.compile(r"-?\d+(?:[.,]\d+)?\s*%")

LABELS = {
    "invoice_number": [
        r"invoice\s*(?:no\.?|number|num|#|id)",
        r"inv\s*(?:no\.?|number|num|#)",
        r"bill\s*(?:no\.?|number|num|#)",
    ],
    "invoice_date": [
        r"invoice\s*date",
        r"date\s*of\s*invoice",
        r"bill\s*date",
        r"\bdate\b",
    ],
    "customer_name": [
        r"customer\s*name",
        r"bill\s*to",
        r"buyer\s*name",
        r"client\s*name",
        r"customer",
        r"buyer",
        r"client",
    ],
    "supplier_name": [
        r"supplier\s*name",
        r"vendor\s*name",
        r"seller\s*name",
        r"bill\s*from",
        r"supplier",
        r"vendor",
        r"seller",
    ],
    "subtotal": [r"sub\s*total", r"net\s*amount", r"taxable\s*amount"],
    "tax": [
        r"harmonized\s+sales\s+tax",
        r"sales\s*tax",
        r"value\s+added\s+tax",
        r"tax\s*amount",
        r"\bvat\b",
        r"\bgst\b",
        r"\bhst\b",
        r"\bmwst\b",
        r"\btax\b",
    ],
    "total": [
        r"grand\s*total",
        r"total\s*amount\s*due",
        r"total\s*due",
        r"amount\s*due",
        r"balance\s*due",
        r"(?<!\bsub\b)(?<!\bsub\s)(?<!\bline\b)(?<!\bline\s)\btotal\b",
    ],
    "currency": [r"currency", r"ccy"],
}

CURRENCY_HINTS = [
    "USD",
    "EUR",
    "GBP",
    "INR",
    "JPY",
    "CAD",
    "AUD",
    "CHF",
    "CNY",
    "£",
    "€",
    "₹",
    "¥",
    "$",
]

_QUALIFIER_WORDS = {
    "combined",
    "invoice",
    "grand",
    "total",
    "sub",
    "line",
    "part",
    "order",
    "amount",
    "net",
    "taxable",
    "due",
    "balance",
    "sales",
    "tax",
    "value",
    "added",
    "harmonized",
    "carried",
    "brought",
    "forward",
    "of",
    "the",
    "current",
    "previous",
    "adjusted",
    "schedule",
    "hs",
    "vat",
    "gst",
    "hst",
    "mwst",
    "1",
    "2",
}

_ANY_FIELD_LABEL_RE = re.compile(
    r"^\s*(?:sub\s*total|grand\s*total|total\s*amount|total\s*due|amount\s*due|"
    r"balance\s*due|sales\s*tax|value\s+added\s+tax|tax\s*amount|\bvat\b|\bgst\b|"
    r"\bhst\b|\bmwst\b|\btax\b|currency|ccy|invoice\s*(?:no|number|num|#|id)|"
    r"invoice\s*date|bill\s+to|supplier\s*name|customer\s*name|remittance|"
    r"payment|page\b|audit\s+note|validation)",
    re.IGNORECASE,
)
_TOTAL_HEADER_RE = re.compile(
    r"^\s*(?:sub\s*total|line\s+total|total\s+(?:line|qty|quantity|items?|units?))",
    re.IGNORECASE,
)
_ITEM_STOP_RE = re.compile(
    r"^\s*(?:sub\s*total|sales\s*tax|value\s+added|tax\b|vat\b|total\s+(?:amount|due)|"
    r"amount\s+due|balance\s+due|remittance|payment|audit|validation|page\b|"
    r"batch\s+reference|invoice\b|bill\s+to|supplier|currency)\b",
    re.IGNORECASE,
)
_HEADER_WORDS = {
    "description",
    "qty",
    "quantity",
    "unit",
    "unit price",
    "unit rate",
    "price",
    "amount",
    "line",
    "line total",
    "sku",
    "sku / code",
    "part number",
    "part / service",
    "item",
    "code",
    "rate",
    "total",
    "tax",
    "vat",
    "hs code",
}


def _lines(text: str) -> list[str]:
    return [normalize_whitespace(line) for line in (text or "").splitlines() if line.strip()]


def _label_match(
    line: str, patterns: list[str], anywhere: bool = False
) -> tuple[str, str] | None:
    """Match a field label at the start of a line (or anywhere with qualifiers)."""
    for pattern in patterns:
        if anywhere:
            match = re.search(rf"(?<!\w)(?:{pattern})(?!\w)", line, re.IGNORECASE)
            if not match:
                continue
            prefix = line[: match.start()]
            prefix_words = re.findall(r"[A-Za-z0-9]+", prefix.lower())
            if prefix_words and not all(word in _QUALIFIER_WORDS for word in prefix_words):
                continue
            remainder = line[match.end() :]
        else:
            match = re.match(rf"^\s*(?:{pattern})(?!\w)", line, re.IGNORECASE)
            if not match:
                continue
            remainder = line[match.end() :]
        remainder = re.sub(r"^[\s:#\-–—]+", "", remainder).strip()
        return match.group(0), remainder
    return None


def _strip_percentages(line: str) -> str:
    return PERCENT_RE.sub(" ", line or "")


def _amounts_in(line: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for match in MONEY_RE.finditer(_strip_percentages(line)):
        raw = match.group(0)
        # Skip fragments of dates such as 2026-10-01.
        after = line[match.end() : match.end() + 1]
        if after in {"-", "/", "."}:
            continue
        parsed = parse_decimal(raw)
        if parsed is None:
            continue
        if "." not in raw and "," not in raw and Decimal("1900") <= parsed <= Decimal("2100"):
            # A bare four-digit number is almost always a year, not money.
            continue
        amounts.append(parsed)
    return amounts


def _amount_from_line(line: str | None) -> Decimal | None:
    if not line:
        return None
    amounts = _amounts_in(line)
    return amounts[-1] if amounts else None


def _money_only(line: str) -> bool:
    cleaned = _strip_percentages(normalize_whitespace(line)).strip()
    cleaned = re.sub(
        r"^(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY)\s*", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"\s*(?:USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY)$", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = cleaned.strip("() []")
    return bool(re.fullmatch(r"-?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,4})?", cleaned))


def _currency_fragment(line: str) -> bool:
    cleaned = line.strip("() [] ").strip()
    return bool(cleaned) and normalize_currency(cleaned) is not None and len(cleaned) <= 8


def _money_near(
    lines: list[str], index: int, remainder: str
) -> tuple[Decimal | None, str | None]:
    """Find the monetary value belonging to a label line.

    Handles the common PDF layouts:
        Subtotal (USD)
        12,000.00
    and annotations that sit between the label and the value:
        Total Amount Due (USD)
        [Discrepant vs. 9,180.00]
        9,480.00
    """
    if _money_only(remainder):
        return _amount_from_line(remainder), lines[index]
    remainder_amount = _amount_from_line(remainder)
    if remainder_amount is not None and re.search(
        r"[£$€₹¥]|USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY", remainder, re.IGNORECASE
    ):
        return remainder_amount, lines[index]

    for offset in (1, 2, 3):
        if index + offset >= len(lines):
            break
        candidate = lines[index + offset]
        if _ANY_FIELD_LABEL_RE.match(candidate):
            break
        if _money_only(candidate):
            return _amount_from_line(candidate), candidate
        if re.search(r"[A-Za-z]{3,}", _strip_percentages(candidate)):
            continue
        amount = _amount_from_line(candidate)
        if amount is not None:
            return amount, candidate

    if remainder_amount is not None and len(remainder) <= 60:
        return remainder_amount, lines[index]
    return None, None


def _extract_money_field(lines: list[str], key: str) -> tuple[Decimal | None, str | None]:
    candidates: list[tuple[int, Decimal, str]] = []
    for index, line in enumerate(lines):
        matched = _label_match(line, LABELS[key], anywhere=True)
        if not matched:
            continue
        if key == "total" and _TOTAL_HEADER_RE.match(line):
            continue
        amount, quote = _money_near(lines, index, matched[1])
        if amount is not None and quote:
            candidates.append((index, amount, quote))
    if not candidates:
        return None, None

    if key == "subtotal":
        preferred = [
            item
            for item in candidates
            if not re.search(r"carried|brought|forward|part\s*[12]", item[2], re.IGNORECASE)
        ]
        candidates = preferred or candidates
    amount = candidates[-1][1]
    quote = candidates[-1][2]
    return amount, quote


def _extract_invoice_date(lines: list[str]) -> tuple[date | None, str | None]:
    for index, line in enumerate(lines):
        matched = _label_match(line, LABELS["invoice_date"])
        if not matched:
            continue
        lowered = line.lower()
        if re.match(r"^\s*(?:due|delivery|valid|expiry|expiration)\b", lowered):
            continue
        inline = DATE_RE.search(matched[1])
        if inline:
            parsed = parse_date_flexible(inline.group(0))
            if parsed:
                return parsed, line
        for offset in (1, 2, 3):
            if index + offset >= len(lines):
                break
            candidate = lines[index + offset]
            if _ANY_FIELD_LABEL_RE.match(candidate):
                break
            inline = DATE_RE.search(candidate)
            if inline:
                parsed = parse_date_flexible(inline.group(0))
                if parsed:
                    return parsed, candidate

    for line in lines[:40]:
        lowered = line.lower()
        if re.search(r"\b(?:due|delivery|valid until|expiry|expiration)\b", lowered):
            continue
        inline = DATE_RE.search(line)
        if inline:
            parsed = parse_date_flexible(inline.group(0))
            if parsed:
                return parsed, line
    return None, None


def _first_currency(text: str) -> tuple[str | None, str | None]:
    for match in re.finditer(
        r"\b(USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY)\b|[£$€₹¥]", text or "", re.IGNORECASE
    ):
        raw = match.group(0)
        code = normalize_currency(raw)
        if code:
            return code, line_containing(text or "", raw) or raw
    return None, None


def _quote_for_value(text: str, value: str | None) -> str | None:
    """Find a source line for a value, including names split over lines."""
    if not value:
        return None
    quote = line_containing(text, value)
    if quote:
        return quote
    words = value.split()
    for length in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:length])
        quote = line_containing(text, prefix)
        if quote:
            return quote
    return None


def _extract_currency(lines: list[str], text: str) -> tuple[str | None, str | None]:
    for index, line in enumerate(lines):
        matched = _label_match(line, LABELS["currency"])
        if not matched:
            continue
        value = normalize_currency(matched[1])
        if value:
            return value, line
        for offset in (1, 2):
            if index + offset >= len(lines):
                break
            candidate = lines[index + offset]
            value = normalize_currency(candidate)
            if value:
                return value, candidate
            if _ANY_FIELD_LABEL_RE.match(candidate):
                break
    return _first_currency(text)


def _is_party_heading(remainder: str) -> bool:
    lowered = remainder.lower().strip(" :#-")
    return (
        not lowered
        or lowered
        in {"details", "detail", "information", "info", "address", "name", "number", "id"}
        or remainder.startswith("&")
    )


def _extract_party(lines: list[str], key: str) -> tuple[str | None, str | None]:
    for index, line in enumerate(lines):
        matched = _label_match(line, LABELS[key])
        if not matched:
            continue
        _label, remainder = matched
        if remainder and not _is_party_heading(remainder):
            return remainder[:120], line
        collected: list[str] = []
        for offset in range(1, 5):
            if index + offset >= len(lines) or len(collected) >= 2:
                break
            candidate = lines[index + offset]
            if _ANY_FIELD_LABEL_RE.match(candidate):
                break
            if re.fullmatch(r"[\d\W]+", candidate):
                break
            collected.append(candidate)
        if collected:
            return normalize_whitespace(" ".join(collected))[:120], line
    return None, None


def _is_header_line(line: str) -> bool:
    lowered = normalize_whitespace(line).lower().strip(" :")
    if lowered in _HEADER_WORDS:
        return True
    return bool(
        re.match(
            r"^(?:description|qty|quantity|unit\s+price|unit\s+rate|price|amount|"
            r"line(?:\s+total)?|sku|part\s+number|part\s*/\s*service|item|code|rate)\b",
            lowered,
        )
    )


def _is_number_line(line: str) -> bool:
    cleaned = normalize_whitespace(line)
    return bool(re.fullmatch(r"-?\d{1,5}(?:[.,]\d{1,2})?", cleaned)) or _money_only(cleaned)


def _join_description(parts: list[str]) -> str:
    result = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not result:
            result = part
        elif result.endswith("-") and part[:1].isalnum():
            result += part
        else:
            result += " " + part
    return normalize_whitespace(result)


def _line_item_confidence(quantity, unit_price, amount) -> float:
    if quantity is None or unit_price is None or amount is None:
        return 0.55
    expected = quantity * unit_price
    tolerance = max(Decimal("0.05"), abs(amount) * Decimal("0.02"))
    return 0.72 if abs(expected - amount) <= tolerance else 0.6


def _parse_line_items(text: str) -> list[ExtractionLineItem]:
    lines = _lines(text)
    found: list[tuple[int, ExtractionLineItem]] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()

    def _add(index: int, description: str, qty, unit, amount) -> None:
        key = (
            normalize_whitespace(description).lower(),
            str(qty) if qty is not None else None,
            str(unit) if unit is not None else None,
            str(amount) if amount is not None else None,
        )
        if not description or len(description) < 3 or key in seen:
            return
        seen.add(key)
        found.append(
            (
                index,
                ExtractionLineItem(
                    description=description[:500],
                    quantity=str(qty) if qty is not None else None,
                    unit_price=str(unit) if unit is not None else None,
                    amount=str(amount) if amount is not None else None,
                    confidence=_line_item_confidence(qty, unit, amount),
                ),
            )
        )

    # Layout A: one row per line (description, qty, unit price, amount).
    single_re = re.compile(
        r"^(?P<desc>[A-Za-z][A-Za-z0-9 ,&()/._'#-]{2,80}?)\s+"
        r"(?P<qty>-?\d{1,5}(?:[.,]\d{1,2})?)\s+"
        r"(?P<unit>\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,4})?)\s+"
        r"(?P<amount>-?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,4})?)\s*$"
    )
    for index, cleaned in enumerate(lines):
        if len(cleaned) < 8 or _ITEM_STOP_RE.match(cleaned):
            continue
        match = single_re.match(cleaned)
        if not match:
            continue
        qty = parse_decimal(match.group("qty"))
        unit = parse_decimal(match.group("unit"))
        amount = parse_decimal(match.group("amount"))
        if qty is None or unit is None or amount is None:
            continue
        _add(index, match.group("desc").strip(), qty, unit, amount)

    # Layout B: columns are emitted as separate lines (very common for PDF text
    # extraction). Accumulate description lines until the qty/unit/amount trio.
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_header_line(line) or _currency_fragment(line) or _ITEM_STOP_RE.match(line):
            index += 1
            continue
        if _money_only(line) or DATE_ONLY_RE.match(line):
            index += 1
            continue

        start = index
        cursor = index
        if re.fullmatch(r"-?\d{1,5}", line):
            # A leading line number belongs to the row, not to the quantity.
            cursor += 1
        description_parts: list[str] = []
        while cursor < len(lines):
            candidate = lines[cursor]
            if _is_number_line(candidate):
                break
            if _is_header_line(candidate) or _currency_fragment(candidate):
                description_parts = []
                cursor += 1
                continue
            if _ITEM_STOP_RE.match(candidate):
                break
            description_parts.append(candidate)
            cursor += 1
            if len(description_parts) > 8:
                description_parts = description_parts[-4:]

        if not description_parts or cursor + 2 >= len(lines):
            index += 1
            continue

        qty = parse_decimal(lines[cursor])
        unit = parse_decimal(lines[cursor + 1]) if _money_only(lines[cursor + 1]) else None
        amount = (
            parse_decimal(lines[cursor + 2]) if _money_only(lines[cursor + 2]) else None
        )
        if qty is None or unit is None or amount is None:
            index += 1
            continue
        _add(start, _join_description(description_parts), qty, unit, amount)
        index = cursor + 3

    found.sort(key=lambda item: item[0])
    return [item for _index, item in found][:200]


def deterministic_extract(pages: list[tuple[int, str]]) -> ExtractionData:
    """Best-effort extraction without an LLM.

    Confidence values reflect how the value was found: labelled/columnar values
    with a supporting source line score higher than heuristic fallbacks. This
    keeps clean digital and high-quality OCR invoices from being pushed into
    manual review purely because a fixed prior was used.
    """
    full_text = "\n".join(text for _page, text in pages)
    lines = _lines(full_text)
    data = ExtractionData()

    def page_for(quote: str | None) -> int:
        if quote:
            needle = normalize_whitespace(quote).lower()
            for page_number, text in pages:
                if needle and needle in normalize_whitespace(text).lower():
                    return page_number
        return pages[0][0] if pages else 1

    raw_number, number_quote = detect_invoice_number_evidence(full_text)
    if raw_number:
        data.invoice_number = FieldValue(
            value=raw_number[:80],
            confidence=0.92 if number_quote else 0.7,
            evidence=Evidence(page=page_for(number_quote), quote=number_quote) if number_quote else None,
        )

    parsed_date, date_quote = _extract_invoice_date(lines)
    if parsed_date:
        data.invoice_date = FieldValue(
            value=parsed_date.isoformat(),
            confidence=0.9 if date_quote else 0.65,
            evidence=Evidence(page=page_for(date_quote), quote=date_quote) if date_quote else None,
        )

    supplier = detect_supplier(full_text)
    if supplier:
        quote = _quote_for_value(full_text, supplier)
        labelled = any(
            re.match(
                r"^\s*(?:supplier|vendor|seller|bill\s*from)\s*(?:name)?\s*[:\-]?",
                line,
                re.IGNORECASE,
            )
            for line in lines
        )
        data.supplier_name = FieldValue(
            value=supplier,
            confidence=0.88 if labelled else 0.85,
            evidence=Evidence(page=page_for(quote), quote=quote) if quote else None,
        )

    customer, customer_quote = _extract_party(lines, "customer_name")
    if customer:
        data.customer_name = FieldValue(
            value=customer,
            confidence=0.87 if customer_quote else 0.7,
            evidence=Evidence(page=page_for(customer_quote), quote=customer_quote)
            if customer_quote
            else None,
        )

    currency, currency_quote = _extract_currency(lines, full_text)
    if currency:
        data.currency = FieldValue(
            value=currency,
            confidence=0.88 if currency_quote else 0.8,
            evidence=Evidence(page=page_for(currency_quote), quote=currency_quote)
            if currency_quote
            else None,
        )

    for key in ("subtotal", "tax", "total"):
        amount, quote = _extract_money_field(lines, key)
        if amount is not None:
            setattr(
                data,
                key,
                FieldValue(
                    value=money_str(amount),
                    confidence=0.9 if quote else 0.8,
                    evidence=Evidence(page=page_for(quote), quote=quote) if quote else None,
                ),
            )

    data.line_items = _parse_line_items(full_text)
    return data
