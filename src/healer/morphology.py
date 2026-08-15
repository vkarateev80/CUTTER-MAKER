from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import unary_union, polygonize, linemerge
import math
from src.parser.geometry import CamPath

class MorphologicalHealer:
    """
    Продвинутый модуль морфологического лечения (Snapping & Noding).
    Включает жесткий Пред-Фильтр для уравнивания "сырых" форматов (DXF, PDF, AI) 
    и высокоуровневых (SVG, CDR, EPS).
    """
    def __init__(self, tolerance: float = 0.01, min_loop_area: float = 0.0):
        self.tolerance = tolerance
        self.min_loop_area = min_loop_area

    def _snap_endpoints(self, lines: list[LineString]) -> list[LineString]:
        if not lines: return []
        
        endpoints = []
        for i, line in enumerate(lines):
            coords = list(line.coords)
            endpoints.append({'pt': coords[0], 'line_idx': i, 'is_start': True})
            endpoints.append({'pt': coords[-1], 'line_idx': i, 'is_start': False})
            
        for i in range(len(endpoints)):
            for j in range(i+1, len(endpoints)):
                pt1 = endpoints[i]['pt']
                pt2 = endpoints[j]['pt']
                dist = math.dist(pt1, pt2)
                if 0 < dist <= self.tolerance:
                    avg_pt = ((pt1[0]+pt2[0])/2, (pt1[1]+pt2[1])/2)
                    endpoints[i]['pt'] = avg_pt
                    endpoints[j]['pt'] = avg_pt
                    
        new_lines = []
        for i, line in enumerate(lines):
            coords = list(line.coords)
            start_pt = next(e['pt'] for e in endpoints if e['line_idx'] == i and e['is_start'])
            end_pt = next(e['pt'] for e in endpoints if e['line_idx'] == i and not e['is_start'])
            coords[0] = start_pt
            coords[-1] = end_pt
            
            if math.dist(coords[0], coords[-1]) < 1e-4:
                coords[-1] = coords[0]
                
            new_lines.append(LineString(coords))
            
        return new_lines

    def heal(self, paths: list[CamPath]) -> list[CamPath]:
        valid_lines = []
        
        # === 1. ЖЕСТКИЙ ПРЕД-ФИЛЬТР МУСОРА ===
        # Удаляем пыль ДО того, как она попадет в сложную математику сшивания!
        for p in paths:
            if len(p.points) < 2: continue
            
            line = LineString(p.points)
            
            if self.min_loop_area > 0:
                if p.is_closed or line.is_closed:
                    try:
                        poly = Polygon(line.coords)
                        if poly.area < self.min_loop_area:
                            continue # Удаляем мелкий замкнутый мусор
                    except Exception:
                        continue # Если не собирается в полигон - это битый мусор
                else:
                    if line.length < self.min_loop_area:
                        continue # Удаляем короткие штрихи-артефакты
                        
            valid_lines.append(line)
            
        if not valid_lines: return []

        # === 2. СНАППИНГ И СЛИЯНИЕ ===
        snapped_lines = self._snap_endpoints(valid_lines)
        merged = linemerge(snapped_lines)
        merged_lines = [merged] if isinstance(merged, LineString) else list(merged.geoms)

        # === 3. РАЗРЕЗАНИЕ ПЕРЕСЕЧЕНИЙ И СБОРКА ===
        noded_lines = unary_union(merged_lines)
        polygons = list(polygonize(noded_lines))
        
        good_polygons = []
        for poly in polygons:
            # Пост-фильтр петель, образовавшихся после сшивания
            if poly.area >= self.min_loop_area:
                good_polygons.append(poly)

        healed_paths = []
        
        if good_polygons:
            final_solid = unary_union(good_polygons)
            
            weld_size = 0.005 
            final_solid = final_solid.buffer(weld_size, join_style=1).buffer(-weld_size, join_style=1)
            
            def extract_poly(geom):
                if isinstance(geom, Polygon):
                    cp = CamPath(is_closed=True, layer_name="HEALED_POLY")
                    for x, y in geom.exterior.coords:
                        cp.add_point(round(x, 4), round(y, 4))
                    healed_paths.append(cp)
                    for interior in geom.interiors:
                        cp_hole = CamPath(is_closed=True, layer_name="HEALED_HOLE")
                        for x, y in interior.coords:
                            cp_hole.add_point(round(x, 4), round(y, 4))
                        healed_paths.append(cp_hole)
                elif isinstance(geom, MultiPolygon):
                    for g in geom.geoms:
                        extract_poly(g)
                        
            extract_poly(final_solid)

        # === 4. СОХРАНЕНИЕ ОСТАВШИХСЯ ОТКРЫТЫХ ЛИНИЙ ===
        if polygons:
            all_poly_lines = unary_union([p.exterior for p in polygons])
            remaining_lines = noded_lines.difference(all_poly_lines)
        else:
            remaining_lines = noded_lines
            
        if not remaining_lines.is_empty:
            merged_tails = linemerge(remaining_lines)
            tails = [merged_tails] if isinstance(merged_tails, LineString) else list(merged_tails.geoms)
            
            for tail in tails:
                # Еще раз проверяем хвосты по длине
                if tail.length >= self.min_loop_area:
                    cp = CamPath(is_closed=False, layer_name="HEALED_TAIL")
                    for x, y in tail.coords:
                        cp.add_point(round(x, 4), round(y, 4))
                    healed_paths.append(cp)

        return healed_paths