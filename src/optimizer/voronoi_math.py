import math
import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import linemerge
from src.parser.geometry import CamPath

class VoronoiSkeletonizer:
    """
    Генератор Медиальной оси (Скелета) на базе Диаграммы Вороного.
    Используется для стратегии V-Carve.
    """
    def __init__(self, step_size: float = 0.5):
        self.step_size = step_size

    def _discretize_ring(self, ring) -> list[tuple[float, float]]:
        points = []
        length = ring.length
        if length == 0: return points
        num_points = max(4, int(length / self.step_size))
        actual_step = length / num_points
        for i in range(num_points):
            pt = ring.interpolate(i * actual_step)
            points.append((pt.x, pt.y))
        return points

    def generate_skeleton(self, poly: Polygon) -> list[CamPath]:
        if poly.is_empty or poly.area < 1e-6: return []

        # 1. Облако точек
        points = self._discretize_ring(poly.exterior)
        for interior in poly.interiors:
            points.extend(self._discretize_ring(interior))
            
        if len(points) < 4: return []

        # 2. Диаграмма Вороного
        try:
            vor = Voronoi(np.array(points))
        except Exception:
            return []

        # 3. Отбираем отрезки внутри детали
        safe_poly = poly.buffer(-1e-4)
        if safe_poly.is_empty: safe_poly = poly

        raw_lines = []
        for ridge in vor.ridge_vertices:
            if ridge[0] == -1 or ridge[1] == -1: continue
            
            p1 = vor.vertices[ridge[0]]
            p2 = vor.vertices[ridge[1]]
            
            if math.dist(p1, p2) < 1e-4: continue
                
            line = LineString([p1, p2])
            if safe_poly.contains(line):
                raw_lines.append(line)
                
        if not raw_lines: return []

        # 4. ИСПРАВЛЕНИЕ "ПИЛЫ": Сшиваем отрезки в длинные магистрали!
        merged = linemerge(raw_lines)
        if isinstance(merged, LineString):
            merged_lines = [merged]
        else:
            merged_lines = list(merged.geoms)

        skeleton_paths = []
        for m_line in merged_lines:
            # Сглаживаем магистраль, чтобы убрать мелкие заусенцы и зубья
            smooth_line = m_line.simplify(0.05)
            
            cp = CamPath(is_closed=False, layer_name="VORONOI_SKELETON")
            for x, y in smooth_line.coords:
                cp.add_point(round(x, 4), round(y, 4))
            skeleton_paths.append(cp)
            
        return skeleton_paths