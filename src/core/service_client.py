"""ServiceClient: вызовы сервисов ingest/render/geometry/math/cam по HTTP с локальным fallback.

Поведение:
- сервис доступен → задача уходит в него (POST /v1/... → polling /v1/jobs/{id});
- ConnectError/ConnectTimeout → операция выполняется локально тем же кодом
  (десктоп работает и без запущенных сервисов);
- ошибка самой задачи (статус error) НЕ маскируется fallback'ом —
  это реальный сбой вычисления, он одинаков локально и в сервисе;
- HTTP 422/500 тоже НЕ уводятся в fallback — это баг клиента или сервиса.

URL задаётся env-переменными; пустая строка принудительно отключает сервис
(локальное выполнение без попытки соединения).
"""

import os
import time
from pathlib import Path

import httpx
from shapely import wkt as shapely_wkt

from contracts import (
    CamPathDTO,
    CheckErrorsRequestDTO,
    CheckErrorsResultDTO,
    CropMarksRequestDTO,
    DistortionRequestDTO,
    GcodeRequestDTO,
    GcodeResultDTO,
    HealRequestDTO,
    MultiplyRequestDTO,
    ParseResultDTO,
    PathsResultDTO,
    PatternRequestDTO,
    PatternResultDTO,
    ReportRequestDTO,
    ReportResultDTO,
    RotateRequestDTO,
    UvMaskRequestDTO,
    UvMaskResultDTO,
)
from src.optimizer.pattern_recognition import PatternRecognizer
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
        geometry_url: str | None = None,
        math_url: str | None = None,
        cam_url: str | None = None,
        job_timeout: float = 300.0,
    ):
        self.ingest_url = self._resolve(ingest_url, "CUTTER_INGEST_URL", "http://127.0.0.1:8765")
        self.render_url = self._resolve(render_url, "CUTTER_RENDER_URL", "http://127.0.0.1:8766")
        self.geometry_url = self._resolve(geometry_url, "CUTTER_GEOMETRY_URL", "http://127.0.0.1:8767")
        self.math_url = self._resolve(math_url, "CUTTER_MATH_URL", "http://127.0.0.1:8768")
        self.cam_url = self._resolve(cam_url, "CUTTER_CAM_URL", "http://127.0.0.1:8769")
        self.job_timeout = job_timeout

    @staticmethod
    def _resolve(explicit: str | None, env_name: str, default: str) -> str:
        value = explicit if explicit is not None else os.environ.get(env_name, default)
        return value.rstrip("/")

    # ==========================================================
    # инфраструктура
    # ==========================================================

    def _call(self, url: str, service: str, path: str, payload: dict) -> dict | None:
        """POST задачи + polling. None = сервис недоступен/отключён (нужен fallback)."""
        if not url:
            return None
        try:
            r = httpx.post(
                f"{url}{path}",
                json=payload,
                timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
            )
            r.raise_for_status()
            return self._wait(url, r.json()["job_id"])
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] {service} недоступен ({url}): {e.__class__.__name__} — выполняю локально")
            return None

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
        req = UvMaskRequestDTO(
            paths=[p.to_dto() for p in paths],
            offset=offset_val,
            output_path=str(output_path),
            badge_text=badge_text,
            mark_d=mark_d,
            mark_margin=mark_margin,
        )
        result = self._call(self.render_url, "render", "/v1/uv-mask", req.model_dump())
        if result is not None:
            parsed = UvMaskResultDTO.model_validate(result)
            return (
                [CamPath.from_dto(p) for p in parsed.visual_paths],
                [CamPath.from_dto(p) for p in parsed.pure_paths],
                shapely_wkt.loads(parsed.mask_geom_wkt),
            )
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
        req = ReportRequestDTO(
            project_name=project_name,
            stats=stats,
            paths=[p.to_dto() for p in paths],
            output_path=str(output_path),
        )
        result = self._call(self.render_url, "render", "/v1/report", req.model_dump())
        if result is not None:
            return ReportResultDTO.model_validate(result)
        ReportGenerator.generate(project_name, stats, paths, output_path)
        return None

    # ==========================================================
    # geometry: проверка геометрии (ШАГ 2)
    # ==========================================================

    def check_errors(self, paths: list[CamPath], min_loop_area: float = 0.0) -> dict:
        req = CheckErrorsRequestDTO(
            paths=[p.to_dto() for p in paths], min_loop_area=min_loop_area
        )
        result = self._call(self.geometry_url, "geometry", "/v1/check-errors", req.model_dump())
        if result is not None:
            return CheckErrorsResultDTO.model_validate(result).model_dump()
        return CamPipeline(min_loop_area=min_loop_area).step2_check_errors(paths)

    # ==========================================================
    # geometry: морфологическое лечение (ШАГ 3)
    # ==========================================================

    def heal(
        self, paths: list[CamPath], tolerance: float = 0.01, min_loop_area: float = 0.0
    ) -> list[CamPath]:
        req = HealRequestDTO(
            paths=[p.to_dto() for p in paths],
            tolerance=tolerance,
            min_loop_area=min_loop_area,
        )
        result = self._call(self.geometry_url, "geometry", "/v1/heal", req.model_dump())
        if result is not None:
            parsed = PathsResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        return CamPipeline(
            tolerance=tolerance, min_loop_area=min_loop_area
        ).step3_heal_and_optimize(paths)

    # ==========================================================
    # math: распознавание массива
    # ==========================================================

    def analyze_pattern(self, paths: list[CamPath], tolerance: float = 0.5) -> dict:
        req = PatternRequestDTO(paths=[p.to_dto() for p in paths], tolerance=tolerance)
        result = self._call(self.math_url, "math", "/v1/pattern", req.model_dump())
        if result is not None:
            parsed = PatternResultDTO.model_validate(result)
            return {
                "is_array": parsed.is_array,
                "count": parsed.count,
                "rows": parsed.rows,
                "cols": parsed.cols,
                "step_x": parsed.step_x,
                "step_y": parsed.step_y,
                "gap_x": parsed.gap_x,
                "gap_y": parsed.gap_y,
                "master_paths": [CamPath.from_dto(p) for p in parsed.master_paths],
                "offsets": [tuple(o) for o in parsed.offsets],
            }
        return PatternRecognizer(tolerance=tolerance).analyze(paths)

    # ==========================================================
    # math: Step & Repeat
    # ==========================================================

    def multiply_paths(self, paths: list[CamPath], offsets: list[tuple]) -> list[CamPath]:
        req = MultiplyRequestDTO(
            paths=[p.to_dto() for p in paths],
            offsets=[tuple(o) for o in offsets],
        )
        result = self._call(self.math_url, "math", "/v1/multiply", req.model_dump())
        if result is not None:
            parsed = PathsResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        return CamPipeline().multiply_paths(paths, offsets)

    # ==========================================================
    # math: дисторсия (сжатие под магнитный вал)
    # ==========================================================

    def apply_distortion(
        self, paths: list[CamPath], factor: float, axis: str = "Y"
    ) -> list[CamPath]:
        req = DistortionRequestDTO(
            paths=[p.to_dto() for p in paths], factor=factor, axis=axis
        )
        result = self._call(self.math_url, "math", "/v1/distortion", req.model_dump())
        if result is not None:
            parsed = PathsResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        return CamPipeline().apply_distortion(paths, factor, axis)

    # ==========================================================
    # math: поворот
    # ==========================================================

    def rotate_geometry(self, paths: list[CamPath], angle_deg: float = 90.0) -> list[CamPath]:
        req = RotateRequestDTO(
            paths=[p.to_dto() for p in paths], angle_deg=angle_deg
        )
        result = self._call(self.math_url, "math", "/v1/rotate", req.model_dump())
        if result is not None:
            parsed = PathsResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        return CamPipeline().rotate_geometry(paths, angle_deg)

    # ==========================================================
    # math: обрезные метки
    # ==========================================================

    def add_crop_marks(
        self, paths: list[CamPath], rapport: float, width: float, axis: str = "Y"
    ) -> list[CamPath]:
        req = CropMarksRequestDTO(
            paths=[p.to_dto() for p in paths], rapport=rapport, width=width, axis=axis
        )
        result = self._call(self.math_url, "math", "/v1/crop-marks", req.model_dump())
        if result is not None:
            parsed = PathsResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        return CamPipeline().add_crop_marks(paths, rapport, width, axis)

    # ==========================================================
    # cam: генерация G-кода
    # ==========================================================

    def generate_gcode(
        self,
        mask_geom,
        output_path: str | Path,
        tool,
        post,
        mask_offset: float,
        enable_sharpening: bool,
        lead_radius: float = 0.0,
        milling_dir: str = "Climb",
    ):
        req = GcodeRequestDTO(
            mask_geom_wkt=mask_geom.wkt,
            output_path=str(output_path),
            tool=tool.to_dto(),
            post=post.to_dto(),
            mask_offset=mask_offset,
            enable_sharpening=enable_sharpening,
            lead_radius=lead_radius,
            milling_dir=milling_dir,
        )
        result = self._call(self.cam_url, "cam", "/v1/gcode", req.model_dump())
        if result is not None:
            parsed = GcodeResultDTO.model_validate(result)
            return (
                [CamPath.from_dto(p) for p in parsed.ideal_paths],
                [CamPath.from_dto(p) for p in parsed.cnc_paths],
                parsed.time_min,
            )
        return CamPipeline().generate_gcode(
            mask_geom, output_path, tool, post, mask_offset,
            enable_sharpening, lead_radius, milling_dir,
        )
