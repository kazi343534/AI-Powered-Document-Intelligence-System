from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Finding, User
from ..presenters import finding_out
from ..reconciliation_sync import auto_dismiss_acknowledged_reconciliations
from ..schemas import FindingOut, FindingUpdateRequest
from .deps import client_ip, get_current_user, record_audit, require_roles

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("", response_model=list[FindingOut])
def list_findings(
    status_filter: str | None = None,
    document_id: str | None = None,
    invoice_id: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FindingOut]:
    stmt = select(Finding).order_by(Finding.created_at.desc())
    if status_filter:
        stmt = stmt.where(Finding.status == status_filter)
    if document_id:
        stmt = stmt.where(Finding.document_id == document_id)
    if invoice_id:
        stmt = stmt.where(Finding.invoice_id == invoice_id)
    return [
        finding_out(finding)
        for finding in db.scalars(stmt.limit(min(max(limit, 1), 500)))
    ]


@router.patch("/{finding_id}", response_model=FindingOut)
def update_finding(
    finding_id: str,
    payload: FindingUpdateRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> FindingOut:
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    finding.status = payload.status
    finding.resolution_note = payload.note
    finding.resolved_by = user.id
    finding.resolved_at = datetime.now(UTC)
    record_audit(
        db,
        user,
        "finding.update",
        "finding",
        finding.id,
        {"status": payload.status, "note": payload.note},
        client_ip(request),
    )
    # Reconciliation diffs are mirrored as findings. Once every linked
    # finding is resolved/dismissed, the mismatch is acknowledged too and
    # must no longer block approval.
    for reconciliation in auto_dismiss_acknowledged_reconciliations(db, finding.invoice_id):
        record_audit(
            db,
            user,
            "reconciliation.update",
            "reconciliation",
            reconciliation.id,
            {
                "status": "dismissed",
                "previous_status": "mismatch",
                "note": "All linked findings resolved",
                "source": "finding.update",
            },
            client_ip(request),
        )
    db.commit()
    return finding_out(finding)
