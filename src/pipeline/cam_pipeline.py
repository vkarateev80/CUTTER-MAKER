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
from src.compiler.gcode_compiler import GCodeCompiler
from src.compiler.tool import VBitTool
from src.parser.geometry import CamPath

class CamPipeline:
    def __init__(self, tolerance: float = 0.01, feedrate: int = 1500, min_loop_area: float = 0.0):
        self.tolerance = tolerance
        self.feedrate = feedrate
        self.min_loop_area = min_loop_area
        self.healer = MorphologicalHealer(tolerance=tolerance, min_loop_area=min_loop_area)
        self.optimizer = TopologicalOptimizer(simplify_tolerance=0.001)
        self.nesting = NestingOptimizer()
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
        return self.optimizer.optimize(self.healer.heal(paths))

    def save_source_dxf(self, paths: list[CamPath], output_path: str | Path):
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        for p in paths:
            if len(p.points) > 1: msp.add_lwpolyline(p.points, close=p.is_closed)
        doc.saveas(output_path)

    def generate_uv_mask_pdf(self, paths: list[CamPath], offset_val: float, output_path: str | Path, badge_text: str = "", mark_d: float = 4.0, mark_margin: float = 10.0) -> tuple[list[CamPath], list[CamPath]]:
        print(f"Генерация УФ-Маски: Офсет={offset_val}мм, Метки={mark_d}мм...")
        
        lines = [LineString(p.points) for p in paths if len(p.points) > 1]
        mask_geom = MultiLineString(lines).buffer(offset_val, cap_style=1, join_style=1) if lines else Polygon()

        pure_mask_paths = []
        def extract_pure_paths(geom):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                cp = CamPath(is_closed=True, layer_name="MASK_EXTERIOR")
                for x, y in geom.exterior.coords: cp.add_point(round(x, 4), round(y, 4))
                pure_mask_paths.append(cp)
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name="MASK_HOLE")
                    for x, y in interior.coords: cp_hole.add_point(round(x, 4), round(y, 4))
                    pure_mask_paths.append(cp_hole)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: extract_pure_paths(g)

        extract_pure_paths(mask_geom)

        generator = AlignmentMarksGenerator(mark_diameter=mark_d, margin=mark_margin)
        fiducial_paths = generator.generate(paths)
        fiducial_polys = []
        for p in fiducial_paths:
            if len(p.points) >= 3:
                poly = Polygon(p.points)
                if poly.is_valid:
                    fiducial_polys.append(poly)

        total_geom = unary_union([mask_geom] + fiducial_polys)
        if total_geom.is_empty: raise ValueError("Геометрия пуста.")

        min_x, min_y, max_x, max_y = total_geom.bounds
        badge_height = 10.0
        badge_margin = 10.0
        overall_min_y = min_y - badge_margin - badge_height
        
        mask_visual_paths = list(pure_mask_paths)
        
        def extract_extra_paths(geom):
            if isinstance(geom, Polygon):
                if geom.is_empty: return
                cp = CamPath(is_closed=True, layer_name="MASK_EXTRA")
                for x, y in geom.exterior.coords: cp.add_point(round(x, 4), round(y, 4))
                mask_visual_paths.append(cp)
                for interior in geom.interiors:
                    cp_hole = CamPath(is_closed=True, layer_name="MASK_EXTRA")
                    for x, y in interior.coords: cp_hole.add_point(round(x, 4), round(y, 4))
                    mask_visual_paths.append(cp_hole)
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: extract_extra_paths(g)

        for poly in fiducial_polys:
            extract_extra_paths(poly)

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
                for i, (x, y) in enumerate(geom.exterior.coords):
                    cmd = "M" if i == 0 else "L"
                    d.append(f"{cmd} {x - min_x + margin:.4f} {height - (y - overall_min_y + margin):.4f}")
                d.append("Z")
                for interior in geom.interiors:
                    for i, (x, y) in enumerate(interior.coords):
                        cmd = "M" if i == 0 else "L"
                        d.append(f"{cmd} {x - min_x + margin:.4f} {height - (y - overall_min_y + margin):.4f}")
                    d.append("Z")
                svg_content.append(f'<path d="{" ".join(d)}" fill="black" fill-rule="evenodd" stroke="none" />')
            elif isinstance(geom, MultiPolygon):
                for g in geom.geoms: geom_to_svg_path(g)

        geom_to_svg_path(mask_geom)
        for poly in fiducial_polys:
            geom_to_svg_path(poly)
            
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
            
        return mask_visual_paths, pure_mask_paths

    def generate_gcode(self, paths: list[CamPath], output_path: str | Path, angle: float, tip: float, depth: float, step_down: float, enable_sharpening: bool = True) -> list[CamPath]:
        print("[ЧПУ] Расчет эквидистант и 3D-подрезки углов...")
        
        tool = VBitTool(angle_deg=angle, tip_diameter=tip, depth=depth)
        print(f"      Инструмент: V-фреза {angle}°, Пятно={tip}мм, Z={depth}мм, Шаг={step_down}мм")
        print(f"      Радиус смещения (R_eff): {tool.offset_radius:.4f} мм")
        
        # Передаем флаг enable_sharpening в сортировщик
        offset_paths = self.nesting.process_wells(paths, tool.offset_radius, tool.depth, enable_sharpening)
        
        print(f"[ЧПУ] Генерация G-кода (Многопроходная обработка. Подрезка углов: {'ВКЛ' if enable_sharpening else 'ВЫКЛ'})...")
        gcode_text = self.compiler.compile(offset_paths, depth=-tool.depth, step_down=step_down)
        
        with open(output_path, "w", encoding="utf-8") as f: 
            f.write(gcode_text)
            
        return offset_paths