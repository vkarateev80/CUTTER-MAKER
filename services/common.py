"""Общие маршруты всех сервисов: health и polling задач."""

from fastapi import FastAPI, HTTPException

from contracts import JobStatusDTO
from services.jobstore import JobStore


def add_common_routes(app: FastAPI, store: JobStore, service_name: str) -> None:
    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": service_name}

    @app.get("/v1/jobs/{job_id}", response_model=JobStatusDTO)
    def job_status(job_id: str) -> JobStatusDTO:
        status = store.get(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return status
