import svgelements
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class SvgParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        
        try:
            svg = svgelements.SVG.parse(str(self.filepath))
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении SVG файла: {e}")

        step_size = 0.1 

        for element in svg.elements():
            if isinstance(element, svgelements.Shape):
                path_obj = element if isinstance(element, svgelements.Path) else svgelements.Path(element)
                path_obj.reify() 
                path_obj.approximate_arcs_with_cubics() 

                cam_path = CamPath(layer_name="SVG_VECTOR")
                
                for segment in path_obj:
                    try:
                        seg_len = segment.length()
                        if seg_len < 1e-5:
                            continue
                        
                        num_pts = max(2, int(seg_len / step_size))
                        for i in range(num_pts + 1):
                            t = i / num_pts
                            pt = segment.point(t)
                            
                            # ИНЖЕНЕРНОЕ ИСПРАВЛЕНИЕ: Реверс оси Y (-pt.y)
                            # Переводим экранную систему координат в декартову (для ЧПУ)
                            real_y = -pt.y
                            
                            if cam_path.points:
                                last_pt = cam_path.points[-1]
                                if abs(last_pt[0] - pt.x) < 1e-4 and abs(last_pt[1] - real_y) < 1e-4:
                                    continue
                                    
                            cam_path.add_point(pt.x, real_y)
                    except Exception:
                        continue
                        
                if len(cam_path.points) > 2:
                    start_pt = cam_path.points[0]
                    end_pt = cam_path.points[-1]
                    if abs(start_pt[0] - end_pt[0]) < 1e-4 and abs(start_pt[1] - end_pt[1]) < 1e-4:
                        cam_path.is_closed = True
                        
                if len(cam_path.points) > 1:
                    cam_paths.append(cam_path)

        return cam_paths