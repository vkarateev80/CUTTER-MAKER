"""Сервис ingest: импорт векторных макетов (DXF/SVG/PDF/AI/CDR/EPS) → CamPathDTO.

Запуск: python -m services.ingest   (http://127.0.0.1:8765)
"""

import sys
import tempfile
from pathlib import Path

# Запуск из корня репозитория: python -m services.ingest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, HTTPException, UploadFile

from contracts import JobRefDTO, JobStatusDTO, ParseResultDTO
from services.jobstore import JobStore
from src.pipeline.cam_pipeline import CamPipeline

app = FastAPI(title="CUTTER MAKER — ingest", version="1.0")
store = JobStore()


def _parse_file(input_path: Path) -> dict:
    paths = CamPipeline().step1_parse(input_path)
    return ParseResultDTO(paths=[p.to_dto() for p in paths]).model_dump()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "ingest"}


@app.post("/v1/parse", response_model=JobRefDTO)
async def parse(file: UploadFile = File(...)) -> JobRefDTO:
    suffix = Path(file.filename or "").suffix
    if not suffix:
        raise HTTPException(status_code=400, detail="У файла нет расширения")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
    finally:
        tmp.close()

    def worker() -> dict:
        try:
            return _parse_file(Path(tmp.name))
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    return JobRefDTO(job_id=store.submit(worker))


@app.get("/v1/jobs/{job_id}", response_model=JobStatusDTO)
def job_status(job_id: str) -> JobStatusDTO:
    status = store.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return status


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
