from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..embeddings import get_embedder
from ..models import (
    Chunk,
    Correction,
    Document,
    Extraction,
    Finding,
    Invoice,
    LineItem,
    Reconciliation,
    User,
)
from ..pipeline import _overall_confidence, _persist_findings, _persist_reconciliations
from ..presenters import extraction_out, invoice_out
from ..schemas import (
    CorrectionRequest,
    ExtractionData,
    ExtractionLineItem,
    ExtractionOut,
    FieldValue,
    InvoiceOut,
    ReviewRequest,
)
from ..utils import normalize_invoice_number, normalize_supplier
from ..validation import validate_invoice
from .deps import client_ip, get_current_user, record_audit, require_roles

router = APIRouter(prefix="/invoices", tags=["invoices"])

ALLOWED_FIELDS = set(ExtractionData().field_names()) | {"line_items"}


def _get_invoice(db: Session, invoice_id: str) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _load_with_lines(db: Session, extraction_id: str) -> Extraction:
    extraction = db.scalar(
        select(Extraction)
        .options(selectinload(Extraction.line_items))
        .where(Extraction.id == extraction_id)
    )
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return extraction


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceOut:
    invoice = _get_invoice(db, invoice_id)
    return invoice_out(db, invoice)


@router.get("/{invoice_id}/extractions", response_model=list[ExtractionOut])
def list_extractions(
    invoice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ExtractionOut]:
    invoice = _get_invoice(db, invoice_id)
    extractions = db.scalars(
        select(Extraction)
        .options(selectinload(Extraction.line_items))
        .where(Extraction.invoice_id == invoice.id)
        .order_by(Extraction.version.desc())
    )
    return [extraction_out(item) for item in extractions]


