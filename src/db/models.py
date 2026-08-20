import uuid
from dataclasses import dataclass, field, asdict

@dataclass
class Tool:
    """
    Модель данных для инструмента (фрезы).
    Содержит физические размеры и режимы резания.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Новая фреза"
    tool_type: str = "V-Bit"
    angle_deg: float = 60.0
    tip_diameter: float = 0.1
    depth: float = 0.5
    step_down: float = 0.2
    feedrate: int = 1500
    spindle_speed: int = 1000

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Tool':
        # Игнорируем неизвестные ключи (полезно для совместимости будущих версий)
        valid_keys = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)

@dataclass
class PostProcessor:
    """
    Модель данных для постпроцессора (станка).
    Содержит шаблоны G-кода для заголовка, подвала и команд управления.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Новый Постпроцессор"
    extension: str = ".txt"
    header: str = "; НАЧАЛО\nG21\nG90\nG0 Z{safe_z}"
    footer: str = "; КОНЕЦ\nG0 Z{safe_z}\nG0 X0 Y0\nM30"
    tool_on: str = "M3 S{rpm}"
    tool_off: str = "M5"
    safe_z: float = 5.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'PostProcessor':
        valid_keys = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)