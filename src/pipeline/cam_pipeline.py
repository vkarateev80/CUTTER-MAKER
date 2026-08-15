from pathlib import Path
from shapely.geometry import LineString, Polygon, MultiPolygon, MultiLineString
import math
import ezdxf 
import subprocess 
import os
import sys
import tempfile
import shutil

from src.parser.dxf_parser import DxfParser
from src.parser.svg_parser import SvgParser
from src.parser.pdf_parser import PdfParser
from src.parser.eps_parser import EpsParser
from src.parser.inkscape_parser import InkscapeParser
from src.parser.ai_parser import AiParser

from src.healer.morphology import MorphologicalHealer
from src.optimizer.topology import TopologicalOptimizer
from src.compiler.gcode_compiler import GCodeCompiler
from src.parser.geometry import CamPath

class CamPipeline:
    def __init__(self, tolerance: float = 0.01, feedrate: int = 1500, min_loop_area: float = 0.0):
        self.tolerance = tolerance
        self.feedrate = feedrate
        self.min_loop_area = min_loop_area
        self.healer = MorphologicalHealer(tolerance=tolerance, min_loop_area=min_loop_area)
        self.optimizer = TopologicalOptimizer(simplify_tolerance=0.001)
        self.compiler = GCodeCompiler(feedrate=feedrate)

    def step1_parse(self, input_path: str | Path) -> list[CamPath]:
        input_file = Path(input_path)
        extension = input_file.suffix.lower()
        print(f"[ШАГ 1] Чтение файла: {input_file.name}")
        if extension == '.dxf': parser = DxfParser(input_file)
        elif extension == '.svg': parser = SvgParser(input_file)
        elif extension == '.pdf': parser = PdfParser(input_file)
        elif extension == '.eps': parser = EpsParser(input_file)
        elif extension == '.cdr': parser = InkscapeParser(input_file)
        elif extension == '.ai': parser = AiParser(input_file)
        else: raise ValueError(f"Формат {extension} не поддерживается!")
        return parser.parse()

    def step2_check_errors(self, paths: list[CamPath]) -> dict:
        print("[ШАГ 2] Проверка геометрии на ошибки...")
        stats = {
            "total_paths": len(paths), "open_paths": 0, "empty_paths": 0,
            "intersections": 0, "duplicates": 0, "dust": 0, "total_points": 0,
            "error_nodes": [], "intersection_nodes": [], "duplicate_nodes": [], "dust_nodes": []
        }
        
        def extract_coords(geom):
            if geom.is_empty: return []
            if getattr(geom, 'geoms', None): 
                pts = []
                for g in geom.geoms: pts.extend(extract_coords(g))
                return pts
            elif getattr(geom, 'coords', None): return list(geom.coords)
            return []

        shapely_lines = []
        for path in paths:
            stats["total_points"] += len(path.points)
            if len(path.points) < 2:
                stats["empty_paths"] += 1
                continue
                
            line = LineString(path.points)
            is_dust = False
            
            if self.min_loop_area > 0:
                if path.is_closed or line.is_closed:
                    try:
                        if Polygon(line.coords).area < self.min_loop_area: is_dust = True
                    except: is_dust = True
                else:
                    if line.length < self.min_loop_area: is_dust = True
                        
            if is_dust:
                stats["dust"] += 1
                stats["dust_nodes"].extend(extract_coords(line))
                continue
                
            if not path.is_closed:
                stats["open_paths"] += 1
                stats["error_nodes"].append(path.points[0])
                stats["error_nodes"].append(path.points[-1])
                
            shapely_lines.append(line)

        for line in shapely_lines:
            if not line.is_simple:
                coords = list(line.coords)
                is_closed = math.dist(coords[0], coords[-1]) < 1e-4
                segments = [LineString([coords[k], coords[k+1]]) for k in range(len(coords)-1)]
                for k in range(len(segments)):
                    for m in range(k + 2, len(segments)): 
                        if is_closed and k == 0 and m == len(segments) - 1: continue
                        if segments[k].intersects(segments[m]):
                            inter = segments[k].intersection(segments[m])
                            if inter.length > 0.01:
                                stats["duplicates"] += 1
                                stats["duplicate_nodes"].extend(extract_coords(inter))
                            else:
                                stats["intersections"] += 1
                                stats["intersection_nodes"].extend(extract_coords(inter))

        for i in range(len(shapely_lines)):
            for j in range(i + 1, len(shapely_lines)):
                if shapely_lines[i].intersects(shapely_lines[j]):
                    inter = shapely_lines[i].intersection(shapely_lines[j])
                    if inter.length > 0.01:
                        stats["duplicates"] += 1
                        stats["duplicate_nodes"].extend(extract_coords(inter))
                    else:
                        stats["intersections"] += 1
                        stats["intersection_nodes"].extend(extract_coords(inter))
                
        return stats

    def step3_heal_and_optimize(self, paths: list[CamPath]) -> list[CamPath]:
        print(f"[ШАГ 3] Запуск морфологии (допуск {self.tolerance} мм)...")
        healed_paths = self.healer.heal(paths)
        optimized_paths = self.optimizer.optimize(healed_paths)
        return optimized_paths

    def save_source_dxf(self, paths: list[CamPath], output_path: str | Path):
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        for p in paths:
            if len(p.points) > 1:
                msp.add_lwpolyline(p.points, close=p.is_closed)
        doc.saveas(output_path)
        print(f" -> Исходник сохранен: {Path(output_path).name}")

    def generate_uv_mask_pdf(self, paths: list[CamPath], offset_val: float, output_path: str | Path) -> list[CamPath]:
        lines = [LineString(p.points) for p in paths if len(p.points) > 1]
        if not lines: return []

        multi_line = MultiLineString(lines)
        mask_geom = multi_line.buffer(offset_val, cap_style=1, join_style=1)
        
        if mask_geom.is_empty:
            raise ValueError("Геометрия пуста. Проверьте значение офсета.")

        # --- 1. ИЗВЛЕКАЕМ КООРДИНАТЫ МАСКИ ДЛЯ GUI ---
        mask_visual_paths = []
        def extract_mask_paths(geom):
            if isinstance(geom, Polygon):
                cp = CamPath(is_closed=True, layer_name="MASK_EXTERIOR")
                for x, y in geom.exterior.coords:
                    cp.add_point(round(x, 4), round(y, 4))
                mask_visual_paths.append(cp)
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name="MASK_HOLE")
                    for x, y in interior.coords:
                        cp_hole.add_point(round(x, 4), round(y, 4))
                    mask_visual_paths.append(cp_hole)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms:
                    extract_mask_paths(g)
                    
        extract_mask_paths(mask_geom)

        # --- 2. ГЕНЕРАЦИЯ PDF ЧЕРЕЗ INKSCAPE (С ЗАЩИТОЙ ОТ КИРИЛЛИЦЫ) ---
        min_x, min_y, max_x, max_y = mask_geom.bounds
        margin = 10 
        width = (max_x - min_x) + 2 * margin
        height = (max_y - min_y) + 2 * margin
        
        svg_content = [
            f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        ]
        
        def geom_to_svg_path(geom):
            if isinstance(geom, Polygon):
                d = []
                for i, (x, y) in enumerate(geom.exterior.coords):
                    px = x - min_x + margin
                    py = height - (y - min_y + margin) 
                    cmd = "M" if i == 0 else "L"
                    d.append(f"{cmd} {px:.4f} {py:.4f}")
                d.append("Z")
                
                for interior in geom.interiors:
                    for i, (x, y) in enumerate(interior.coords):
                        px = x - min_x + margin
                        py = height - (y - min_y + margin)
                        cmd = "M" if i == 0 else "L"
                        d.append(f"{cmd} {px:.4f} {py:.4f}")
                    d.append("Z")
                    
                path_str = " ".join(d)
                svg_content.append(f'<path d="{path_str}" fill="black" fill-rule="evenodd" stroke="none" />')
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms:
                    geom_to_svg_path(g)
                    
        geom_to_svg_path(mask_geom)
        svg_content.append('</svg>')
        
        # СОЗДАЕМ БЕЗОПАСНЫЕ ПУТИ ВО ВРЕМЕННОЙ ПАПКЕ WINDOWS (без русских букв)
        temp_dir = Path(tempfile.gettempdir())
        safe_svg = temp_dir / f"cam_mask_in_{os.getpid()}.svg"
        safe_pdf = temp_dir / f"cam_mask_out_{os.getpid()}.pdf"
        
        with open(safe_svg, "w", encoding="utf-8") as f:
            f.write("\n".join(svg_content))
            
        if getattr(sys, 'frozen', False):
            project_root = Path(sys.executable).parent
        else:
            project_root = Path(os.getcwd())
            
        if os.name == 'nt':
            inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe'
        else:
            inkscape_exe = Path('inkscape')
            
        if not inkscape_exe.exists():
            raise RuntimeError("Для создания PDF-маски нужен Inkscape! Убедитесь, что папка inkscape_engine на месте.")
            
        cmd = [
            str(inkscape_exe),
            str(safe_svg),
            f'--export-filename={safe_pdf}'
        ]
        
        cflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(cmd, check=True, capture_output=True, text=True, creationflags=cflags)
        
        # ПЕРЕНОСИМ ГОТОВЫЙ PDF ИЗ БЕЗОПАСНОЙ ПАПКИ В РУССКУЮ ПАПКУ ПРОЕКТА
        if safe_pdf.exists():
            shutil.move(str(safe_pdf), str(output_path))
        else:
            raise RuntimeError("Inkscape не смог сгенерировать PDF-маску. Возможно, сбой движка.")
            
        if safe_svg.exists():
            try: safe_svg.unlink()
            except: pass
            
        print(f" -> УФ Маска сохранена: {Path(output_path).name}")
        
        return mask_visual_paths

    def generate_gcode(self, paths: list[CamPath], output_path: str | Path) -> None:
        gcode = self.compiler.compile(paths)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(gcode)
        print(f" -> G-код сохранен: {Path(output_path).name}")