"""Сервис math: паттерны массивов, Step&Repeat, дисторсия, поворот, обрезные метки.

Запуск: python -m services.math   (http://127.0.0.1:8768)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI

from contracts import (
    CropMarksRequestDTO,
    DistortionRequestDTO,
    JobRefDTO,
    MultiplyRequestDTO,
    PathsResultDTO,
    PatternRequestDTO,
    PatternResultDTO,
    RotateRequestDTO,
)
from services.common import add_common_routes
from services.jobstore import JobStore
from src.optimizer.pattern_recognition import PatternRecognizer
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline

app = FastAPI(title="CUTTER MAKER — math", version="1.0")
store = JobStore()
add_common_routes(app, store, "math")


@app.post("/v1/pattern", response_model=JobRefDTO)
def pattern(req: PatternRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        res = PatternRecognizer(tolerance=req.tolerance).analyze(paths)
        return PatternResultDTO(
            is_array=res.get("is_array", False),
            count=res.get("count", 0),
            rows=res.get("rows", 0),
            cols=res.get("cols", 0),
            step_x=res.get("step_x", 0.0),
            step_y=res.get("step_y", 0.0),
            gap_x=res.get("gap_x", 0.0),
            gap_y=res.get("gap_y", 0.0),
            master_paths=[p.to_dto() for p in res.get("master_paths", [])],
            offsets=[tuple(o) for o in res.get("offsets", [])],
        ).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/multiply", response_model=JobRefDTO)
def multiply(req: MultiplyRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]
    offsets = [tuple(o) for o in req.offsets]

    def worker() -> dict:
        multiplied = CamPipeline().multiply_paths(paths, offsets)
        return PathsResultDTO(paths=[p.to_dto() for p in multiplied]).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/distortion", response_model=JobRefDTO)
def distortion(req: DistortionRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        distorted = CamPipeline().apply_distortion(paths, req.factor, req.axis)
        return PathsResultDTO(paths=[p.to_dto() for p in distorted]).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/rotate", response_model=JobRefDTO)
def rotate(req: RotateRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        rotated = CamPipeline().rotate_geometry(paths, req.angle_deg)
        return PathsResultDTO(paths=[p.to_dto() for p in rotated]).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/crop-marks", response_model=JobRefDTO)
def crop_marks(req: CropMarksRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        with_marks = CamPipeline().add_crop_marks(paths, req.rapport, req.width, req.axis)
        return PathsResultDTO(paths=[p.to_dto() for p in with_marks]).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8768, log_level="warning")
