"""Thread-safe in-memory job registry (single-user, local-only)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    status: str = "pending"  # pending | running | done | failed
    progress: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, **meta: Any) -> Job:
        job = Job(id=uuid.uuid4().hex, meta=meta)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job: Job, target: Callable[[Job], Any]) -> None:
        def _runner() -> None:
            job.status = "running"
            job.started_at = time.time()
            try:
                job.result = target(job)
                job.status = "done"
            except Exception as exc:  # noqa: BLE001
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "failed"
            finally:
                job.finished_at = time.time()
        threading.Thread(target=_runner, daemon=True).start()


REGISTRY = JobRegistry()
