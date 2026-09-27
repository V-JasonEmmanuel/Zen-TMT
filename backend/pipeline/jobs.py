"""Background job execution: one worker thread, jobs run sequentially (keeps RAM/VRAM bounded).

Progress is reported per real pipeline stage and persisted, so the UI shows actual state.
"""
from __future__ import annotations

import queue
import threading
import traceback
from typing import Callable, Optional

from backend.schemas import GenerationJob, StageStatus, utcnow
from backend.storage.database import Database, get_db
from backend.utils.files import new_id
from backend.utils.logging import get_logger

log = get_logger(__name__)


class JobCancelled(Exception):
    pass


class StageFailed(Exception):
    """A required stage failed; the message is user-facing."""


class Reporter:
    def __init__(self, db: Database, job: GenerationJob, cancelled: Callable[[], bool]):
        self.db, self.job, self._cancelled = db, job, cancelled

    def _stage(self, key: str) -> StageStatus:
        for s in self.job.stages:
            if s.key == key:
                return s
        raise KeyError(key)

    def _save(self) -> None:
        self.db.save_job(self.job)

    def check(self) -> None:
        if self._cancelled():
            raise JobCancelled()

    def start(self, key: str, message: str = "") -> None:
        self.check()
        s = self._stage(key)
        s.status, s.message, s.started_at = "running", message, utcnow()
        self._save()

    def update(self, key: str, message: str) -> None:
        self._stage(key).message = message
        self._save()

    def done(self, key: str, message: str = "") -> None:
        s = self._stage(key)
        s.status, s.finished_at = "done", utcnow()
        if message:
            s.message = message
        self._save()

    def warn(self, key: str, message: str) -> None:
        s = self._stage(key)
        s.status, s.message, s.finished_at = "warning", message, utcnow()
        self.job.warnings.append(message)
        self._save()

    def fail(self, key: str, message: str) -> None:
        s = self._stage(key)
        s.status, s.message, s.finished_at = "failed", message, utcnow()
        self.job.warnings.append(message)
        self._save()

    def skip(self, key: str, message: str = "Not requested") -> None:
        s = self._stage(key)
        s.status, s.message = "skipped", message
        self._save()

    def note(self, message: str) -> None:
        if message not in self.job.warnings:
            self.job.warnings.append(message)
            self._save()


Handler = Callable[[Reporter, GenerationJob], None]


class JobRunner:
    def __init__(self):
        self._q: "queue.Queue[str]" = queue.Queue()
        self._handlers: dict[str, Handler] = {}
        self._cancelled: set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self.current: Optional[str] = None

    def register(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def submit(self, project_id: str, kind: str, stages: list[tuple[str, str]], params: dict | None = None) -> GenerationJob:
        job = GenerationJob(id=new_id("job_"), project_id=project_id, kind=kind, params=params or {},
                            stages=[StageStatus(key=k, label=l) for k, l in stages])
        db = get_db()
        db.save_job(job)
        db.update_project(project_id, last_job_id=job.id, status="queued")
        self._q.put(job.id)
        return job

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)

    def queue_position(self, job_id: str) -> int:
        return list(self._q.queue).index(job_id) + 1 if job_id in self._q.queue else 0

    def run_inline(self, job_id: str) -> None:
        """Execute a job synchronously (tests / CLI)."""
        self._run(job_id)

    def _loop(self) -> None:
        while True:
            job_id = self._q.get()
            try:
                self._run(job_id)
            finally:
                self._q.task_done()

    def _run(self, job_id: str) -> None:
        db = get_db()
        job = db.get_job(job_id)
        if job is None:
            return
        self.current = job_id
        rep = Reporter(db, job, lambda: job_id in self._cancelled)
        job.status, job.started_at = "running", utcnow()
        db.save_job(job)
        db.update_project(job.project_id, status="generating")
        log.info("Job started", job=job_id, kind=job.kind)
        try:
            if job_id in self._cancelled:
                raise JobCancelled()
            self._handlers[job.kind](rep, job)
            failed = any(s.status == "failed" for s in job.stages)
            job.status = "completed_with_warnings" if (failed or job.warnings) else "completed"
            db.update_project(job.project_id, status="ready")
        except JobCancelled:
            job.status = "cancelled"
            for s in job.stages:
                if s.status in ("pending", "running"):
                    s.status = "skipped"
            db.update_project(job.project_id, status="ready" if db.latest_plan(job.project_id) else "draft")
        except StageFailed as exc:
            job.status, job.error = "failed", str(exc)
            for s in job.stages:
                if s.status == "running":
                    s.status, s.message = "failed", str(exc)
                elif s.status == "pending":
                    s.status = "skipped"
            db.update_project(job.project_id, status="failed" if not db.latest_plan(job.project_id) else "ready")
        except Exception as exc:  # unexpected: never leave a job hanging
            log.error("Job crashed", job=job_id, error=type(exc).__name__)
            log.debug(traceback.format_exc())
            job.status, job.error = "failed", "An unexpected error occurred. See the application log for details."
            for s in job.stages:
                if s.status == "running":
                    s.status = "failed"
                elif s.status == "pending":
                    s.status = "skipped"
            db.update_project(job.project_id, status="failed")
        finally:
            job.finished_at = utcnow()
            db.save_job(job)
            self._cancelled.discard(job_id)
            self.current = None
            log.info("Job finished", job=job_id, status=job.status)


runner = JobRunner()
