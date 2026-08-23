import os
import sys
import tempfile
import subprocess
import shutil
import datetime
from pathlib import Path
from src.parser.geometry import CamPath

class ReportGenerator:
    @staticmethod
    def generate(project_name: str, stats: dict, paths: list[CamPath], output_path: str | Path):
        print("[ОТЧЕТ] Генерация Технологической Карты (PDF)...")
        
        # Габариты А4 в мм
        a4_w, a4_h = 210.0, 297.0
        margin = 15.0
        
        svg = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg width="{a4_w}mm" height="{a4_h}mm" viewBox="0 0 {a4_w} {a4_h}" xmlns="http://www.w3.org/2000/svg">'
        ]
        
        # Белый фон
        svg.append(f'<rect width="{a4_w}" height="{a4_h}" fill="white" />')
        
        # Заголовок
        date_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        svg.append(f'<text x="{a4_w/2}" y="{margin + 10}" font-family="Arial" font-size="8" font-weight="bold" text-anchor="middle" fill="#000080">ТЕХНОЛОГИЧЕСКАЯ КАРТА ПРОЕКТА</text>')
        svg.append(f'<line x1="{margin}" y1="{margin + 15}" x2="{a4_w - margin}" y2="{margin + 15}" stroke="#000080" stroke-width="0.5" />')
        
        # Блок 1: Общая информация
        y_pos = margin + 25
        line_h = 6
        
        def add_text(x, y, text, bold=False, color="black", size=4):
            fw = "bold" if bold else "normal"
            safe_text = str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            svg.append(f'<text x="{x}" y="{y}" font-family="Arial" font-size="{size}" font-weight="{fw}" fill="{color}">{safe_text}</text>')

        add_text(margin, y_pos, "1. ОБЩАЯ ИНФОРМАЦИЯ", bold=True, color="#333333", size=5); y_pos += line_h
        add_text(margin + 5, y_pos, f"Имя проекта: {project_name}"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Дата генерации: {date_str}"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Файл УП (G-code): 04_УП_Фрезер.nc (или аналогичный)"); y_pos += line_h + 5
        
        # Блок 2: Дисторсия и Печать
        add_text(margin, y_pos, "2. ПАРАМЕТРЫ ДИСТОРСИИ (СЖАТИЯ)", bold=True, color="#333333", size=5); y_pos += line_h
        dist_status = f"Применена (Ось: {stats['dist_axis']})" if stats['is_distorted'] else "НЕ ПРИМЕНЯЛАСЬ"
        dist_color = "#008800" if stats['is_distorted'] else "#FF0000"
        
        add_text(margin + 5, y_pos, f"Статус сжатия: "); 
        add_text(margin + 35, y_pos, dist_status, bold=True, color=dist_color); y_pos += line_h
        add_text(margin + 5, y_pos, f"Коэффициент (K): {stats['k_dist']}%"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Рапорт шестерни: {stats['rapport']} мм (Z={stats['z']}, CP={stats['cp']})"); y_pos += line_h + 5
        
        # Блок 3: Инструмент и Режимы
        add_text(margin, y_pos, "3. ИНСТРУМЕНТ И РЕЖИМЫ РЕЗАНИЯ", bold=True, color="#333333", size=5); y_pos += line_h
        add_text(margin + 5, y_pos, f"Фреза: {stats['tool_name']}", bold=True); y_pos += line_h
        add_text(margin + 5, y_pos, f"Геометрия фрезы: Угол {stats['tool_angle']}°, Пятно {stats['tool_tip']} мм, Глубина {stats['tool_depth']} мм"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Обороты шпинделя (S): {stats['tool_rpm']} об/мин"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Рабочая подача (F): {stats['tool_feed']} мм/мин"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Направление реза: {stats['milling_dir']}"); y_pos += line_h
        add_text(margin + 5, y_pos, f"Офсет (подтравливание): {stats['offset']} мм"); y_pos += line_h
        
        time_min = stats['time_min']
        hours = int(time_min // 60)
        minutes = int(time_min % 60)
        time_str = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин {int((time_min*60)%60)} сек"
        
        add_text(margin + 5, y_pos, f"Расчетное машинное время: ");
        add_text(margin + 60, y_pos, time_str, bold=True, color="#FF4500"); y_pos += line_h + 5
        
        # Блок 4: Визуализация
        add_text(margin, y_pos, "4. ЭСКИЗ МАКЕТА (ПРЕДПРОСМОТР)", bold=True, color="#333333", size=5); y_pos += line_h
        
        box_x = margin
        box_y = y_pos
        box_w = a4_w - 2 * margin
        box_h = a4_h - box_y - margin
        
        svg.append(f'<rect x="{box_x}" y="{box_y}" width="{box_w}" height="{box_h}" fill="#F9F9F9" stroke="#CCCCCC" stroke-width="0.5" />')
        
        # Отрисовка векторов
        if paths:
            all_x = [pt[0] for p in paths for pt in p.points]
            all_y = [pt[1] for p in paths for pt in p.points]
            if all_x and all_y:
                min_x, max_x = min(all_x), max(all_x)
                min_y, max_y = min(all_y), max(all_y)
                
                geom_w = max(max_x - min_x, 1.0)
                geom_h = max(max_y - min_y, 1.0)
                
                pad = 10.0
                scale = min((box_w - 2*pad) / geom_w, (box_h - 2*pad) / geom_h)
                
                offset_x = box_x + pad + (box_w - 2*pad - geom_w * scale) / 2.0
                offset_y = box_y + pad + (box_h - 2*pad - geom_h * scale) / 2.0
                
                for p in paths:
                    if len(p.points) < 2: continue
                    d = []
                    for i, pt in enumerate(p.points):
                        cmd = "M" if i == 0 else "L"
                        # Перевод из декартовой СК (Y вверх) в экранную (Y вниз)
                        sx = offset_x + (pt[0] - min_x) * scale
                        sy = offset_y + (max_y - pt[1]) * scale
                        d.append(f"{cmd} {sx:.3f} {sy:.3f}")
                    if p.is_closed: d.append("Z")
                    
                    color = "#000000" if p.layer_name != "CROP_MARKS" else "#FF0000"
                    stroke_w = 0.5 if p.layer_name != "CROP_MARKS" else 0.3
                    svg.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="{stroke_w}" />')
                    
                # Добавим габариты
                add_text(box_x + 2, box_y + box_h - 2, f"Габариты (X x Y): {geom_w:.2f} x {geom_h:.2f} мм", size=3, color="#555555")

        svg.append('</svg>')
        
        # Сохранение и конвертация
        temp_dir = Path(tempfile.gettempdir())
        safe_svg = temp_dir / f"cam_report_{os.getpid()}.svg"
        
        with open(safe_svg, "w", encoding="utf-8") as f:
            f.write("\n".join(svg))
            
        project_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(os.getcwd())
        inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe' if os.name == 'nt' else Path('inkscape')
        
        cflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run([str(inkscape_exe), str(safe_svg), '--export-text-to-path', f'--export-filename={output_path}'], check=True, capture_output=True, creationflags=cflags)
        
        if safe_svg.exists():
            try: safe_svg.unlink()
            except: pass