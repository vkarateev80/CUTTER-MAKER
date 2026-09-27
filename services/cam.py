"""Сервис cam: генерация управляющей программы (G-кода) из геометрии маски.

Запуск: python -m services.cam   (http://127.0.0.1:8769)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from shapely import wkt as shapely_wkt

from contracts import GcodeRequestDTO, GcodeResultDTO, JobRefDTO
from services.common import add_common_routes
from services.jobstore import JobStore
from src.db.models import PostProcessor, Tool
from src.pipeline.cam_pipeline import CamPipeline

app = FastAPI(title="CUTTER MAKER — cam", version="1.0")
store = JobStore()
add_common_routes(app, store, "cam")


@app.post("/v1/gcode", response_model=JobRefDTO)
def gcode(req: GcodeRequestDTO) -> JobRefDTO:
    def worker() -> dict:
        mask_geom = shapely_wkt.loads(req.mask_geom_wkt)
        if mask_geom.is_empty:
            raise ValueError("Геометрия маски пуста.")

        output_path = Path(req.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ideal, cnc, time_min = CamPipeline().generate_gcode(
            mask_geom,
            output_path,
            Tool.from_dto(req.tool),
            PostProcessor.from_dto(req.post),
            req.mask_offset,
            req.enable_sharpening,
            req.lead_radius,
            req.milling_dir,
        )
        return GcodeResultDTO(
            ideal_paths=[p.to_dto() for p in ideal],
            cnc_paths=[p.to_dto() for p in cnc],
            time_min=time_min,
        ).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8769, log_level="warning")
