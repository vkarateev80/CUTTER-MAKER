import math
from src.parser.geometry import CamPath
from src.db.models import Tool, PostProcessor

class GCodeCompiler:
    def __init__(self, tool: Tool, postprocessor: PostProcessor):
        self.tool = tool
        self.post = postprocessor
        self.safe_z = postprocessor.safe_z
        self.feedrate = tool.feedrate

    def _optimize_path_order(self, paths: list[CamPath], start_pos: tuple[float, float] = (0.0, 0.0)) -> list[CamPath]:
        """
        Алгоритм 'Ближайшего соседа' (Nearest Neighbor) для минимизации холостых переездов (G0).
        """
        if not paths:
            return []
            
        unvisited = paths.copy()
        ordered = []
        curr_pos = start_pos
        
        while unvisited:
            best_idx = -1
            best_dist = float('inf')
            reverse_path = False
            
            for i, path in enumerate(unvisited):
                if not path.points: 
                    continue
                
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
                        
            if best_idx == -1:
                break
                
            chosen_path = unvisited.pop(best_idx)
            
            if reverse_path and not chosen_path.is_closed:
                chosen_path.points.reverse()
                
            ordered.append(chosen_path)
            curr_pos = chosen_path.points[-1]
            
        return ordered

    def _apply_lead_in_out(self, path: CamPath, radius: float) -> CamPath:
        """Генерация входа и выхода по касательной (четверть окружности ОТ заготовки)"""
        if not path.is_closed or len(path.points) < 3 or radius <= 0.001:
            return path
            
        p0 = path.points[0]
        z_val = p0[2] if len(p0) > 2 else None
        
        # Вычисляем вектор касательной ВХОДА
        p1 = None
        for pt in path.points[1:]:
            if math.hypot(pt[0]-p0[0], pt[1]-p0[1]) > 1e-4:
                p1 = pt; break
        if not p1: return path
        
        dx, dy = p1[0]-p0[0], p1[1]-p0[1]
        l = math.hypot(dx, dy)
        t_in = (dx/l, dy/l)
        
        # Вычисляем вектор касательной ВЫХОДА (в точке p0)
        pn_prev = None
        for pt in reversed(path.points[:-1]):
            if math.hypot(pt[0]-p0[0], pt[1]-p0[1]) > 1e-4:
                pn_prev = pt; break
        if not pn_prev: return path
        
        dx, dy = p0[0]-pn_prev[0], p0[1]-pn_prev[1]
        l = math.hypot(dx, dy)
        t_out = (dx/l, dy/l)
        
        def gen_arc(pt, t_vec, is_in):
            tx, ty = t_vec
            # ИНВЕРТИРОВАННАЯ НОРМАЛЬ: Направляет центр дуги строго ОТ ножей (в стружку)
            nx, ny = -ty, tx 
            
            cx, cy = pt[0] + nx * radius, pt[1] + ny * radius
            alpha = math.atan2(ny, nx)
            th_base = alpha + math.pi
            
            pts = []
            segments = max(4, int(radius * math.pi / 2 / 0.2)) # Разбиение на отрезки
            
            if is_in:
                # Вход: четверть окружности
                th_start = th_base - (math.pi / 2)
                th_end = th_base
            else:
                # Выход: четверть окружности
                th_start = th_base
                th_end = th_base + (math.pi / 2)
                
            for i in range(segments + 1):
                t = i / segments
                th = th_start + (th_end - th_start) * t
                x = cx + radius * math.cos(th)
                y = cy + radius * math.sin(th)
                if z_val is not None: pts.append((x, y, z_val))
                else: pts.append((x, y))
            return pts
            
        lead_in = gen_arc(p0, t_in, True)
        lead_out = gen_arc(p0, t_out, False)
        
        # Создаем НОВЫЙ открытый контур, который включает в себя дуги
        new_path = CamPath(layer_name=path.layer_name, is_closed=False)
        new_path.points.extend(lead_in)
        
        for pt in path.points[1:]:
            if math.hypot(pt[0]-new_path.points[-1][0], pt[1]-new_path.points[-1][1]) > 1e-4:
                new_path.points.append(pt)
                
        if math.hypot(new_path.points[-1][0]-p0[0], new_path.points[-1][1]-p0[1]) > 1e-4:
            new_path.points.append(p0)
            
        new_path.points.extend(lead_out[1:]) # Добавляем выход, пропуская дубликат первой точки
        return new_path

    def compile(self, paths: list[CamPath], lead_radius: float = 0.0) -> tuple[str, list[CamPath]]:
        header = self.post.header.format(safe_z=self.safe_z, rpm=self.tool.spindle_speed)
        gcode = [header]
        
        target_depth = -abs(self.tool.depth)
        step_z = abs(self.tool.step_down)
        if step_z <= 0.001: 
            step_z = abs(target_depth)

        z_passes = []
        current_z = 0.0
        while current_z - step_z > target_depth + 1e-4:
            current_z -= step_z
            z_passes.append(round(current_z, 3))
        z_passes.append(round(target_depth, 3)) 

        regular_paths = [p for p in paths if p.layer_name != "SHARPEN"]
        sharpen_paths = [p for p in paths if p.layer_name == "SHARPEN"]

        # Сортируем пути
        regular_paths = self._optimize_path_order(regular_paths, start_pos=(0.0, 0.0))
        
        # ПРИМЕНЯЕМ ВХОД/ВЫХОД ПО ДУГЕ
        if lead_radius > 0:
            regular_paths = [self._apply_lead_in_out(p, lead_radius) for p in regular_paths]
        
        last_pos = (0.0, 0.0)
        if regular_paths and regular_paths[-1].points:
            last_pos = regular_paths[-1].points[-1]
            
        sharpen_paths = self._optimize_path_order(sharpen_paths, start_pos=last_pos)

        tool_on_cmd = self.post.tool_on.format(rpm=self.tool.spindle_speed)
        tool_off_cmd = self.post.tool_off

        for i, path in enumerate(regular_paths):
            if not path.points: continue
            
            gcode.append(f"\n; --- Контур {i+1} (Слой: {path.layer_name}) ---")
            start_pt = path.points[0]
            
            # Фреза переезжает в стартовую точку (начало дуги входа) на безопасной высоте
            gcode.append(f"G0 Z{self.safe_z:.3f}")
            gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
            gcode.append(tool_on_cmd)
            
            for pass_idx, pass_z in enumerate(z_passes):
                gcode.append(f"; Проход {pass_idx + 1}/{len(z_passes)} (Z={pass_z:.3f})")
                
                # ВРЕЗАНИЕ: Опускаемся на рабочую высоту Z прямо в точке старта дуги
                gcode.append(f"G1 Z{pass_z:.3f} F300")
                
                # ПРОХОД: Рисуем дугу входа, сам контур и дугу выхода строго на рабочей высоте Z
                for pt in path.points[1:]:
                    gcode.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    
                if path.is_closed and path.points[-1] != start_pt:
                    gcode.append(f"G1 X{start_pt[0]:.3f} Y{start_pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    
                if pass_idx < len(z_passes) - 1 and not path.is_closed:
                    gcode.append(f"G0 Z{self.safe_z:.3f}")
                    gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                    
        if regular_paths:
            gcode.append(f"G0 Z{self.safe_z:.3f}")
            gcode.append(tool_off_cmd)

        if sharpen_paths:
            gcode.append("\n; --- 3D ПОДРЕЗКА ВНУТРЕННИХ УГЛОВ ---")
            gcode.append(tool_on_cmd)
            for i, path in enumerate(sharpen_paths):
                if len(path.points) < 2: continue
                start_pt = path.points[0] 
                end_pt = path.points[1]   
                z_start = start_pt[2] if len(start_pt) > 2 else target_depth
                z_end = end_pt[2] if len(end_pt) > 2 else 0.000
                
                gcode.append(f"\n; Угол {i+1}")
                gcode.append(f"G0 Z{self.safe_z:.3f}")
                gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                gcode.append(f"G1 Z{z_start:.3f} F300")
                gcode.append(f"G1 X{end_pt[0]:.3f} Y{end_pt[1]:.3f} Z{z_end:.3f} F300")
                gcode.append(f"G0 Z{self.safe_z:.3f}")
                
            gcode.append(tool_off_cmd)
            
        footer = self.post.footer.format(safe_z=self.safe_z, rpm=self.tool.spindle_speed)
        gcode.append(f"\n{footer}")
        
        ordered_paths = regular_paths + sharpen_paths
        return "\n".join(gcode), ordered_paths