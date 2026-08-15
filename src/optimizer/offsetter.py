from shapely.geometry import Polygon
from src.parser.geometry import CamPath

class Offsetter:
    """
    Модуль построения эквидистанты (Offset).
    Компенсирует химическое подтравливание для гибких штампов 
    или радиус фрезы для механической обработки.
    """
    def __init__(self, offset_value: float = 0.0):
        self.offset_value = offset_value

    def apply_offset(self, paths: list[CamPath]) -> list[CamPath]:
        if self.offset_value == 0.0:
            return paths

        result_paths = []
        for path in paths:
            # Разомкнутые линии (хвосты) пока оставляем без изменений
            if len(path.points) < 3 or not path.is_closed:
                result_paths.append(path)
                continue

            try:
                poly = Polygon(path.points)
            except Exception:
                result_paths.append(path)
                continue
            
            # --- ИНЖЕНЕРНАЯ ЛОГИКА ---
            # Если это внешняя граница, положительный офсет УВЕЛИЧИВАЕТ деталь.
            # Если это внутренняя дырка, положительный офсет (нарост металла) СУЖАЕТ дырку.
            actual_offset = self.offset_value
            if path.layer_name == "HEALED_HOLE":
                actual_offset = -self.offset_value
                
            # join_style=2 (Mitre) сохраняет острые режущие кромки штампа!
            offset_poly = poly.buffer(actual_offset, join_style=2)
            
            def extract(geom, original_layer):
                if geom.is_empty: return
                if geom.geom_type == 'Polygon':
                    cp = CamPath(is_closed=True, layer_name=original_layer)
                    for x, y in geom.exterior.coords:
                        cp.add_point(round(x, 4), round(y, 4))
                    result_paths.append(cp)
                elif geom.geom_type == 'MultiPolygon':
                    for g in geom.geoms:
                        extract(g, original_layer)

            extract(offset_poly, path.layer_name)
            
        return result_paths