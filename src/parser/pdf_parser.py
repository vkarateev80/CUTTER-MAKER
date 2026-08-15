import fitz  # PyMuPDF
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class PdfParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        
        try:
            doc = fitz.open(self.filepath)
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении PDF файла: {e}")

        for page in doc:
            # ВАЖНО: Получаем высоту страницы для реверса оси Y!
            # В PDF ось Y растет вниз, а для станка ЧПУ ось Y должна расти вверх.
            page_height = page.rect.height
            drawings = page.get_drawings()
            
            for drawing in drawings:
                current_path = CamPath(layer_name="PDF_VECTOR")
                
                for item in drawing["items"]:
                    if item[0] == "l": 
                        p1, p2 = item[1], item[2]
                        
                        # Переворачиваем Y
                        y1 = page_height - p1.y
                        y2 = page_height - p2.y
                        
                        if not current_path.points:
                            current_path.add_point(p1.x, y1)
                        elif abs(current_path.points[-1][0] - p1.x) > 1e-4 or abs(current_path.points[-1][1] - y1) > 1e-4:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                            current_path.add_point(p1.x, y1)
                            
                        current_path.add_point(p2.x, y2)
                        
                    elif item[0] == "c": 
                        p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                        y1 = page_height - p1.y
                        
                        if not current_path.points:
                            current_path.add_point(p1.x, y1)
                        elif abs(current_path.points[-1][0] - p1.x) > 1e-4 or abs(current_path.points[-1][1] - y1) > 1e-4:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                            current_path.add_point(p1.x, y1)
                            
                        segments = 15 
                        for i in range(1, segments + 1):
                            t = i / segments
                            x = (1-t)**3 * p1.x + 3*(1-t)**2 * t * p2.x + 3*(1-t) * t**2 * p3.x + t**3 * p4.x
                            raw_y = (1-t)**3 * p1.y + 3*(1-t)**2 * t * p2.y + 3*(1-t) * t**2 * p3.y + t**3 * p4.y
                            
                            # Переворачиваем вычисленный Y
                            current_path.add_point(x, page_height - raw_y)
                            
                    elif item[0] == "re": 
                        if current_path.points:
                            cam_paths.append(current_path)
                            current_path = CamPath(layer_name="PDF_VECTOR")
                            
                        rect = item[1]
                        rect_path = CamPath(layer_name="PDF_VECTOR")
                        
                        # Переворачиваем Y для прямоугольника
                        rect_path.add_point(rect.x0, page_height - rect.y0)
                        rect_path.add_point(rect.x1, page_height - rect.y0)
                        rect_path.add_point(rect.x1, page_height - rect.y1)
                        rect_path.add_point(rect.x0, page_height - rect.y1)
                        rect_path.add_point(rect.x0, page_height - rect.y0) 
                        rect_path.is_closed = True
                        cam_paths.append(rect_path)
                        
                if current_path.points:
                    cam_paths.append(current_path)

        doc.close()
        
        valid_paths = []
        for path in cam_paths:
            if len(path.points) > 2:
                start_pt = path.points[0]
                end_pt = path.points[-1]
                if abs(start_pt[0] - end_pt[0]) < 1e-4 and abs(start_pt[1] - end_pt[1]) < 1e-4:
                    path.is_closed = True
            
            if len(path.points) > 1:
                valid_paths.append(path)
                
        return valid_paths