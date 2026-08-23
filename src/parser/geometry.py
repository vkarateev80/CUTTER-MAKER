from dataclasses import dataclass, field

@dataclass
class CamPath:
    points: list[tuple[float, float] | tuple[float, float, float]] = field(default_factory=list)
    is_closed: bool = False
    layer_name: str = "default"

    def add_point(self, x: float, y: float, z: float = None) -> None:
        if z is not None: self.points.append((x, y, z))
        else: self.points.append((x, y))

    def __len__(self) -> int: return len(self.points)

    def to_dict(self) -> dict:
        return {
            "points": self.points,
            "is_closed": self.is_closed,
            "layer_name": self.layer_name
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CamPath':
        # При загрузке из JSON списки координат конвертируем обратно в кортежи (tuples)
        pts = [tuple(p) for p in data.get("points", [])]
        return cls(
            points=pts,
            is_closed=data.get("is_closed", False),
            layer_name=data.get("layer_name", "default")
        )