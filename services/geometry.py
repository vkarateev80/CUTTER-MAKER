"""Сервис geometry: проверка геометрии (ШАГ 2) и морфологическое лечение (ШАГ 3).

Запуск: python -m services.geometry   (http://127.0.0.1:8767)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI

from contracts import (
    CheckErrorsRequestDTO,
    CheckErrorsResultDTO,
    HealRequestDTO,
    JobRefDTO,
    PathsResultDTO,
)
from services.common import add_common_routes
from services.jobstore import JobStore
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline

app = FastAPI(title="CUTTER MAKER — geometry", version="1.0")
store = JobStore()
add_common_routes(app, store, "geometry")


@app.post("/v1/check-errors", response_model=JobRefDTO)
def check_errors(req: CheckErrorsRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        stats = CamPipeline(min_loop_area=req.min_loop_area).step2_check_errors(paths)
        return CheckErrorsResultDTO(**stats).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/heal", response_model=JobRefDTO)
def heal(req: HealRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]

    def worker() -> dict:
        healed = CamPipeline(
            tolerance=req.tolerance, min_loop_area=req.min_loop_area
        ).step3_heal_and_optimize(paths)
        return PathsResultDTO(paths=[p.to_dto() for p in healed]).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
