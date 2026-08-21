import math
from src.parser.geometry import CamPath

class LayoutAnalyzer:
    """
    Анализатор геометрии для вычисления фактического рапорта макета 
    (сумма размеров элементов + зазоры на стык).
    """
    @staticmethod
    def analyze(paths: list[CamPath], axis: str = 'Y') -> dict:
        if not paths:
            return {"rows": 0, "avg_gap": 0.0, "layout_length": 0.0}

        intervals = []
        for p in paths:
            # Берем только замкнутые контуры (игнорируем линии и текст)
            if not p.is_closed or len(p.points) < 3:
                continue
            
            if axis.upper() == 'Y':
                coords = [pt[1] for pt in p.points]
            else:
                coords = [pt[0] for pt in p.points]
                
            c_min, c_max = min(coords), max(coords)
            size = c_max - c_min
            
            # Игнорируем пыль и артефакты (меньше 1 мм)
            if size < 1.0:
                continue
                
            intervals.append([c_min, c_max])
            
        if not intervals:
            return {"rows": 0, "avg_gap": 0.0, "layout_length": 0.0}
            
        # Фильтрация технологических рамок (контуры, занимающие > 90% всего макета)
        total_min = min(i[0] for i in intervals)
        total_max = max(i[1] for i in intervals)
        total_span = total_max - total_min
        
        if total_span > 0:
            filtered_intervals = [i for i in intervals if (i[1] - i[0]) < total_span * 0.9]
            # Если отфильтровалось всё (например, макет состоит из одной большой этикетки), возвращаем как было
            if filtered_intervals:
                intervals = filtered_intervals

        # Сортируем интервалы по начальной координате
        intervals.sort(key=lambda x: x[0])
        
        # Сливаем пересекающиеся интервалы (группируем в Ряды)
        merged = [intervals[0]]
        for current in intervals[1:]:
            prev = merged[-1]
            # Если пересекаются или касаются (с допуском 0.1 мм на погрешность чертежа)
            if current[0] <= prev[1] + 0.1:
                prev[1] = max(prev[1], current[1])
            else:
                merged.append(current)
                
        n = len(merged)
        if n == 0:
            return {"rows": 0, "avg_gap": 0.0, "layout_length": 0.0}
        elif n == 1:
            # Один ряд: зазор на стык неизвестен, берем чистый размер
            return {"rows": 1, "avg_gap": 0.0, "layout_length": round(merged[0][1] - merged[0][0], 4)}
            
        # Вычисляем зазоры между рядами
        gaps = [merged[i][0] - merged[i-1][1] for i in range(1, n)]
        avg_gap = sum(gaps) / len(gaps)
        
        # Итоговый рапорт: от начала первого до конца последнего + 1 средний зазор на стык
        layout_length = (merged[-1][1] - merged[0][0]) + avg_gap
        
        return {
            "rows": n,
            "avg_gap": round(avg_gap, 4),
            "layout_length": round(layout_length, 4)
        }

class DistortionCalculator:
    """
    Класс для расчета и применения коэффициента дисторсии (Distortion Factor).
    """
    
    @staticmethod
    def calculate_factor(
        z: int, 
        cp: float = 3.175, 
        h_undercut: float = 0.48, 
        t_p: float = 0.44, 
        t_b: float = 0.24, 
        k_factor: float = 0.5
    ) -> dict:
        
        # 1. Теоретический рапорт (Repeat Length)
        rapport = z * cp
        
        # 2. Делительный диаметр шестерни (Pitch Diameter)
        d_pitch = rapport / math.pi
        
        # 3. Диаметр тела магнитного цилиндра
        d_cyl = d_pitch - (2.0 * h_undercut)
        
        # 4. Радиус нейтрального слоя
        r_neutral = (d_cyl / 2.0) + (k_factor * t_b)
        
        # 5. Радиус режущей кромки (максимальное растяжение)
        r_cut = (d_cyl / 2.0) + t_p
        
        # 6. Коэффициент дисторсии
        k_dist = r_neutral / r_cut
        
        return {
            "rapport": round(rapport, 4),
            "d_pitch": round(d_pitch, 4),
            "d_cyl": round(d_cyl, 4),
            "r_neutral": round(r_neutral, 4),
            "r_cut": round(r_cut, 4),
            "k_dist": k_dist,
            "k_dist_percent": round(k_dist * 100, 4)
        }

    @staticmethod
    def apply_distortion(paths: list[CamPath], factor: float, axis: str = 'Y') -> list[CamPath]:
        if not paths:
            return []

        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        
        if not all_x or not all_y:
            return paths
            
        center_x = (min(all_x) + max(all_x)) / 2.0
        center_y = (min(all_y) + max(all_y)) / 2.0

        distorted_paths = []
        
        for original_path in paths:
            new_path = CamPath(layer_name=original_path.layer_name, is_closed=original_path.is_closed)
            
            for pt in original_path.points:
                x, y = pt[0], pt[1]
                z = pt[2] if len(pt) > 2 else None
                
                if axis.upper() == 'Y':
                    new_x = x
                    new_y = center_y + (y - center_y) * factor
                elif axis.upper() == 'X':
                    new_x = center_x + (x - center_x) * factor
                    new_y = y
                else:
                    new_x, new_y = x, y 
                
                new_path.add_point(round(new_x, 4), round(new_y, 4), z)
                
            distorted_paths.append(new_path)
            
        return distorted_paths