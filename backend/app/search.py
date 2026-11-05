from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .embeddings import cosine_similarity, get_embedder
from .models import Chunk, Document, Extraction, Finding, Invoice
from .presenters import document_list_item
from .schemas import SearchHit
from .utils import normalize_supplier, parse_decimal

logger = logging.getLogger(__name__)
settings = get_settings()
MAX_SEMANTIC_CHUNKS = 500


@dataclass
class ChunkInput:
    content: str
    page_number: int | None = None
    invoice_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class SearchFilters:
    status: str | None = None
    kind: str | None = None
    supplier: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    has_findings: bool | None = None
    currency: str | None = None


def split_text(text: str, max_chars: int = 1400, overlap: int = 150) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind("\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(start + 1, end - overlap)
    return chunks


def index_chunks(db: Session, document: Document, items: list[ChunkInput]) -> int:
    db.query(Chunk).filter(Chunk.document_id == document.id).delete(synchronize_session=False)
    if not items:
        return 0

    embedder = None
    vectors: list[list[float] | None] = [None] * len(items)
    embeddable = [
        (index, item.content)
        for index, item in enumerate(items)
        if item.content.strip() and index < MAX_SEMANTIC_CHUNKS
    ]
    if embeddable:
        try:
            embedder = get_embedder()
            for offset in range(0, len(embeddable), 32):
                batch = embeddable[offset : offset + 32]
                batch_vectors = embedder.embed_texts([text for _index, text in batch])
                for (item_index, _text), vector in zip(batch, batch_vectors, strict=False):
                    vectors[item_index] = vector
        except Exception as exc:
            logger.warning("embedding indexing failed for %s: %s", document.id, exc)

    for index, item in enumerate(items):
        db.add(
            Chunk(
                document_id=document.id,
                invoice_id=item.invoice_id,
                page_number=item.page_number,
                chunk_index=index,
                content=item.content[:12000],
                embedding=vectors[index],
                meta=item.meta,
            )
        )
    db.flush()
    return len(items)


def _keyword_chunks(db: Session, query: str, limit: int = 80) -> list[Chunk]:
    if settings.is_postgres:
        tsv = func.to_tsvector("english", Chunk.content)
        tsq = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(tsv, tsq).label("rank")
        stmt = (
            select(Chunk)
            .where(tsv.op("@@")(tsq))
            .order_by(rank.desc())
            .limit(limit)
        )
        results = list(db.scalars(stmt))
        if results:
            return results
    pattern = f"%{query}%"
    stmt = (
        select(Chunk)
        .where(or_(Chunk.content.ilike(pattern), Chunk.meta["invoice_number"].as_string().ilike(pattern)))
        .limit(limit)
    )
    return list(db.scalars(stmt))


def _semantic_chunks(db: Session, query: str, limit: int = 80) -> list[Chunk]:
    try:
        query_vector = get_embedder().embed_query(query)
    except Exception as exc:
        logger.warning("query embedding failed: %s", exc)
        return []
    if settings.is_postgres:
        distance = Chunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(Chunk)
            .where(Chunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        return list(db.scalars(stmt))

    chunks = list(
        db.scalars(select(Chunk).where(Chunk.embedding.is_not(None)).limit(MAX_SEMANTIC_CHUNKS))
    )
    scored = [
        (cosine_similarity(query_vector, chunk.embedding), chunk)
        for chunk in chunks
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for score, chunk in scored[:limit] if score > 0.01]


def _supplier_match(db: Session, document: Document, supplier: str) -> bool:
    normalized = normalize_supplier(supplier)
    if not normalized:
        return True
    for invoice in document.invoices:
        if invoice.supplier_norm and normalized in invoice.supplier_norm:
            return True
        if invoice.current_extraction_id:
            extraction = db.get(Extraction, invoice.current_extraction_id)
            if extraction:
                value = (extraction.data.get("supplier_name") or {}).get("value") or ""
                if normalized in (normalize_supplier(value) or ""):
                    return True
    return False


def _currency_match(db: Session, document: Document, currency: str) -> bool:
    for invoice in document.invoices:
        if not invoice.current_extraction_id:
            continue
        extraction = db.get(Extraction, invoice.current_extraction_id)
        if extraction and (extraction.data.get("currency") or {}).get("value") == currency.upper():
            return True
    return False


def _total_range_match(db: Session, document: Document, filters: SearchFilters) -> bool:
    if filters.min_total is None and filters.max_total is None:
        return True
    for invoice in document.invoices:
        if not invoice.current_extraction_id:
            continue
        extraction = db.get(Extraction, invoice.current_extraction_id)
        if not extraction:
            continue
        total = parse_decimal((extraction.data.get("total") or {}).get("value"))
        if total is None:
            continue
        if filters.min_total is not None and total < filters.min_total:
            continue
        if filters.max_total is not None and total > filters.max_total:
            continue
        return True
    return False


def _matches_filters(db: Session, document: Document, filters: SearchFilters) -> bool:
    if document.deleted_at is not None:
        return False
    if filters.status and document.status != filters.status:
        return False
    if filters.kind and document.kind != filters.kind:
        return False
    if filters.date_from and document.created_at.date() < filters.date_from:
        return False
    if filters.date_to and document.created_at.date() > filters.date_to:
        return False
    if filters.supplier and not _supplier_match(db, document, filters.supplier):
        return False
    if filters.has_findings:
        count = db.scalar(
            select(func.count(Finding.id)).where(
                Finding.document_id == document.id, Finding.status == "open"
            )
        )
        if not count:
            return False
    if filters.currency and not _currency_match(db, document, filters.currency):
        return False
    return _total_range_match(db, document, filters)


def _snippet(content: str, query: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return ""
    if not query:
        return text[:limit]
    lowered = text.lower()
    positions = [lowered.find(term) for term in query.lower().split() if term]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - 90)
    end = min(len(text), start + limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def search_documents(
    db: Session,
    query: str,
    mode: str = "hybrid",
    filters: SearchFilters | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    filters = filters or SearchFilters()
    query = (query or "").strip()
    if not query:
        stmt = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
        if filters.kind:
            stmt = stmt.where(Document.kind == filters.kind)
        if filters.status:
            stmt = stmt.where(Document.status == filters.status)
        docs = [doc for doc in db.scalars(stmt.limit(200)) if _matches_filters(db, doc, filters)]
        return [
            SearchHit(
                document_id=doc.id,
                document=document_list_item(db, doc),
                score=1.0,
                snippet="Matches the selected filters",
                page_number=None,
                invoice_id=None,
                match="filter",
            )
            for doc in docs[:limit]
        ]

    keyword: list[Chunk] = []
    semantic: list[Chunk] = []
    if mode in {"keyword", "hybrid"}:
        keyword = _keyword_chunks(db, query)
    if mode in {"semantic", "hybrid"}:
        semantic = _semantic_chunks(db, query)
    if mode == "hybrid" and not keyword:
        keyword = _keyword_chunks(db, query)
    if mode == "hybrid" and not semantic:
        semantic = []

    scores: dict[str, float] = {}
    chunk_map: dict[str, Chunk] = {}
    matches: dict[str, str] = {}
    for rank, chunk in enumerate(keyword):
        chunk_map[chunk.id] = chunk
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (60 + rank)
        matches[chunk.id] = "keyword"
    for rank, chunk in enumerate(semantic):
        chunk_map[chunk.id] = chunk
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (60 + rank)
        matches[chunk.id] = "semantic" if matches.get(chunk.id) != "keyword" else "hybrid"

    if not scores:
        return []

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    max_score = ordered[0][1] or 1.0
    hits: list[SearchHit] = []
    used_documents: set[str] = set()
    document_cache: dict[str, Document | None] = {}
    for chunk_id, score in ordered:
        chunk = chunk_map[chunk_id]
        if chunk.document_id in used_documents:
            continue
        if chunk.document_id not in document_cache:
            document_cache[chunk.document_id] = db.get(Document, chunk.document_id)
        document = document_cache[chunk.document_id]
        if not document or not _matches_filters(db, document, filters):
            continue
        used_documents.add(document.id)
        hits.append(
            SearchHit(
                document_id=document.id,
                document=document_list_item(db, document),
                score=round(score / max_score, 4),
                snippet=_snippet(chunk.content, query),
                page_number=chunk.page_number,
                invoice_id=chunk.invoice_id,
                match=matches.get(chunk_id, "hybrid"),
            )
        )
        if len(hits) >= limit:
            break
    return hits


def build_document_chunks(
    pages: list, invoices: list[tuple[Invoice, object]], extra_texts: list[tuple[str, str | None]]
) -> list[ChunkInput]:
    items: list[ChunkInput] = []
    for page in pages:
        for index, part in enumerate(split_text(page.text)):
            items.append(
                ChunkInput(
                    content=part,
                    page_number=page.page_number,
                    meta={"source": "page", "part": index, "text_source": page.text_source},
                )
            )
    for invoice, data in invoices:
        number = getattr(data.invoice_number, "value", None) or "unknown"
        supplier = getattr(data.supplier_name, "value", None) or "unknown supplier"
        total = getattr(data.total, "value", None)
        currency = getattr(data.currency, "value", None) or ""
        date = getattr(data.invoice_date, "value", None) or ""
        summary = (
            f"Invoice {number} from {supplier}. Date: {date}. Total: {currency} {total or ''}. "
        )
        if getattr(data, "line_items", None):
            summary += "Line items: " + "; ".join(
                f"{item.description} ({item.amount or ''})" for item in data.line_items[:20]
            )
        items.append(
            ChunkInput(
                content=summary,
                page_number=invoice.page_start,
                invoice_id=invoice.id,
                meta={"source": "invoice_summary", "invoice_number": number},
            )
        )
    for content, label in extra_texts:
        for index, part in enumerate(split_text(content)):
            items.append(
                ChunkInput(
                    content=part,
                    page_number=None,
                    meta={"source": label or "spreadsheet", "part": index},
                )
            )
    return items
