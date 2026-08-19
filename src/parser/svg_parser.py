import svgelements
import math
from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class SvgParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        try: svg = svgelements.SVG.parse(str(self.filepath))
        except Exception as e: raise RuntimeError(f"Ошибка при чтении SVG файла: {e}")

        step_size = 0.05 
        for element in svg.elements():
            if isinstance(element, svgelements.Shape):
                path_obj = element if isinstance(element, svgelements.Path) else svgelements.Path(element)
                path_obj.reify() 
                path_obj.approximate_arcs_with_cubics() 

                cam_path = CamPath(layer_name="SVG_VECTOR")
                for segment in path_obj:
                    try:
                        # --- ОПТИМИЗАЦИЯ СКОРОСТИ (Без интегралов) ---
                        if isinstance(segment, (svgelements.Line, svgelements.Close)):
                            num_pts = 1
                        elif isinstance(segment, svgelements.QuadraticBezier):
                            # Быстрая аппроксимация длины по контрольным точкам
                            approx_len = math.hypot(segment.control.x - segment.start.x, segment.control.y - segment.start.y) + \
                                         math.hypot(segment.end.x - segment.control.x, segment.end.y - segment.control.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                        elif isinstance(segment, svgelements.CubicBezier):
                            approx_len = math.hypot(segment.control1.x - segment.start.x, segment.control1.y - segment.start.y) + \
                                         math.hypot(segment.control2.x - segment.control1.x, segment.control2.y - segment.control1.y) + \
                                         math.hypot(segment.end.x - segment.control2.x, segment.end.y - segment.control2.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                        else:
                            approx_len = math.hypot(segment.end.x - segment.start.x, segment.end.y - segment.start.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                            if num_pts < 2: num_pts = 10
                        # ---------------------------------------------

                        for i in range(num_pts + 1):
                            t = i / num_pts
                            pt = segment.point(t)
                            real_y = -pt.y
                            
                            if cam_path.points:
                                last_pt = cam_path.points[-1]
                                if abs(last_pt[0] - pt.x) < 1e-4 and abs(last_pt[1] - real_y) < 1e-4:
                                    continue
                            cam_path.add_point(pt.x, real_y)
                    except Exception: continue
                        
                if len(cam_path.points) > 2:
                    start_pt = cam_path.points[0]
                    end_pt = cam_path.points[-1]
                    if abs(start_pt[0] - end_pt[0]) < 1e-4 and abs(start_pt[1] - end_pt[1]) < 1e-4:
                        cam_path.is_closed = True
                if len(cam_path.points) > 1:
                    cam_paths.append(cam_path)
        return cam_paths