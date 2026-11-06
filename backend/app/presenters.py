from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, Extraction, Finding, Invoice, ProcessingJob, Reconciliation
from .schemas import (
    DocumentDetail,
    DocumentListItem,
    DocumentSummary,
    ExtractionOut,
    FindingOut,
    InvoiceOut,
    JobOut,
    LineItemOut,
    PageOut,
    ReconciliationOut,
)


def finding_out(finding: Finding) -> FindingOut:
    return FindingOut(
        id=finding.id,
        document_id=finding.document_id,
        invoice_id=finding.invoice_id,
        extraction_id=finding.extraction_id,
        rule_code=finding.rule_code,
        severity=finding.severity,
        field_path=finding.field_path,
        message=finding.message,
        expected=finding.expected,
        actual=finding.actual,
        status=finding.status,
        resolution_note=finding.resolution_note,
        created_at=finding.created_at,
    )


def job_out(job: ProcessingJob) -> JobOut:
    return JobOut(
        id=job.id,
        document_id=job.document_id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        progress=job.progress,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def extraction_out(extraction: Extraction) -> ExtractionOut:
    line_items = [
        LineItemOut(
            id=item.id,
            line_no=item.line_no,
            description=item.description,
            quantity=str(item.quantity) if item.quantity is not None else None,
            unit_price=str(item.unit_price) if item.unit_price is not None else None,
            amount=str(item.amount) if item.amount is not None else None,
            tax_rate=str(item.tax_rate) if item.tax_rate is not None else None,
            confidence=item.confidence,
            page=item.page,
        )
        for item in extraction.line_items
    ]
    return ExtractionOut(
        id=extraction.id,
        invoice_id=extraction.invoice_id,
        version=extraction.version,
        schema_version=extraction.schema_version,
        prompt_version=extraction.prompt_version,
        model=extraction.model,
        source=extraction.source,
        data=extraction.data,
        confidence=extraction.confidence,
        review_status=extraction.review_status,
        reviewed_at=extraction.reviewed_at,
        review_note=extraction.review_note,
        created_at=extraction.created_at,
        line_items=line_items,
    )


def reconciliation_out(item: Reconciliation) -> ReconciliationOut:
    return ReconciliationOut(
        id=item.id,
        invoice_id=item.invoice_id,
        matched_invoice_id=item.matched_invoice_id,
        matched_document_id=item.matched_document_id,
        sheet_row_id=item.sheet_row_id,
        match_type=item.match_type,
        confidence=item.confidence,
        diffs=item.diffs or [],
        status=item.status,
        created_at=item.created_at,
    )


def invoice_out(
    db: Session, invoice: Invoice, include_findings: bool = True
) -> InvoiceOut:
    extraction = (
        db.get(Extraction, invoice.current_extraction_id)
        if invoice.current_extraction_id
        else None
    )
    findings: list[FindingOut] = []
    if include_findings:
        findings = [
            finding_out(item)
            for item in db.scalars(
                select(Finding)
                .where(Finding.invoice_id == invoice.id, Finding.status == "open")
                .order_by(Finding.created_at)
            )
        ]
    return InvoiceOut(
        id=invoice.id,
        document_id=invoice.document_id,
        page_start=invoice.page_start,
        page_end=invoice.page_end,
        status=invoice.status,
        grouping_confidence=invoice.grouping_confidence,
        current_extraction=extraction_out(extraction) if extraction else None,
        findings=findings,
    )


def _summary(db: Session, document: Document) -> DocumentSummary | None:
    for invoice in document.invoices:
        extraction = (
            db.get(Extraction, invoice.current_extraction_id)
            if invoice.current_extraction_id
            else None
        )
        if not extraction:
            continue
        data = extraction.data or {}
        return DocumentSummary(
            invoice_number=(data.get("invoice_number") or {}).get("value"),
            supplier_name=(data.get("supplier_name") or {}).get("value"),
            total=(data.get("total") or {}).get("value"),
            currency=(data.get("currency") or {}).get("value"),
            confidence=(extraction.confidence or {}).get("overall"),
            review_status=extraction.review_status,
        )
    return None


def document_list_item(db: Session, document: Document) -> DocumentListItem:
    open_findings = db.scalar(
        select(Finding)
        .where(Finding.document_id == document.id, Finding.status == "open")
        .limit(1)
    )
    finding_count = len(
        list(
            db.scalars(
                select(Finding.id).where(
                    Finding.document_id == document.id, Finding.status == "open"
                )
            )
        )
    )
    return DocumentListItem(
        id=document.id,
        original_filename=document.original_filename,
        kind=document.kind,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        status=document.status,
        stage=document.stage,
        page_count=document.page_count,
        progress=document.progress,
        error_code=document.error_code,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        invoice_count=len(document.invoices),
        finding_count=finding_count if open_findings else 0,
        summary=_summary(db, document),
    )


def document_detail(db: Session, document: Document, include_text: bool = False) -> DocumentDetail:
    base = document_list_item(db, document)
    invoice_ids = [invoice.id for invoice in document.invoices]
    reconciliations: list[Reconciliation] = []
    if invoice_ids:
        reconciliations.extend(
            db.scalars(
                select(Reconciliation).where(
                    (Reconciliation.invoice_id.in_(invoice_ids))
                    | (Reconciliation.matched_document_id == document.id)
                )
            )
        )
    findings = [
        finding_out(item)
        for item in db.scalars(
            select(Finding)
            .where(Finding.document_id == document.id)
            .order_by(Finding.created_at)
        )
    ]
    jobs = [
        job_out(item)
        for item in db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document.id)
            .order_by(ProcessingJob.created_at.desc())
        )
    ]
    return DocumentDetail(
        **base.model_dump(),
        pages=[
            PageOut(
                page_number=page.page_number,
                text_source=page.text_source,
                ocr_confidence=page.ocr_confidence,
                width=page.width,
                height=page.height,
                error=page.error,
                text=page.text if include_text else None,
            )
            for page in document.pages
        ],
        invoices=[
            invoice_out(db, invoice, include_findings=False) for invoice in document.invoices
        ],
        findings=findings,
        jobs=jobs,
        reconciliations=[reconciliation_out(item) for item in reconciliations],
    )
