"""Ин-процессный job-store: submit → job_id → polling.

Контракт (GET /v1/jobs/{id} → JobStatusDTO) совпадает с будущим
Redis-бэкендом серверного профиля — здесь он заменяется без смены HTTP API.
"""

import threading
import time
import traceback
import uuid
from typing import Any, Callable

from contracts import JobStatusDTO

_MAX_JOBS = 200
_POLL_INTERVAL = 0.2


class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], dict], *args: Any) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._prune_locked()
            self._jobs[job_id] = {"status": "queued", "error": None, "result": None}

        def run():
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            try:
                result = fn(*args)
                with self._lock:
                    self._jobs[job_id].update(status="done", result=result)
            except Exception as e:
                traceback.print_exc()
                with self._lock:
                    self._jobs[job_id].update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True, name=f"job-{job_id[:8]}").start()
        return job_id

    def get(self, job_id: str) -> JobStatusDTO | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        return JobStatusDTO(job_id=job_id, **job)

    def wait(self, job_id: str, timeout: float = 30.0) -> JobStatusDTO:
        """Для тестов: блокирующее ожидание терминального статуса."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get(job_id)
            if status and status.status in ("done", "error"):
                return status
            time.sleep(_POLL_INTERVAL)
        raise TimeoutError(f"Задача {job_id} не завершилась за {timeout} с")

    def _prune_locked(self):
        if len(self._jobs) < _MAX_JOBS:
            return
        terminal = [jid for jid, j in self._jobs.items() if j["status"] in ("done", "error")]
        for jid in terminal[: len(self._jobs) - _MAX_JOBS + 1]:
            del self._jobs[jid]
