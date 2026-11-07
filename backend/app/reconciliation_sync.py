from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Finding, Reconciliation


def _diff_fields(reconciliation: Reconciliation) -> set[str]:
    fields: set[str] = set()
    for diff in reconciliation.diffs or []:
        if isinstance(diff, dict) and diff.get("field"):
            fields.add(str(diff["field"]))
    return fields


def _linked_findings_stmt(reconciliation: Reconciliation):
    """Select the findings that describe the same cross-document difference.

    Reconciliation diffs are also emitted as review findings (V013 for
    PDF↔spreadsheet comparisons, V010 for duplicate invoice numbers), so both
    views must be resolved together.
    """
    if not reconciliation.invoice_id:
        return None
    stmt = select(Finding).where(Finding.invoice_id == reconciliation.invoice_id)
    if reconciliation.match_type == "pdf_pdf":
        return stmt.where(Finding.rule_code == "V010")
    fields = _diff_fields(reconciliation)
    if not fields:
        return None
    return stmt.where(
        Finding.rule_code == "V013",
        Finding.field_path.in_(fields),
    )


def linked_findings(
    db: Session, reconciliation: Reconciliation, *, only_open: bool = False
) -> list[Finding]:
    stmt = _linked_findings_stmt(reconciliation)
    if stmt is None:
        return []
    if only_open:
        stmt = stmt.where(Finding.status == "open")
    return list(db.scalars(stmt))


def dismiss_linked_findings(
    db: Session,
    reconciliation: Reconciliation,
    *,
    user_id: str | None,
    note: str | None,
) -> list[Finding]:
    """Dismiss the findings that belong to a reconciliation decision."""
    findings = linked_findings(db, reconciliation, only_open=True)
    if not findings:
        return []
    now = datetime.now(UTC)
    for finding in findings:
        finding.status = "dismissed"
        if note and not finding.resolution_note:
            finding.resolution_note = note
        finding.resolved_by = user_id
        finding.resolved_at = now
    return findings


def auto_dismiss_acknowledged_reconciliations(
    db: Session, invoice_id: str | None
) -> list[Reconciliation]:
    """Dismiss mismatches once a reviewer resolved all of their findings.

    Reviewers may work from either tab. When every finding for a mismatch is
    already resolved/dismissed, the reconciliation is acknowledged too and
    must stop blocking approval.
    """
    if not invoice_id:
        return []
    mismatches = list(
        db.scalars(
            select(Reconciliation).where(
                Reconciliation.invoice_id == invoice_id,
                Reconciliation.status == "mismatch",
            )
        )
    )
    dismissed: list[Reconciliation] = []
    for reconciliation in mismatches:
        findings = linked_findings(db, reconciliation)
        if not findings:
            # No linked finding (e.g. a manually created reconciliation):
            # keep the explicit reconciliation decision.
            continue
        if any(finding.status == "open" for finding in findings):
            continue
        reconciliation.status = "dismissed"
        dismissed.append(reconciliation)
    return dismissed
