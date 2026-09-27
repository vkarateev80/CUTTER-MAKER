"""ServiceClient: вызовы сервисов ingest/render по HTTP с локальным fallback.

Поведение:
- сервис доступен → задача уходит в него (POST /v1/... → polling /v1/jobs/{id});
- ConnectError/ConnectTimeout → операция выполняется локально тем же кодом
  (десктоп работает и без запущенных сервисов);
- ошибка самой задачи (статус error) НЕ маскируется fallback'ом —
  это реальный сбой вычисления, он одинаков локально и в сервисе.

URL задаётся env-переменными; пустая строка принудительно отключает сервис.
"""

import os
import time
from pathlib import Path

import httpx
from shapely import wkt as shapely_wkt

from contracts import (
    CamPathDTO,
    ParseResultDTO,
    ReportRequestDTO,
    ReportResultDTO,
    UvMaskRequestDTO,
    UvMaskResultDTO,
)
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline
from src.pipeline.report_generator import ReportGenerator

_CONNECT_TIMEOUT = 2.0
_POLL_INTERVAL = 0.2


class ServiceClient:
    def __init__(
        self,
        ingest_url: str | None = None,
        render_url: str | None = None,
        job_timeout: float = 300.0,
    ):
        self.ingest_url = (ingest_url if ingest_url is not None else os.environ.get("CUTTER_INGEST_URL", "http://127.0.0.1:8765")).rstrip("/")
        self.render_url = (render_url if render_url is not None else os.environ.get("CUTTER_RENDER_URL", "http://127.0.0.1:8766")).rstrip("/")
        self.job_timeout = job_timeout

    # ==========================================================
    # ingest: парсинг макета
    # ==========================================================

    def parse(self, input_path: str | Path) -> list[CamPath]:
        if not self.ingest_url:
            return CamPipeline().step1_parse(input_path)
        try:
            with open(input_path, "rb") as f:
                r = httpx.post(
                    f"{self.ingest_url}/v1/parse",
                    files={"file": (Path(input_path).name, f)},
                    timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
                )
            r.raise_for_status()
            result = self._wait(self.ingest_url, r.json()["job_id"])
            parsed = ParseResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] ingest недоступен ({self.ingest_url}): {e.__class__.__name__} — выполняю локально")
            return CamPipeline().step1_parse(input_path)

    # ==========================================================
    # render: УФ-маска PDF
    # ==========================================================

    def generate_uv_mask_pdf(
        self,
        paths: list[CamPath],
        offset_val: float,
        output_path: str | Path,
        badge_text: str = "",
        mark_d: float = 4.0,
        mark_margin: float = 10.0,
    ):
        if not self.render_url:
            return CamPipeline().generate_uv_mask_pdf(
                paths, offset_val, output_path, badge_text, mark_d, mark_margin
            )
        try:
            req = UvMaskRequestDTO(
                paths=[p.to_dto() for p in paths],
                offset=offset_val,
                output_path=str(output_path),
                badge_text=badge_text,
                mark_d=mark_d,
                mark_margin=mark_margin,
            )
            r = httpx.post(
                f"{self.render_url}/v1/uv-mask",
                json=req.model_dump(),
                timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
            )
            r.raise_for_status()
            result = self._wait(self.render_url, r.json()["job_id"])
            parsed = UvMaskResultDTO.model_validate(result)
            return (
                [CamPath.from_dto(p) for p in parsed.visual_paths],
                [CamPath.from_dto(p) for p in parsed.pure_paths],
                shapely_wkt.loads(parsed.mask_geom_wkt),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] render недоступен ({self.render_url}): {e.__class__.__name__} — выполняю локально")
            return CamPipeline().generate_uv_mask_pdf(
                paths, offset_val, output_path, badge_text, mark_d, mark_margin
            )

    # ==========================================================
    # render: технологическая карта PDF
    # ==========================================================

    def generate_report(
        self,
        project_name: str,
        stats: dict,
        paths: list[CamPath],
        output_path: str | Path,
    ) -> ReportResultDTO | None:
        if not self.render_url:
            ReportGenerator.generate(project_name, stats, paths, output_path)
            return None
        try:
            req = ReportRequestDTO(
                project_name=project_name,
                stats=stats,
                paths=[p.to_dto() for p in paths],
                output_path=str(output_path),
            )
            r = httpx.post(
                f"{self.render_url}/v1/report",
                json=req.model_dump(),
                timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
            )
            r.raise_for_status()
            result = self._wait(self.render_url, r.json()["job_id"])
            return ReportResultDTO.model_validate(result)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] render недоступен ({self.render_url}): {e.__class__.__name__} — выполняю локально")
            ReportGenerator.generate(project_name, stats, paths, output_path)
            return None

    # ==========================================================
    # polling
    # ==========================================================

    def _wait(self, base_url: str, job_id: str) -> dict:
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            r = httpx.get(
                f"{base_url}/v1/jobs/{job_id}",
                timeout=httpx.Timeout(10.0, connect=_CONNECT_TIMEOUT),
            )
            r.raise_for_status()
            data = r.json()
            status = data.get("status")
            if status == "done":
                return data.get("result") or {}
            if status == "error":
                raise RuntimeError(f"Сервис {base_url} вернул ошибку: {data.get('error')}")
            time.sleep(_POLL_INTERVAL)
        raise TimeoutError(f"Задача {job_id} на {base_url} не завершилась за {self.job_timeout:.0f} с")
