import math

class VBitTool:
    """
    Математическая модель V-образной гравировальной фрезы.
    Вычисляет эффективный радиус смещения (эквидистанту) на основе геометрии инструмента.
    """
    def __init__(self, angle_deg: float = 60.0, tip_diameter: float = 0.1, depth: float = 0.5, shank_diameter: float = 3.175):
        self.angle_deg = angle_deg
        self.tip_diameter = tip_diameter
        self.depth = abs(depth)
        self.shank_diameter = shank_diameter

    @property
    def offset_radius(self) -> float:
        """
        Возвращает точное значение отступа (R_eff) от вектора детали до центра фрезы,
        чтобы верхний край реза идеально совпал с линией макета.
        """
        # Переводим половину угла заточки в радианы
        angle_rad = math.radians(self.angle_deg / 2.0)
        
        # R_eff = (d / 2) + Z * tan(alpha / 2)
        r_eff = (self.tip_diameter / 2.0) + (self.depth * math.tan(angle_rad))
        
        # Физическое ограничение: смещение не может быть больше радиуса самой фрезы!
        max_r = self.shank_diameter / 2.0
        return min(r_eff, max_r)