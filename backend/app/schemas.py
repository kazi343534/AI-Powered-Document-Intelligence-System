from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------------------
# Extraction contract
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    page: int | None = None
    quote: str | None = None


class FieldValue(BaseModel):
    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: Evidence | None = None
    reason: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, value):
        if value is None or isinstance(value, str):
            return value
        return str(value)


class ExtractionLineItem(BaseModel):
    description: str = ""
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    tax_rate: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    page: int | None = None

    @field_validator("quantity", "unit_price", "amount", "tax_rate", mode="before")
    @classmethod
    def _coerce_number_fields(cls, value):
        if value is None or isinstance(value, str):
            return value
        return str(value)

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_description(cls, value):
        if value is None:
            return ""
        return str(value)


class ExtractionData(BaseModel):
    schema_version: str = "1.0"
    document_type: str = "invoice"
    invoice_number: FieldValue = Field(default_factory=FieldValue)
    invoice_date: FieldValue = Field(default_factory=FieldValue)
    supplier_name: FieldValue = Field(default_factory=FieldValue)
    supplier_tax_id: FieldValue = Field(default_factory=FieldValue)
    customer_name: FieldValue = Field(default_factory=FieldValue)
    currency: FieldValue = Field(default_factory=FieldValue)
    subtotal: FieldValue = Field(default_factory=FieldValue)
    tax: FieldValue = Field(default_factory=FieldValue)
    total: FieldValue = Field(default_factory=FieldValue)
    line_items: list[ExtractionLineItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def field_names(self) -> list[str]:
        return [
            "invoice_number",
            "invoice_date",
            "supplier_name",
            "customer_name",
            "currency",
            "subtotal",
            "tax",
            "total",
        ]


# ---------------------------------------------------------------------------
# API resources
# ---------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    invoice_number: str | None = None
    supplier_name: str | None = None
    total: str | None = None
    currency: str | None = None
    confidence: float | None = None
    review_status: str | None = None


class DocumentListItem(BaseModel):
    id: str
    original_filename: str
    kind: str
    mime_type: str
    size_bytes: int
    status: str
    stage: str
    page_count: int
    progress: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    invoice_count: int = 0
    finding_count: int = 0
    summary: DocumentSummary | None = None
    duplicate: bool = False


class PageOut(BaseModel):
    page_number: int
    text_source: str
    ocr_confidence: float | None = None
    width: int = 0
    height: int = 0
    error: str | None = None
    text: str | None = None


class LineItemOut(BaseModel):
    id: str
    line_no: int
    description: str
    quantity: str | None
    unit_price: str | None
    amount: str | None
    tax_rate: str | None
    confidence: float
    page: int | None


class ExtractionOut(BaseModel):
    id: str
    invoice_id: str
    version: int
    schema_version: str
    prompt_version: str
    model: str
    source: str
    data: dict[str, Any]
    confidence: dict[str, Any]
    review_status: str
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime
    line_items: list[LineItemOut] = Field(default_factory=list)


class FindingOut(BaseModel):
    id: str
    document_id: str
    invoice_id: str | None
    extraction_id: str | None
    rule_code: str
    severity: str
    field_path: str
    message: str
    expected: str | None
    actual: str | None
    status: str
    resolution_note: str | None
    created_at: datetime


class InvoiceOut(BaseModel):
    id: str
    document_id: str
    page_start: int
    page_end: int
    status: str
    grouping_confidence: float
    current_extraction: ExtractionOut | None = None
    findings: list[FindingOut] = Field(default_factory=list)


class JobOut(BaseModel):
    id: str
    document_id: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ReconciliationOut(BaseModel):
    id: str
    invoice_id: str
    matched_invoice_id: str | None
    matched_document_id: str | None
    sheet_row_id: str | None
    match_type: str
    confidence: float
    diffs: list[dict[str, Any]]
    status: str
    created_at: datetime


class DocumentDetail(DocumentListItem):
    pages: list[PageOut] = Field(default_factory=list)
    invoices: list[InvoiceOut] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    jobs: list[JobOut] = Field(default_factory=list)
    reconciliations: list[ReconciliationOut] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    limit: int
    offset: int


class UploadRejected(BaseModel):
    filename: str
    code: str
    message: str


class UploadResponse(BaseModel):
    documents: list[DocumentListItem]
    rejected: list[UploadRejected] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class CorrectionRequest(BaseModel):
    changes: dict[str, Any]
    reason: str | None = None

    @field_validator("changes")
    @classmethod
    def _reject_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("changes must contain at least one field")
        return value


class ReviewRequest(BaseModel):
    action: Literal["approve", "reopen"]
    note: str | None = None


class ApproveRequest(BaseModel):
    note: str | None = None


class ReprocessRequest(BaseModel):
    stage: Literal["all", "extract"] = "all"


class FindingUpdateRequest(BaseModel):
    status: Literal["resolved", "dismissed"]
    note: str | None = None


class SearchHit(BaseModel):
    document_id: str
    document: DocumentListItem
    score: float
    snippet: str
    page_number: int | None = None
    invoice_id: str | None = None
    match: str


class SearchResponse(BaseModel):
    query: str
    mode: str
    items: list[SearchHit]
    total: int


class DashboardStats(BaseModel):
    documents: dict[str, int]
    kinds: dict[str, int]
    findings: dict[str, int]
    recent_documents: list[DocumentListItem]
    queue_depth: int
    avg_processing_seconds: float | None
    total_documents: int
    needs_review: int
    failed: int


class MetaResponse(BaseModel):
    app: str
    environment: str
    ai_enabled: bool
    ai_model: str | None
    ocr_engine: str
    embedding_provider: str
    storage_backend: str
    supported_extensions: list[str]
    max_file_mb: int


class SheetRowOut(BaseModel):
    id: str
    sheet_name: str
    row_number: int
    data: dict[str, Any]
    normalized: dict[str, Any]
    warnings: list[Any]


class SheetRowsResponse(BaseModel):
    items: list[SheetRowOut]
    total: int
