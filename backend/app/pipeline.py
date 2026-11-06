from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import (
    Chunk,
    Document,
    DocumentPage,
    Extraction,
    Finding,
    Invoice,
    LineItem,
    ProcessingJob,
    Reconciliation,
    SheetRow,
)
from .ocr import OCRUnavailableError
from .parsers.grouping import group_invoice_pages
from .parsers.pdf import (
    PdfProcessingError,
    PageExtraction,
    extract_image,
    extract_pdf,
)
from .parsers.spreadsheet import (
    ParsedSheet,
    SpreadsheetError,
    parse_spreadsheet,
    sheets_summary,
)
from .presenters import extraction_out
from .schemas import ExtractionData
from .search import ChunkInput, build_document_chunks, index_chunks
from .storage import StorageError, get_storage
from .utils import (
    normalize_invoice_number,
    normalize_supplier,
    parse_decimal,
)
from .validation import (
    ReconciliationDraft,
    ValidationIssue,
    ValidationResult,
    validate_invoice,
    validate_sheet_document,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class ProcessingFailure(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@contextmanager
def materialize_document(storage_key: str, suffix: str) -> Iterator[Path]:
    storage = get_storage()
    local = storage.local_path(storage_key)
    if local and local.exists():
        yield local
        return
    temp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    temp_path = Path(temp.name)
    temp.close()
    try:
        content = storage.read_bytes(storage_key)
        temp_path.write_bytes(content)
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def enqueue_document(db: Session, document: Document, job_type: str = "process_document") -> ProcessingJob:
    job = ProcessingJob(document_id=document.id, job_type=job_type, status="queued")
    db.add(job)
    document.status = "queued"
    document.stage = "queued"
    document.progress = 0
    document.error_code = None
    document.error_message = None
    db.flush()
    return job


def clear_document_results(db: Session, document: Document) -> None:
    invoice_ids = [
        row[0] for row in db.execute(select(Invoice.id).where(Invoice.document_id == document.id))
    ]
    if invoice_ids:
        db.execute(
            delete(Reconciliation).where(Reconciliation.invoice_id.in_(invoice_ids))
        )
    db.execute(
        delete(Reconciliation).where(
            (Reconciliation.matched_document_id == document.id)
            | (Reconciliation.matched_invoice_id.in_(invoice_ids) if invoice_ids else False)
        )
    )
    db.execute(delete(Finding).where(Finding.document_id == document.id))
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    db.execute(delete(SheetRow).where(SheetRow.document_id == document.id))
    db.execute(delete(Invoice).where(Invoice.document_id == document.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    document.page_count = 0
    document.progress = 0
    db.flush()


def _set_stage(
    db: Session,
    document: Document,
    job: ProcessingJob | None,
    stage: str,
    progress: int | None = None,
) -> None:
    document.stage = stage
    document.status = "processing"
    if progress is not None:
        document.progress = max(0, min(100, progress))
        if job:
            job.progress = document.progress
    db.flush()


def _persist_pages(db: Session, document: Document, pages: list[PageExtraction]) -> list[DocumentPage]:
    records = [
        DocumentPage(
            document_id=document.id,
            page_number=page.page_number,
            text=page.text,
            text_source=page.text_source,
            ocr_confidence=page.ocr_confidence,
            width=page.width,
            height=page.height,
            error=page.error,
        )
        for page in pages
    ]
    db.add_all(records)
    document.page_count = len(pages)
    db.flush()
    return records


def _persist_findings(
    db: Session,
    document: Document,
    invoice: Invoice | None,
    extraction: Extraction | None,
    issues: list[ValidationIssue],
) -> list[Finding]:
    rows: list[Finding] = []
    for issue in issues:
        finding = Finding(
            document_id=document.id,
            invoice_id=issue.invoice_id or (invoice.id if invoice else None),
            extraction_id=extraction.id if extraction else None,
            rule_code=issue.rule_code,
            severity=issue.severity,
            field_path=issue.field_path,
            message=issue.message,
            expected=issue.expected,
            actual=issue.actual,
        )
        db.add(finding)
        rows.append(finding)
    return rows


def _persist_reconciliations(
    db: Session, drafts: list[ReconciliationDraft]
) -> list[Reconciliation]:
    rows: list[Reconciliation] = []
    for draft in drafts:
        exists = db.scalar(
            select(Reconciliation.id).where(
                Reconciliation.invoice_id == draft.invoice_id,
                Reconciliation.match_type == draft.match_type,
                Reconciliation.matched_invoice_id == draft.matched_invoice_id,
                Reconciliation.sheet_row_id == draft.sheet_row_id,
            )
        )
        if exists:
            continue
        row = Reconciliation(
            invoice_id=draft.invoice_id,
            matched_invoice_id=draft.matched_invoice_id,
            matched_document_id=draft.matched_document_id,
            sheet_row_id=draft.sheet_row_id,
            match_type=draft.match_type,
            confidence=draft.confidence,
            diffs=draft.diffs,
            status=draft.status,
        )
        db.add(row)
        rows.append(row)
    return rows


def _persist_extraction(
    db: Session,
    invoice: Invoice,
    outcome,
) -> tuple[Extraction, ExtractionData]:
    data: ExtractionData = outcome.data
    version = (
        db.scalar(
            select(Extraction.version)
            .where(Extraction.invoice_id == invoice.id)
            .order_by(Extraction.version.desc())
            .limit(1)
        )
        or 0
    ) + 1
    extraction = Extraction(
        invoice_id=invoice.id,
        version=version,
        schema_version=data.schema_version,
        prompt_version=outcome.prompt_version,
        model=outcome.model,
        source=outcome.source,
        data=data.model_dump(mode="json"),
        confidence={
            **(outcome.usage or {}),
            "fields": {key: getattr(data, key).confidence for key in data.field_names()},
            "overall": _overall_confidence(data),
        },
        review_status="pending",
    )
    db.add(extraction)
    db.flush()
    for index, item in enumerate(data.line_items, start=1):
        db.add(
            LineItem(
                extraction_id=extraction.id,
                line_no=index,
                description=item.description,
                quantity=parse_decimal(item.quantity),
                unit_price=parse_decimal(item.unit_price),
                amount=parse_decimal(item.amount),
                tax_rate=parse_decimal(item.tax_rate),
                confidence=item.confidence,
                page=item.page,
            )
        )
    invoice.current_extraction_id = extraction.id
    invoice.invoice_number_norm = normalize_invoice_number(getattr(data.invoice_number, "value", None))
    invoice.supplier_norm = normalize_supplier(getattr(data.supplier_name, "value", None))
    db.flush()
    return extraction, data


def _overall_confidence(data: ExtractionData) -> float:
    required = ["invoice_number", "invoice_date", "supplier_name", "total", "currency"]
    return round(sum(getattr(data, key).confidence for key in required) / len(required), 3)


def _required_confidence_ok(data: ExtractionData, threshold: float) -> bool:
    required = ["invoice_number", "invoice_date", "supplier_name", "total", "currency"]
    return all(
        getattr(data, key).value is not None and getattr(data, key).confidence >= threshold
        for key in required
    )


def _finalize_invoice(
    db: Session,
    document: Document,
    invoice: Invoice,
    extraction: Extraction,
    data: ExtractionData,
    result: ValidationResult,
) -> None:
    db.execute(delete(Finding).where(Finding.invoice_id == invoice.id))
    db.execute(delete(Reconciliation).where(Reconciliation.invoice_id == invoice.id))
    db.execute(delete(Reconciliation).where(Reconciliation.matched_invoice_id == invoice.id))
    _persist_findings(db, document, invoice, extraction, result.issues)
    _persist_reconciliations(db, result.reconciliations)
    approved = not result.blocking and _required_confidence_ok(
        data, settings.auto_approve_confidence
    )
    extraction.review_status = "approved" if approved else "pending"
    invoice.status = "completed" if approved else "needs_review"
    db.flush()


def _process_pdf(
    db: Session, document: Document, job: ProcessingJob | None, path: Path, suffix: str
) -> tuple[list[DocumentPage], list[tuple[Invoice, ExtractionData]], list[ChunkInput]]:
    if document.kind == "image":
        _set_stage(db, document, job, "ocr", 20)
        pages = extract_image(path)
    else:
        _set_stage(db, document, job, "ocr", 10)
        total_holder = {"total": 0}

        def progress(page_number: int, total: int, source: str) -> None:
            total_holder["total"] = total
            document.page_count = total
            pct = 15 + int(45 * (page_number / max(total, 1)))
            document.progress = pct
            if job:
                job.progress = pct
            document.stage = "ocr" if source != "digital" else "text_extraction"
            if page_number % 5 == 0 or page_number == total:
                db.commit()

        pages = extract_pdf(path, progress=progress)

    page_records = _persist_pages(db, document, pages)
    page_map = {page.page_number: page for page in pages}
    groups = group_invoice_pages(pages)
    db.commit()

    _set_stage(db, document, job, "extraction", 62)
    invoice_pairs: list[tuple[Invoice, ExtractionData]] = []
    from .extraction.service import extract_invoice

    total_groups = max(len(groups), 1)
    for index, group in enumerate(groups, start=1):
        if group.page_texts:
            group_pages = list(group.page_texts)
        else:
            group_pages = [
                (page_number, page_map[page_number].text)
                for page_number in range(group.page_start, group.page_end + 1)
                if page_number in page_map
            ]
        invoice = Invoice(
            document_id=document.id,
            page_start=group.page_start,
            page_end=group.page_end,
            status="processing",
            grouping_confidence=group.confidence,
        )
        db.add(invoice)
        db.flush()
        try:
            outcome = extract_invoice(group_pages)
        except Exception as exc:
            logger.exception("extraction failed for invoice %s", invoice.id)
            raise ProcessingFailure(
                "EXTRACTION_ERROR", f"Invoice extraction failed: {exc}", retryable=True
            ) from exc
        extraction, data = _persist_extraction(db, invoice, outcome)
        validation = validate_invoice(db, document, invoice, extraction, data)
        _finalize_invoice(db, document, invoice, extraction, data, validation)
        invoice_pairs.append((invoice, data))
        document.progress = 62 + int(20 * (index / total_groups))
        if job:
            job.progress = document.progress
        db.commit()

    # Build chunk inputs before the session closes.
    document_pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    chunk_inputs = build_document_chunks(document_pages, invoice_pairs, [])
    return document_pages, invoice_pairs, chunk_inputs


def _spreadsheet_extra_texts(sheets: list[ParsedSheet]) -> list[tuple[str, str | None]]:
    items: list[tuple[str, str | None]] = []
    for sheet in sheets:
        lines = [f"Spreadsheet sheet: {sheet.name}", "Columns: " + " | ".join(sheet.headers)]
        for row in [*sheet.rows, *sheet.line_items]:
            values = [str(value) for value in row["data"].values() if value not in (None, "")]
            if values:
                lines.append(" | ".join(values))
            if len(lines) > 2500:
                break
        items.append(("\n".join(lines), f"sheet:{sheet.name}"))
    if not items:
        items.append((f"Spreadsheet {sheets_summary(sheets)[:2000]}", "spreadsheet"))
    return items


def _process_spreadsheet(
    db: Session, document: Document, job: ProcessingJob | None, path: Path, suffix: str
) -> tuple[list[ChunkInput], ValidationResult]:
    _set_stage(db, document, job, "spreadsheet_parsing", 30)
    try:
        sheets = parse_spreadsheet(path, suffix)
    except SpreadsheetError:
        raise
    except Exception as exc:
        raise ProcessingFailure("SPREADSHEET_ERROR", f"Spreadsheet parsing failed: {exc}") from exc
    document.page_count = len(sheets)
    db.flush()

    row_records: list[SheetRow] = []
    for sheet in sheets:
        for row in [*sheet.rows, *sheet.line_items]:
            record = SheetRow(
                document_id=document.id,
                sheet_name=sheet.name,
                row_number=row["row_number"],
                data=row["data"],
                normalized=row["normalized"],
                warnings=row["warnings"],
            )
            db.add(record)
            row_records.append(record)
    db.flush()
    _set_stage(db, document, job, "validation", 65)
    validation = validate_sheet_document(db, document, row_records)
    _persist_findings(db, document, None, None, validation.issues)
    _persist_reconciliations(db, validation.reconciliations)
    db.flush()
    chunk_inputs = build_document_chunks([], [], _spreadsheet_extra_texts(sheets))
    return chunk_inputs, validation


def process_document(
    document_id: str, job_id: str | None = None, db: Session | None = None
) -> None:
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if not document:
            raise ProcessingFailure("NOT_FOUND", "Document no longer exists")
        job = db.get(ProcessingJob, job_id) if job_id else None

        clear_document_results(db, document)
        document.status = "processing"
        document.stage = "downloading"
        document.error_code = None
        document.error_message = None
        document.progress = 5
        db.commit()

        suffix = Path(document.original_filename).suffix.lower()
        with materialize_document(document.storage_key, suffix) as path:
            _set_stage(db, document, job, "parsing", 10)
            db.commit()
            if document.kind in {"pdf", "image"}:
                pages, invoice_pairs, chunk_inputs = _process_pdf(
                    db, document, job, path, suffix
                )
            elif document.kind == "spreadsheet":
                chunk_inputs, validation = _process_spreadsheet(db, document, job, path, suffix)
            else:
                raise ProcessingFailure("UNSUPPORTED_TYPE", "Unsupported document kind")

        _set_stage(db, document, job, "indexing", 90)
        db.commit()
        index_chunks(db, document, chunk_inputs)
        db.flush()

        if document.kind in {"pdf", "image"}:
            statuses = [invoice.status for invoice in document.invoices]
            document.status = (
                "completed"
                if statuses and all(status == "completed" for status in statuses)
                else "needs_review"
            )
        else:
            open_findings = list(
                db.scalars(
                    select(Finding).where(
                        Finding.document_id == document.id, Finding.status == "open"
                    )
                )
            )
            has_blocking = any(
                finding.severity in {"error", "warning"} for finding in open_findings
            )
            document.status = "needs_review" if has_blocking else "completed"
        document.stage = "completed"
        document.progress = 100
        document.error_code = None
        document.error_message = None
        if job:
            job.progress = 100
        db.commit()
        logger.info(
            "processed document %s status=%s invoices=%s",
            document.id,
            document.status,
            len(document.invoices),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


def reset_for_reprocess(db: Session, document: Document) -> ProcessingJob:
    clear_document_results(db, document)
    for job in document.jobs:
        if job.status in {"queued", "running", "retry_wait"}:
            job.status = "cancelled"
    document.status = "queued"
    document.stage = "queued"
    document.progress = 0
    document.error_code = None
    document.error_message = None
    db.flush()
    return enqueue_document(db, document)
