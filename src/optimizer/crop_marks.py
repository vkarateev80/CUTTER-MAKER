import math
from src.parser.geometry import CamPath

class CropMarksGenerator:
    """
    Генератор обрезных меток (Crop Marks) для вырубных штампов.
    Создает 4 L-образных уголка по габаритам (Рапорт х Ширина пластины).
    """
    @staticmethod
    def generate(paths: list[CamPath], rapport: float, width: float, axis: str = 'Y', mark_length: float = 10.0) -> list[CamPath]:
        if not paths:
            return []
        
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        
        if not all_x or not all_y:
            return []
            
        # Центр макета
        cx = (min(all_x) + max(all_x)) / 2.0
        cy = (min(all_y) + max(all_y)) / 2.0
        
        # Определяем габариты в зависимости от оси рапорта
        if axis.upper() == 'Y':
            dim_x = width
            dim_y = rapport
        else:
            dim_x = rapport
            dim_y = width
            
        half_x = dim_x / 2.0
        half_y = dim_y / 2.0
        
        marks = []
        layer = "CROP_MARKS"
        
        # Левый верхний угол (Top-Left)
        p_tl = CamPath(is_closed=False, layer_name=layer)
        p_tl.add_point(round(cx - half_x, 4), round(cy + half_y - mark_length, 4))
        p_tl.add_point(round(cx - half_x, 4), round(cy + half_y, 4))
        p_tl.add_point(round(cx - half_x + mark_length, 4), round(cy + half_y, 4))
        marks.append(p_tl)
        
        # Правый верхний угол (Top-Right)
        p_tr = CamPath(is_closed=False, layer_name=layer)
        p_tr.add_point(round(cx + half_x - mark_length, 4), round(cy + half_y, 4))
        p_tr.add_point(round(cx + half_x, 4), round(cy + half_y, 4))
        p_tr.add_point(round(cx + half_x, 4), round(cy + half_y - mark_length, 4))
        marks.append(p_tr)
        
        # Левый нижний угол (Bottom-Left)
        p_bl = CamPath(is_closed=False, layer_name=layer)
        p_bl.add_point(round(cx - half_x, 4), round(cy - half_y + mark_length, 4))
        p_bl.add_point(round(cx - half_x, 4), round(cy - half_y, 4))
        p_bl.add_point(round(cx - half_x + mark_length, 4), round(cy - half_y, 4))
        marks.append(p_bl)
        
        # Правый нижний угол (Bottom-Right)
        p_br = CamPath(is_closed=False, layer_name=layer)
        p_br.add_point(round(cx + half_x - mark_length, 4), round(cy - half_y, 4))
        p_br.add_point(round(cx + half_x, 4), round(cy - half_y, 4))
        p_br.add_point(round(cx + half_x, 4), round(cy - half_y + mark_length, 4))
        marks.append(p_br)
        
        return marks