from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser

CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "£": "GBP",
    "€": "EUR",
    "₹": "INR",
    "¥": "JPY",
    "₩": "KRW",
    "C$": "CAD",
    "A$": "AUD",
    "CHF": "CHF",
}
CURRENCY_CODES = {
    "USD",
    "EUR",
    "GBP",
    "INR",
    "JPY",
    "CNY",
    "CAD",
    "AUD",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "SGD",
    "HKD",
    "AED",
    "SAR",
    "ZAR",
    "BRL",
    "MXN",
    "NZD",
    "PKR",
    "BDT",
}

# Active ISO 4217 currency codes, excluding fund, metal, and testing codes.
ISO_4217_CODES = CURRENCY_CODES | {
    "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AWG", "AZN", "BAM", "BBD",
    "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BSD", "BTN", "BWP", "BYN",
    "BZD", "CDF", "CLP", "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DOP",
    "DZD", "EGP", "ERN", "ETB", "FJD", "FKP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HNL", "HTG", "HUF", "IDR", "ILS", "IQD", "IRR",
    "ISK", "JMD", "JOD", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD",
    "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL",
    "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MYR",
    "MZN", "NAD", "NGN", "NIO", "NPR", "OMR", "PAB", "PEN", "PGK", "PHP",
    "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF", "SBD", "SCR", "SDG",
    "SHP", "SLE", "SLL", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL",
    "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH",
    "UGX", "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF",
    "XPF", "YER", "ZMW", "ZWL",
}

INVOICE_PREFIXES = re.compile(
    r"^(?:invoice|inv|bill|doc|document)\s*(?:no|number|num|#|id)?\s*[:#\-]?\s*",
    re.IGNORECASE,
)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_for_match(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def normalize_invoice_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = INVOICE_PREFIXES.sub("", value.strip())
    cleaned = re.sub(r"[^A-Za-z0-9]", "", cleaned).upper()
    return cleaned or None


def normalize_supplier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^a-z0-9 ]", " ", value.lower())
    cleaned = re.sub(
        r"\b(?:ltd|limited|inc|incorporated|llc|gmbh|plc|co|company|corp|corporation)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    # Resolve separators: whichever appears last is the decimal separator.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    if negative:
        result = -result
    return result


def money_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.quantize(Decimal("0.01"))
    return f"{normalized:.2f}"


def parse_date_flexible(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", text, flags=re.IGNORECASE)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed.year < 1980 or parsed.year > 2100:
        return None
    return parsed.date()


def normalize_currency(value: str | None, text: str = "") -> str | None:
    combined = f"{value or ''} {text}"
    for code in CURRENCY_CODES:
        if re.search(rf"\b{code}\b", combined, re.IGNORECASE):
            return code
    for symbol in sorted(CURRENCY_SYMBOLS, key=len, reverse=True):
        if symbol in combined and (value is None or symbol in (value or "")):
            return CURRENCY_SYMBOLS[symbol]
    return None


def normalize_currency_cell(value: Any) -> tuple[str | None, bool]:
    """Normalize one spreadsheet currency cell without guessing from other rows.

    Returns ``(currency, valid)``. Recognized ISO codes/symbols are canonicalized;
    an explicit unknown value is preserved and reported as invalid so callers can
    surface a warning instead of silently coercing it to USD.
    """
    raw = normalize_whitespace(str(value or ""))
    if not raw:
        return None, True
    upper = raw.upper()
    if upper in ISO_4217_CODES:
        return upper, True
    mapped = normalize_currency(raw, "")
    if mapped:
        return mapped, True
    return raw[:12], False


def currency_symbol(currency: str | None) -> str:
    mapping = {v: k for k, v in CURRENCY_SYMBOLS.items() if k not in {"US$", "C$", "A$"}}
    return mapping.get(currency or "", "")


def line_containing(text: str, needle: str) -> str | None:
    if not needle:
        return None
    needle_norm = normalize_whitespace(needle).lower()
    for line in (text or "").splitlines():
        if needle_norm and needle_norm in normalize_whitespace(line).lower():
            return line.strip()
    return None


def snippet(text: str, start: int, end: int, radius: int = 90) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return normalize_whitespace(text[left:right])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"
