from shapely.geometry import Polygon, MultiPolygon
import math
from src.parser.geometry import CamPath

class NestingNode:
    """Узел топологического дерева вложенности (Колодец)."""
    def __init__(self, path: CamPath, poly: Polygon):
        self.path = path
        self.poly = poly
        self.children = []
        self.is_root = True
        self.level = 0

class NestingOptimizer:
    """
    Оптимизатор ЧПУ-стратегии "По колодцам" с учетом эквидистант.
    Строит деревья вложенности и генерирует траектории со смещением инструмента.
    """
    def process_wells(self, paths: list[CamPath], offset_radius: float, tool_depth: float, enable_sharpening: bool = True) -> list[CamPath]:
        open_paths = []
        nodes = []
        
        # 1. Разделяем пути на замкнутые (полигоны) и разомкнутые (пропилы)
        for p in paths:
            if p.is_closed and len(p.points) >= 3:
                # Игнорируем Z при создании 2D полигона
                pts_2d = [(pt[0], pt[1]) for pt in p.points]
                poly = Polygon(pts_2d)
                if poly.is_valid and poly.area > 0:
                    nodes.append(NestingNode(p, poly))
                else:
                    open_paths.append(p)
            else:
                open_paths.append(p)

        # 2. Строим дерево вложенности "Колодцы"
        for i in range(len(nodes)):
            parent = None
            min_area = float('inf')
            
            for j in range(len(nodes)):
                if i == j: continue
                if nodes[j].poly.contains(nodes[i].poly):
                    if nodes[j].poly.area < min_area:
                        min_area = nodes[j].poly.area
                        parent = nodes[j]
                        
            if parent:
                parent.children.append(nodes[i])
                nodes[i].is_root = False

        def set_levels(node: NestingNode, level: int):
            node.level = level
            for child in node.children:
                set_levels(child, level + 1)

        roots = [n for n in nodes if n.is_root]
        for r in roots:
            set_levels(r, 0)

        final_toolpaths = []
        final_toolpaths.extend(open_paths)
        
        # --- ФУНКЦИЯ 3D ПОДРЕЗКИ УГЛОВ ---
        def get_sharpening_moves(poly: Polygon, is_outer: bool) -> list[CamPath]:
            moves = []
            coords = list(poly.exterior.coords)
            if len(coords) < 4: return moves
            if math.dist(coords[0], coords[-1]) < 1e-6: coords = coords[:-1]
            
            is_ccw = poly.exterior.is_ccw
            n = len(coords)
            
            for i in range(n):
                A, B, C = coords[i - 1], coords[i], coords[(i + 1) % n]
                
                # Векторное произведение для определения направления поворота
                cross = (B[0] - A[0]) * (C[1] - B[1]) - (B[1] - A[1]) * (C[0] - B[0])
                
                # Математически точное определение острого угла, уходящего в материал
                is_concave = False
                if is_outer:
                    if is_ccw and cross < -1e-4: is_concave = True
                    elif not is_ccw and cross > 1e-4: is_concave = True
                else:
                    if is_ccw and cross > 1e-4: is_concave = True
                    elif not is_ccw and cross < -1e-4: is_concave = True
                    
                if is_concave:
                    v1x, v1y = A[0] - B[0], A[1] - B[1]
                    v2x, v2y = C[0] - B[0], C[1] - B[1]
                    len_v1, len_v2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
                    if len_v1 < 1e-6 or len_v2 < 1e-6: continue
                    v1x, v1y = v1x / len_v1, v1y / len_v1
                    v2x, v2y = v2x / len_v2, v2y / len_v2
                    
                    # Биссектриса
                    bx, by = v1x + v2x, v1y + v2y
                    len_b = math.hypot(bx, by)
                    if len_b < 1e-6: continue
                    bx, by = bx / len_b, by / len_b
                    
                    dot = max(-1.0, min(1.0, v1x * v2x + v1y * v2y))
                    sin_half = math.sqrt((1.0 - dot) / 2.0)
                    if sin_half < 1e-4: continue
                    
                    D = offset_radius / sin_half
                    
                    # ИСПРАВЛЕНИЕ: Знак направления выезда фрезы
                    # Для отверстий фреза должна оставаться внутри отверстия!
                    sign = -1.0 if is_outer else 1.0
                    px, py = B[0] + sign * bx * D, B[1] + sign * by * D
                    
                    # Формируем 3D движение
                    cp = CamPath(is_closed=False, layer_name="SHARPEN")
                    cp.add_point(round(px, 4), round(py, 4), -tool_depth) # Старт со дна
                    cp.add_point(round(B[0], 4), round(B[1], 4), 0.0)     # Выезд в самый угол наверх
                    cp.add_point(round(px, 4), round(py, 4), -tool_depth) # Возврат на дно
                    moves.append(cp)
            return moves

        def traverse_and_offset(node: NestingNode):
            # Сначала режем детей (внутренние отверстия)
            for child in node.children:
                traverse_and_offset(child)
            
            # Надежное определение внешнего контура по имени слоя от УФ-маски
            is_outer = (node.path.layer_name != "MASK_HOLE")
            
            offset_val = offset_radius if is_outer else -offset_radius
            
            # Применяем смещение. join_style=2 (Mitre) сохраняет острые углы штампа!
            offset_poly = node.poly.buffer(offset_val, join_style=2)
            
            if offset_poly.is_empty:
                return 
                
            def extract_paths(geom):
                if geom.geom_type == 'Polygon':
                    if geom.is_empty: return
                    cp = CamPath(is_closed=True, layer_name=node.path.layer_name)
                    for x, y in geom.exterior.coords:
                        cp.add_point(round(x, 4), round(y, 4))
                    final_toolpaths.append(cp)
                    for interior in geom.interiors:
                        cp_hole = CamPath(is_closed=True, layer_name="MASK_HOLE")
                        for x, y in interior.coords:
                            cp_hole.add_point(round(x, 4), round(y, 4))
                        final_toolpaths.append(cp_hole)
                elif geom.geom_type == 'MultiPolygon':
                    for g in geom.geoms:
                        extract_paths(g)
                        
            extract_paths(offset_poly)
            
            # Подрезка углов ТОЛЬКО для внутренних отверстий И если включена галочка!
            if not is_outer and enable_sharpening:
                final_toolpaths.extend(get_sharpening_moves(node.poly, is_outer))

        for r in roots:
            traverse_and_offset(r)

        return final_toolpaths