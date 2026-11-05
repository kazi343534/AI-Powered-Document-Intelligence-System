from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..embeddings import embed_provider_name
from ..ingest_validation import ALLOWED_EXTENSIONS
from ..models import Document, Finding, Invoice, ProcessingJob, Reconciliation, User
from ..ocr import engine_hint
from ..presenters import document_list_item, job_out
from ..schemas import DashboardStats, JobOut, MetaResponse, ReconciliationOut
from ..storage import get_storage
from .deps import client_ip, get_current_user, record_audit, require_roles

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/health/live")
def health_live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "storage": settings.storage_backend,
        "ai": settings.ai_enabled,
    }


@router.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    return MetaResponse(
        app=settings.app_name,
        environment=settings.environment,
        ai_enabled=settings.ai_enabled,
        ai_model=settings.groq_model if settings.ai_enabled else None,
        ocr_engine=engine_hint(),
        embedding_provider=embed_provider_name(),
        storage_backend=get_storage().backend,
        supported_extensions=sorted(ALLOWED_EXTENSIONS),
        max_file_mb=settings.max_file_mb,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DashboardStats:
    status_rows = db.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.deleted_at.is_(None))
        .group_by(Document.status)
    ).all()
    counts = {status: 0 for status in ("uploaded", "queued", "processing", "completed", "needs_review", "failed")}
    counts.update({row[0]: row[1] for row in status_rows})

    kind_rows = db.execute(
        select(Document.kind, func.count(Document.id))
        .where(Document.deleted_at.is_(None))
        .group_by(Document.kind)
    ).all()
    kinds = {"pdf": 0, "image": 0, "spreadsheet": 0}
    kinds.update({row[0]: row[1] for row in kind_rows})

    finding_rows = db.execute(
        select(Finding.severity, Finding.status, func.count(Finding.id)).group_by(
            Finding.severity, Finding.status
        )
    ).all()
    findings: dict[str, int] = {}
    for severity, status, count in finding_rows:
        findings[severity] = findings.get(severity, 0) + count
        findings[f"{status}:{severity}"] = count

    recent = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
            .limit(6)
        )
    )
    queue_depth = db.scalar(
        select(func.count(ProcessingJob.id)).where(ProcessingJob.status.in_(["queued", "running"]))
    ) or 0
    finished_jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "completed",
                ProcessingJob.started_at.is_not(None),
                ProcessingJob.finished_at.is_not(None),
            )
            .order_by(ProcessingJob.finished_at.desc())
            .limit(100)
        )
    )
    durations = []
    for job in finished_jobs:
        start = _aware(job.started_at)
        end = _aware(job.finished_at)
        if start and end:
            durations.append(max(0.0, (end - start).total_seconds()))
    avg_seconds = round(sum(durations) / len(durations), 2) if durations else None
    total = sum(counts.values())
    return DashboardStats(
        documents=counts,
        kinds=kinds,
        findings=findings,
        recent_documents=[document_list_item(db, document) for document in recent],
        queue_depth=queue_depth,
        avg_processing_seconds=avg_seconds,
        total_documents=total,
        needs_review=counts.get("needs_review", 0),
        failed=counts.get("failed", 0),
    )


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    status_filter: str | None = None,
    document_id: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    stmt = select(ProcessingJob).order_by(ProcessingJob.created_at.desc())
    if status_filter:
        stmt = stmt.where(ProcessingJob.status == status_filter)
    if document_id:
        stmt = stmt.where(ProcessingJob.document_id == document_id)
    return [job_out(job) for job in db.scalars(stmt.limit(min(limit, 200)))]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> JobOut:
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_out(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    document = db.get(Document, job.document_id)
    if not document or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    active = db.scalar(
        select(func.count(ProcessingJob.id)).where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="Document already has an active job")
    job.status = "queued"
    job.attempts = 0
    job.progress = 0
    job.error_code = None
    job.error_message = None
    job.locked_at = None
    job.locked_by = None
    job.started_at = None
    job.finished_at = None
    job.next_run_at = datetime.now(timezone.utc)
    document.status = "queued"
    document.stage = "queued"
    document.progress = 0
    document.error_code = None
    document.error_message = None
    record_audit(
        db, user, "job.retry", "job", job.id, {"document_id": document.id}, client_ip(request)
    )
    db.commit()
    return job_out(job)


@router.get("/reconciliations", response_model=list[ReconciliationOut])
def list_reconciliations(
    document_id: str | None = None,
    invoice_id: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReconciliationOut]:
    stmt = select(Reconciliation).order_by(Reconciliation.created_at.desc())
    if document_id:
        invoice_ids = select(Invoice.id).where(Invoice.document_id == document_id)
        stmt = stmt.where(
            (Reconciliation.matched_document_id == document_id)
            | (Reconciliation.invoice_id.in_(invoice_ids))
        )
    if invoice_id:
        stmt = stmt.where(Reconciliation.invoice_id == invoice_id)
    rows = list(db.scalars(stmt.limit(min(limit, 200))))
    return [
        ReconciliationOut(
            id=row.id,
            invoice_id=row.invoice_id,
            matched_invoice_id=row.matched_invoice_id,
            matched_document_id=row.matched_document_id,
            sheet_row_id=row.sheet_row_id,
            match_type=row.match_type,
            confidence=row.confidence,
            diffs=row.diffs or [],
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
