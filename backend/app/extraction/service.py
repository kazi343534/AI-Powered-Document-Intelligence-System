from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..schemas import Evidence, ExtractionData, ExtractionLineItem, FieldValue
from ..utils import (
    line_containing,
    money_str,
    normalize_for_match,
    normalize_currency,
    normalize_whitespace,
    parse_date_flexible,
    parse_decimal,
)
from .deterministic import deterministic_extract
from .groq import GroqClient, GroqError, ai_available

logger = logging.getLogger(__name__)

FIELD_KEYS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "supplier_tax_id",
    "customer_name",
    "currency",
    "subtotal",
    "tax",
    "total",
]
MONEY_KEYS = {"subtotal", "tax", "total"}
DATE_KEYS = {"invoice_date"}
TEXT_KEYS = {"invoice_number", "supplier_name", "supplier_tax_id", "customer_name"}


@dataclass
class ExtractionOutcome:
    data: ExtractionData
    source: str
    model: str
    prompt_version: str
    usage: dict | None = None


def _find_quote(
    pages: list[tuple[int, str]], quote: str | None, preferred_page: int | None
) -> tuple[int | None, str | None]:
    if not quote or not quote.strip():
        return None, None
    needle = normalize_whitespace(quote).lower()
    ordered = sorted(pages, key=lambda item: 0 if item[0] == preferred_page else 1)
    for page_number, text in ordered:
        if needle and needle in normalize_whitespace(text).lower():
            return page_number, line_containing(text, quote) or quote
    # Fallback to punctuation-insensitive matching.
    needle_compact = normalize_for_match(quote)
    if needle_compact:
        for page_number, text in ordered:
            if needle_compact in normalize_for_match(text):
                return page_number, line_containing(text, quote) or quote
    return None, None


def _find_value_in_text(
    pages: list[tuple[int, str]], key: str, value: str
) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    needle = normalize_whitespace(value).lower()
    for page_number, text in pages:
        if needle and needle in normalize_whitespace(text).lower():
            return page_number, line_containing(text, value)
    compact = normalize_for_match(value)
    if compact and key in TEXT_KEYS:
        for page_number, text in pages:
            if compact in normalize_for_match(text):
                return page_number, line_containing(text, value)
    if key in DATE_KEYS:
        try:
            target = date.fromisoformat(value)
        except ValueError:
            target = None
        if target:
            for page_number, text in pages:
                for match in re.finditer(
                    r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b",
                    text,
                ):
                    if parse_date_flexible(match.group(0)) == target:
                        return page_number, line_containing(text, match.group(0)) or match.group(0)
    if key in MONEY_KEYS:
        try:
            target = Decimal(value)
        except Exception:
            target = None
        if target is not None:
            for page_number, text in pages:
                for match in re.finditer(r"\d[\d,\s]*\.\d{2}", text):
                    if parse_decimal(match.group(0)) == target:
                        return page_number, line_containing(text, match.group(0)) or match.group(0)
    return None, None


def _normalize_field(key: str, field: FieldValue) -> FieldValue:
    field.evidence = field.evidence or None
    if field.value is None or not str(field.value).strip():
        field.value = None
        field.confidence = 0.0
        return field
    raw = str(field.value).strip()
    if key in MONEY_KEYS:
        amount = parse_decimal(raw)
        if amount is None:
            field.value = None
            field.confidence = 0.0
            field.reason = "amount could not be parsed"
            return field
        field.value = money_str(amount)
    elif key in DATE_KEYS:
        parsed = parse_date_flexible(raw)
        if parsed is None:
            field.value = None
            field.confidence = 0.0
            field.reason = "date could not be parsed"
            return field
        field.value = parsed.isoformat()
    elif key == "currency":
        normalized = normalize_currency(raw)
        if normalized is None:
            field.value = None
            field.confidence = 0.0
            field.reason = "currency could not be recognized"
            return field
        field.value = normalized
    elif key == "invoice_number":
        field.value = normalize_whitespace(raw)[:100] or None
    else:
        field.value = normalize_whitespace(raw)[:255] or None
    if field.value is None:
        field.confidence = 0.0
    return field


def _merge_field(key: str, ai: FieldValue, det: FieldValue) -> FieldValue:
    if ai.value is not None and str(ai.value).strip():
        chosen = ai.model_copy(deep=True)
        if (
            key in MONEY_KEYS | {"invoice_number"}
            and det.value is not None
            and normalize_whitespace(str(det.value)) != normalize_whitespace(str(ai.value))
        ):
            # Conflicting sources are a warning for the reviewer, but keep the
            # AI value; deterministic parsing can pick the wrong column.
            chosen.confidence = max(0.0, chosen.confidence - 0.05)
        return chosen
    if det.value is not None:
        fallback = det.model_copy(deep=True)
        fallback.confidence = min(fallback.confidence, 0.8)
        return fallback
    return FieldValue()


