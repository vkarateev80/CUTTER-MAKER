import math
from shapely.geometry import Polygon, Point
from src.parser.geometry import CamPath
from src.db.models import Tool, PostProcessor

class GCodeCompiler:
    def __init__(self, tool: Tool, postprocessor: PostProcessor):
        self.tool = tool
        self.post = postprocessor
        self.safe_z = postprocessor.safe_z
        self.feedrate = tool.feedrate

    def _fix_orientation(self, path: CamPath, milling_dir: str):
        """Разворачивает контур для Попутного (Climb) или Встречного (Conv) резания"""
        if not path.is_closed or len(path.points) < 3: return

        pts = path.points
        area = 0.0
        for i in range(len(pts)-1):
            area += (pts[i][0]*pts[i+1][1] - pts[i+1][0]*pts[i][1])
        area /= 2.0
        
        is_ccw = area > 0 # Если площадь положительная - контур идет против часовой стрелки
        
        if path.layer_name == "CNC_EXTERIOR":
            # Для внешнего контура: Попутное = По часовой (CW), Встречное = Против (CCW)
            needs_ccw = (milling_dir == "Conventional")
        elif path.layer_name == "CNC_HOLE":
            # Для отверстий всё наоборот: Попутное = Против (CCW), Встречное = По часовой (CW)
            needs_ccw = (milling_dir == "Climb")
        else:
            return 
            
        if is_ccw != needs_ccw:
            path.points.reverse()

    def _optimize_path_order(self, paths: list[CamPath], start_pos: tuple[float, float] = (0.0, 0.0)) -> list[CamPath]:
        if not paths: return []
        unvisited = paths.copy()
        ordered = []
        curr_pos = start_pos
        
        while unvisited:
            best_idx = -1
            best_dist = float('inf')
            reverse_path = False
            
            for i, path in enumerate(unvisited):
                if not path.points: continue
                pt_start = path.points[0]
                dist_to_start = math.hypot(pt_start[0] - curr_pos[0], pt_start[1] - curr_pos[1])
                if dist_to_start < best_dist:
                    best_dist = dist_to_start
                    best_idx = i
                    reverse_path = False
                if not path.is_closed:
                    pt_end = path.points[-1]
                    dist_to_end = math.hypot(pt_end[0] - curr_pos[0], pt_end[1] - curr_pos[1])
                    if dist_to_end < best_dist:
                        best_dist = dist_to_end
                        best_idx = i
                        reverse_path = True
                        
            if best_idx == -1: break
            chosen_path = unvisited.pop(best_idx)
            if reverse_path and not chosen_path.is_closed:
                chosen_path.points.reverse()
            ordered.append(chosen_path)
            curr_pos = chosen_path.points[-1]
            
        return ordered

    def _apply_smart_lead_in_out(self, path: CamPath, radius: float) -> CamPath:
        """Поиск безопасной точки и построение дуг строго ОТ заготовки"""
        if len(path.points) < 2 or radius <= 0.001: return path
        z_val = path.points[0][2] if len(path.points[0]) > 2 else None
        is_hole = (path.layer_name == "CNC_HOLE")
        
        def get_arc(cx, cy, a_start, a_end, ccw):
            if ccw:
                while a_end < a_start: a_end += 2*math.pi
            else:
                while a_end > a_start: a_end -= 2*math.pi
            steps = max(4, int(radius * math.pi / 2 / 0.2))
            arc = []
            for k in range(steps + 1):
                t = k / steps
                ang = a_start + (a_end - a_start) * t
                px, py = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
                arc.append((px, py, z_val) if z_val is not None else (px, py))
            return arc

        if not path.is_closed:
            p0, p1 = path.points[0], path.points[1]
            l_in = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
            if l_in > 1e-4:
                tx, ty = (p1[0]-p0[0])/l_in, (p1[1]-p0[1])/l_in
                nx, ny = -ty, tx
                is_ccw = (tx*ny - ty*nx) > 0
                cx, cy = p0[0]+nx*radius, p0[1]+ny*radius
                a_S = math.atan2(-ty, -tx)
                a_p0 = math.atan2(-ny, -nx)
                lead_in = get_arc(cx, cy, a_S, a_p0, is_ccw)
            else: lead_in = [p0]

            pn, pn_1 = path.points[-1], path.points[-2]
            l_out = math.hypot(pn[0]-pn_1[0], pn[1]-pn_1[1])
            if l_out > 1e-4:
                tx, ty = (pn[0]-pn_1[0])/l_out, (pn[1]-pn_1[1])/l_out
                nx, ny = -ty, tx
                is_ccw = (tx*ny - ty*nx) > 0
                cx, cy = pn[0]+nx*radius, pn[1]+ny*radius
                a_pn = math.atan2(-ny, -nx)
                a_E = math.atan2(ty, tx)
                lead_out = get_arc(cx, cy, a_pn, a_E, is_ccw)
            else: lead_out = [pn]

            new_path = CamPath(layer_name=path.layer_name, is_closed=False)
            new_path.points = lead_in[:-1] + path.points + lead_out[1:]
            return new_path
            
        else:
            pts = path.points.copy()
            if math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1]) < 1e-4: pts = pts[:-1]
            n = len(pts)
            if n < 3: return path
            
            poly = Polygon([pt[:2] for pt in pts])
            if not poly.is_valid or poly.area < 1e-6: return path
                
            segments = []
            for i in range(n):
                p1, p2 = pts[i], pts[(i+1)%n]
                l = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
                segments.append((l, i, p1, p2))
            segments.sort(key=lambda x: x[0], reverse=True)
            
            best_lead_in, best_lead_out, best_new_pts = None, None, None
            
            for l, i, p1, p2 in segments:
                if l < 1e-4: continue
                pm = ((p1[0]+p2[0])/2.0, (p1[1]+p2[1])/2.0)
                tx, ty = (p2[0]-p1[0])/l, (p2[1]-p1[1])/l
                nx, ny = -ty, tx 
                
                # Строгая проверка: нормаль смотрит внутрь полигона?
                test_pt = Point(pm[0] + nx*0.01, pm[1] + ny*0.01)
                points_inside = poly.contains(test_pt)
                
                # Для отверстия (HOLE) облой ВНУТРИ. Для внешнего (EXTERIOR) облой СНАРУЖИ.
                if is_hole:
                    if not points_inside: nx, ny = -nx, -ny # Выгибаем внутрь дырки
                else:
                    if points_inside: nx, ny = -nx, -ny # Выгибаем наружу от этикетки
                
                cx, cy = pm[0] + nx * radius, pm[1] + ny * radius
                cross = (-nx)*ty - (-ny)*tx
                a_pm = math.atan2(-ny, -nx)
                
                if cross > 0:
                    a_start_in, a_end_out = a_pm - math.pi/2, a_pm + math.pi/2
                    is_ccw = True
                else:
                    a_start_in, a_end_out = a_pm + math.pi/2, a_pm - math.pi/2
                    is_ccw = False
                
                lead_in = get_arc(cx, cy, a_start_in, a_pm, is_ccw)
                lead_out = get_arc(cx, cy, a_pm, a_end_out, is_ccw)
                
                # Collision Check
                safe = True
                poly_ext = poly.exterior
                for pt in lead_in[:-1] + lead_out[1:]:
                    p = Point(pt[0], pt[1])
                    # Задевает деталь? (Для отверстий тело снаружи полигона, для внешних - внутри)
                    if is_hole:
                        if not poly.contains(p): safe = False; break
                    else:
                        if poly.contains(p): safe = False; break
                        
                    if math.hypot(pt[0]-pm[0], pt[1]-pm[1]) > 0.05:
                        if p.distance(poly_ext) < 0.01: safe = False; break
                            
                if safe or (best_new_pts is None): 
                    pm_3d = (pm[0], pm[1], z_val) if z_val is not None else pm
                    best_new_pts = [pm_3d] + pts[i+1:] + pts[:i+1] + [pm_3d]
                    best_lead_in = lead_in
                    best_lead_out = lead_out
                    if safe: break 
                    
            if best_new_pts:
                new_path = CamPath(layer_name=path.layer_name, is_closed=False)
                new_path.points = best_lead_in[:-1] + best_new_pts + best_lead_out[1:]
                return new_path
                
        return path

    def compile(self, paths: list[CamPath], lead_radius: float = 0.0, milling_dir: str = "Climb") -> tuple[str, list[CamPath], float]:
        header = self.post.header.format(safe_z=self.safe_z, rpm=self.tool.spindle_speed)
        gcode = [header]
        
        target_depth = -abs(self.tool.depth)
        step_z = abs(self.tool.step_down)
        if step_z <= 0.001: step_z = abs(target_depth)

        z_passes = []
        current_z = 0.0
        while current_z - step_z > target_depth + 1e-4:
            current_z -= step_z
            z_passes.append(round(current_z, 3))
        z_passes.append(round(target_depth, 3)) 

        regular_paths = [p for p in paths if p.layer_name != "SHARPEN"]
        sharpen_paths = [p for p in paths if p.layer_name == "SHARPEN"]

        # 1. Применяем ориентацию (Попутное/Встречное) ДО дуг!
        for p in regular_paths:
            self._fix_orientation(p, milling_dir)

        # 2. Сортируем
        regular_paths = self._optimize_path_order(regular_paths, start_pos=(0.0, 0.0))
        
        # 3. Строим дуги
        if lead_radius > 0:
            regular_paths = [self._apply_smart_lead_in_out(p, lead_radius) for p in regular_paths]
        
        last_pos = (0.0, 0.0)
        if regular_paths and regular_paths[-1].points: last_pos = regular_paths[-1].points[-1]
        sharpen_paths = self._optimize_path_order(sharpen_paths, start_pos=last_pos)

        tool_on_cmd = self.post.tool_on.format(rpm=self.tool.spindle_speed)
        tool_off_cmd = self.post.tool_off

        total_time_min = 0.0
        sim_x, sim_y, sim_z = 0.0, 0.0, self.safe_z
        rapid_rate = 3000.0 
        plunge_rate = 300.0 
        work_rate = float(self.feedrate) 

        def calc_time(nx, ny, nz, rate):
            nonlocal total_time_min, sim_x, sim_y, sim_z
            dist = math.sqrt((nx - sim_x)**2 + (ny - sim_y)**2 + (nz - sim_z)**2)
            if rate > 0: total_time_min += dist / rate
            sim_x, sim_y, sim_z = nx, ny, nz

        for i, path in enumerate(regular_paths):
            if not path.points: continue
            
            gcode.append(f"\n; --- Контур {i+1} (Слой: {path.layer_name}) ---")
            start_pt = path.points[0]
            
            gcode.append(f"G0 Z{self.safe_z:.3f}")
            calc_time(sim_x, sim_y, self.safe_z, rapid_rate)
            gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
            calc_time(start_pt[0], start_pt[1], self.safe_z, rapid_rate)
            gcode.append(tool_on_cmd)
            
            for pass_idx, pass_z in enumerate(z_passes):
                gcode.append(f"; Проход {pass_idx + 1}/{len(z_passes)} (Z={pass_z:.3f})")
                gcode.append(f"G1 Z{pass_z:.3f} F300")
                calc_time(start_pt[0], start_pt[1], pass_z, plunge_rate)
                
                for pt in path.points[1:]:
                    gcode.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    calc_time(pt[0], pt[1], pass_z, work_rate)
                    
                if path.is_closed and path.points[-1] != start_pt:
                    gcode.append(f"G1 X{start_pt[0]:.3f} Y{start_pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    calc_time(start_pt[0], start_pt[1], pass_z, work_rate)
                    
                if pass_idx < len(z_passes) - 1 and not path.is_closed:
                    gcode.append(f"G0 Z{self.safe_z:.3f}")
                    calc_time(sim_x, sim_y, self.safe_z, rapid_rate)
                    gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                    calc_time(start_pt[0], start_pt[1], self.safe_z, rapid_rate)
                    
        if regular_paths:
            gcode.append(f"G0 Z{self.safe_z:.3f}")
            calc_time(sim_x, sim_y, self.safe_z, rapid_rate)
            gcode.append(tool_off_cmd)

        if sharpen_paths:
            gcode.append("\n; --- 3D ПОДРЕЗКА ВНУТРЕННИХ УГЛОВ ---")
            gcode.append(tool_on_cmd)
            for i, path in enumerate(sharpen_paths):
                if len(path.points) < 2: continue
                start_pt, end_pt = path.points[0], path.points[1]   
                z_start = start_pt[2] if len(start_pt) > 2 else target_depth
                z_end = end_pt[2] if len(end_pt) > 2 else 0.000
                
                gcode.append(f"\n; Угол {i+1}")
                gcode.append(f"G0 Z{self.safe_z:.3f}")
                calc_time(sim_x, sim_y, self.safe_z, rapid_rate)
                gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                calc_time(start_pt[0], start_pt[1], self.safe_z, rapid_rate)
                gcode.append(f"G1 Z{z_start:.3f} F300")
                calc_time(start_pt[0], start_pt[1], z_start, plunge_rate)
                gcode.append(f"G1 X{end_pt[0]:.3f} Y{end_pt[1]:.3f} Z{z_end:.3f} F300")
                calc_time(end_pt[0], end_pt[1], z_end, plunge_rate)
                gcode.append(f"G0 Z{self.safe_z:.3f}")
                calc_time(end_pt[0], end_pt[1], self.safe_z, rapid_rate)
                
            gcode.append(tool_off_cmd)
            
        footer = self.post.footer.format(safe_z=self.safe_z, rpm=self.tool.spindle_speed)
        gcode.append(f"\n{footer}")
        
        calc_time(0.0, 0.0, self.safe_z, rapid_rate)
        ordered_paths = regular_paths + sharpen_paths
        return "\n".join(gcode), ordered_paths, total_time_min