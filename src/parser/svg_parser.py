import svgelements
import math
from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class SvgParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        try: 
            svg = svgelements.SVG.parse(str(self.filepath))
        except Exception as e: 
            raise RuntimeError(f"Ошибка при чтении SVG: {e}")

        # Расчет коэффициента масштабирования SVG в миллиметры
        # По умолчанию SVG использует 96 DPI (пикселей на дюйм), т.е. 1 px = 25.4 / 96 мм.
        scale = 25.4 / 96.0
        try:
            if svg.width and svg.viewbox and svg.viewbox.width > 0:
                # Конвертируем физическую ширину SVG в пиксели (при 96 dpi), затем в мм
                w_px = float(svg.width.value(ppi=96))
                w_mm = w_px * (25.4 / 96.0)
                vb_w = float(svg.viewbox.width)
                scale = w_mm / vb_w
        except Exception:
            pass # Оставляем дефолтный масштаб 25.4/96

        # Адаптируем шаг аппроксимации кривых Безье в зависимости от масштаба
        step_size = 0.05 / scale if scale > 0 else 0.05 
        
        for element in svg.elements():
            if isinstance(element, svgelements.Shape):
                path_obj = element if isinstance(element, svgelements.Path) else svgelements.Path(element)
                path_obj.reify() 
                path_obj.approximate_arcs_with_cubics() 

                cam_path = CamPath(layer_name="SVG_VECTOR")
                for segment in path_obj:
                    try:
                        if isinstance(segment, (svgelements.Line, svgelements.Close)): 
                            num_pts = 1
                        elif isinstance(segment, svgelements.QuadraticBezier):
                            approx_len = math.hypot(segment.control.x - segment.start.x, segment.control.y - segment.start.y) + math.hypot(segment.end.x - segment.control.x, segment.end.y - segment.control.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                        elif isinstance(segment, svgelements.CubicBezier):
                            approx_len = math.hypot(segment.control1.x - segment.start.x, segment.control1.y - segment.start.y) + math.hypot(segment.control2.x - segment.control1.x, segment.control2.y - segment.control1.y) + math.hypot(segment.end.x - segment.control2.x, segment.end.y - segment.control2.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                        else:
                            approx_len = math.hypot(segment.end.x - segment.start.x, segment.end.y - segment.start.y)
                            num_pts = max(2, min(200, int(approx_len / step_size)))
                            if num_pts < 2: num_pts = 10

                        for i in range(num_pts + 1):
                            t = i / num_pts
                            pt = segment.point(t)
                            
                            # SVG координата Y направлена вниз. Инвертируем и масштабируем обе оси.
                            real_x = pt.x * scale
                            real_y = -pt.y * scale
                            
                            if cam_path.points:
                                if abs(cam_path.points[-1][0] - real_x) < 1e-4 and abs(cam_path.points[-1][1] - real_y) < 1e-4: 
                                    continue
                            cam_path.add_point(real_x, real_y)
                    except Exception: 
                        continue
                        
                if len(cam_path.points) > 2:
                    if abs(cam_path.points[0][0] - cam_path.points[-1][0]) < 1e-4 and abs(cam_path.points[0][1] - cam_path.points[-1][1]) < 1e-4:
                        cam_path.is_closed = True
                if len(cam_path.points) > 1: 
                    cam_paths.append(cam_path)
        return cam_paths