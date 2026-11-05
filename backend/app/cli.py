from __future__ import annotations

import argparse
import getpass
import logging
import sys

from .config import get_settings
from .database import SessionLocal, init_db, seed_db
from .models import User
from .security import hash_password
from .storage import get_storage


def command_init() -> None:
    init_db()
    seed_db()
    try:
        storage = get_storage()
        print(f"storage: {storage.backend}")
    except Exception as exc:
        print(f"storage warning: {exc}", file=sys.stderr)
    settings = get_settings()
    print(f"database: {'postgres' if settings.is_postgres else 'sqlite'}")
    print(f"demo login: {settings.demo_email} / {settings.demo_password}")


def command_create_user(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email.lower()).one_or_none()
        if existing:
            print(f"user already exists: {existing.email}")
            return
        user = User(
            email=args.email.lower(),
            name=args.name,
            password_hash=hash_password(args.password),
            role=args.role,
        )
        db.add(user)
        db.commit()
        print(f"created {user.role} user {user.email}")
    finally:
        db.close()


def command_process_pending(args: argparse.Namespace) -> None:
    from .worker import Worker

    worker = Worker("cli-worker")
    processed = 0
    while processed < args.limit:
        if not worker.run_once():
            break
        processed += 1
    print(f"processed {processed} job(s)")


def command_show_config() -> None:
    settings = get_settings()
    print(f"database_url: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")
    print(f"storage_backend: {settings.storage_backend}")
    print(f"ai_enabled: {settings.ai_enabled}")
    print(f"ocr_engine: {settings.ocr_engine}")
    print(f"embedding_provider: {settings.embedding_provider}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s :: %(message)s")
    parser = argparse.ArgumentParser(description="DocIntel maintenance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create tables, seed demo user, verify storage")
    user_parser = sub.add_parser("create-user", help="Create a user")
    user_parser.add_argument("email")
    user_parser.add_argument("--name", default="")
    user_parser.add_argument("--role", choices=["admin", "reviewer", "viewer"], default="reviewer")
    user_parser.add_argument("--password", default=None)
    process_parser = sub.add_parser("process-pending", help="Drain queued jobs (development)")
    process_parser.add_argument("--limit", type=int, default=100)
    sub.add_parser("config", help="Print effective configuration")

    args = parser.parse_args()
    if args.command == "init-db":
        command_init()
    elif args.command == "create-user":
        if not args.password:
            args.password = getpass.getpass("Password: ")
        command_create_user(args)
    elif args.command == "process-pending":
        command_process_pending(args)
    elif args.command == "config":
        command_show_config()


if __name__ == "__main__":
    main()
