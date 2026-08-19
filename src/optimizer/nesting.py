from shapely.geometry import Polygon, MultiPolygon, Point
import math
from src.parser.geometry import CamPath

class NestingOptimizer:
    def _get_true_sharpening(self, ideal_geom, tool_radius: float, tool_depth: float) -> list[CamPath]:
        moves = []
        
        def process_ring(ring):
            raw_coords = list(ring.coords)
            if not raw_coords: return
            
            coords = [raw_coords[0]]
            for pt in raw_coords[1:]:
                if math.dist(pt, coords[-1]) > 1e-4:
                    coords.append(pt)
            if len(coords) > 1 and math.dist(coords[0], coords[-1]) < 1e-4:
                coords = coords[:-1]
                
            n = len(coords)
            if n < 3: return
            
            for i in range(n):
                B = coords[i]
                A = coords[i - 1]
                C = coords[(i + 1) % n]
                
                vBA_x, vBA_y = A[0] - B[0], A[1] - B[1]
                vBC_x, vBC_y = C[0] - B[0], C[1] - B[1]
                
                L_BA = math.hypot(vBA_x, vBA_y)
                L_BC = math.hypot(vBC_x, vBC_y)
                if L_BA < 1e-6 or L_BC < 1e-6: continue
                
                nBA_x, nBA_y = vBA_x / L_BA, vBA_y / L_BA
                nBC_x, nBC_y = vBC_x / L_BC, vBC_y / L_BC
                
                dot = nBA_x * nBC_x + nBA_y * nBC_y
                
                # ПРАВИЛО 1: УГЛОВОЙ ФИЛЬТР
                # Если угол больше ~162 градусов (почти прямая или дуга), пропускаем!
                # Это уберет сотни ложных подрезок на плавных кривых.
                if dot < -0.95: 
                    continue
                
                b_x, b_y = nBA_x + nBC_x, nBA_y + nBC_y
                L_b = math.hypot(b_x, b_y)
                
                if L_b < 1e-6: continue 
                    
                b_unit_x, b_unit_y = b_x / L_b, b_y / L_b
                
                eps = 1e-4
                test_pt = Point(B[0] + b_unit_x * eps, B[1] + b_unit_y * eps)
                
                # ПРАВИЛО 2: ТОПОЛОГИЧЕСКИЙ ТЕСТ
                # Если биссектриса указывает внутрь заготовки -> это внешний угол (подрезка не нужна)
                if ideal_geom.contains(test_pt):
                    continue
                    
                sin_half = math.sqrt(max(0.0, (1.0 - dot) / 2.0))
                if sin_half < 1e-4: continue
                
                D = tool_radius / sin_half
                
                px = B[0] + b_unit_x * D
                py = B[1] + b_unit_y * D
                
                cp = CamPath(is_closed=False, layer_name="SHARPEN")
                cp.add_point(round(px, 4), round(py, 4), -tool_depth) 
                cp.add_point(round(B[0], 4), round(B[1], 4), 0.0)     
                moves.append(cp)

        if isinstance(ideal_geom, Polygon):
            process_ring(ideal_geom.exterior)
            for interior in ideal_geom.interiors:
                process_ring(interior)
        elif isinstance(ideal_geom, MultiPolygon):
            for poly in ideal_geom.geoms:
                process_ring(poly.exterior)
                for interior in poly.interiors:
                    process_ring(interior)
                    
        return moves

    def process_mask_geometry(self, mask_geom, mask_offset: float, tool_radius: float, tool_depth: float, enable_sharpening: bool) -> tuple[list[CamPath], list[CamPath]]:
        ideal_offset = -(mask_offset - 0.001)
        
        # Увеличен mitre_limit до 50.0 (сохраняем острые углы) + очистка мусорных узлов
        ideal_geom = mask_geom.buffer(ideal_offset, join_style=2, mitre_limit=50.0).simplify(0.001, preserve_topology=True)

        ideal_paths = []
        def extract_ideal(geom):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                cp = CamPath(is_closed=True, layer_name="IDEAL_BLADE")
                for x, y in geom.exterior.coords: cp.add_point(round(x, 4), round(y, 4), 0.0)
                ideal_paths.append(cp)
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name="IDEAL_HOLE")
                    for x, y in interior.coords: cp_hole.add_point(round(x, 4), round(y, 4), 0.0)
                    ideal_paths.append(cp_hole)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: extract_ideal(g)
        extract_ideal(ideal_geom)

        # Увеличен mitre_limit до 50.0 + очистка
        cnc_geom = ideal_geom.buffer(tool_radius, join_style=2, mitre_limit=50.0).simplify(0.001, preserve_topology=True)

        cnc_holes = []
        cnc_exteriors = []
        
        def extract_cnc(geom):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name="CNC_HOLE")
                    for x, y in interior.coords: cp_hole.add_point(round(x, 4), round(y, 4), -tool_depth)
                    cnc_holes.append(cp_hole)
                cp_ext = CamPath(is_closed=True, layer_name="CNC_EXTERIOR")
                for x, y in geom.exterior.coords: cp_ext.add_point(round(x, 4), round(y, 4), -tool_depth)
                cnc_exteriors.append(cp_ext)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: extract_cnc(g)
        extract_cnc(cnc_geom)

        cnc_paths = cnc_holes + cnc_exteriors

        if enable_sharpening:
            sharpen_moves = self._get_true_sharpening(ideal_geom, tool_radius, tool_depth)
            cnc_paths.extend(sharpen_moves)

        return ideal_paths, cnc_paths