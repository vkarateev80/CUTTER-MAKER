import math
import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, LineString, Point
from src.parser.geometry import CamPath

class VoronoiSkeletonizer:
    """
    Генератор Медиальной оси (Скелета) на базе Диаграммы Вороного.
    Используется для стратегии V-Carve (динамическое изменение глубины Z).
    """
    def __init__(self, step_size: float = 0.5):
        # Шаг дискретизации контура. 
        # 0.5 мм — идеальный баланс между точностью скелета и скоростью вычислений.
        self.step_size = step_size

    def _discretize_ring(self, ring) -> list[tuple[float, float]]:
        """Разбивает контур (LineString/LinearRing) на равномерные точки."""
        points = []
        length = ring.length
        if length == 0:
            return points
            
        num_points = max(4, int(length / self.step_size))
        actual_step = length / num_points
        
        for i in range(num_points):
            pt = ring.interpolate(i * actual_step)
            points.append((pt.x, pt.y))
            
        return points

    def generate_skeleton(self, poly: Polygon) -> list[CamPath]:
        """
        Принимает полигон (Колодец) и возвращает список линий,
        образующих его внутренний скелет.
        """
        if poly.is_empty or poly.area < 1e-6:
            return []

        # 1. Разбиваем внешний контур и все внутренние отверстия на облако точек
        points = self._discretize_ring(poly.exterior)
        for interior in poly.interiors:
            points.extend(self._discretize_ring(interior))
            
        # Для диаграммы Вороного нужно хотя бы 4 точки
        if len(points) < 4:
            return []

        # 2. Строим математическую Диаграмму Вороного
        # Она построит паутину линий, равноудаленных от всех точек контура
        try:
            vor = Voronoi(np.array(points))
        except Exception:
            # Защита от коллизий qhull (если точки лежат на одной прямой)
            return []

        # 3. Фильтрация граней (оставляем только то, что внутри колодца)
        skeleton_paths = []
        
        # Делаем микро-отступ внутрь, чтобы избежать багов с плавающей запятой на границах
        safe_poly = poly.buffer(-1e-4)
        if safe_poly.is_empty:
            safe_poly = poly

        # Проходим по всем граням (хребтам) диаграммы Вороного
        for ridge in vor.ridge_vertices:
            # Если грань уходит в бесконечность (индекс -1), игнорируем
            if ridge[0] == -1 or ridge[1] == -1:
                continue
            
            p1 = vor.vertices[ridge[0]]
            p2 = vor.vertices[ridge[1]]
            
            # Пропускаем микро-сегменты
            if math.dist(p1, p2) < 1e-4:
                continue
                
            line = LineString([p1, p2])
            
            # САМОЕ ГЛАВНОЕ: Грань Вороного должна лежать СТРОГО внутри детали!
            # Так мы отсекаем внешнюю паутину и оставляем только внутренний скелет.
            if safe_poly.contains(line):
                cp = CamPath(is_closed=False, layer_name="VORONOI_SKELETON")
                cp.add_point(round(p1[0], 4), round(p1[1], 4))
                cp.add_point(round(p2[0], 4), round(p2[1], 4))
                skeleton_paths.append(cp)
                
        return skeleton_paths