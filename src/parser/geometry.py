from dataclasses import dataclass, field

@dataclass
class CamPath:
    """
    Единое представление векторного контура для нашей CAM-системы.
    Любой формат (DXF, PDF, SVG) после парсинга будет конвертироваться в объекты этого класса.
    
    Атрибуты:
        points: Список координат (x, y). Представляет собой полилинию (ломаную линию).
        is_closed: Флаг замкнутости контура (True, если начальная и конечная точки совпадают).
        layer_name: Имя слоя (полезно для разделения реза, гравировки и маркировки).
    """
    # Используем field(default_factory=list), чтобы у каждого нового объекта 
    # был свой собственный, независимый список точек.
    points: list[tuple[float, float]] = field(default_factory=list)
    is_closed: bool = False
    layer_name: str = "default"

    def add_point(self, x: float, y: float) -> None:
        """
        Метод для удобного добавления новой точки в контур.
        
        :param x: Координата X
        :param y: Координата Y
        """
        self.points.append((x, y))

    def __len__(self) -> int:
        """Возвращает количество точек в контуре."""
        return len(self.points)