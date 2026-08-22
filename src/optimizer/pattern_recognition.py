from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union, polygonize
from collections import defaultdict
from src.parser.geometry import CamPath

class PatternRecognizer:
    def __init__(self, tolerance: float = 0.5):
        self.tolerance = tolerance # Допуск для поиска рядов и колонок

    def analyze(self, paths: list[CamPath]) -> dict:
        lines = []
        polys = []
        for p in paths:
            if len(p.points) < 2: continue
            if p.is_closed and len(p.points) >= 3:
                try:
                    poly = Polygon([(pt[0], pt[1]) for pt in p.points])
                    if poly.is_valid and poly.area > 5.0:
                        polys.append(poly)
                except: pass
            lines.append(LineString([(pt[0], pt[1]) for pt in p.points]))

        if not polys and lines:
            try:
                noded = unary_union(lines)
                for poly in polygonize(noded):
                    if poly.area > 5.0:
                        polys.append(poly)
            except: pass

        if not polys:
            return self._empty_result()

        # Шаг 1: Группировка по Габаритам (Ширина, Высота)
        # Округляем до целых миллиметров, чтобы избежать погрешностей парсинга
        buckets = defaultdict(list)
        for poly in polys:
            minx, miny, maxx, maxy = poly.bounds
            w = round(maxx - minx)
            h = round(maxy - miny)
            buckets[(w, h)].append(poly)

        if not buckets: return self._empty_result()

        main_bucket = max(buckets.values(), key=len)
        if len(main_bucket) < 2:
            return self._empty_result()

        # Шаг 2: Изоляция МАСТЕР-ШТАМПА
        main_bucket.sort(key=lambda p: (-round(p.centroid.y, 1), round(p.centroid.x, 1)))
        master_poly = main_bucket[0]
        master_centroid = master_poly.centroid

        # СТРОГАЯ ИЗОЛЯЦИЯ: Вектор должен быть ПОЛНОСТЬЮ внутри буфера эталона
        search_area = master_poly.buffer(0.2)
        master_paths = []
        for p in paths:
            if len(p.points) < 2: continue
            ls = LineString([(pt[0], pt[1]) for pt in p.points])
            if search_area.contains(ls) or search_area.covers(ls):
                master_paths.append(p)
                
        # Резервный поиск (если строгий ничего не нашел из-за микро-артефактов)
        if not master_paths:
            search_area_fallback = master_poly.buffer(0.5)
            for p in paths:
                if len(p.points) < 2: continue
                ls = LineString([(pt[0], pt[1]) for pt in p.points])
                if search_area_fallback.intersects(ls):
                    master_paths.append(p)

        # Шаг 3: Расчет смещений
        offsets = []
        for poly in main_bucket:
            dx = poly.centroid.x - master_centroid.x
            dy = poly.centroid.y - master_centroid.y
            offsets.append((dx, dy))

        # Шаг 4: Анализ сетки
        centroids = [poly.centroid for poly in main_bucket]
        rows = self._group_1d([c.y for c in centroids], self.tolerance)
        cols = self._group_1d([c.x for c in centroids], self.tolerance)

        num_rows = len(rows)
        num_cols = len(cols)

        step_x = self._calc_median_step(cols) if num_cols > 1 else 0.0
        step_y = self._calc_median_step(rows) if num_rows > 1 else 0.0

        minx, miny, maxx, maxy = master_poly.bounds
        label_w = maxx - minx
        label_h = maxy - miny

        gap_x = max(0.0, step_x - label_w) if step_x > 0 else 0.0
        gap_y = max(0.0, step_y - label_h) if step_y > 0 else 0.0

        return {
            "is_array": True,
            "count": len(main_bucket),
            "rows": num_rows,
            "cols": num_cols,
            "step_x": round(step_x, 3),
            "step_y": round(step_y, 3),
            "gap_x": round(gap_x, 3),
            "gap_y": round(gap_y, 3),
            "master_paths": master_paths,
            "offsets": offsets
        }

    def _group_1d(self, values: list[float], tol: float) -> list[float]:
        sorted_vals = sorted(values)
        groups = []
        if not sorted_vals: return groups
        current_group = [sorted_vals[0]]
        for v in sorted_vals[1:]:
            if v - current_group[-1] <= tol:
                current_group.append(v)
            else:
                groups.append(sum(current_group)/len(current_group))
                current_group = [v]
        groups.append(sum(current_group)/len(current_group))
        return groups

    def _calc_median_step(self, groups: list[float]) -> float:
        if len(groups) < 2: return 0.0
        steps = [groups[i] - groups[i-1] for i in range(1, len(groups))]
        steps.sort()
        return steps[len(steps)//2]

    def _empty_result(self) -> dict:
        return {"is_array": False}