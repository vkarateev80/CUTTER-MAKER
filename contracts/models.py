"""Pydantic-модели контрактов (API v1).

Правила:
- только поля, существующие в текущем wire-формате (project_state.json,
  tools.json, postprocessors.json) — совместимость со старыми файлами;
- extra-поля игнорируются (как раньше делал from_dict через .get);
- все поля имеют дефолты — загрузка старого файла без поля не падает.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Точка: (x, y) либо (x, y, z) — z появляется после V-Carve/калибровки
Point = tuple[float, float] | tuple[float, float, float]


class CamPathDTO(BaseModel):
    """Векторный контур: полилиния + признак замкнутости + имя слоя."""

    model_config = ConfigDict(extra="ignore")

    points: list[Point] = Field(default_factory=list)
    is_closed: bool = False
    layer_name: str = "default"


class ToolDTO(BaseModel):
    """Фреза: геометрия конуса и режимы резания."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Новая фреза"
    tool_type: str = "V-Bit"
    angle_deg: float = 60.0
    tip_diameter: float = 0.1
    depth: float = 0.5
    step_down: float = 0.2
    feedrate: int = 1500
    spindle_speed: int = 1000


class PostProcessorDTO(BaseModel):
    """Постпроцессор станка: шаблоны строк G-кода и безопасная высота."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Новый Постпроцессор"
    extension: str = ".txt"
    header: str = "; НАЧАЛО\nG21\nG90\nG0 Z{safe_z}"
    footer: str = "; КОНЕЦ\nG0 Z{safe_z}\nG0 X0 Y0\nM30"
    tool_on: str = "M3 S{rpm}"
    tool_off: str = "M5"
    safe_z: float = 5.0


# ============================================================
# Фаза 2: асинхронные задачи (ingest / render services)
# ============================================================

class JobRefDTO(BaseModel):
    """Ответ на принятую задачу: клиент опрашивает статус по job_id."""

    model_config = ConfigDict(extra="ignore")

    job_id: str


class JobStatusDTO(BaseModel):
    """Статус задачи при polling GET /v1/jobs/{id}."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: Literal["queued", "running", "done", "error"]
    error: str | None = None
    result: dict[str, Any] | None = None


class ParseResultDTO(BaseModel):
    """Результат ingest: распарсенный макет."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]


class UvMaskRequestDTO(BaseModel):
    """Запрос render: генерация УФ-маски PDF (output_path — путь на хосте сервиса)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    offset: float
    output_path: str
    badge_text: str = ""
    mark_d: float = 4.0
    mark_margin: float = 10.0


class UvMaskResultDTO(BaseModel):
    """Результат УФ-маски: слои для холста + геометрия маски (WKT, как в project_state.json)."""

    model_config = ConfigDict(extra="ignore")

    visual_paths: list[CamPathDTO]
    pure_paths: list[CamPathDTO]
    mask_geom_wkt: str


class ReportRequestDTO(BaseModel):
    """Запрос render: технологическая карта (PDF) для оператора ЧПУ."""

    model_config = ConfigDict(extra="ignore")

    project_name: str
    stats: dict[str, str | float | int | bool]
    paths: list[CamPathDTO]
    output_path: str


class ReportResultDTO(BaseModel):
    """Результат техкарты: куда записан PDF."""

    model_config = ConfigDict(extra="ignore")

    output_path: str
