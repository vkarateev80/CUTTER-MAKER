import math
from shapely.geometry import Point, Polygon
from src.parser.geometry import CamPath
from src.compiler.tool import VBitTool

class VCarveCalculator:
    """
    Калькулятор динамической глубины (Z) для стратегии V-Carve.
    Вычисляет глубину погружения конической фрезы на основе ширины колодца.
    """
    def __init__(self, tool: VBitTool):
        self.tool = tool
        # Тангенс половины угла заточки (в радианах)
        self.tan_half_angle = math.tan(math.radians(tool.angle_deg / 2.0))
        # Радиус плоского кончика (пятна) фрезы
        self.tip_radius = tool.tip_diameter / 2.0

    def calculate_3d_paths(self, skeleton_paths: list[CamPath], boundary_poly: Polygon) -> list[CamPath]:
        """
        Принимает линии скелета и полигон колодца (идеального лезвия).
        Возвращает те же линии, но с добавленной координатой Z для каждой точки.
        """
        vcarve_paths = []
        
        # Граница полигона (shapely автоматически включает сюда и внешний контур, и все отверстия)
        # Это именно те лезвия, которых должна коснуться фреза!
        boundary_lines = boundary_poly.boundary
        
        for path in skeleton_paths:
            # Создаем новый 3D-путь
            cp = CamPath(is_closed=False, layer_name="VCARVE")
            
            for pt in path.points:
                x, y = pt[0], pt[1]
                point_geom = Point(x, y)
                
                # Находим кратчайшее расстояние (R) от точки скелета до лезвия штампа
                R = boundary_lines.distance(point_geom)
                
                # Расчет глубины Z
                if R <= self.tip_radius:
                    # Если расстояние меньше радиуса кончика фрезы, фреза даже не влезет.
                    z = 0.0
                else:
                    # Вычисляем нужную глубину по тригонометрической формуле
                    z = -((R - self.tip_radius) / self.tan_half_angle)
                
                # ЗАЩИТА СТАНКА: Ограничиваем глубину максимальной рабочей глубиной (Z)
                # (z и tool.depth — отрицательные числа, поэтому используем max)
                z = max(z, -self.tool.depth)
                
                # Добавляем X, Y и вычисленный Z
                cp.add_point(round(x, 4), round(y, 4), round(z, 4))
                
            vcarve_paths.append(cp)
            
        return vcarve_paths