from __future__ import annotations

import logging
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import Document, ProcessingJob
from .pipeline import ProcessingFailure, process_document

logger = logging.getLogger(__name__)
settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.stop_event = threading.Event()
        self._last_reap = 0.0

    def stop(self) -> None:
        self.stop_event.set()

    def claim_job(self) -> ProcessingJob | None:
        now = _now()
        if time.time() - self._last_reap > 60:
            self._last_reap = time.time()
            self.reap_stale()
        db = SessionLocal()
        try:
            if settings.is_postgres:
                result = db.execute(
                    text(
                        """
                        UPDATE processing_jobs
                        SET status = 'running',
                            locked_at = now(),
                            locked_by = :worker,
                            attempts = attempts + 1,
                            started_at = COALESCE(started_at, now())
                        WHERE id = (
                            SELECT id FROM processing_jobs
                            WHERE status = 'queued' AND next_run_at <= now()
                            ORDER BY created_at
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING id
                        """
                    ),
                    {"worker": self.worker_id},
                )
                row = result.first()
                db.commit()
                if not row:
                    return None
                return db.get(ProcessingJob, row[0])
            job = None
            candidates = list(
                db.scalars(
                    select(ProcessingJob)
                    .where(ProcessingJob.status == "queued")
                    .order_by(ProcessingJob.created_at)
                    .limit(10)
                )
            )
            for candidate in candidates:
                next_run = candidate.next_run_at
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)
                if next_run <= now:
                    job = candidate
                    break
            if not job:
                return None
            job.status = "running"
            job.locked_at = now
            job.locked_by = self.worker_id
            job.attempts += 1
            job.started_at = job.started_at or now
            db.commit()
            return job
        finally:
            db.close()

    def reap_stale(self) -> None:
        cutoff = _now() - timedelta(seconds=settings.job_stale_seconds)
        db = SessionLocal()
        try:
            if settings.is_postgres:
                result = db.execute(
                    text(
                        """
                        UPDATE processing_jobs
                        SET status = 'queued',
                            locked_at = NULL,
                            next_run_at = now(),
                            error_code = 'WORKER_LOST',
                            error_message = 'Worker heartbeat expired; job requeued'
                        WHERE status = 'running' AND locked_at < now() - make_interval(secs => :seconds)
                        """
                    ),
                    {"seconds": settings.job_stale_seconds},
                )
                db.commit()
                if result.rowcount:
                    logger.warning("requeued %s stale jobs", result.rowcount)
            else:
                stale = list(
                    db.scalars(select(ProcessingJob).where(ProcessingJob.status == "running"))
                )
                count = 0
                for job in stale:
                    locked = job.locked_at
                    if locked and locked.tzinfo is None:
                        locked = locked.replace(tzinfo=timezone.utc)
                    if locked and locked < cutoff:
                        job.status = "queued"
                        job.locked_at = None
                        job.next_run_at = _now()
                        job.error_code = "WORKER_LOST"
                        job.error_message = "Worker heartbeat expired; job requeued"
                        count += 1
                db.commit()
                if count:
                    logger.warning("requeued %s stale jobs", count)
        finally:
            db.close()

    def process_job(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            job = db.get(ProcessingJob, job_id)
            if not job:
                return
            document_id = job.document_id
        finally:
            db.close()

        try:
            process_document(document_id, job_id)
        except Exception as exc:
            if isinstance(exc, ProcessingFailure):
                failure = exc
            else:
                logger.exception("job %s failed", job_id)
                failure = ProcessingFailure("PROCESSING_ERROR", str(exc), retryable=True)
            self._record_failure(job_id, failure)
            return
        db = SessionLocal()
        try:
            job = db.get(ProcessingJob, job_id)
            if job:
                job.status = "completed"
                job.progress = 100
                job.finished_at = _now()
                job.locked_at = None
                job.error_code = None
                job.error_message = None
            db.commit()
            logger.info("job %s completed", job_id)
        finally:
            db.close()

    def _record_failure(self, job_id: str, failure: ProcessingFailure) -> None:
        db = SessionLocal()
        try:
            job = db.get(ProcessingJob, job_id)
            if not job:
                return
            document = db.get(Document, job.document_id)
            job.error_code = failure.code
            job.error_message = failure.message[:2000]
            job.locked_at = None
            job.finished_at = _now()
            if document:
                document.error_code = failure.code
                document.error_message = failure.message[:2000]
            if failure.retryable and job.attempts < job.max_attempts:
                backoff = min(300, 15 * (2 ** max(0, job.attempts - 1)))
                job.status = "queued"
                job.next_run_at = _now() + timedelta(seconds=backoff)
                job.progress = 0
                if document:
                    document.status = "queued"
                    document.stage = "retry_wait"
                logger.warning(
                    "job %s failed (attempt %s/%s); retrying in %ss: %s",
                    job_id,
                    job.attempts,
                    job.max_attempts,
                    backoff,
                    failure.message,
                )
            else:
                job.status = "failed"
                if document:
                    document.status = "failed"
                    document.stage = "failed"
                logger.error("job %s permanently failed: %s", job_id, failure.message)
            db.commit()
        finally:
            db.close()

    def run_once(self) -> bool:
        job = self.claim_job()
        if not job:
            return False
        self.process_job(job.id)
        return True

    def run_forever(self) -> None:
        logger.info("worker %s started", self.worker_id)
        while not self.stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("worker loop error")
                worked = False
            if not worked:
                self.stop_event.wait(settings.worker_poll_seconds)
        logger.info("worker %s stopped", self.worker_id)


def start_background_worker() -> tuple[Worker, threading.Thread]:
    worker = Worker("api-inline-worker")
    thread = threading.Thread(target=worker.run_forever, name="docintel-worker", daemon=True)
    thread.start()
    return worker, thread


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    worker_count = 1 if settings.is_sqlite else max(1, settings.worker_concurrency)
    logger.info("starting %s worker(s)", worker_count)
    if worker_count == 1:
        worker = Worker()
        signal.signal(signal.SIGTERM, lambda *_: worker.stop())
        signal.signal(signal.SIGINT, lambda *_: worker.stop())
        worker.run_forever()
        return

    workers = [Worker() for _ in range(worker_count)]
    executor = ThreadPoolExecutor(max_workers=worker_count)
    for worker in workers:
        executor.submit(worker.run_forever)

    def shutdown(*_args) -> None:
        for worker in workers:
            worker.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while any(not worker.stop_event.is_set() for worker in workers):
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
    executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
