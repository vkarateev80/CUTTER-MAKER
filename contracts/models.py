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


# ============================================================
# Фаза 3: сервисы geometry / math / cam
# ============================================================

class PathsResultDTO(BaseModel):
    """Универсальный результат: список контуров."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO] = Field(default_factory=list)


class CheckErrorsRequestDTO(BaseModel):
    """geometry: проверка геометрии на ошибки (ШАГ 2)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    min_loop_area: float = 0.0


class CheckErrorsResultDTO(BaseModel):
    """Счётчики и узлы ошибок — ключи совпадают со stats из step2_check_errors."""

    model_config = ConfigDict(extra="ignore")

    open_paths: int = 0
    empty_paths: int = 0
    intersections: int = 0
    duplicates: int = 0
    dust: int = 0
    error_nodes: list[Point] = Field(default_factory=list)
    intersection_nodes: list[Point] = Field(default_factory=list)
    duplicate_nodes: list[Point] = Field(default_factory=list)
    dust_nodes: list[Point] = Field(default_factory=list)


class HealRequestDTO(BaseModel):
    """geometry: морфологическое лечение (ШАГ 3)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    tolerance: float = 0.01
    min_loop_area: float = 0.0


class PatternRequestDTO(BaseModel):
    """math: распознавание массива (Master-штамп)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    tolerance: float = 0.5


class PatternResultDTO(BaseModel):
    """Результат PatternRecognizer — поля с дефолтами = формат _empty_result."""

    model_config = ConfigDict(extra="ignore")

    is_array: bool = False
    count: int = 0
    rows: int = 0
    cols: int = 0
    step_x: float = 0.0
    step_y: float = 0.0
    gap_x: float = 0.0
    gap_y: float = 0.0
    master_paths: list[CamPathDTO] = Field(default_factory=list)
    offsets: list[Point] = Field(default_factory=list)


class MultiplyRequestDTO(BaseModel):
    """math: размножение мастер-штампа по смещениям (Step & Repeat)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    offsets: list[tuple[float, float]] = Field(default_factory=list)


class DistortionRequestDTO(BaseModel):
    """math: сжатие макета под магнитный вал (дисторсия)."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    factor: float
    axis: str = "Y"


class RotateRequestDTO(BaseModel):
    """math: поворот геометрии вокруг центра."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    angle_deg: float = 90.0


class CropMarksRequestDTO(BaseModel):
    """math: генерация обрезных меток по рапорту."""

    model_config = ConfigDict(extra="ignore")

    paths: list[CamPathDTO]
    rapport: float
    width: float
    axis: str = "Y"


class GcodeRequestDTO(BaseModel):
    """cam: генерация УП из геометрии маски (output_path — путь на хосте сервиса)."""

    model_config = ConfigDict(extra="ignore")

    mask_geom_wkt: str
    output_path: str
    tool: ToolDTO
    post: PostProcessorDTO
    mask_offset: float
    enable_sharpening: bool = False
    lead_radius: float = 0.0
    milling_dir: str = "Climb"


class GcodeResultDTO(BaseModel):
    """cam: слои идеального лезвия/ЧПУ, расчётное время и текст УП."""

    model_config = ConfigDict(extra="ignore")

    ideal_paths: list[CamPathDTO] = Field(default_factory=list)
    cnc_paths: list[CamPathDTO] = Field(default_factory=list)
    time_min: float = 0.0
    gcode_text: str = ""


# ============================================================
# Фаза 4: сервис state (tools/postprocessors/документы проекта)
# ============================================================

class ToolsPayloadDTO(BaseModel):
    """Список фрез для загрузки/сохранения в БД state-сервиса."""

    model_config = ConfigDict(extra="ignore")

    tools: list[ToolDTO] = Field(default_factory=list)


class PostsPayloadDTO(BaseModel):
    """Список постпроцессоров для загрузки/сохранения в БД state-сервиса."""

    model_config = ConfigDict(extra="ignore")

    posts: list[PostProcessorDTO] = Field(default_factory=list)


class SaveResultDTO(BaseModel):
    """Результат сохранения: сколько записей записано."""

    model_config = ConfigDict(extra="ignore")

    count: int = 0


class StatePathDTO(BaseModel):
    """Путь к документу проекта (project_state.json): запрос загрузки / ответ сохранения."""

    model_config = ConfigDict(extra="ignore")

    path: str


class StateDocDTO(BaseModel):
    """Документ проекта: путь + произвольный JSON."""

    model_config = ConfigDict(extra="ignore")

    path: str
    data: dict = Field(default_factory=dict)


# ============================================================
# Фаза 5+: доп-сервисы pricing (стоимость) и eta (срок изготовления)
# ============================================================

class PriceConfigDTO(BaseModel):
    """Тарифы расчёта стоимости (state-артефакт data/pricing.json)."""

    model_config = ConfigDict(extra="ignore")

    rate_per_hour: float = 2500.0     # ₽ за час машинного времени
    setup_cost: float = 500.0         # ₽ за наладку
    material_per_mm2: float = 0.05    # ₽ за мм² (0 — без материала)
    min_price: float = 1000.0         # минимальный заказ
    currency: str = "RUB"


class PriceRequestDTO(BaseModel):
    """Расчёт стоимости одного заказа."""

    model_config = ConfigDict(extra="ignore")

    time_min: float = 0.0
    area_mm2: float = 0.0
    config: PriceConfigDTO | None = None  # override тарифов из сохранённых


class PriceResultDTO(BaseModel):
    """Разбивка стоимости заказа."""

    model_config = ConfigDict(extra="ignore")

    setup: float = 0.0
    machine: float = 0.0
    material: float = 0.0
    subtotal: float = 0.0
    total: float = 0.0
    currency: str = "RUB"
    hours: float = 0.0
    time_min: float = 0.0


class EtaBookRequestDTO(BaseModel):
    """Бронь машинного времени в очередь."""

    model_config = ConfigDict(extra="ignore")

    time_min: float
    label: str = ""


class QueueItemDTO(BaseModel):
    """Элемент очереди ЧПУ."""

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    time_min: float = 0.0
    booked_at: str = ""


class QueueDTO(BaseModel):
    """Снимок очереди: элементы и суммарные минуты."""

    model_config = ConfigDict(extra="ignore")

    items: list[QueueItemDTO] = Field(default_factory=list)
    total_minutes: float = 0.0


class EtaRequestDTO(BaseModel):
    """Оценка срока для заказа длиной time_min."""

    model_config = ConfigDict(extra="ignore")

    time_min: float = 0.0


class EtaResultDTO(BaseModel):
    """Срок изготовления: очередь + собственное время заказа."""

    model_config = ConfigDict(extra="ignore")

    queue_minutes: float = 0.0
    machine_minutes: float = 0.0
    ready_minutes_from_now: float = 0.0
    ready_at: str = ""
