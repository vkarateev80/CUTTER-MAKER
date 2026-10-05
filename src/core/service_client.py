"""ServiceClient: вызовы сервисов ingest/render/geometry/math/cam/state по HTTP с локальным fallback.

Поведение:
- сервис доступен → задача уходит в него (compute: POST → polling /v1/jobs/{id};
  state: синхронный POST, результат сразу);
- ConnectError/ConnectTimeout/HTTP 503 → операция выполняется локально тем же
  кодом (десктоп работает и без запущенных сервисов); 503 отдаёт gateway,
  когда его бэкенд недоступен;
- ошибка самой задачи (статус error), 4xx/500 НЕ маскируются fallback'ом —
  это реальный сбой, он одинаков локально и в сервисе.

Режимы URL:
- прямой (по умолчанию): каждый сервис по своему env URL;
- gateway: CUTTER_GATEEND_URL задан → ВСЕ операции идут на один URL
  {gateway}/{service}/..., а gateway проксирует на бэкенды;
- пустая строка URL сервиса принудительно отключает его (локально).
"""

import json
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
    EtaBookRequestDTO,
    EtaRequestDTO,
    EtaResultDTO,
    GcodeRequestDTO,
    GcodeResultDTO,
    HealRequestDTO,
    MultiplyRequestDTO,
    ParseResultDTO,
    PathsResultDTO,
    PatternRequestDTO,
    PatternResultDTO,
    PostsPayloadDTO,
    PriceRequestDTO,
    PriceResultDTO,
    QueueDTO,
    ReportRequestDTO,
    ReportResultDTO,
    RotateRequestDTO,
    SaveResultDTO,
    StateDocDTO,
    ToolDTO,
    ToolsPayloadDTO,
    UvMaskRequestDTO,
    UvMaskResultDTO,
)
from src.db.db_manager import DatabaseManager
from src.db.models import PostProcessor, Tool
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
        state_url: str | None = None,
        pricing_url: str | None = None,
        eta_url: str | None = None,
        gateway_url: str | None = None,
        job_timeout: float = 300.0,
    ):
        self.ingest_url = self._resolve(ingest_url, "CUTTER_INGEST_URL", "http://127.0.0.1:8765")
        self.render_url = self._resolve(render_url, "CUTTER_RENDER_URL", "http://127.0.0.1:8766")
        self.geometry_url = self._resolve(geometry_url, "CUTTER_GEOMETRY_URL", "http://127.0.0.1:8767")
        self.math_url = self._resolve(math_url, "CUTTER_MATH_URL", "http://127.0.0.1:8768")
        self.cam_url = self._resolve(cam_url, "CUTTER_CAM_URL", "http://127.0.0.1:8769")
        self.state_url = self._resolve(state_url, "CUTTER_STATE_URL", "http://127.0.0.1:8770")
        self.pricing_url = self._resolve(pricing_url, "CUTTER_PRICING_URL", "http://127.0.0.1:8774")
        self.eta_url = self._resolve(eta_url, "CUTTER_ETA_URL", "http://127.0.0.1:8775")
        # "" = gateway выключен (прямые URL сервисов); задан → все операции через него
        self.gateway_url = self._resolve(gateway_url, "CUTTER_GATEWAY_URL", "")
        self.job_timeout = job_timeout

    @staticmethod
    def _resolve(explicit: str | None, env_name: str, default: str) -> str:
        value = explicit if explicit is not None else os.environ.get(env_name, default)
        return (value or "").rstrip("/")

    # ==========================================================
    # инфраструктура
    # ==========================================================

    def _base(self, service: str) -> str:
        """Базовый URL операции: gateway-режим или прямой URL сервиса."""
        if self.gateway_url:
            return f"{self.gateway_url}/{service}"
        return getattr(self, f"{service}_url")

    def _call(self, service: str, path: str, payload: dict) -> dict | None:
        """POST compute-задачи + polling. None = сервис недоступен (нужен fallback)."""
        base = self._base(service)
        if not base:
            return None
        try:
            r = httpx.post(
                f"{base}{path}",
                json=payload,
                timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
            )
            if r.status_code == 503:
                print(f"[КЛИЕНТ] {service} недоступен (503 от {base}) — выполняю локально")
                return None
            r.raise_for_status()
            return self._wait(base, r.json()["job_id"])
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] {service} недоступен ({base}): {e.__class__.__name__} — выполняю локально")
            return None

    def _post_sync(self, service: str, path: str, payload: dict) -> dict | None:
        """Синхронный POST (state-сервис). None = сервис недоступен (нужен fallback)."""
        base = self._base(service)
        if not base:
            return None
        try:
            r = httpx.post(
                f"{base}{path}",
                json=payload,
                timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
            )
            if r.status_code == 503:
                print(f"[КЛИЕНТ] {service} недоступен (503 от {base}) — выполняю локально")
                return None
            r.raise_for_status()
            return r.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] {service} недоступен ({base}): {e.__class__.__name__} — выполняю локально")
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

    @staticmethod
    def _local_db() -> DatabaseManager:
        # Тот же корень, что и у state-сервиса: тесты меняют env, прод использует cwd
        return DatabaseManager(root=os.environ.get("CUTTER_STATE_ROOT") or None)

    # ==========================================================
    # ingest: парсинг макета
    # ==========================================================

    def parse(self, input_path: str | Path) -> list[CamPath]:
        base = self._base("ingest")
        if not base:
            return CamPipeline().step1_parse(input_path)
        try:
            with open(input_path, "rb") as f:
                r = httpx.post(
                    f"{base}/v1/parse",
                    files={"file": (Path(input_path).name, f)},
                    timeout=httpx.Timeout(30.0, connect=_CONNECT_TIMEOUT),
                )
            if r.status_code == 503:
                print(f"[КЛИЕНТ] ingest недоступен (503 от {base}) — выполняю локально")
                return CamPipeline().step1_parse(input_path)
            r.raise_for_status()
            result = self._wait(base, r.json()["job_id"])
            parsed = ParseResultDTO.model_validate(result)
            return [CamPath.from_dto(p) for p in parsed.paths]
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            print(f"[КЛИЕНТ] ingest недоступен ({base}): {e.__class__.__name__} — выполняю локально")
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
        result = self._call("render", "/v1/uv-mask", req.model_dump())
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
        result = self._call("render", "/v1/report", req.model_dump())
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
        result = self._call("geometry", "/v1/check-errors", req.model_dump())
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
        result = self._call("geometry", "/v1/heal", req.model_dump())
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
        result = self._call("math", "/v1/pattern", req.model_dump())
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
        result = self._call("math", "/v1/multiply", req.model_dump())
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
        result = self._call("math", "/v1/distortion", req.model_dump())
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
        result = self._call("math", "/v1/rotate", req.model_dump())
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
        result = self._call("math", "/v1/crop-marks", req.model_dump())
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
        result = self._call("cam", "/v1/gcode", req.model_dump())
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

    # ==========================================================
    # state: БД инструментов (фрезы)
    # ==========================================================

    def load_tools(self) -> list[Tool]:
        result = self._post_sync("state", "/v1/tools/load", {})
        if result is not None:
            parsed = ToolsPayloadDTO.model_validate(result)
            return [Tool.from_dto(t) for t in parsed.tools]
        return self._local_db().load_tools()

    def save_tools(self, tools: list[Tool]) -> None:
        req = ToolsPayloadDTO(tools=[t.to_dto() for t in tools])
        result = self._post_sync("state", "/v1/tools/save", req.model_dump())
        if result is None:
            self._local_db().save_tools(tools)

    def import_tools(self, filepath: str | Path) -> None:
        """Импорт из внешнего файла: чтение всегда локально (filedialog → наш хост)."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_tools = [Tool.from_dict(item) for item in json.load(f)]
        except Exception as e:
            raise RuntimeError(f"Не удалось импортировать инструменты: {e}")
        tools = self.load_tools()
        tools.extend(new_tools)
        self.save_tools(tools)

    def export_tools(self, filepath: str | Path) -> None:
        try:
            tools = self.load_tools()
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump([t.to_dict() for t in tools], f, indent=4, ensure_ascii=False)
        except Exception as e:
            raise RuntimeError(f"Не удалось экспортировать инструменты: {e}")

    # ==========================================================
    # state: БД постпроцессоров
    # ==========================================================

    def load_postprocessors(self) -> list[PostProcessor]:
        result = self._post_sync("state", "/v1/posts/load", {})
        if result is not None:
            parsed = PostsPayloadDTO.model_validate(result)
            return [PostProcessor.from_dto(p) for p in parsed.posts]
        return self._local_db().load_postprocessors()

    def save_postprocessors(self, posts: list[PostProcessor]) -> None:
        req = PostsPayloadDTO(posts=[p.to_dto() for p in posts])
        result = self._post_sync("state", "/v1/posts/save", req.model_dump())
        if result is None:
            self._local_db().save_postprocessors(posts)

    def import_postprocessors(self, filepath: str | Path) -> None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_posts = [PostProcessor.from_dict(item) for item in json.load(f)]
        except Exception as e:
            raise RuntimeError(f"Не удалось импортировать постпроцессоры: {e}")
        posts = self.load_postprocessors()
        posts.extend(new_posts)
        self.save_postprocessors(posts)

    def export_postprocessors(self, filepath: str | Path) -> None:
        try:
            posts = self.load_postprocessors()
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in posts], f, indent=4, ensure_ascii=False)
        except Exception as e:
            raise RuntimeError(f"Не удалось экспортировать постпроцессоры: {e}")

    # ==========================================================
    # state: документы проектов (project_state.json)
    # ==========================================================

    def save_project_doc(self, path: str | Path, data: dict) -> None:
        req = StateDocDTO(path=str(path), data=data)
        result = self._post_sync("state", "/v1/project/save", req.model_dump())
        if result is None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

    def load_project_doc(self, path: str | Path) -> dict:
        try:
            result = self._post_sync("state", "/v1/project/load", {"path": str(path)})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Сервис жив, файла нет — как и локальный open() бросил бы FileNotFoundError
                raise FileNotFoundError(f"Файл проекта не найден: {path}")
            # Остальные 4xx/500: показываем detail сервиса, а не сухой httpx-текст
            try:
                detail = e.response.json().get("detail")
            except Exception:
                detail = None
            raise RuntimeError(str(detail) if detail else str(e)) from e
        if result is not None:
            return StateDocDTO.model_validate(result).data
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except UnicodeDecodeError as e:
            raise RuntimeError(
                f"«{Path(path).name}» не UTF-8 JSON — это не документ проекта (нужен project_state.json). "
                "Если это макет — нажмите «НОВЫЙ ПРОЕКТ (ИЗ МАКЕТА)»."
            ) from e

    # ==========================================================
    # pricing / eta: синхронные доп-сервисы (HTTP или локальное ядро)
    # ==========================================================

    def price(self, time_min: float, area_mm2: float = 0.0) -> PriceResultDTO:
        req = PriceRequestDTO(time_min=time_min, area_mm2=area_mm2)
        result = self._post_sync("pricing", "/v1/price", req.model_dump())
        if result is not None:
            return PriceResultDTO.model_validate(result)
        from src.biz.pricing import calc_price

        return calc_price(time_min, area_mm2)

    def eta(self, time_min: float) -> EtaResultDTO:
        req = EtaRequestDTO(time_min=time_min)
        result = self._post_sync("eta", "/v1/eta", req.model_dump())
        if result is not None:
            return EtaResultDTO.model_validate(result)
        from src.biz.eta_store import eta_now

        return eta_now(time_min)

    def book_eta(self, time_min: float, label: str = "") -> QueueDTO:
        req = EtaBookRequestDTO(time_min=time_min, label=label)
        result = self._post_sync("eta", "/v1/book", req.model_dump())
        if result is not None:
            return QueueDTO.model_validate(result)
        from src.biz.eta_store import book

        return book(time_min, label)
