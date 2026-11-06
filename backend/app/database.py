from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_connect_args: dict = {}
if settings.is_sqlite:
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    _connect_args = {"check_same_thread": False}
elif settings.is_postgres:
    # Supabase's transaction pooler (PgBouncer, port 6543) does not support
    # server-side prepared statements. psycopg prepares statements after five
    # executions by default, which otherwise surfaces as
    # "prepared statement ... does not exist" mid-job.
    _connect_args = {"prepare_threshold": None}

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=180,
    connect_args=_connect_args,
    future=True,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register metadata)

    if settings.is_postgres:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("pgvector extension ensured")

    Base.metadata.create_all(bind=engine)

    if settings.is_postgres:
        # Indexes that SQLAlchemy cannot express portably.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_fts "
                    "ON chunks USING gin (to_tsvector('english', content))"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
                    "ON chunks USING hnsw (embedding vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_sheet_rows_norm_gin "
                    "ON sheet_rows USING gin (normalized jsonb_path_ops)"
                )
            )
    logger.info("database schema ready (%s)", "postgres" if settings.is_postgres else "sqlite")


def seed_db() -> None:
    from .models import User
    from .security import hash_password

    with session_scope() as db:
        existing = db.query(User).filter(User.email == settings.demo_email).one_or_none()
        if existing:
            return
        db.add(
            User(
                email=settings.demo_email,
                name="Demo Admin",
                password_hash=hash_password(settings.demo_password),
                role="admin",
            )
        )
        logger.info("seeded demo user %s", settings.demo_email)
