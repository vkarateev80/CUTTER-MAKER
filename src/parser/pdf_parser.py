import fitz
import math
from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class PdfParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        try: 
            doc = fitz.open(self.filepath)
        except Exception as e: 
            raise RuntimeError(f"Ошибка при чтении PDF: {e}")

        # PDF всегда использует типографские пункты (points). 1 дюйм = 72 пункта = 25.4 мм.
        scale = 25.4 / 72.0

        for page in doc:
            page_height = page.rect.height
            for drawing in page.get_drawings():
                current_path = CamPath(layer_name="PDF_VECTOR")
                for item in drawing["items"]:
                    if item[0] == "l": 
                        p1, p2 = item[1], item[2]
                        y1, y2 = page_height - p1.y, page_height - p2.y
                        if not current_path.points: 
                            current_path.add_point(p1.x * scale, y1 * scale)
                        elif abs(current_path.points[-1][0] - p1.x * scale) > 1e-4 or abs(current_path.points[-1][1] - y1 * scale) > 1e-4:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                            current_path.add_point(p1.x * scale, y1 * scale)
                        current_path.add_point(p2.x * scale, y2 * scale)
                    elif item[0] == "c": 
                        p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                        y1 = page_height - p1.y
                        if not current_path.points: 
                            current_path.add_point(p1.x * scale, y1 * scale)
                        elif abs(current_path.points[-1][0] - p1.x * scale) > 1e-4 or abs(current_path.points[-1][1] - y1 * scale) > 1e-4:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                            current_path.add_point(p1.x * scale, y1 * scale)
                        approx_len = math.hypot(p2.x - p1.x, p2.y - p1.y) + math.hypot(p3.x - p2.x, p3.y - p2.y) + math.hypot(p4.x - p3.x, p4.y - p3.y)
                        segments = max(5, min(200, int(approx_len / 0.05)))
                        for i in range(1, segments + 1):
                            t = i / segments
                            x = (1-t)**3 * p1.x + 3*(1-t)**2 * t * p2.x + 3*(1-t) * t**2 * p3.x + t**3 * p4.x
                            raw_y = (1-t)**3 * p1.y + 3*(1-t)**2 * t * p2.y + 3*(1-t) * t**2 * p3.y + t**3 * p4.y
                            current_path.add_point(x * scale, (page_height - raw_y) * scale)
                    elif item[0] == "re": 
                        if current_path.points:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                        rect = item[1]
                        rect_path = CamPath(layer_name="PDF_VECTOR")
                        rect_path.add_point(rect.x0 * scale, (page_height - rect.y0) * scale)
                        rect_path.add_point(rect.x1 * scale, (page_height - rect.y0) * scale)
                        rect_path.add_point(rect.x1 * scale, (page_height - rect.y1) * scale)
                        rect_path.add_point(rect.x0 * scale, (page_height - rect.y1) * scale)
                        rect_path.add_point(rect.x0 * scale, (page_height - rect.y0) * scale) 
                        rect_path.is_closed = True
                        cam_paths.append(rect_path)
                if current_path.points: 
                    cam_paths.append(current_path)
        doc.close()
        
        valid_paths = []
        for path in cam_paths:
            if len(path.points) > 2:
                if abs(path.points[0][0] - path.points[-1][0]) < 1e-4 and abs(path.points[0][1] - path.points[-1][1]) < 1e-4:
                    path.is_closed = True
            if len(path.points) > 1: valid_paths.append(path)
        return valid_paths