@router.get("/{invoice_id}/corrections")
def list_corrections(
    invoice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    invoice = _get_invoice(db, invoice_id)
    extraction_ids = [
        row[0]
        for row in db.execute(select(Extraction.id).where(Extraction.invoice_id == invoice.id))
    ]
    if not extraction_ids:
        return []
    corrections = db.scalars(
        select(Correction)
        .where(Correction.extraction_id.in_(extraction_ids))
        .order_by(Correction.created_at.desc())
    )
    return [
        {
            "id": item.id,
            "extraction_id": item.extraction_id,
            "field_path": item.field_path,
            "old_value": item.old_value,
            "new_value": item.new_value,
            "reason": item.reason,
            "created_at": item.created_at.isoformat(),
        }
        for item in corrections
    ]


@router.patch("/{invoice_id}/extractions/{extraction_id}", response_model=ExtractionOut)
def correct_extraction(
    invoice_id: str,
    extraction_id: str,
    payload: CorrectionRequest,
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> ExtractionOut:
    invoice = _get_invoice(db, invoice_id)
    current = _load_with_lines(db, extraction_id)
    if invoice.current_extraction_id != current.id:
        raise HTTPException(status_code=409, detail="Only the current extraction can be edited")
    if if_match and str(current.version) != if_match.strip().strip('"'):
        raise HTTPException(status_code=409, detail="Extraction changed; reload before editing")
    unknown = set(payload.changes) - ALLOWED_FIELDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown fields: {', '.join(sorted(unknown))}")

    data = ExtractionData.model_validate(current.data)
    corrections: list[Correction] = []
    for key, raw_value in payload.changes.items():
        old_value = (
            [item.model_dump(mode="json") for item in data.line_items]
            if key == "line_items"
            else getattr(data, key).value
        )
        if key == "line_items":
            if raw_value is None:
                raw_value = []
            if not isinstance(raw_value, list):
                raise HTTPException(status_code=422, detail="line_items must be a list")
            try:
                new_items = [ExtractionLineItem.model_validate(item) for item in raw_value]
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Invalid line item: {exc}") from exc
            data.line_items = new_items
            new_value = [item.model_dump(mode="json") for item in new_items]
        else:
            if isinstance(raw_value, dict):
                field = FieldValue.model_validate(raw_value)
            else:
                field = FieldValue(value=raw_value, confidence=1.0)
            if key == "currency" and field.value:
                from ..extraction.service import normalize_manual_field

                field = normalize_manual_field(key, field)
            else:
                from ..extraction.service import normalize_manual_field

                field = normalize_manual_field(key, field)
            if field.value is None and raw_value not in (None, ""):
                raise HTTPException(
                    status_code=422, detail=f"Value for {key} could not be normalized"
                )
            field.confidence = 1.0 if field.value is not None else 0.0
            field.evidence = None
            setattr(data, key, field)
            new_value = field.value
        corrections.append(
            Correction(
                extraction_id=current.id,
                user_id=user.id,
                field_path=key,
                old_value=old_value,
                new_value=new_value,
                reason=payload.reason,
            )
        )

    version = (
        db.scalar(
            select(func.max(Extraction.version)).where(Extraction.invoice_id == invoice.id)
        )
        or 0
    ) + 1
    new_extraction = Extraction(
        invoice_id=invoice.id,
        version=version,
        schema_version=data.schema_version,
        prompt_version=current.prompt_version,
        model="manual-correction",
        source="manual",
        data=data.model_dump(mode="json"),
        confidence={
            "fields": {key: getattr(data, key).confidence for key in data.field_names()},
            "overall": _overall_confidence(data),
        },
        review_status="pending",
        created_by=user.id,
    )
    db.add(new_extraction)
    db.flush()
    for index, item in enumerate(data.line_items, start=1):
        db.add(
            LineItem(
                extraction_id=new_extraction.id,
                line_no=index,
                description=item.description,
                quantity=_decimal(item.quantity),
                unit_price=_decimal(item.unit_price),
                amount=_decimal(item.amount),
                tax_rate=_decimal(item.tax_rate),
                confidence=item.confidence,
                page=item.page,
            )
        )
    for correction in corrections:
        correction.extraction_id = new_extraction.id
        db.add(correction)
    db.flush()

    invoice.current_extraction_id = new_extraction.id
    invoice.invoice_number_norm = normalize_invoice_number(data.invoice_number.value)
    invoice.supplier_norm = normalize_supplier(data.supplier_name.value)
    invoice.status = "needs_review"
    document = db.get(Document, invoice.document_id)
    if document:
        document.status = "needs_review"
        document.stage = "review_required"

    db.execute(delete(Finding).where(Finding.invoice_id == invoice.id))
    db.execute(delete(Reconciliation).where(Reconciliation.invoice_id == invoice.id))
    db.execute(delete(Reconciliation).where(Reconciliation.matched_invoice_id == invoice.id))
    validation = validate_invoice(db, document, invoice, new_extraction, data)
    _persist_findings(db, document, invoice, new_extraction, validation.issues)
    _persist_reconciliations(db, validation.reconciliations)
    _refresh_summary_chunk(db, invoice, data)
    record_audit(
        db,
        user,
        "invoice.correct",
        "invoice",
        invoice.id,
        {"extraction_id": new_extraction.id, "fields": list(payload.changes)},
        client_ip(request),
    )
    db.commit()
    return extraction_out(_load_with_lines(db, new_extraction.id))


def _decimal(value: str | None):
    from ..utils import parse_decimal

    return parse_decimal(value)


def _refresh_summary_chunk(db: Session, invoice: Invoice, data: ExtractionData) -> None:
    db.execute(delete(Chunk).where(Chunk.invoice_id == invoice.id))
    content = (
        f"Invoice {data.invoice_number.value or 'unknown'} from "
        f"{data.supplier_name.value or 'unknown supplier'}. "
        f"Date: {data.invoice_date.value or ''}. "
        f"Total: {data.currency.value or ''} {data.total.value or ''}. "
    )
    if data.line_items:
        content += "Line items: " + "; ".join(
            f"{item.description} ({item.amount or ''})" for item in data.line_items[:20]
        )
    embedding = None
    try:
        embedding = get_embedder().embed_query(content)
    except Exception:
        pass
    db.add(
        Chunk(
            document_id=invoice.document_id,
            invoice_id=invoice.id,
            page_number=invoice.page_start,
            chunk_index=0,
            content=content,
            embedding=embedding,
            meta={"source": "invoice_summary", "invoice_number": data.invoice_number.value},
        )
    )
    db.flush()


def _approve_invoice(db: Session, invoice: Invoice, user: User, note: str | None) -> Invoice:
    """Approve an invoice extraction (approve workflow).

    Blocks approval while open error/warning findings or reconciliation
    mismatches exist; otherwise marks the extraction approved and completes the
    invoice (and document) status. Raises HTTPException(409) when blocked.
    """
    blocking = list(
        db.scalars(
            select(Finding).where(
                Finding.document_id == invoice.document_id,
                or_(
                    Finding.invoice_id == invoice.id,
                    Finding.invoice_id.is_(None),
                ),
                Finding.status == "open",
                Finding.severity.in_(["error", "warning"]),
            )
        )
    )
    mismatches = list(
        db.scalars(
            select(Reconciliation).where(
                or_(
                    Reconciliation.invoice_id == invoice.id,
                    Reconciliation.matched_invoice_id == invoice.id,
                ),
                Reconciliation.status == "mismatch",
            )
        )
    )
    if blocking or mismatches:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot approve: {len(blocking)} open finding(s) and "
                f"{len(mismatches)} reconciliation mismatch(es) must be resolved first"
            ),
        )
    extraction = _load_with_lines(db, invoice.current_extraction_id)
    invoice.status = "completed"
    extraction.review_status = "approved"
    extraction.reviewed_by = user.id
    extraction.reviewed_at = datetime.now(timezone.utc)
    extraction.review_note = note
    document = db.get(Document, invoice.document_id)
    if document:
        statuses = [
            item.status
            for item in db.scalars(select(Invoice).where(Invoice.document_id == document.id))
        ]
        document.status = "completed" if all(status == "completed" for status in statuses) else "needs_review"
        if document.status == "completed":
            document.stage = "completed"
    return invoice


@router.post("/{invoice_id}/review", response_model=InvoiceOut)
def review_invoice(
    invoice_id: str,
    payload: ReviewRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> InvoiceOut:
    invoice = _get_invoice(db, invoice_id)
    if not invoice.current_extraction_id:
        raise HTTPException(status_code=409, detail="Invoice has no extraction to review")
    extraction = _load_with_lines(db, invoice.current_extraction_id)
    document = db.get(Document, invoice.document_id)

    if payload.action == "approve":
        invoice = _approve_invoice(db, invoice, user, payload.note)
    else:
        extraction.review_status = "pending"
        extraction.reviewed_by = None
        extraction.reviewed_at = None
        extraction.review_note = payload.note
        invoice.status = "needs_review"
        if document:
            document.status = "needs_review"
            document.stage = "review_required"

    record_audit(
        db,
        user,
        f"invoice.{payload.action}",
        "invoice",
        invoice.id,
        {"extraction_id": extraction.id, "note": payload.note},
        client_ip(request),
    )
    db.commit()
    return invoice_out(db, invoice)
