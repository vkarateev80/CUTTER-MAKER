from pathlib import Path
from shapely.geometry import LineString, Polygon, MultiPolygon, MultiLineString
from shapely.ops import unary_union
import math
import ezdxf 
import subprocess 
import os
import sys
import tempfile
import shutil
import datetime

from src.parser.dxf_parser import DxfParser
from src.parser.svg_parser import SvgParser
from src.parser.pdf_parser import PdfParser
from src.parser.eps_parser import EpsParser
from src.parser.inkscape_parser import InkscapeParser
from src.parser.ai_parser import AiParser

from src.healer.morphology import MorphologicalHealer
from src.optimizer.topology import TopologicalOptimizer
from src.optimizer.alignment_marks import AlignmentMarksGenerator
from src.optimizer.nesting import NestingOptimizer
from src.optimizer.distortion import DistortionCalculator
from src.optimizer.crop_marks import CropMarksGenerator
from src.compiler.gcode_compiler import GCodeCompiler
from src.compiler.tool import VBitTool
from src.parser.geometry import CamPath
from src.db.models import Tool, PostProcessor

class CamPipeline:
    def __init__(self, tolerance: float = 0.01, min_loop_area: float = 0.0):
        self.tolerance = tolerance
        self.min_loop_area = min_loop_area
        self.healer = MorphologicalHealer(tolerance=tolerance, min_loop_area=min_loop_area)
        self.optimizer = TopologicalOptimizer(simplify_tolerance=0.001)
        self.nesting = NestingOptimizer()

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
        stats = {"open_paths": 0, "empty_paths": 0, "intersections": 0, "duplicates": 0, "dust": 0, "error_nodes": [], "intersection_nodes": [], "duplicate_nodes": [], "dust_nodes": []}
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
            if path.layer_name == "CROP_MARKS": 
                continue # Игнорируем обрезные метки при поиске ошибок
                
            if len(path.points) < 2: continue
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
        print(f"[ШАГ 3] Запуск морфологии...")
        # Защита: отделяем обрезные метки, чтобы лекарь не слил их с макетом и не стер их слой
        regular_paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        crop_paths = [p for p in paths if p.layer_name == "CROP_MARKS"]
        
        healed = self.optimizer.optimize(self.healer.heal(regular_paths))
        return healed + crop_paths

    def apply_distortion(self, paths: list[CamPath], factor: float, axis: str = 'Y') -> list[CamPath]:
        print(f"[ДИСТОРСИЯ] Применение коэффициента {factor:.4f} по оси {axis}...")
        return DistortionCalculator.apply_distortion(paths, factor, axis)

    def rotate_geometry(self, paths: list[CamPath], angle_deg: float) -> list[CamPath]:
        print(f"[ТРАНСФОРМАЦИЯ] Поворот макета на {angle_deg}°...")
        if not paths: return []
        
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x or not all_y: return paths
        
        cx = (min(all_x) + max(all_x)) / 2.0
        cy = (min(all_y) + max(all_y)) / 2.0
        
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        
        rotated_paths = []
        for path in paths:
            new_path = CamPath(layer_name=path.layer_name, is_closed=path.is_closed)
            for pt in path.points:
                dx = pt[0] - cx
                dy = pt[1] - cy
                nx = cx + dx * cos_a - dy * sin_a
                ny = cy + dx * sin_a + dy * cos_a
                z = pt[2] if len(pt) > 2 else None
                new_path.add_point(round(nx, 4), round(ny, 4), z)
            rotated_paths.append(new_path)
            
        return rotated_paths

    def add_crop_marks(self, paths: list[CamPath], rapport: float, width: float, axis: str) -> list[CamPath]:
        print(f"[ОПТИМИЗАЦИЯ] Генерация обрезных меток (Ось: {axis}, Рапорт: {rapport}мм, Ширина: {width}мм)...")
        marks = CropMarksGenerator.generate(paths, rapport, width, axis)
        return paths + marks

    def save_source_dxf(self, paths: list[CamPath], output_path: str | Path):
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        for p in paths:
            if len(p.points) > 1: msp.add_lwpolyline(p.points, close=p.is_closed)
        doc.saveas(output_path)

    def export_paths_to_svg(self, paths: list[CamPath], output_path: str | Path):
        if not paths: return
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x: return
        
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        w = max(max_x - min_x, 1.0)
        h = max(max_y - min_y, 1.0)
        
        svg = [f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>']
        svg.append(f'<svg width="{w+2}mm" height="{h+2}mm" viewBox="{min_x-1} {-max_y-1} {w+2} {h+2}" xmlns="http://www.w3.org/2000/svg">')
        
        for p in paths:
            if len(p.points) < 2: continue
            d = []
            for i, pt in enumerate(p.points):
                cmd = "M" if i == 0 else "L"
                d.append(f"{cmd} {pt[0]:.4f} {-pt[1]:.4f}")
            if p.is_closed: d.append("Z")
            color = "blue" if p.layer_name.startswith("HEALED") else "black"
            svg.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="0.2" />')
        svg.append('</svg>')
        with open(output_path, "w", encoding="utf-8") as f: f.write("\n".join(svg))

    def generate_uv_mask_pdf(self, paths: list[CamPath], offset_val: float, output_path: str | Path, badge_text: str = "", mark_d: float = 4.0, mark_margin: float = 10.0) -> tuple[list[CamPath], list[CamPath], Polygon]:
        print(f"Генерация УФ-Маски: Офсет={offset_val}мм, Метки={mark_d}мм...")
        
        regular_lines = []
        crop_lines = []
        
        # Разделяем основную геометрию и обрезные метки
        for p in paths:
            if len(p.points) > 1:
                line = LineString([(pt[0], pt[1]) for pt in p.points])
                if p.layer_name == "CROP_MARKS":
                    crop_lines.append(line)
                else:
                    regular_lines.append(line)
                
        # 1. Основная геометрия штампа (буфер = offset_val)
        mask_geom = MultiLineString(regular_lines).buffer(offset_val, cap_style=2, join_style=2, mitre_limit=50.0).simplify(0.001, preserve_topology=True) if regular_lines else Polygon()

        # 2. Обрезные метки (жесткая толщина линии 0.1 мм -> радиус буфера 0.05 мм)
        crop_geom = MultiLineString(crop_lines).buffer(0.05, cap_style=2, join_style=2, mitre_limit=50.0).simplify(0.001, preserve_topology=True) if crop_lines else Polygon()

        pure_mask_paths = []
        def extract_pure_paths(geom, target_list, layer_ext, layer_hole):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                cp = CamPath(is_closed=True, layer_name=layer_ext)
                for pt in geom.exterior.coords: cp.add_point(round(pt[0], 4), round(pt[1], 4))
                target_list.append(cp)
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name=layer_hole)
                    for pt in interior.coords: cp_hole.add_point(round(pt[0], 4), round(pt[1], 4))
                    target_list.append(cp_hole)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: extract_pure_paths(g, target_list, layer_ext, layer_hole)

        extract_pure_paths(mask_geom, pure_mask_paths, "MASK_EXTERIOR", "MASK_HOLE")

        # 3. Реперные метки (строим только вокруг основного макета, игнорируя обрезные метки)
        regular_cam_paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        generator = AlignmentMarksGenerator(mark_diameter=mark_d, margin=mark_margin)
        fiducial_paths = generator.generate(regular_cam_paths)
        fiducial_polys = []
        for p in fiducial_paths:
            if len(p.points) >= 3:
                poly = Polygon(p.points)
                if poly.is_valid: fiducial_polys.append(poly)

        # Общий габарит для PDF (штамп + обрезные метки + реперные метки)
        total_geom = unary_union([mask_geom, crop_geom] + fiducial_polys)
        if total_geom.is_empty: raise ValueError("Геометрия пуста.")

        min_x, min_y, max_x, max_y = total_geom.bounds
        badge_height = 10.0
        badge_margin = 10.0
        overall_min_y = min_y - badge_margin - badge_height
        
        mask_visual_paths = list(pure_mask_paths)
        extract_pure_paths(crop_geom, mask_visual_paths, "MASK_EXTRA", "MASK_EXTRA")
        
        for poly in fiducial_polys: 
            extract_pure_paths(poly, mask_visual_paths, "MASK_EXTRA", "MASK_EXTRA")

        badge_path = CamPath(is_closed=True, layer_name="MASK_EXTRA")
        badge_path.add_point(min_x, overall_min_y)
        badge_path.add_point(max_x, overall_min_y)
        badge_path.add_point(max_x, overall_min_y + badge_height)
        badge_path.add_point(min_x, overall_min_y + badge_height)
        mask_visual_paths.append(badge_path)

        margin = 10 
        width = (max_x - min_x) + 2 * margin
        height = (max_y - overall_min_y) + 2 * margin
        
        svg_content = [f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>', f'<svg width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
        
        def geom_to_svg_path(geom):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                d = []
                for i, pt in enumerate(geom.exterior.coords):
                    cmd = "M" if i == 0 else "L"
                    d.append(f"{cmd} {pt[0] - min_x + margin:.4f} {height - (pt[1] - overall_min_y + margin):.4f}")
                d.append("Z")
                for interior in geom.interiors:
                    for i, pt in enumerate(interior.coords):
                        cmd = "M" if i == 0 else "L"
                        d.append(f"{cmd} {pt[0] - min_x + margin:.4f} {height - (pt[1] - overall_min_y + margin):.4f}")
                    d.append("Z")
                svg_content.append(f'<path d="{" ".join(d)}" fill="black" fill-rule="evenodd" stroke="none" />')
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: geom_to_svg_path(g)

        geom_to_svg_path(mask_geom)
        geom_to_svg_path(crop_geom)
        for poly in fiducial_polys: geom_to_svg_path(poly)
            
        badge_w = max_x - min_x
        bx = margin
        by = height - margin - badge_height
        safe_text = badge_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        svg_content.append(f'<rect x="{bx}" y="{by}" width="{badge_w}" height="{badge_height}" fill="black" rx="1" ry="1" />')
        svg_content.append(f'<text x="{bx + 3}" y="{by + badge_height/2 + 1.5}" font-family="Arial" font-size="4" fill="white" font-weight="bold">{safe_text}</text>')
        svg_content.append('</svg>')
        
        temp_dir = Path(tempfile.gettempdir())
        safe_svg = temp_dir / f"cam_mask_in_{os.getpid()}.svg"
        safe_pdf = temp_dir / f"cam_mask_out_{os.getpid()}.pdf"
        with open(safe_svg, "w", encoding="utf-8") as f: f.write("\n".join(svg_content))
            
        project_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(os.getcwd())
        inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe' if os.name == 'nt' else Path('inkscape')
        cflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run([str(inkscape_exe), str(safe_svg), '--export-text-to-path', f'--export-filename={safe_pdf}'], check=True, capture_output=True, creationflags=cflags)
        
        if safe_pdf.exists(): shutil.move(str(safe_pdf), str(output_path))
        if safe_svg.exists():
            try: safe_svg.unlink()
            except: pass
            
        # Возвращаем ТОЛЬКО mask_geom (регулярную геометрию). 
        # CNC получит только её и проигнорирует обрезные метки.
        return mask_visual_paths, pure_mask_paths, mask_geom

    def generate_gcode(self, mask_geom, output_path: str | Path, tool_obj: Tool, post_obj: PostProcessor, mask_offset: float, enable_sharpening: bool) -> tuple[list[CamPath], list[CamPath]]:
        print("[ЧПУ] Расчет Идеального лезвия и эквидистант от УФ-Маски...")
        tool = VBitTool(tool_obj)
        print(f"      Инструмент: {tool_obj.name} ({tool_obj.angle_deg}°, Пятно={tool_obj.tip_diameter}мм, Z={tool_obj.depth}мм, Шаг={tool_obj.step_down}мм)")
        print(f"      Радиус смещения (R_eff): {tool.offset_radius:.4f} мм")
        
        ideal_paths, cnc_paths = self.nesting.process_mask_geometry(mask_geom, mask_offset, tool.offset_radius, tool.depth, enable_sharpening)
        print(f"[ЧПУ] Генерация G-кода (Подрезка: {'ВКЛ' if enable_sharpening else 'ВЫКЛ'})...")
        
        compiler = GCodeCompiler(tool=tool_obj, postprocessor=post_obj)
        gcode_text = compiler.compile(cnc_paths)
        with open(output_path, "w", encoding="utf-8") as f: f.write(gcode_text)
        return ideal_paths, cnc_paths