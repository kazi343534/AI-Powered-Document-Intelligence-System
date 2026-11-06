from __future__ import annotations

import logging
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..ingest_validation import (
    UploadValidationError,
    detect_extension,
    safe_filename,
    validate_file,
)
from ..models import (
    Document,
    DocumentPage,
    Finding,
    Invoice,
    ProcessingJob,
    Reconciliation,
    SheetRow,
    User,
)
from ..parsers.pdf import PdfProcessingError, image_preview, render_pdf_page
from ..pipeline import enqueue_document, materialize_document, reset_for_reprocess
from ..presenters import document_detail, document_list_item, finding_out
from ..schemas import (
    ApproveRequest,
    DocumentDetail,
    DocumentListItem,
    DocumentListResponse,
    FindingOut,
    InvoiceOut,
    PageOut,
    ReprocessRequest,
    SheetRowOut,
    SheetRowsResponse,
    UploadRejected,
    UploadResponse,
)
from ..storage import StorageError, get_storage
from ..utils import normalize_invoice_number, normalize_supplier, sha256_file
from .deps import client_ip, get_current_user, record_audit, require_roles
from .invoices import _approve_invoice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


@router.post("", response_model=UploadResponse, status_code=202)
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files; limit is {settings.max_files_per_upload} per upload",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    storage = get_storage()
    accepted: list[DocumentListItem] = []
    rejected: list[UploadRejected] = []

    with tempfile.TemporaryDirectory(prefix="docintel-upload-") as temp_dir:
        for index, upload in enumerate(files):
            filename = safe_filename(upload.filename)
            try:
                suffix, kind = detect_extension(filename)
            except UploadValidationError as exc:
                rejected.append(UploadRejected(filename=filename, code=exc.code, message=exc.message))
                await upload.close()
                continue

            temp_path = Path(temp_dir) / f"upload-{index}{suffix}"
            size = 0
            try:
                with temp_path.open("wb") as handle:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_file_bytes:
                            raise UploadValidationError(
                                "FILE_TOO_LARGE",
                                f"File exceeds the {settings.max_file_mb} MB limit",
                            )
                        handle.write(chunk)
                if size == 0:
                    raise UploadValidationError("EMPTY_FILE", "File is empty")
                suffix, kind, detected_mime = validate_file(temp_path, filename, upload.content_type)
            except UploadValidationError as exc:
                rejected.append(UploadRejected(filename=filename, code=exc.code, message=exc.message))
                temp_path.unlink(missing_ok=True)
                await upload.close()
                continue
            except Exception as exc:
                logger.exception("upload validation failed for %s", filename)
                rejected.append(
                    UploadRejected(filename=filename, code="UPLOAD_ERROR", message=str(exc)[:300])
                )
                temp_path.unlink(missing_ok=True)
                await upload.close()
                continue

            sha = sha256_file(str(temp_path))
            existing = db.scalar(
                select(Document).where(Document.sha256 == sha, Document.deleted_at.is_(None))
            )
            if existing:
                item = document_list_item(db, existing)
                item.duplicate = True
                accepted.append(item)
                temp_path.unlink(missing_ok=True)
                await upload.close()
                continue

            storage_key = f"documents/{sha[:2]}/{sha}{suffix}"
            try:
                storage.upload_file(temp_path, storage_key, detected_mime)
            except StorageError as exc:
                logger.error("storage upload failed: %s", exc)
                rejected.append(
                    UploadRejected(filename=filename, code="STORAGE_ERROR", message=str(exc)[:300])
                )
                temp_path.unlink(missing_ok=True)
                await upload.close()
                continue

            document = Document(
                original_filename=filename,
                storage_key=storage_key,
                mime_type=detected_mime,
                kind=kind,
                size_bytes=size,
                sha256=sha,
                uploaded_by=user.id,
                status="uploaded",
                stage="queued",
            )
            db.add(document)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                existing = db.scalar(
                    select(Document).where(Document.sha256 == sha, Document.deleted_at.is_(None))
                )
                if existing:
                    item = document_list_item(db, existing)
                    item.duplicate = True
                    accepted.append(item)
                await upload.close()
                continue
            enqueue_document(db, document)
            record_audit(
                db,
                user,
                "document.upload",
                "document",
                document.id,
                {"filename": filename, "size": size, "kind": kind},
                client_ip(request),
            )
            db.commit()
            accepted.append(document_list_item(db, document))
            await upload.close()

    return UploadResponse(documents=accepted, rejected=rejected)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = None,
    q: str | None = None,
    supplier: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "created_desc",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    conditions = [Document.deleted_at.is_(None)]
    if status_filter:
        statuses = [value.strip() for value in status_filter.split(",") if value.strip()]
        if statuses:
            conditions.append(Document.status.in_(statuses))
    if kind:
        conditions.append(Document.kind == kind)
    if date_from:
        start = datetime.combine(date_from, datetime.min.time())
        if settings.is_postgres:
            start = start.replace(tzinfo=UTC)
        conditions.append(Document.created_at >= start)
    if date_to:
        end = datetime.combine(date_to, datetime.max.time())
        if settings.is_postgres:
            end = end.replace(tzinfo=UTC)
        conditions.append(Document.created_at <= end)
    if supplier:
        normalized = normalize_supplier(supplier)
        invoice_subquery = select(Invoice.document_id).where(
            Invoice.supplier_norm.like(f"%{normalized}%")
        )
        conditions.append(Document.id.in_(invoice_subquery))
    if q:
        pattern = f"%{q.strip()}%"
        invoice_number = normalize_invoice_number(q) or q.strip()
        supplier_key = normalize_supplier(q) or q.strip().lower()
        invoice_subquery = select(Invoice.document_id).where(
            or_(
                Invoice.invoice_number_norm.like(f"%{invoice_number}%"),
                Invoice.supplier_norm.like(f"%{supplier_key}%"),
            )
        )
        conditions.append(
            or_(
                Document.original_filename.ilike(pattern),
                Document.id.in_(invoice_subquery),
            )
        )

    base = select(Document).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    if sort == "created_asc":
        base = base.order_by(Document.created_at.asc())
    elif sort == "updated_desc":
        base = base.order_by(Document.updated_at.desc())
    elif sort == "filename":
        base = base.order_by(Document.original_filename.asc())
    else:
        base = base.order_by(Document.created_at.desc())
    documents = list(db.scalars(base.offset(offset).limit(limit)))
    return DocumentListResponse(
        items=[document_list_item(db, document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


def _get_document(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if not document or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    include_text: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = _get_document(db, document_id)
    return document_detail(db, document, include_text=include_text)


@router.get("/{document_id}/status")
def get_document_status(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_document(db, document_id)
    latest_job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    return {
        "id": document.id,
        "status": document.status,
        "stage": document.stage,
        "progress": document.progress,
        "page_count": document.page_count,
        "error_code": document.error_code,
        "error_message": document.error_message,
        "job": {
            "id": latest_job.id,
            "status": latest_job.status,
            "attempts": latest_job.attempts,
            "error_code": latest_job.error_code,
            "error_message": latest_job.error_message,
        }
        if latest_job
        else None,
    }


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id)
    storage = get_storage()
    signed = storage.signed_url(document.storage_key, expires_in=3600)
    if signed:
        return RedirectResponse(signed, status_code=307)
    local = storage.local_path(document.storage_key)
    if local and local.exists():
        return FileResponse(
            local,
            media_type=document.mime_type,
            headers={
                "Content-Disposition": f'inline; filename="{document.original_filename}"',
                "Cache-Control": "private, max-age=60",
            },
        )
    try:
        content = storage.read_bytes(document.storage_key)
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'inline; filename="{document.original_filename}"'},
    )


@router.get("/{document_id}/pages/{page_number}/preview")
def get_page_preview(
    document_id: str,
    page_number: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_document(db, document_id)
    if document.kind == "spreadsheet":
        raise HTTPException(status_code=400, detail="Spreadsheets do not have page previews")
    suffix = Path(document.original_filename).suffix.lower()
    try:
        with materialize_document(document.storage_key, suffix) as path:
            if document.kind == "image":
                content, media_type = image_preview(path)
            else:
                content = render_pdf_page(path, page_number, dpi=150)
                media_type = "image/jpeg"
    except PdfProcessingError as exc:
        raise HTTPException(status_code=exc.code == "PAGE_NOT_FOUND" and 404 or 422, detail=exc.message) from exc
    return Response(
        content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{document_id}/text")
def get_document_text(
    document_id: str,
    page_from: int = Query(1, ge=1),
    page_to: int | None = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_document(db, document_id)
    stmt = select(DocumentPage).where(DocumentPage.document_id == document.id)
    stmt = stmt.where(DocumentPage.page_number >= page_from)
    if page_to:
        stmt = stmt.where(DocumentPage.page_number <= page_to)
    pages = list(db.scalars(stmt.order_by(DocumentPage.page_number)))
    return {
        "document_id": document.id,
        "pages": [
            PageOut(
                page_number=page.page_number,
                text_source=page.text_source,
                ocr_confidence=page.ocr_confidence,
                width=page.width,
                height=page.height,
                error=page.error,
                text=page.text,
            ).model_dump()
            for page in pages
        ],
    }


@router.get("/{document_id}/invoices", response_model=list[InvoiceOut])
def get_document_invoices(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InvoiceOut]:
    from ..presenters import invoice_out

    document = _get_document(db, document_id)
    return [invoice_out(db, invoice) for invoice in document.invoices]


@router.get("/{document_id}/findings", response_model=list[FindingOut])
def get_document_findings(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FindingOut]:
    document = _get_document(db, document_id)
    findings = db.scalars(
        select(Finding)
        .where(Finding.document_id == document.id)
        .order_by(Finding.created_at)
    )
    return [finding_out(finding) for finding in findings]


@router.get("/{document_id}/sheet-rows", response_model=SheetRowsResponse)
def get_sheet_rows(
    document_id: str,
    sheet: str | None = None,
    row_type: str = Query("invoice", pattern="^(invoice|line_item|all)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SheetRowsResponse:
    document = _get_document(db, document_id)
    if document.kind != "spreadsheet":
        raise HTTPException(status_code=400, detail="Document is not a spreadsheet")
    conditions = [SheetRow.document_id == document.id]
    if sheet:
        conditions.append(SheetRow.sheet_name == sheet)
    rows = list(
        db.scalars(
            select(SheetRow)
            .where(*conditions)
            .order_by(SheetRow.sheet_name, SheetRow.row_number)
        )
    )

    def _type(item: SheetRow) -> str:
        return str((item.normalized or {}).get("row_type") or "invoice")

    invoice_rows = [item for item in rows if _type(item) == "invoice"]
    line_item_rows = [item for item in rows if _type(item) == "line_item"]
    selected = (
        rows
        if row_type == "all"
        else invoice_rows
        if row_type == "invoice"
        else line_item_rows
    )
    return SheetRowsResponse(
        items=[
            SheetRowOut(
                id=row.id,
                sheet_name=row.sheet_name,
                row_number=row.row_number,
                data=row.data or {},
                normalized=row.normalized or {},
                warnings=row.warnings or [],
                row_type=_type(row),
                parent_invoice_number=(row.normalized or {}).get(
                    "parent_invoice_number"
                ),
                line_item_count=len((row.normalized or {}).get("line_items") or []),
            )
            for row in selected[offset : offset + limit]
        ],
        total=len(selected),
        invoice_total=len(invoice_rows),
        line_item_total=len(line_item_rows),
    )


@router.post("/{document_id}/reprocess")
def reprocess_document(
    document_id: str,
    payload: ReprocessRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_document(db, document_id)
    job = reset_for_reprocess(db, document)
    record_audit(
        db,
        user,
        "document.reprocess",
        "document",
        document.id,
        {"stage": payload.stage, "job_id": job.id},
        client_ip(request),
    )
    db.commit()
    return {"document_id": document.id, "job_id": job.id, "status": "queued"}


def _approval_blocked_detail(finding_count: int, mismatch_count: int) -> str:
    return (
        f"Cannot approve: {finding_count} open finding(s) and "
        f"{mismatch_count} reconciliation mismatch(es) must be resolved first"
    )


def _document_blockers(
    db: Session, document: Document
) -> tuple[list[Finding], list[Reconciliation]]:
    """Find document-level checks that are not attached to a single invoice."""
    findings = list(
        db.scalars(
            select(Finding).where(
                Finding.document_id == document.id,
                Finding.invoice_id.is_(None),
                Finding.status == "open",
                Finding.severity.in_(["error", "warning"]),
            )
        )
    )
    mismatches = list(
        db.scalars(
            select(Reconciliation).where(
                Reconciliation.matched_document_id == document.id,
                Reconciliation.status == "mismatch",
            )
        )
    )
    return findings, mismatches


@router.post("/{document_id}/approve")
def approve_document(
    document_id: str,
    payload: ApproveRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Approve a document and complete its review.

    PDF/image documents approve all reviewable invoice extractions using the
    per-invoice rules. Spreadsheets have no invoices, so their document-level
    findings and reconciliation mismatches are checked directly. In both cases
    the document is marked completed and a document.approve audit event is
    written.
    """
    document = _get_document(db, document_id)
    approved_ids: list[str] = []

    if document.kind == "spreadsheet":
        blocking = list(
            db.scalars(
                select(Finding).where(
                    Finding.document_id == document.id,
                    Finding.status == "open",
                    Finding.severity.in_(["error", "warning"]),
                )
            )
        )
        mismatches = list(
            db.scalars(
                select(Reconciliation).where(
                    Reconciliation.matched_document_id == document.id,
                    Reconciliation.status == "mismatch",
                )
            )
        )
        if blocking or mismatches:
            raise HTTPException(
                status_code=409,
                detail=_approval_blocked_detail(len(blocking), len(mismatches)),
            )
        document.status = "completed"
        document.stage = "completed"
    else:
        invoices = list(
            db.scalars(select(Invoice).where(Invoice.document_id == document_id))
        )
        reviewable = [invoice for invoice in invoices if invoice.current_extraction_id]
        if not reviewable:
            raise HTTPException(status_code=409, detail="Document has no reviewable invoices")
        document_findings, document_mismatches = _document_blockers(db, document)
        if document_findings or document_mismatches:
            raise HTTPException(
                status_code=409,
                detail=_approval_blocked_detail(
                    len(document_findings), len(document_mismatches)
                ),
            )
        for invoice in reviewable:
            approved_invoice = _approve_invoice(db, invoice, user, payload.note)
            approved_ids.append(approved_invoice.id)

    record_audit(
        db,
        user,
        "document.approve",
        "document",
        document.id,
        {"approved_invoice_ids": approved_ids, "note": payload.note},
        client_ip(request),
    )
    db.commit()
    return {
        "document_id": document.id,
        "status": document.status,
        "approved_invoice_ids": approved_ids,
    }
