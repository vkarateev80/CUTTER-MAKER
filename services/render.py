"""Сервис render: УФ-маска PDF и технологическая карта (PDF).

Зависит от Inkscape (SVG → PDF); на машине без Inkscape задачи падают
в статус error с сообщением — клиент откатится на локальное выполнение.

Запуск: python -m services.render   (http://127.0.0.1:8766)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI

from contracts import (
    JobRefDTO,
    ReportRequestDTO,
    ReportResultDTO,
    UvMaskRequestDTO,
    UvMaskResultDTO,
)
from services.common import add_common_routes
from services.jobstore import JobStore
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline
from src.pipeline.report_generator import ReportGenerator

app = FastAPI(title="CUTTER MAKER — render", version="1.0")
store = JobStore()
add_common_routes(app, store, "render")


@app.post("/v1/uv-mask", response_model=JobRefDTO)
def uv_mask(req: UvMaskRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]
    output_path = Path(req.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def worker() -> dict:
        visual, pure, mask_geom = CamPipeline().generate_uv_mask_pdf(
            paths, req.offset, output_path, req.badge_text, req.mark_d, req.mark_margin
        )
        return UvMaskResultDTO(
            visual_paths=[p.to_dto() for p in visual],
            pure_paths=[p.to_dto() for p in pure],
            mask_geom_wkt=mask_geom.wkt,
        ).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


@app.post("/v1/report", response_model=JobRefDTO)
def report(req: ReportRequestDTO) -> JobRefDTO:
    paths = [CamPath.from_dto(p) for p in req.paths]
    output_path = Path(req.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def worker() -> dict:
        ReportGenerator.generate(req.project_name, req.stats, paths, output_path)
        return ReportResultDTO(output_path=str(output_path)).model_dump()

    return JobRefDTO(job_id=store.submit(worker))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
