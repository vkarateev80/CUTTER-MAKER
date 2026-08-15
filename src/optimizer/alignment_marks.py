import math
from src.parser.geometry import CamPath

class AlignmentMarksGenerator:
    """
    Генератор реперных меток (Fiducials) для точного позиционирования заготовки на ЧПУ-станке.
    Создает классическую оптическую метку-перекрестие (состоит из 4-х сегментов).
    """
    def __init__(self, mark_diameter: float = 4.0, margin: float = 10.0, cross_width: float = 0.2):
        self.mark_diameter = mark_diameter
        self.margin = margin
        self.cross_width = cross_width

    def generate(self, paths: list[CamPath]) -> list[CamPath]:
        if not paths:
            return []

        # 1. Вычисляем Bounding Box
        all_x = []
        all_y = []
        for path in paths:
            for x, y in path.points:
                all_x.append(x)
                all_y.append(y)

        if not all_x or not all_y:
            return []

        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        # 2. Определяем координаты центров 4-х меток
        centers = [
            (min_x - self.margin, min_y - self.margin),
            (max_x + self.margin, min_y - self.margin),
            (max_x + self.margin, max_y + self.margin),
            (min_x - self.margin, max_y + self.margin)
        ]

        # 3. Генерируем геометрию перекрестий
        marks_paths = []
        for cx, cy in centers:
            marks_paths.extend(self._create_crosshair_mark(cx, cy, self.mark_diameter, self.cross_width))

        return marks_paths

    def _create_crosshair_mark(self, cx: float, cy: float, diameter: float, cross_width: float) -> list[CamPath]:
        """
        Генерирует 4 замкнутых контура (четвертинки), образующих круг с вырезанным перекрестием.
        """
        radius = diameter / 2.0
        offset = cross_width / 2.0
        
        # Защита: если толщина перекрестия больше диаметра, не строим
        if offset >= radius:
            return []
            
        # 1. Генерируем базовый квадрант (Верхний Правый) относительно центра (0,0)
        base_points = []
        
        # Внутренний угол (возле центра)
        base_points.append((offset, offset))
        
        # Правый нижний угол квадранта (начало дуги)
        start_x = math.sqrt(radius**2 - offset**2)
        base_points.append((start_x, offset))
        
        # Точки дуги (используем тригонометрию)
        angle_start = math.asin(offset / radius)
        angle_end = math.acos(offset / radius)
        segments = 12
        for i in range(1, segments):
            t = i / segments
            ang = angle_start + t * (angle_end - angle_start)
            base_points.append((radius * math.cos(ang), radius * math.sin(ang)))
            
        # Левый верхний угол квадранта (конец дуги)
        base_points.append((offset, start_x))
        
        # 2. Создаем 4 повернутые копии (для каждого из 4 углов перекрестия)
        paths = []
        rotations = [
            (1, 0, 0, 1),    # 0 градусов (Верхний Правый)
            (0, -1, 1, 0),   # 90 градусов (Верхний Левый)
            (-1, 0, 0, -1),  # 180 градусов (Нижний Левый)
            (0, 1, -1, 0)    # 270 градусов (Нижний Правый)
        ]
        
        for r11, r12, r21, r22 in rotations:
            quad_path = CamPath(layer_name="FIDUCIAL_MARK", is_closed=True)
            for bx, by in base_points:
                # Поворот через матрицу 2x2
                rx = bx * r11 + by * r12
                ry = bx * r21 + by * r22
                # Смещение к реальному центру метки на холсте
                quad_path.add_point(round(cx + rx, 4), round(cy + ry, 4))
            
            # Обязательно замыкаем контур (возвращаемся в первую точку)
            quad_path.add_point(quad_path.points[0][0], quad_path.points[0][1])
            paths.append(quad_path)
            
        return paths