def _normalize_line_items(items: list[ExtractionLineItem]) -> list[ExtractionLineItem]:
    result: list[ExtractionLineItem] = []
    for item in items[:200]:
        item.description = normalize_whitespace(item.description)[:500]
        for key in ("quantity", "unit_price", "amount", "tax_rate"):
            raw = getattr(item, key)
            if raw is None or str(raw).strip() == "":
                setattr(item, key, None)
                continue
            parsed = parse_decimal(raw)
            setattr(item, key, str(parsed) if parsed is not None else None)
        if not item.description and item.amount is None:
            continue
        item.confidence = max(0.0, min(1.0, item.confidence))
        result.append(item)
    return result


def extract_invoice(pages: list[tuple[int, str]]) -> ExtractionOutcome:
    """Extract one logical invoice from a set of (page_number, text) pairs."""
    deterministic = deterministic_extract(pages)
    warnings: list[str] = list(deterministic.warnings)
    source = "fallback"
    model = "deterministic"
    prompt_version = "det-v1"
    usage: dict | None = None

    ai_data: ExtractionData | None = None
    if ai_available():
        try:
            ai_data, usage = GroqClient().extract(pages)
            source = "ai"
            model = GroqClient().model
            prompt_version = "extract_invoice.v1"
        except GroqError as exc:
            logger.warning("Groq extraction unavailable, using deterministic fallback: %s", exc)
            warnings.append("AI extraction failed; deterministic extraction used")
    else:
        warnings.append("AI extraction not configured; deterministic extraction used")

    merged = ExtractionData()
    for key in FIELD_KEYS:
        ai_field = getattr(ai_data, key) if ai_data else FieldValue()
        det_field = getattr(deterministic, key)
        field = _merge_field(key, ai_field, det_field)
        field = _normalize_field(key, field)
        setattr(merged, key, field)

    if ai_data and ai_data.line_items:
        merged.line_items = _normalize_line_items(ai_data.line_items)
    else:
        merged.line_items = deterministic.line_items

    # Evidence verification: every non-null value must be supported by the source.
    for key in FIELD_KEYS:
        field = getattr(merged, key)
        if field.value is None:
            field.confidence = 0.0
            continue
        quote = field.evidence.quote if field.evidence else None
        preferred = field.evidence.page if field.evidence else None
        page_number, found_quote = _find_quote(pages, quote, preferred)
        if page_number is None:
            page_number, found_quote = _find_value_in_text(pages, key, str(field.value))
            if page_number is not None:
                field.confidence = min(field.confidence, 0.7)
                warnings.append(f"Evidence quote not found for {key}; value located in text")
            else:
                field.confidence = min(field.confidence, 0.25)
                warnings.append(f"Unverified field: {key}")
        else:
            field.confidence = max(0.0, min(1.0, field.confidence))
        field.evidence = Evidence(page=page_number, quote=found_quote or quote)

    if source == "ai" and ai_data:
        for key in MONEY_KEYS | {"invoice_number"}:
            ai_value = getattr(ai_data, key).value
            det_value = getattr(deterministic, key).value
            if ai_value and det_value and str(ai_value) != str(det_value):
                warnings.append(f"Sources disagree on {key}; reviewer must verify")

    merged.warnings = list(dict.fromkeys(warnings))
    confidence = {key: round(getattr(merged, key).confidence, 3) for key in FIELD_KEYS}
    merged_confidence = {
        "fields": confidence,
        "line_items": round(
            sum(item.confidence for item in merged.line_items) / len(merged.line_items), 3
        )
        if merged.line_items
        else 0.0,
        "overall": round(
            sum(confidence[key] for key in ("invoice_number", "invoice_date", "supplier_name", "total", "currency"))
            / 5,
            3,
        ),
    }
    return ExtractionOutcome(
        data=merged,
        source=source,
        model=model,
        prompt_version=prompt_version,
        usage=usage,
    )


def extraction_confidence_map(data: ExtractionData) -> dict[str, float]:
    return {key: float(getattr(data, key).confidence) for key in FIELD_KEYS}


def normalize_manual_field(key: str, field: FieldValue) -> FieldValue:
    """Public wrapper used when a reviewer edits a field."""
    return _normalize_field(key, field)
