from dataclasses import dataclass, field

from contracts import CamPathDTO

@dataclass
class CamPath:
    points: list[tuple[float, float] | tuple[float, float, float]] = field(default_factory=list)
    is_closed: bool = False
    layer_name: str = "default"

    def add_point(self, x: float, y: float, z: float = None) -> None:
        if z is not None: self.points.append((x, y, z))
        else: self.points.append((x, y))

    def __len__(self) -> int: return len(self.points)

    def to_dto(self) -> CamPathDTO:
        return CamPathDTO(points=self.points, is_closed=self.is_closed, layer_name=self.layer_name)

    @classmethod
    def from_dto(cls, dto: CamPathDTO) -> "CamPath":
        return cls(
            points=[tuple(p) for p in dto.points],
            is_closed=dto.is_closed,
            layer_name=dto.layer_name
        )

    def to_dict(self) -> dict:
        return self.to_dto().model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> 'CamPath':
        # Валидация и приведение типов (списки -> кортежи) — на стороне контракта
        return cls.from_dto(CamPathDTO.model_validate(data))
