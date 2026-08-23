import numpy as np
import math
from src.parser.geometry import CamPath

class AlignmentTransform:
    def __init__(self):
        # По умолчанию единичная матрица (без изменений)
        self.matrix = np.eye(3) 

    def compute_from_points(self, ideal_pts: list[tuple[float, float]], actual_pts: list[tuple[float, float]]) -> dict:
        """
        Вычисляет матрицу аффинного преобразования от идеальных координат к фактическим.
        Возвращает словарь с рассчитанными параметрами для вывода в UI оператору.
        """
        if len(ideal_pts) != len(actual_pts):
            raise ValueError("Количество идеальных и фактических точек должно совпадать.")
        
        n = len(ideal_pts)
        if n < 2:
            raise ValueError("Для калибровки нужно минимум 2 точки.")

        if n == 2:
            # РЕЖИМ 1: Подобие (Смещение, Поворот, Равномерный Масштаб)
            x1, y1 = ideal_pts[0]
            x2, y2 = ideal_pts[1]
            x1p, y1p = actual_pts[0]
            x2p, y2p = actual_pts[1]

            dx = x2 - x1
            dy = y2 - y1
            dxp = x2p - x1p
            dyp = y2p - y1p

            L_ideal = math.hypot(dx, dy)
            L_actual = math.hypot(dxp, dyp)

            if L_ideal < 1e-6:
                raise ValueError("Идеальные точки расположены слишком близко друг к другу.")

            scale = L_actual / L_ideal
            angle = math.atan2(dyp, dxp) - math.atan2(dy, dx)

            cos_a = math.cos(angle) * scale
            sin_a = math.sin(angle) * scale

            tx = x1p - (x1 * cos_a - y1 * sin_a)
            ty = y1p - (x1 * sin_a + y1 * cos_a)

            self.matrix = np.array([
                [cos_a, -sin_a, tx],
                [sin_a,  cos_a, ty],
                [0,      0,      1]
            ])
            
            return {
                "points": 2,
                "scale_x": round(scale, 5),
                "scale_y": round(scale, 5),
                "angle_deg": round(math.degrees(angle), 4),
                "offset_x": round(tx, 3),
                "offset_y": round(ty, 3)
            }
        else:
            # РЕЖИМ 2: Полное Аффинное преобразование (Метод наименьших квадратов)
            # Решаем систему уравнений: X * A = Y
            X = np.array([[x, y, 1] for x, y in ideal_pts])
            Y = np.array([[x, y] for x, y in actual_pts])
            
            # Находим матрицу A (размер 3x2)
            A, residuals, rank, s = np.linalg.lstsq(X, Y, rcond=None)
            
            # Превращаем ее в стандартную матрицу трансформации 3x3
            self.matrix = np.eye(3)
            self.matrix[0:2, 0:3] = A.T
            
            # Извлекаем примерные параметры для визуального отчета
            a, b, tx = self.matrix[0]
            c, d, ty = self.matrix[1]
            
            scale_x = math.hypot(a, c)
            scale_y = math.hypot(b, d)
            angle_rad = math.atan2(c, a)
            
            return {
                "points": n,
                "scale_x": round(scale_x, 5),
                "scale_y": round(scale_y, 5),
                "angle_deg": round(math.degrees(angle_rad), 4),
                "offset_x": round(tx, 3),
                "offset_y": round(ty, 3)
            }

    def apply(self, paths: list[CamPath]) -> list[CamPath]:
        """Применяет вычисленную матрицу ко всем координатам в переданных векторах."""
        if np.allclose(self.matrix, np.eye(3)):
            return paths # Матрица единичная, изменений нет

        transformed_paths = []
        a, b, tx = self.matrix[0]
        c, d, ty = self.matrix[1]

        for path in paths:
            new_path = CamPath(layer_name=path.layer_name, is_closed=path.is_closed)
            for pt in path.points:
                x, y = pt[0], pt[1]
                z = pt[2] if len(pt) > 2 else None
                
                # Умножение матрицы на вектор [x, y, 1]
                new_x = a * x + b * y + tx
                new_y = c * x + d * y + ty
                
                new_path.add_point(round(new_x, 4), round(new_y, 4), z)
                
            transformed_paths.append(new_path)
            
        return transformed_paths