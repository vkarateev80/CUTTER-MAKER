from shapely.geometry import LineString, LinearRing
from src.parser.geometry import CamPath

class TopologicalOptimizer:
    """
    Модуль топологической оптимизации.
    Удаляет дублирующиеся узлы и коллинеарные точки на прямых участках,
    чтобы предотвратить "заикание" (торможение) ЧПУ станка.
    """
    def __init__(self, simplify_tolerance: float = 0.001):
        """
        :param simplify_tolerance: Допуск аппроксимации (алгоритм Дугласа-Пекера).
                                   Точки, отклоняющиеся от идеальной прямой менее 
                                   чем на 0.001 мм, будут удалены.
        """
        self.tolerance = simplify_tolerance

    def optimize(self, paths: list[CamPath]) -> list[CamPath]:
        optimized_paths = []
        
        for path in paths:
            # Если в контуре меньше 2 точек, это мусор, просто пропускаем его
            if len(path.points) < 2:
                continue

            # Превращаем наши точки в объект Shapely
            # Если контур замкнут, используем LinearRing, иначе LineString
            if path.is_closed and len(path.points) >= 3:
                geom = LinearRing(path.points)
            else:
                geom = LineString(path.points)
                
            # ОПТИМИЗАЦИЯ: Алгоритм Дугласа-Пекера
            # preserve_topology=True гарантирует, что мы не сломаем замкнутые контуры
            simplified_geom = geom.simplify(self.tolerance, preserve_topology=True)
            
            # Создаем новый чистый объект CamPath
            opt_path = CamPath(layer_name=path.layer_name, is_closed=path.is_closed)
            
            # Извлекаем очищенные координаты
            coords = list(simplified_geom.coords)
            
            for x, y in coords:
                # Округляем до 4 знаков после запятой (0.0001 мм - предел точности ЧПУ)
                opt_path.add_point(round(x, 4), round(y, 4))
                
            optimized_paths.append(opt_path)
            
        return optimized_paths