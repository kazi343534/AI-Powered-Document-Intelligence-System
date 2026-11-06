from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, Reconciliation, User
from ..presenters import reconciliation_out
from ..schemas import ReconciliationOut, ReconciliationUpdateRequest
from .deps import client_ip, get_current_user, record_audit, require_roles

router = APIRouter(prefix="/reconciliations", tags=["reconciliations"])


@router.get("", response_model=list[ReconciliationOut])
def list_reconciliations(
    document_id: str | None = None,
    invoice_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReconciliationOut]:
    stmt = select(Reconciliation).order_by(Reconciliation.created_at.desc())
    if invoice_id:
        stmt = stmt.where(
            or_(
                Reconciliation.invoice_id == invoice_id,
                Reconciliation.matched_invoice_id == invoice_id,
            )
        )
    if document_id:
        invoice_ids = select(Invoice.id).where(Invoice.document_id == document_id)
        stmt = stmt.where(
            or_(
                Reconciliation.invoice_id.in_(invoice_ids),
                Reconciliation.matched_invoice_id.in_(invoice_ids),
                Reconciliation.matched_document_id == document_id,
            )
        )
    if status_filter:
        stmt = stmt.where(Reconciliation.status == status_filter)
    return [
        reconciliation_out(item)
        for item in db.scalars(stmt.limit(min(max(limit, 1), 500)))
    ]


@router.patch("/{reconciliation_id}", response_model=ReconciliationOut)
def update_reconciliation(
    reconciliation_id: str,
    payload: ReconciliationUpdateRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> ReconciliationOut:
    """Resolve a reconciliation mismatch.

    Reviewers can either dismiss an expected difference or mark the pair as
    matched after verifying it. Dismissed/matched rows no longer block invoice
    or document approval. The decision is recorded in the audit trail.
    """
    item = db.get(Reconciliation, reconciliation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Reconciliation not found")
    previous_status = item.status
    item.status = payload.status
    record_audit(
        db,
        user,
        "reconciliation.update",
        "reconciliation",
        item.id,
        {
            "status": payload.status,
            "previous_status": previous_status,
            "note": payload.note,
        },
        client_ip(request),
    )
    db.commit()
    return reconciliation_out(item)
