from src.parser.geometry import CamPath

class GCodeCompiler:
    def __init__(self, feedrate: int = 1500, safe_z: float = 5.0):
        self.feedrate = feedrate
        self.safe_z = safe_z

    def compile(self, paths: list[CamPath], depth: float = -0.5, step_down: float = 0.2) -> str:
        gcode = ["; --- НАЧАЛО ПРОГРАММЫ ---", "G21", "G90", f"G0 Z{self.safe_z:.3f}"]
        
        target_depth = -abs(depth)
        step_z = abs(step_down)

        z_passes = []
        current_z = 0.0
        while current_z - step_z > target_depth + 1e-4:
            current_z -= step_z
            z_passes.append(round(current_z, 3))
        z_passes.append(round(target_depth, 3)) 

        regular_paths = [p for p in paths if p.layer_name != "SHARPEN"]
        sharpen_paths = [p for p in paths if p.layer_name == "SHARPEN"]

        # =========================================================
        # ЭТАП 1: ПОСЛОЙНАЯ ВЫБОРКА ОСНОВНЫХ КОНТУРОВ
        # =========================================================
        for i, path in enumerate(regular_paths):
            if not path.points: continue
            
            gcode.append(f"\n; --- Контур {i+1} (Слой: {path.layer_name}) ---")
            start_pt = path.points[0]
            gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
            gcode.append("M3 S1000")
            
            for pass_idx, pass_z in enumerate(z_passes):
                gcode.append(f"; Проход {pass_idx + 1}/{len(z_passes)} (Z={pass_z:.3f})")
                gcode.append(f"G1 Z{pass_z:.3f} F300")
                
                for pt in path.points[1:]:
                    gcode.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    
                if path.is_closed and path.points[-1] != start_pt:
                    gcode.append(f"G1 X{start_pt[0]:.3f} Y{start_pt[1]:.3f} Z{pass_z:.3f} F{self.feedrate}")
                    
                if pass_idx < len(z_passes) - 1 and not path.is_closed:
                    gcode.append(f"G0 Z{self.safe_z:.3f}")
                    gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                    
            gcode.append(f"G0 Z{self.safe_z:.3f}")
            gcode.append("M5")

        # =========================================================
        # ЭТАП 2: ФИНАЛЬНАЯ ПОДРЕЗКА УГЛОВ
        # =========================================================
        if sharpen_paths:
            gcode.append("\n; --- 3D ПОДРЕЗКА ВНУТРЕННИХ УГЛОВ ---")
            gcode.append("M3 S1000")
            for i, path in enumerate(sharpen_paths):
                if len(path.points) < 2: continue
                
                start_pt = path.points[0] # Дно (в очищенной зоне ЧПУ)
                end_pt = path.points[1]   # Вершина (в теле заготовки)
                
                z_start = start_pt[2] if len(start_pt) > 2 else target_depth
                z_end = end_pt[2] if len(end_pt) > 2 else 0.000
                
                gcode.append(f"\n; Угол {i+1}")
                gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                gcode.append(f"G1 Z{z_start:.3f} F300")
                gcode.append(f"G1 X{end_pt[0]:.3f} Y{end_pt[1]:.3f} Z{z_end:.3f} F300")
                gcode.append(f"G0 Z{self.safe_z:.3f}")
                
            gcode.append("M5")
            
        gcode.append("\n; --- КОНЕЦ ПРОГРАММЫ ---")
        gcode.append(f"G0 Z{self.safe_z:.3f}")
        gcode.append("G0 X0.000 Y0.000")
        gcode.append("M30")
        return "\n".join(gcode)