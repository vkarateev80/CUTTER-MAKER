"""Pydantic-модели контрактов (API v1).

Правила:
- только поля, существующие в текущем wire-формате (project_state.json,
  tools.json, postprocessors.json) — совместимость со старыми файлами;
- extra-поля игнорируются (как раньше делал from_dict через .get);
- все поля имеют дефолты — загрузка старого файла без поля не падает.
"""

import uuid

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
