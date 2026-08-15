from pathlib import Path
from shapely.geometry import LineString, Polygon
import math

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
        
        print(f"[ШАГ 1] Чтение файла: {input_file.name} (Формат: {extension.upper()})")
        
        if extension == '.dxf': parser = DxfParser(input_file)
        elif extension == '.svg': parser = SvgParser(input_file)
        elif extension == '.pdf': parser = PdfParser(input_file)
        elif extension == '.eps': parser = EpsParser(input_file)
        elif extension == '.cdr':
            parser = InkscapeParser(input_file)
        elif extension == '.ai':
            parser = AiParser(input_file)
        else:
            raise ValueError(f"Формат {extension} не поддерживается!")

        paths = parser.parse()
        total_points = sum(len(p) for p in paths)
        print(f" -> Успех: Извлечено контуров: {len(paths)}, Точек: {total_points}")
        return paths

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
            elif getattr(geom, 'coords', None):
                return list(geom.coords)
            return []

        shapely_lines = []
        for path in paths:
            stats["total_points"] += len(path.points)
            if len(path.points) < 2:
                stats["empty_paths"] += 1
                continue
                
            line = LineString(path.points)
            is_dust = False
            
            # --- ПРОВЕРКА НА АРТЕФАКТЫ (МУСОР) ---
            if self.min_loop_area > 0:
                if path.is_closed or line.is_closed:
                    try:
                        if Polygon(line.coords).area < self.min_loop_area:
                            is_dust = True
                    except: is_dust = True
                else:
                    if line.length < self.min_loop_area:
                        is_dust = True
                        
            if is_dust:
                stats["dust"] += 1
                stats["dust_nodes"].extend(extract_coords(line))
                continue # Мусор не участвует в поиске пересечений!
                
            if not path.is_closed:
                stats["open_paths"] += 1
                stats["error_nodes"].append(path.points[0])
                stats["error_nodes"].append(path.points[-1])
                
            shapely_lines.append(line)

        # Поиск самопересечений и петель
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

        # Поиск пересечений между контурами
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
                
        print(f" -> Всего контуров: {stats['total_paths']}")
        print(f" -> Мусорных артефактов (пыль): {stats['dust']}")
        print(f" -> Разорванных (незамкнутых): {stats['open_paths']}")
        print(f" -> Самопересечений (крестов и петель): {stats['intersections']}")
        print(f" -> Задвоенных линий (наложений): {stats['duplicates']}")
        
        return stats

    def step3_heal_and_optimize(self, paths: list[CamPath]) -> list[CamPath]:
        print(f"[ШАГ 3] Запуск морфологии (допуск {self.tolerance} мм, удаление артефактов < {self.min_loop_area})...")
        healed_paths = self.healer.heal(paths)
        optimized_paths = self.optimizer.optimize(healed_paths)
        total_points_after = sum(len(p) for p in optimized_paths)
        print(f" -> Успех: Контуров после слияния: {len(optimized_paths)}, Точек: {total_points_after}")
        return optimized_paths

    def step4_generate_gcode(self, paths: list[CamPath], output_path: str | Path) -> None:
        print(f"[ШАГ 4] Компиляция G-кода (F{self.feedrate})...")
        gcode = self.compiler.compile(paths)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(gcode)
        print(f" -> УСПЕХ! G-код сохранен в файл: {Path(output_path).name}")