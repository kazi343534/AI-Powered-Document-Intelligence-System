from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import SearchResponse
from ..search import SearchFilters, get_embedder, search_documents
from ..models import User
from .deps import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query("", max_length=500),
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid",
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = None,
    supplier: str | None = None,
    currency: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_total: Decimal | None = None,
    max_total: Decimal | None = None,
    has_findings: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchResponse:
    filters = SearchFilters(
        status=status_filter,
        kind=kind,
        supplier=supplier,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        max_total=max_total,
        has_findings=has_findings,
    )
    try:
        hits = search_documents(db, q, mode=mode, filters=filters, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc
    return SearchResponse(query=q, mode=mode, items=hits, total=len(hits))


@router.get("/status/embedding")
def embedding_status(user: User = Depends(get_current_user)) -> dict:
    try:
        provider = get_embedder().name
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    return {"available": True, "provider": provider}
