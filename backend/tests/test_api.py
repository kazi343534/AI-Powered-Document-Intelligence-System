"""End-to-end API tests: auth, uploads, findings, corrections, search, jobs."""

from pathlib import Path

CROSS_VERIFICATION_WORKBOOK = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "invoice_test_suite_cross_verification.xlsx"
)


class TestAuth:
    def test_login_demo(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@docintel.local", "password": "admin12345"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "token" in body
        assert body["user"]["email"] == "admin@docintel.local"
        assert body["user"]["role"] == "admin"

    def test_login_wrong_password(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@docintel.local", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_me_requires_auth(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_me_with_token(self, client, auth_headers):
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["email"] == "admin@docintel.local"


class TestUpload:
    def test_upload_pdf(self, client, auth_headers, make_pdf):
        with open(make_pdf, "rb") as handle:
            response = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        assert response.status_code == 202, response.text
        body = response.json()
        assert len(body["documents"]) == 1
        assert body["documents"][0]["original_filename"] == "invoice.pdf"
        assert body["documents"][0]["kind"] == "pdf"

    def test_upload_rejects_unsupported_type(self, client, auth_headers, tmp_path):
        bad = tmp_path / "notes.txt"
        bad.write_text("hello")
        with open(bad, "rb") as handle:
            response = client.post(
                "/api/v1/documents",
                files={"files": ("notes.txt", handle, "text/plain")},
                headers=auth_headers,
            )
        assert response.status_code == 202
        body = response.json()
        assert len(body["rejected"]) == 1
        assert body["rejected"][0]["code"] == "UNSUPPORTED_TYPE"

    def test_upload_duplicate_is_flagged(self, client, auth_headers, make_pdf):
        with open(make_pdf, "rb") as handle:
            first = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        assert first.status_code == 202
        # Re-upload same bytes -> duplicate
        with open(make_pdf, "rb") as handle:
            second = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        assert second.status_code == 202
        body = second.json()
        assert body["documents"][0].get("duplicate") is True

    def test_upload_requires_auth(self, client, make_pdf):
        with open(make_pdf, "rb") as handle:
            response = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
            )
        assert response.status_code in (401, 403)


class TestDocumentsListAndDetail:
    def test_list_documents(self, client, auth_headers, make_pdf):
        with open(make_pdf, "rb") as handle:
            client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        response = client.get("/api/v1/documents?limit=10", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert len(body["items"]) >= 1

    def test_document_detail(self, client, auth_headers, make_pdf):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        response = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
        assert response.status_code == 200
        detail = response.json()
        assert detail["id"] == doc_id
        assert "pages" in detail
        assert "invoices" in detail
        assert "jobs" in detail

    def test_document_text(self, client, auth_headers, make_pdf, process_jobs):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        response = client.get(
            f"/api/v1/documents/{doc_id}/text?page_from=1&page_to=1",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["pages"]) == 1
        assert "INVOICE" in body["pages"][0]["text"]


class TestFindings:
    def test_findings_list_and_update(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        from app.models import Finding

        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        db.add(
            Finding(
                document_id=doc_id,
                invoice_id=detail["invoices"][0]["id"],
                rule_code="V999",
                severity="warning",
                field_path="total",
                message="Synthetic review finding",
            )
        )
        db.commit()

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        findings = detail.get("findings", [])
        assert len(findings) > 0, "expected the synthetic finding in document detail"

        finding_id = findings[0]["id"]
        response = client.patch(
            f"/api/v1/findings/{finding_id}",
            json={"status": "resolved", "note": "test resolution"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert response.json()["resolution_note"] == "test resolution"


class TestSearch:
    def test_search_hybrid(self, client, auth_headers, make_pdf, process_jobs):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        response = client.get(
            "/api/v1/search?q=INV-2024-0042&mode=hybrid&limit=5",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "hybrid"
        assert body["total"] >= 1

    def test_search_requires_auth(self, client):
        response = client.get("/api/v1/search?q=x")
        assert response.status_code in (401, 403)


class TestReprocessAndJobs:
    def test_reprocess_queues_job(self, client, auth_headers, make_pdf):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        response = client.post(
            f"/api/v1/documents/{doc_id}/reprocess",
            json={"stage": "all"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "queued"

    def test_list_jobs(self, client, auth_headers):
        response = client.get("/api/v1/jobs", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestMeta:
    def test_meta_endpoint(self, client, auth_headers):
        response = client.get("/api/v1/meta", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["app"] == "DocIntel"
        assert "storage_backend" in body


class TestCorrections:
    def test_correct_extraction_creates_new_version(
        self, client, auth_headers, make_pdf, process_jobs
    ):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        invoice = detail["invoices"][0]
        extraction = invoice["current_extraction"]
        assert extraction is not None
        invoice_id = invoice["id"]
        extraction_id = extraction["id"]

        response = client.patch(
            f"/api/v1/invoices/{invoice_id}/extractions/{extraction_id}",
            json={
                "changes": {"total": "999.00"},
                "reason": "test correction",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["version"] == extraction["version"] + 1
        assert body["data"]["total"]["value"] == "999.00"

        # The correction history should record the change.
        corrections = client.get(
            f"/api/v1/invoices/{invoice_id}/corrections", headers=auth_headers
        ).json()
        assert any(c["field_path"] == "total" for c in corrections)


class TestWorkerRetry:
    def test_retry_requeues_failed_job(self, client, auth_headers, db):
        from app.models import Document, ProcessingJob

        document = Document(
            original_filename="failed.pdf",
            storage_key="documents/xx/failed.pdf",
            mime_type="application/pdf",
            kind="pdf",
            size_bytes=100,
            sha256="deadbeef",
            status="failed",
            stage="failed",
        )
        db.add(document)
        db.flush()
        job = ProcessingJob(
            document_id=document.id,
            job_type="process_document",
            status="failed",
            attempts=1,
            max_attempts=3,
            progress=0,
            error_code="TEST_FAIL",
            error_message="forced failure",
        )
        db.add(job)
        db.commit()
        job_id = job.id

        response = client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "queued"
        assert response.json()["error_code"] is None


class TestApprove:
    @staticmethod
    def _add_open_finding(db, detail):
        from app.models import Finding

        finding = Finding(
            document_id=detail["id"],
            invoice_id=detail["invoices"][0]["id"],
            rule_code="V999",
            severity="warning",
            field_path="total",
            message="Synthetic review finding",
        )
        db.add(finding)
        db.commit()
        return finding

    def test_approve_blocks_when_findings_open(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        self._add_open_finding(db, detail)

        response = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "should be blocked"},
            headers=auth_headers,
        )
        assert response.status_code == 409, response.text
        assert "1 open finding" in response.text

    def test_approve_completes_document_when_findings_resolved(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        self._add_open_finding(db, detail)
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        for finding in detail.get("findings") or []:
            response = client.patch(
                f"/api/v1/findings/{finding['id']}",
                json={"status": "resolved"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text

        response = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "test approval"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["document_id"] == doc_id
        assert body["status"] == "completed"
        assert len(body["approved_invoice_ids"]) >= 1


class TestReconciliationDismissal:
    def test_dismiss_mismatch_unblocks_document_approval(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        from app.models import Reconciliation

        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        for finding in detail.get("findings") or []:
            response = client.patch(
                f"/api/v1/findings/{finding['id']}",
                json={"status": "resolved"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text

        reconciliation = Reconciliation(
            invoice_id=detail["invoices"][0]["id"],
            match_type="pdf_sheet",
            confidence=0.95,
            diffs=[
                {
                    "field": "total",
                    "invoice_value": "150.00",
                    "sheet_value": "999.00",
                    "severity": "error",
                }
            ],
            status="mismatch",
        )
        db.add(reconciliation)
        db.commit()
        reconciliation_id = reconciliation.id

        blocked = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "blocked by mismatch"},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "1 reconciliation mismatch" in blocked.text

        updated = client.patch(
            f"/api/v1/reconciliations/{reconciliation_id}",
            json={"status": "dismissed", "note": "known timing difference"},
            headers=auth_headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "dismissed"

        approved = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "approved after dismissal"},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"

    def test_resolving_linked_findings_dismisses_reconciliation(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        """Dismissing the findings for a mismatch must also clear the mismatch.

        Reviewers can work from either the Findings or Reconciliation tab; the
        same difference is stored in both places and must not block approval
        twice.
        """
        from app.models import Finding, Reconciliation

        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        invoice_id = detail["invoices"][0]["id"]
        for finding in detail.get("findings") or []:
            response = client.patch(
                f"/api/v1/findings/{finding['id']}",
                json={"status": "resolved"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text

        reconciliation = Reconciliation(
            invoice_id=invoice_id,
            match_type="pdf_sheet",
            confidence=0.95,
            diffs=[
                {
                    "field": "total",
                    "invoice_value": "150.00",
                    "sheet_value": "999.00",
                    "severity": "error",
                }
            ],
            status="mismatch",
        )
        db.add(reconciliation)
        db.flush()
        finding = Finding(
            document_id=doc_id,
            invoice_id=invoice_id,
            rule_code="V013",
            severity="error",
            field_path="total",
            message="Total differs between the PDF invoice and the spreadsheet ledger",
            expected="150.00",
            actual="999.00",
        )
        db.add(finding)
        db.commit()
        reconciliation_id = reconciliation.id

        blocked = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "blocked by mismatch"},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "1 reconciliation mismatch" in blocked.text

        resolved = client.patch(
            f"/api/v1/findings/{finding.id}",
            json={"status": "dismissed", "note": "known test data difference"},
            headers=auth_headers,
        )
        assert resolved.status_code == 200, resolved.text

        recs = client.get(
            "/api/v1/reconciliations",
            params={"invoice_id": invoice_id},
            headers=auth_headers,
        ).json()
        assert any(
            item["id"] == reconciliation_id and item["status"] == "dismissed"
            for item in recs
        )

        approved = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "approved after findings resolved"},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"

    def test_dismissing_reconciliation_dismisses_linked_findings(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        from app.models import Finding, Reconciliation

        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)

        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        invoice_id = detail["invoices"][0]["id"]
        reconciliation = Reconciliation(
            invoice_id=invoice_id,
            match_type="pdf_sheet",
            confidence=0.95,
            diffs=[
                {
                    "field": "tax",
                    "invoice_value": "30.00",
                    "sheet_value": "12.00",
                    "severity": "warning",
                }
            ],
            status="mismatch",
        )
        db.add(reconciliation)
        db.flush()
        finding = Finding(
            document_id=doc_id,
            invoice_id=invoice_id,
            rule_code="V013",
            severity="warning",
            field_path="tax",
            message="Tax differs between the PDF invoice and the spreadsheet ledger",
            expected="30.00",
            actual="12.00",
        )
        db.add(finding)
        db.commit()
        reconciliation_id = reconciliation.id

        updated = client.patch(
            f"/api/v1/reconciliations/{reconciliation_id}",
            json={"status": "dismissed", "note": "rounding difference"},
            headers=auth_headers,
        )
        assert updated.status_code == 200, updated.text

        findings = client.get(
            "/api/v1/findings",
            params={"invoice_id": invoice_id},
            headers=auth_headers,
        ).json()
        assert any(
            item["id"] == finding.id and item["status"] == "dismissed"
            for item in findings
        )

    def test_other_document_findings_do_not_block_invoice_approval(
        self, client, auth_headers, make_pdf, process_jobs, db
    ):
        """Spreadsheet-side findings belong to the spreadsheet's review, not the PDF."""
        import secrets

        from app.models import Document, Finding

        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()

        sheet = Document(
            original_filename="ledger.csv",
            storage_key="documents/aa/ledger.csv",
            mime_type="text/csv",
            kind="spreadsheet",
            size_bytes=10,
            sha256=secrets.token_hex(32),
            status="needs_review",
            stage="review_required",
            page_count=1,
        )
        db.add(sheet)
        db.flush()
        db.add(
            Finding(
                document_id=sheet.id,
                invoice_id=detail["invoices"][0]["id"],
                rule_code="V013",
                severity="error",
                field_path="sheet.row.total",
                message="Spreadsheet row total differs from the PDF invoice",
            )
        )
        db.commit()

        approved = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "PDF itself has no findings"},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"

        sheet_blocked = client.post(
            f"/api/v1/documents/{sheet.id}/approve",
            json={"note": "spreadsheet finding is visible here"},
            headers=auth_headers,
        )
        assert sheet_blocked.status_code == 409, sheet_blocked.text
        assert "1 open finding" in sheet_blocked.text


class TestSpreadsheetApproval:
    @staticmethod
    def _create_spreadsheet(db):
        import secrets

        from app.models import Document

        document = Document(
            original_filename="ledger.csv",
            storage_key="documents/aa/ledger.csv",
            mime_type="text/csv",
            kind="spreadsheet",
            size_bytes=10,
            sha256=secrets.token_hex(32),
            status="needs_review",
            stage="review_required",
            page_count=1,
        )
        db.add(document)
        db.commit()
        return document

    def test_approve_spreadsheet_without_invoices(self, client, auth_headers, db):
        document = self._create_spreadsheet(db)
        response = client.post(
            f"/api/v1/documents/{document.id}/approve",
            json={"note": "spreadsheet approved"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["approved_invoice_ids"] == []

        detail = client.get(
            f"/api/v1/documents/{document.id}", headers=auth_headers
        ).json()
        assert detail["status"] == "completed"
        assert detail["invoices"] == []

    def test_spreadsheet_blocks_blocking_findings(self, client, auth_headers, db):
        from app.models import Finding

        document = self._create_spreadsheet(db)
        finding = Finding(
            document_id=document.id,
            rule_code="V014",
            severity="warning",
            field_path="row.total",
            message="Spreadsheet row subtotal + tax does not equal total",
        )
        db.add(finding)
        db.commit()

        blocked = client.post(
            f"/api/v1/documents/{document.id}/approve",
            json={"note": "blocked"},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "1 open finding" in blocked.text

        resolved = client.patch(
            f"/api/v1/findings/{finding.id}",
            json={"status": "dismissed"},
            headers=auth_headers,
        )
        assert resolved.status_code == 200, resolved.text

        approved = client.post(
            f"/api/v1/documents/{document.id}/approve",
            json={"note": "approved after dismissal"},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text

    def test_spreadsheet_mismatch_blocks_until_dismissed(
        self, client, auth_headers, db, make_pdf, process_jobs
    ):
        from app.models import Reconciliation

        document = self._create_spreadsheet(db)
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        pdf_id = created.json()["documents"][0]["id"]
        process_jobs(pdf_id)
        pdf_detail = client.get(
            f"/api/v1/documents/{pdf_id}", headers=auth_headers
        ).json()

        reconciliation = Reconciliation(
            invoice_id=pdf_detail["invoices"][0]["id"],
            matched_document_id=document.id,
            match_type="pdf_sheet",
            confidence=0.95,
            diffs=[
                {
                    "field": "total",
                    "invoice_value": "150.00",
                    "sheet_value": "999.00",
                    "severity": "error",
                }
            ],
            status="mismatch",
        )
        db.add(reconciliation)
        db.commit()

        blocked = client.post(
            f"/api/v1/documents/{document.id}/approve",
            json={"note": "blocked by sheet mismatch"},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "1 reconciliation mismatch" in blocked.text

        dismissed = client.patch(
            f"/api/v1/reconciliations/{reconciliation.id}",
            json={"status": "dismissed", "note": "row belongs to a different period"},
            headers=auth_headers,
        )
        assert dismissed.status_code == 200, dismissed.text

        approved = client.post(
            f"/api/v1/documents/{document.id}/approve",
            json={"note": "approved after dismissal"},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text


class TestCrossVerificationWorkbook:
    def _upload(self, client, auth_headers):
        with open(CROSS_VERIFICATION_WORKBOOK, "rb") as handle:
            response = client.post(
                "/api/v1/documents",
                files={
                    "files": (
                        CROSS_VERIFICATION_WORKBOOK.name,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                headers=auth_headers,
            )
        assert response.status_code == 202, response.text
        document = response.json()["documents"][0]
        assert document["kind"] == "spreadsheet"
        return document["id"]

    def test_invoice_and_line_item_records(
        self, client, auth_headers, process_jobs
    ):
        document_id = self._upload(client, auth_headers)
        process_jobs(document_id)

        response = client.get(
            f"/api/v1/documents/{document_id}/sheet-rows", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invoice_total"] == 14
        assert body["line_item_total"] == 20
        assert body["total"] == 14
        assert len(body["items"]) == 14
        assert all(item["row_type"] == "invoice" for item in body["items"])
        assert {item["sheet_name"] for item in body["items"]} == {
            "Master_PO_Ledger",
            "Dirty_Data_Stress_Test",
        }

        rows = {(item["sheet_name"], item["row_number"]): item for item in body["items"]}
        assert ("Master_PO_Ledger", 10) not in rows
        assert ("Dirty_Data_Stress_Test", 6) not in rows

        master = rows[("Master_PO_Ledger", 2)]
        assert master["normalized"]["supplier_name"] == "Apex Cloud Solutions Inc."
        assert master["normalized"]["customer_name"] == "Global FinTech Corp"
        assert master["normalized"]["currency"] == "USD"
        assert master["line_item_count"] == 6

        invalid_date = rows[("Dirty_Data_Stress_Test", 4)]
        assert invalid_date["normalized"]["invoice_date"] is None
        assert "invalid date format" in invalid_date["warnings"]

        invalid_subtotal = rows[("Dirty_Data_Stress_Test", 5)]
        assert invalid_subtotal["normalized"]["subtotal"] is None
        assert "invalid or missing subtotal" in invalid_subtotal["warnings"]

        unknown_currency = rows[("Dirty_Data_Stress_Test", 7)]
        assert unknown_currency["normalized"]["currency"] == "XYZ"
        assert "invalid currency (XYZ)" in unknown_currency["warnings"]
        assert any(
            warning.startswith(
                "math mismatch: subtotal + tax (4500.00) != total (4100.00)"
            )
            for warning in unknown_currency["warnings"]
        )

        for row_number in (2, 8):
            assert "duplicate invoice number" in rows[
                ("Dirty_Data_Stress_Test", row_number)
            ]["warnings"]
        for row_number in (2, 6):
            assert "duplicate invoice number" in rows[
                ("Master_PO_Ledger", row_number)
            ]["warnings"]

    def test_line_item_records_and_parent_links(
        self, client, auth_headers, process_jobs
    ):
        document_id = self._upload(client, auth_headers)
        process_jobs(document_id)

        response = client.get(
            f"/api/v1/documents/{document_id}/sheet-rows",
            params={"row_type": "line_item", "limit": 100},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invoice_total"] == 14
        assert body["line_item_total"] == 20
        assert body["total"] == 20
        assert len(body["items"]) == 20
        assert {item["sheet_name"] for item in body["items"]} == {"Line_Items_Detail"}
        assert all(item["row_type"] == "line_item" for item in body["items"])

        linked = [item for item in body["items"] if item["normalized"]["linked"]]
        unlinked = [item for item in body["items"] if not item["normalized"]["linked"]]
        assert len(linked) == 17
        assert len(unlinked) == 3
        assert {item["parent_invoice_number"] for item in linked} == {
            "INV-2026-00101",
            "INV-2026-00102",
            "INV-2026-00103",
            "INV-2026-00107",
        }
        assert all(item["parent_invoice_number"] is None for item in unlinked)

        first = min(linked, key=lambda item: item["row_number"])
        assert first["normalized"]["sku"] == "CLD-ENT-01"
        assert first["normalized"]["quantity"] == "2"
        assert first["normalized"]["unit_price"] == "3200"
        assert first["normalized"]["line_total"] == "6400"

