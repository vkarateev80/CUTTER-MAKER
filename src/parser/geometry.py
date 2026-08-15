from dataclasses import dataclass, field

@dataclass
class CamPath:
    # Теперь точки могут хранить либо (X, Y), либо (X, Y, Z)
    points: list[tuple[float, float] | tuple[float, float, float]] = field(default_factory=list)
    is_closed: bool = False
    layer_name: str = "default"

    def add_point(self, x: float, y: float, z: float = None) -> None:
        if z is not None:
            self.points.append((x, y, z))
        else:
            self.points.append((x, y))

    def __len__(self) -> int:
        return len(self.points)