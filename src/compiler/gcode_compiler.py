from src.parser.geometry import CamPath

class GCodeCompiler:
    """
    Транслятор геометрических путей (CamPath) в машинный G-код.
    Формирует заголовок программы, команды перемещения (G0, G1) и управление инструментом (M3, M5).
    """
    def __init__(self, feedrate: int = 1500, safe_z: float = 5.0):
        """
        :param feedrate: Скорость рабочего хода (резки) в мм/мин (команда F).
        :param safe_z: Безопасная высота поднятия инструмента при холостых переездах.
        """
        self.feedrate = feedrate
        self.safe_z = safe_z

    def compile(self, paths: list[CamPath]) -> str:
        """
        Основной метод. Превращает список контуров в единый текстовый блок G-кода.
        """
        gcode = []
        
        # --- ШАПКА ПРОГРАММЫ (Preamble) ---
        gcode.append("; --- НАЧАЛО ПРОГРАММЫ ---")
        gcode.append("G21 ; Установка метрической системы (мм)")
        gcode.append("G90 ; Абсолютное позиционирование координат")
        gcode.append(f"G0 Z{self.safe_z:.3f} ; Подъем инструмента на безопасную высоту")
        
        # --- ОБРАБОТКА КОНТУРОВ ---
        for i, path in enumerate(paths):
            if not path.points:
                continue
                
            gcode.append(f"\n; --- Контур {i+1} (Слой: {path.layer_name}) ---")
            
            # 1. Переезд к начальной точке (холостой ход)
            start_pt = path.points[0]
            gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f} ; Быстрый переезд к началу реза")
            
            # 2. Включение инструмента и опускание
            gcode.append("M3 S1000 ; Включение инструмента (лазер/шпиндель на 100% мощности)")
            gcode.append("G1 Z0.000 F300 ; Опускание инструмента в рабочую зону")
            
            # 3. Рабочий ход (резка) по всем остальным точкам
            for pt in path.points[1:]:
                gcode.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{self.feedrate} ; Рез")
            
            # 4. Проверка замыкания контура
            # Если контур замкнут, но последняя точка физически не совпадает с первой - принудительно замыкаем
            if path.is_closed:
                last_pt = path.points[-1]
                if last_pt != start_pt:
                    gcode.append(f"G1 X{start_pt[0]:.3f} Y{start_pt[1]:.3f} F{self.feedrate} ; Замыкание контура")
                    
            # 5. Выключение инструмента и подъем
            gcode.append(f"G0 Z{self.safe_z:.3f} ; Подъем инструмента")
            gcode.append("M5 ; Выключение инструмента")
            
        # --- ПОДВАЛ ПРОГРАММЫ (Postamble) ---
        gcode.append("\n; --- КОНЕЦ ПРОГРАММЫ ---")
        gcode.append("G0 X0.000 Y0.000 ; Возврат станка в домашнюю точку (нуль)")
        gcode.append("M30 ; Конец программы и остановка")
        
        # Объединяем все строки через перенос строки
        return "\n".join(gcode)