from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, Extraction, Finding, Invoice, User
from ..schemas import (
    SalesAnalytics,
    SalesCurrencyBreakdown,
    SalesPeriod,
    SalesStatus,
    SalesSummary,
    SalesSupplier,
)
from .deps import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

_CENT = Decimal("0.01")
_MONEY_CLEANUP = re.compile(r"[^0-9.\-]")


def _field_value(data: dict, key: str):
    """Read a field from the extraction JSON, supporting both schema shapes."""
    value = data.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _parse_date(value) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        from dateutil import parser as date_parser

        return date_parser.parse(text, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def _parse_money(value) -> Decimal | None:
    if value is None:
        return None
    text = _MONEY_CLEANUP.sub("", str(value).replace(",", ""))
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return Decimal(text).quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _currency(value) -> str:
    text = str(value or "").strip().upper()
    return text[:12] if text else "UNSPECIFIED"


def _supplier(value) -> str:
    text = str(value or "").strip()
    return text[:255] if text else "Unknown supplier"


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_label(value: date) -> str:
    return value.strftime("%b %y")


def _shift_months(value: date, delta: int) -> date:
    index = value.year * 12 + (value.month - 1) + delta
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def _money_out(value: Decimal) -> float:
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _empty_bucket() -> dict:
    return {
        "total": Decimal("0.00"),
        "count": 0,
        "approved_total": Decimal("0.00"),
        "approved_count": 0,
    }


def _add_to_bucket(bucket: dict, record: dict) -> None:
    bucket["count"] += 1
    if record["total"] is not None:
        bucket["total"] += record["total"]
    if record["approved"]:
        bucket["approved_count"] += 1
        if record["total"] is not None:
            bucket["approved_total"] += record["total"]


@router.get("/sales", response_model=SalesAnalytics)
def sales_analytics(
    currency: str | None = Query(default=None, min_length=1, max_length=12),
    months: int = Query(default=12, ge=1, le=60),
    years: int = Query(default=5, ge=1, le=10),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesAnalytics:
    """Monthly and yearly invoice totals with supplier and currency breakdowns.

    Only the current extraction of each invoice contributes. Invoices with an
    open duplicate finding (V010) are excluded so the same sale is not counted
    twice. Amounts are never summed across currencies; the response selects one
    currency and reports the others separately.
    """
    rows = db.execute(
        select(Invoice, Extraction)
        .join(Extraction, Invoice.current_extraction_id == Extraction.id)
        .join(Document, Invoice.document_id == Document.id)
        .where(Document.deleted_at.is_(None))
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
    ).all()

    duplicate_ids = set(
        db.scalars(
            select(Finding.invoice_id).where(
                Finding.rule_code == "V010",
                Finding.status == "open",
                Finding.invoice_id.is_not(None),
            )
        )
    )

    candidates: list[dict] = []
    for invoice, extraction in rows:
        data = extraction.data or {}
        identity = (
            (invoice.invoice_number_norm, invoice.supplier_norm)
            if invoice.invoice_number_norm and invoice.supplier_norm
            else None
        )
        candidates.append(
            {
                "currency": _currency(_field_value(data, "currency")),
                "supplier": _supplier(_field_value(data, "supplier_name")),
                "date": _parse_date(_field_value(data, "invoice_date")),
                "total": _parse_money(_field_value(data, "total")),
                "approved": extraction.review_status == "approved",
                "flagged": invoice.id in duplicate_ids,
                "identity": identity,
                "created_at": invoice.created_at,
            }
        )

    # Count each supplier invoice once. When the same identity appears more
    # than once, prefer the copy without an open duplicate flag, then the
    # approved copy, then the earliest one. A flagged invoice with no clean
    # counterpart is still excluded because V010 says it duplicates another
    # document that is not part of this identity group.
    grouped: dict[tuple[str, str], list[dict]] = {}
    kept: list[dict] = []
    excluded_duplicates = 0
    for record in candidates:
        if record["identity"] is None:
            if record["flagged"]:
                excluded_duplicates += 1
            else:
                kept.append(record)
        else:
            grouped.setdefault(record["identity"], []).append(record)

    for group in grouped.values():
        clean = [record for record in group if not record["flagged"]]
        if not clean:
            excluded_duplicates += len(group)
            continue
        clean.sort(key=lambda record: (not record["approved"], record["created_at"]))
        kept.append(clean[0])
        excluded_duplicates += len(group) - 1

    records = sorted(kept, key=lambda record: record["created_at"])

    currency_totals: dict[str, dict] = {}
    for record in records:
        entry = currency_totals.setdefault(
            record["currency"], {"count": 0, "total": Decimal("0.00")}
        )
        entry["count"] += 1
        if record["total"] is not None:
            entry["total"] += record["total"]

    requested = currency.upper() if currency else None
    if requested:
        selected = requested
    elif currency_totals:
        selected = max(
            currency_totals,
            key=lambda code: (
                currency_totals[code]["count"],
                currency_totals[code]["total"],
            ),
        )
    else:
        selected = "USD"

    selected_records = [record for record in records if record["currency"] == selected]
    dated_records = [record for record in selected_records if record["date"] is not None]

    total = sum(
        (record["total"] for record in selected_records if record["total"] is not None),
        Decimal("0.00"),
    )
    with_total = sum(1 for record in selected_records if record["total"] is not None)
    approved_records = [record for record in selected_records if record["approved"]]
    pending_records = [record for record in selected_records if not record["approved"]]

    summary = SalesSummary(
        invoice_count=len(selected_records),
        total=_money_out(total),
        average_invoice=_money_out(total / with_total) if with_total else 0.0,
        supplier_count=len({record["supplier"] for record in selected_records}),
        approved_count=len(approved_records),
        pending_count=len(pending_records),
        dated_count=len(dated_records),
        undated_count=len(selected_records) - len(dated_records),
        missing_total_count=len(selected_records) - with_total,
        excluded_duplicates=excluded_duplicates,
    )

    latest_date = max((record["date"] for record in dated_records), default=None)
    end_month = (latest_date or date.today()).replace(day=1)
    start_month = _shift_months(end_month, -(months - 1))

    monthly: dict[str, dict] = {}
    for offset in range(months):
        month = _shift_months(start_month, offset)
        monthly[_month_key(month)] = {
            "label": _month_label(month),
            **_empty_bucket(),
        }
    for record in dated_records:
        bucket = monthly.get(_month_key(record["date"]))
        if bucket is not None:
            _add_to_bucket(bucket, record)

    end_year = end_month.year
    start_year = end_year - (years - 1)
    yearly: dict[str, dict] = {
        str(year): {"label": str(year), **_empty_bucket()}
        for year in range(start_year, end_year + 1)
    }
    for record in dated_records:
        bucket = yearly.get(str(record["date"].year))
        if bucket is not None:
            _add_to_bucket(bucket, record)

    supplier_totals: dict[str, dict] = {}
    for record in selected_records:
        entry = supplier_totals.setdefault(
            record["supplier"], {"count": 0, "total": Decimal("0.00")}
        )
        entry["count"] += 1
        if record["total"] is not None:
            entry["total"] += record["total"]

    def _status_total(items: list[dict]) -> Decimal:
        return sum(
            (record["total"] for record in items if record["total"] is not None),
            Decimal("0.00"),
        )

    return SalesAnalytics(
        currency=selected,
        months=months,
        years=years,
        period_start=next(iter(monthly)),
        period_end=_month_key(end_month),
        currencies=[
            SalesCurrencyBreakdown(
                currency=code,
                invoice_count=entry["count"],
                total=_money_out(entry["total"]),
            )
            for code, entry in sorted(
                currency_totals.items(),
                key=lambda item: (-item[1]["count"], -item[1]["total"], item[0]),
            )
        ],
        summary=summary,
        monthly=[
            SalesPeriod(
                period=key,
                label=bucket["label"],
                total=_money_out(bucket["total"]),
                invoice_count=bucket["count"],
                approved_total=_money_out(bucket["approved_total"]),
                approved_count=bucket["approved_count"],
            )
            for key, bucket in monthly.items()
        ],
        yearly=[
            SalesPeriod(
                period=key,
                label=bucket["label"],
                total=_money_out(bucket["total"]),
                invoice_count=bucket["count"],
                approved_total=_money_out(bucket["approved_total"]),
                approved_count=bucket["approved_count"],
            )
            for key, bucket in yearly.items()
        ],
        top_suppliers=[
            SalesSupplier(
                supplier_name=name,
                total=_money_out(entry["total"]),
                invoice_count=entry["count"],
            )
            for name, entry in sorted(
                supplier_totals.items(),
                key=lambda item: (-item[1]["total"], -item[1]["count"], item[0]),
            )[:6]
        ],
        statuses=[
            SalesStatus(
                status="approved",
                count=len(approved_records),
                total=_money_out(_status_total(approved_records)),
            ),
            SalesStatus(
                status="pending",
                count=len(pending_records),
                total=_money_out(_status_total(pending_records)),
            ),
        ],
    )
