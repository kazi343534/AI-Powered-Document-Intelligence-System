"""End-to-end API tests: auth, uploads, findings, corrections, search, jobs."""




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
    def test_findings_list_and_update(self, client, auth_headers, make_pdf, process_jobs):
        with open(make_pdf, "rb") as handle:
            created = client.post(
                "/api/v1/documents",
                files={"files": ("invoice.pdf", handle, "application/pdf")},
                headers=auth_headers,
            )
        doc_id = created.json()["documents"][0]["id"]
        process_jobs(doc_id)
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).json()
        findings = detail.get("findings", [])
        assert len(findings) > 0, "expected validation findings from sample PDF"

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
    def test_approve_blocks_when_findings_open(
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

        response = client.post(
            f"/api/v1/documents/{doc_id}/approve",
            json={"note": "should be blocked"},
            headers=auth_headers,
        )
        assert response.status_code == 409, response.text

    def test_approve_completes_document_when_findings_resolved(
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

