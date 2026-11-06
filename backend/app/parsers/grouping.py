from __future__ import annotations

import re
from dataclasses import dataclass, field

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
INVOICE_TITLE_ONLY_RE = re.compile(
    r"^\s*(?:(?:commercial|tax|sales)\s+)?invoice\s*$", re.IGNORECASE
)
CONTINUATION_RE = re.compile(
    r"(page\s+\d+\s+(?:of|/)\s+\d+|continued|continuation)", re.IGNORECASE
)

# A page (or a line) that explicitly starts a new invoice record. Test suites and
# some ERP exports use headings such as
# "COMMERCIAL TAX INVOICE — RECORD 03"; real invoices commonly use
# "Invoice No: ..." or a label line followed by the value.
RECORD_HEADING_RE = re.compile(
    r"^\s*(?:commercial\s+|tax\s+|sales\s+)*invoice\s*[—–-]+\s*record\s*#?\s*"
    r"([A-Z0-9][A-Z0-9\-\/\._]{0,20})",
    re.IGNORECASE,
)
NON_INVOICE_HEADING_RE = re.compile(
    r"^\s*(?:internal\s+procurement|labeled\s+ground|ground\s*[- ]?truth|appendix|annex|"
    r"terms\s+and\s+conditions|notes?\s+to\s+the\s+financial)"
    r"\b",
    re.IGNORECASE,
)
INVOICE_NUMBER_LABEL_RE = re.compile(
    r"^\s*(?:invoice|inv|bill)\s*(?:no\.?|number|num|#|id)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
INLINE_INVOICE_NUMBER_RE = re.compile(
    r"^\s*(?:invoice|inv|bill)\s*(?:no\.?|number|num|#|id)\s*[:\-]?\s+"
    r"([A-Za-z0-9][A-Za-z0-9\-\/\._#]{1,40})",
    re.IGNORECASE,
)
INVOICE_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-\/\._#]{1,40}$")
PLACEHOLDER_RE = re.compile(
    r"^[\[\](){}<>\s]*(?:not\s+provided|not\s+available|n/?a|blank|omitted|unspecified|"
    r"missing|none|unknown|tbd)[^A-Za-z0-9]*$",
    re.IGNORECASE,
)


@dataclass
class InvoiceGroup:
    page_start: int
    page_end: int
    invoice_number: str | None
    supplier_name: str | None
    confidence: float
    # Text belonging to this logical invoice. When boundaries fall in the middle
    # of a page this is a subset of the page text, which prevents values from the
    # previous/next invoice on the same page leaking into the extraction.
    page_texts: list[tuple[int, str]] = field(default_factory=list)


def _clean_invoice_token(value: str | None) -> str | None:
    """Return the first plausible invoice-number token on a line."""
    candidate = normalize_whitespace(value).strip(" :#-–—")
    if not candidate or PLACEHOLDER_RE.match(candidate):
        return None
    match = re.match(r"([A-Za-z0-9][A-Za-z0-9\-\/\._#]{1,40})(?:\s|$)", candidate)
    if not match:
        return None
    token = match.group(1).rstrip(".,;:")
    if not INVOICE_ID_TOKEN_RE.match(token):
        return None
    if not re.search(r"\d", token):
        return None
    if token.lower() in {
        "number",
        "no",
        "date",
        "total",
        "invoice",
        "reference",
        "details",
        "amount",
    }:
        return None
    return token


def detect_invoice_number_evidence(text: str) -> tuple[str | None, str | None]:
    """Find the invoice number and the line that supplied it.

    The detector is deliberately anchored to the start of a line (or to a label
    line whose value is on the following line). Searching anywhere in a line
    picks up prose such as "Reference Invoice Number INV-123 on all wire
    advice" and numeric fragments such as routing/account numbers.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]

    # 1) "Invoice Number" label line followed by its value, e.g.
    #       Invoice Number
    #       INV-2026-00103
    for index, line in enumerate(lines):
        if not INVOICE_NUMBER_LABEL_RE.match(line):
            continue
        for offset in (1, 2, 3):
            if index + offset >= len(lines):
                break
            candidate = lines[index + offset]
            token = _clean_invoice_token(candidate)
            if token:
                return token, candidate
            if not PLACEHOLDER_RE.match(candidate):
                # A non-placeholder, non-token line means this label does not
                # carry a usable value; keep looking at later labels.
                break

    # 2) Anchored inline label, e.g. "Invoice No: INV-2024-0087".
    for line in lines:
        match = INLINE_INVOICE_NUMBER_RE.match(line)
        if match:
            token = _clean_invoice_token(match.group(1))
            if token:
                return token, line

    # 3) Conservative fallback for formats not covered above.
    for match in INVOICE_NUMBER_RE.finditer(text or ""):
        token = _clean_invoice_token(match.group(1) or match.group(2))
        if token:
            return token, line_containing_safe(text, token)

    return None, None


def line_containing_safe(text: str, needle: str) -> str | None:
    from ..utils import line_containing

    return line_containing(text, needle)


def detect_invoice_number(text: str) -> str | None:
    raw, _quote = detect_invoice_number_evidence(text)
    return normalize_invoice_number(raw)


_STOP_LABEL_RE = re.compile(
    r"^\s*(?:supplier|vendor|seller|customer|buyer|client|bill\s+to|bill\s+from|"
    r"tax\b|vat\b|gst\b|hst\b|invoice|inv\b|bill\b|date\b|due\s+date|currency|ccy|"
    r"purchase|po\b|billing|shipping|delivery|port\b|payment|itemized|line\b|sku\b|"
    r"part\s+number|description|qty\b|quantity|unit\s+price|unit\s+rate|amount|"
    r"sub\s*total|total|sales\s+tax|remittance|audit\s+note|validation|page\b|"
    r"batch\s+reference|document\s+type|submission|inventory|ledger|record\b)",
    re.IGNORECASE,
)
_HEADING_REMAINDERS = {
    "details",
    "detail",
    "information",
    "info",
    "address",
    "name",
    "number",
    "id",
}


def _label_line(line: str) -> tuple[str, str] | None:
    """Match a supplier/customer label at the start of a line.

    Returns (matched label, remainder). Headings such as "Supplier Details" or
    "Customer & Billing Details" are rejected.
    """
    patterns = (
        r"supplier\s*name",
        r"vendor\s*name",
        r"seller\s*name",
        r"bill\s*from",
        r"supplier",
        r"vendor",
        r"seller",
        r"customer\s*name",
        r"bill\s*to",
        r"buyer\s*name",
        r"client\s*name",
        r"customer",
        r"buyer",
        r"client",
    )
    for pattern in patterns:
        match = re.match(rf"^\s*(?:{pattern})(?!\w)", line, re.IGNORECASE)
        if not match:
            continue
        remainder = line[match.end() :]
        remainder = re.sub(r"^[\s:#\-–—]+", "", remainder).strip()
        lowered = remainder.lower().strip()
        if lowered in _HEADING_REMAINDERS or remainder.startswith("&"):
            return None
        return match.group(0).strip(), remainder
    return None


def _gather_name(lines: list[str], index: int) -> str | None:
    collected: list[str] = []
    for offset in range(1, 5):
        if index + offset >= len(lines) or len(collected) >= 2:
            break
        candidate = normalize_whitespace(lines[index + offset])
        if not candidate:
            continue
        if _STOP_LABEL_RE.match(candidate):
            break
        if re.fullmatch(r"[\d\W]+", candidate):
            break
        collected.append(candidate)
    if not collected:
        return None
    return normalize_whitespace(" ".join(collected))[:80] or None


def detect_supplier(text: str) -> str | None:
    lines = [normalize_whitespace(line) for line in (text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        matched = _label_line(line)
        if not matched or not re.search(r"supplier|vendor|seller|bill\s*from", matched[0], re.I):
            continue
        _label, remainder = matched
        if remainder:
            return remainder[:80]
        gathered = _gather_name(lines, index)
        if gathered:
            return gathered

    head = "\n".join(lines[:25])
    match = SUPPLIER_RE.search(head)
    if match:
        candidate = normalize_whitespace(match.group(1))
        if candidate and len(candidate) < 80:
            return candidate

    for line in lines[:12]:
        if (
            len(line) >= 3
            and not INVOICE_TITLE_RE.search(line)
            and not _STOP_LABEL_RE.match(line)
            and not re.search(r"\b(invoice|date|page|no\.?)\b", line, re.IGNORECASE)
            and not re.fullmatch(r"[\d\W]+", line)
        ):
            return line[:80]
    return None


def _invoice_number_at(lines: list[str], index: int) -> str | None:
    line = lines[index]
    if INVOICE_NUMBER_LABEL_RE.match(line):
        for offset in (1, 2, 3):
            if index + offset >= len(lines):
                break
            token = _clean_invoice_token(lines[index + offset])
            if token:
                return normalize_invoice_number(token)
            if not PLACEHOLDER_RE.match(lines[index + offset]):
                break
        return None
    match = INLINE_INVOICE_NUMBER_RE.match(line)
    if match:
        token = _clean_invoice_token(match.group(1))
        if token:
            return normalize_invoice_number(token)
    return None


def _identity_at(lines: list[str], index: int) -> tuple[str, str] | None:
    """Return ("record"|"number", identity) for a line starting a new invoice."""
    line = lines[index]
    match = RECORD_HEADING_RE.match(line)
    if match:
        return "record", match.group(1).upper()
    number = _invoice_number_at(lines, index)
    if number:
        return "number", number
    return None


def _build_groups(pages: list) -> list[InvoiceGroup]:
    lines = [
        (page.page_number, line.strip())
        for page in pages
        for line in (getattr(page, "text", "") or "").splitlines()
    ]
    text_lines = [line for _page, line in lines]
    boundaries: list[tuple[int, str, str]] = []
    stop_index = len(lines)
    for index, line in enumerate(text_lines):
        if NON_INVOICE_HEADING_RE.match(line):
            if boundaries:
                stop_index = index
                break
            continue
        identity = _identity_at(text_lines, index)
        if identity:
            boundaries.append((index, identity[0], identity[1]))

    if not boundaries:
        return []

    boundary_map = {index: (kind, value) for index, kind, value in boundaries}

    # An "INVOICE" title line directly above the invoice-number label belongs
    # to the new invoice, not to the end of the previous one. Move the boundary
    # back over it so page_texts do not leak across invoices.
    for index in sorted(boundary_map):
        start = index
        while start - 1 >= 0 and start - 1 not in boundary_map:
            if not INVOICE_TITLE_ONLY_RE.match(text_lines[start - 1]):
                break
            start -= 1
            if index - start >= 2:
                break
        if start != index:
            kind, value = boundary_map.pop(index)
            boundary_map[start] = (kind, value)

    segments: list[dict] = []
    current: dict | None = None
    prefix: list[int] = []
    first_boundary = min(boundary_map) if boundary_map else stop_index
    if first_boundary > 0:
        prefix = list(range(first_boundary))

    for index, (page_number, line) in enumerate(lines):
        if index >= stop_index:
            break
        if index in boundary_map:
            kind, value = boundary_map[index]
            start_new = False
            if current is None:
                start_new = True
            elif kind == "number":
                if current["number"] is None:
                    current["number"] = value
                elif current["number"] != value:
                    start_new = True
            elif kind == "record":
                if current["record"] is None:
                    # The first heading of this invoice after a cover page.
                    current["record"] = value
                elif current["record"] != value:
                    start_new = True
            if start_new:
                if current is not None:
                    segments.append(current)
                current = {
                    "record": value if kind == "record" else None,
                    "number": value if kind == "number" else None,
                    "lines": prefix if not segments else [],
                }
                prefix = []
        if current is not None:
            current["lines"].append(index)

    if current is not None:
        segments.append(current)

    if not segments:
        return []

    groups: list[InvoiceGroup] = []
    for segment in segments:
        segment_lines = [lines[index] for index in segment["lines"]]
        if not segment_lines:
            continue
        page_map: dict[int, list[str]] = {}
        for page_number, line in segment_lines:
            page_map.setdefault(page_number, []).append(line)
        page_texts = [
            (page_number, "\n".join(page_lines))
            for page_number, page_lines in sorted(page_map.items())
        ]
        text = "\n".join(line for _page, line in segment_lines)
        number = segment["number"] or detect_invoice_number(text)
        supplier = detect_supplier(text)
        groups.append(
            InvoiceGroup(
                page_start=min(page_map),
                page_end=max(page_map),
                invoice_number=number,
                supplier_name=supplier,
                confidence=0.0,
                page_texts=page_texts,
            )
        )

    # Adjacent segments that resolved to the same invoice identity are one
    # invoice (e.g. a repeated label without a new record heading).
    merged: list[InvoiceGroup] = []
    for group in groups:
        previous = merged[-1] if merged else None
        if (
            previous
            and group.invoice_number
            and previous.invoice_number == group.invoice_number
            and group.page_start <= previous.page_end + 1
        ):
            previous.page_end = max(previous.page_end, group.page_end)
            previous.page_texts = _merge_page_texts(previous.page_texts, group.page_texts)
            previous.supplier_name = previous.supplier_name or group.supplier_name
        else:
            merged.append(group)

    saw_any_number = any(group.invoice_number for group in merged)
    for group in merged:
        score = 0.55
        if group.invoice_number:
            score += 0.3
        if group.supplier_name:
            score += 0.1
        if saw_any_number:
            score += 0.05
        group.confidence = min(score, 0.98)
    return merged


def _merge_page_texts(
    left: list[tuple[int, str]], right: list[tuple[int, str]]
) -> list[tuple[int, str]]:
    merged: dict[int, list[str]] = {}
    for page_number, text in left + right:
        merged.setdefault(page_number, []).append(text)
    return [(page, "\n".join(texts)) for page, texts in sorted(merged.items())]


def _group_pages_fallback(pages: list) -> list[InvoiceGroup]:
    """Legacy page-based grouping used when no invoice labels are present."""
    page_meta: list[tuple[str | None, str | None]] = []
    for page in pages:
        text = getattr(page, "text", "") or ""
        number = detect_invoice_number(text)
        supplier = detect_supplier(text)
        page_meta.append((number, supplier))

    groups: list[InvoiceGroup] = []
    current: InvoiceGroup | None = None
    current_number: str | None = None
    saw_any_number = any(number for number, _ in page_meta)

    for page, (number, supplier) in zip(pages, page_meta, strict=False):
        is_new = False
        if current is None:
            is_new = True
        elif number and current_number and number != current_number:
            is_new = True
        elif number and not current_number:
            # Upgrade a previously anonymous group rather than splitting it.
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
        else:
            assert current is not None
            current.page_end = page.page_number
            if not current.invoice_number and number:
                current.invoice_number = number
                current_number = number
            if not current.supplier_name and supplier:
                current.supplier_name = supplier

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


def group_invoice_pages(pages: list) -> list[InvoiceGroup]:
    """Group PDF pages into logical invoice units.

    When the document exposes invoice labels/record headings, boundaries are
    detected at line level so that several invoices sharing a page are all
    extracted (and pages from one invoice are merged). Documents without such
    labels fall back to the classic page-based grouping.
    """
    if not pages:
        return []
    labelled = _build_groups(pages)
    if labelled:
        return labelled
    return _group_pages_fallback(pages)
