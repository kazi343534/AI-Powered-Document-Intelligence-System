"""Pytest fixtures for DocIntel backend tests.

Tests run against an isolated file-based SQLite database (tests/data/test_docintel.db)
so the dev database is never touched. Settings are overridden via environment
variables *before* importing the app, and the lru_cached `get_settings` is
cleared/re-created before each test.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TEST_DB_PATH = Path(__file__).resolve().parent / "data" / "test_docintel.db"

# Point settings at the isolated test DB *before* importing anything that
# calls get_settings() at import time.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-do-not-use-in-production")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, engine, init_db, seed_db  # noqa: E402
from app.main import app  # noqa: E402


def _remove_test_db() -> None:
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        try:
            (TEST_DB_PATH.parent / (TEST_DB_PATH.name + suffix)).unlink()
        except FileNotFoundError:
            pass


@pytest.fixture(scope="session", autouse=True)
def _test_db_schema() -> None:
    """Create all tables once for the session against the isolated test DB."""
    _remove_test_db()
    init_db()
    seed_db()
    yield
    _remove_test_db()


@pytest.fixture()
def settings() -> object:
    """Re-read settings from env for each test (clears lru cache)."""
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy session rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with the DB dependency overridden to use `db`."""

    import app.database as database_module

    def _override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[database_module.get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(database_module.get_db, None)


@pytest.fixture()
def process_jobs(db: Session):
    """Process queued jobs synchronously against the test DB.

    Call with a document_id to process that document immediately, or with no
    argument to drain the whole queue (useful when the background worker is
    not running against the test database).
    """

    def _run(document_id: str | None = None) -> None:
        from app.pipeline import process_document

        if document_id:
            process_document(document_id, db=db)
        else:
            from app.worker import Worker

            worker = Worker("test-worker")
            while worker.run_once():
                pass

    return _run


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    """Log in as the demo admin user and return bearer auth headers."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@docintel.local", "password": "admin12345"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def make_pdf(tmp_path):
    """Build a small single-page PDF invoice file; return its path."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "invoice.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "INVOICE")
    c.drawString(72, 700, "Invoice No: INV-2024-0042")
    c.drawString(72, 680, "Invoice Date: 15 March 2024")
    c.drawString(72, 660, "Supplier: ACME COMPONENTS LTD")
    c.drawString(72, 640, "Customer: TEST CUSTOMER")
    c.drawString(72, 600, "Hex bolt M8      10    12.50    125.00")
    c.drawString(72, 580, "Subtotal      125.00")
    c.drawString(72, 560, "Tax            25.00")
    c.drawString(72, 540, "Total          150.00")
    c.drawString(72, 520, "GBP")
    c.save()
    return path


@pytest.fixture()
def make_csv(tmp_path):
    """Build a small CSV spreadsheet file; return its path."""
    path = tmp_path / "invoices.csv"
    path.write_text(
        "invoice number,date,supplier,total\nINV-CSV-001,2024-01-10,Acme Corp,123.45\n"
    )
    return path
