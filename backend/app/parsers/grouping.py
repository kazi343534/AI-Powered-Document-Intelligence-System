from __future__ import annotations

import re
from dataclasses import dataclass

from ..utils import normalize_invoice_number, normalize_supplier, normalize_whitespace

INVOICE_NUMBER_RE = re.compile(
    r"(?:invoice|inv|bill)[ \t]*(?:no\.?|number|num|#|id)?[ \t]*[:\-][ \t]*"
    r"([A-Z0-9][A-Z0-9][A-Z0-9\-\/\._]{1,30})"
    r"|(?:invoice|inv|bill)[ \t]*(?:no\.?|number|num|#|id)[ \t]+"
    r"([A-Z0-9][A-Z0-9][A-Z0-9\-\/\._]{1,30})",
    re.IGNORECASE,
)
SUPPLIER_RE = re.compile(
    r"(?:supplier|vendor|seller|bill\s*from|from)\s*[:\-]\s*([^\n\r]{2,80})",
    re.IGNORECASE,
)
INVOICE_TITLE_RE = re.compile(r"\b(invoice|tax invoice|commercial invoice)\b", re.IGNORECASE)
CONTINUATION_RE = re.compile(
    r"(page\s+\d+\s+(?:of|/)\s+\d+|continued|continuation)", re.IGNORECASE
)


@dataclass
class InvoiceGroup:
    page_start: int
    page_end: int
    invoice_number: str | None
    supplier_name: str | None
    confidence: float


def detect_invoice_number(text: str) -> str | None:
    head = "\n".join((text or "").splitlines()[:45])
    match = INVOICE_NUMBER_RE.search(head)
    if not match:
        return None
    candidate = (match.group(1) or match.group(2) or "").strip().rstrip(".,;:")
    if candidate.lower() in {"number", "no", "date", "total", "invoice"}:
        return None
    return normalize_invoice_number(candidate)


def detect_supplier(text: str) -> str | None:
    head = "\n".join((text or "").splitlines()[:25])
    match = SUPPLIER_RE.search(head)
    if match:
        candidate = normalize_whitespace(match.group(1))
        if candidate and len(candidate) < 80:
            return candidate
    lines = [normalize_whitespace(line) for line in (text or "").splitlines()[:12]]
    for line in lines:
        if (
            len(line) >= 3
            and not INVOICE_TITLE_RE.search(line)
            and not re.search(r"\b(invoice|date|page|no\.?)\b", line, re.IGNORECASE)
            and not re.fullmatch(r"[\d\W]+", line)
        ):
            return line[:80]
    return None


def group_invoice_pages(pages: list) -> list[InvoiceGroup]:
    """Group multi-page PDFs into logical invoice units.

    Pages with a new invoice number start a new group. Pages without one attach
    to the current group (continuation pages), which is the common case for
    multi-page invoices. If no invoice number is found anywhere, the file is
    treated as one logical invoice.
    """
    if not pages:
        return []

    page_meta: list[tuple[str | None, str | None]] = []
    for page in pages:
        text = getattr(page, "text", "") or ""
        number = detect_invoice_number(text)
        supplier = detect_supplier(text)
        page_meta.append((number, supplier))

    groups: list[InvoiceGroup] = []
    current: InvoiceGroup | None = None
    current_number: str | None = None
    current_supplier: str | None = None
    saw_any_number = any(number for number, _ in page_meta)

    for page, (number, supplier) in zip(pages, page_meta, strict=False):
        is_new = False
        if current is None:
            is_new = True
        elif number and current_number and number != current_number:
            is_new = True
        elif number and not current_number:
            # Upgrade a previously anonymous group (e.g. a cover page followed
            # by the invoice) rather than creating a spurious split.
            pass
        elif page.page_number == 1:
            is_new = True

        if is_new:
            if current is not None:
                groups.append(current)
            current = InvoiceGroup(
                page_start=page.page_number,
                page_end=page.page_number,
                invoice_number=number,
                supplier_name=supplier,
                confidence=0.0,
            )
            current_number = number
            current_supplier = supplier
        else:
            assert current is not None
            current.page_end = page.page_number
            if not current.invoice_number and number:
                current.invoice_number = number
                current_number = number
            if not current.supplier_name and supplier:
                current.supplier_name = supplier
                current_supplier = supplier

    if current is not None:
        groups.append(current)

    for group in groups:
        score = 0.55
        if group.invoice_number:
            score += 0.3
        if group.supplier_name:
            score += 0.1
        if saw_any_number:
            score += 0.05
        group.confidence = min(score, 0.98)

    # If every page contains the same number but grouping created multiple
    # groups due to a supplier change, merge adjacent groups with equal numbers.
    merged: list[InvoiceGroup] = []
    for group in groups:
        if (
            merged
            and group.invoice_number
            and merged[-1].invoice_number == group.invoice_number
            and merged[-1].page_end + 1 == group.page_start
        ):
            merged[-1].page_end = group.page_end
        else:
            merged.append(group)
    return merged
