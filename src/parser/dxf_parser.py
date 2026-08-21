import ezdxf
from ezdxf.path import make_path
from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class DxfParser(BaseParser):
    def parse(self) -> list[CamPath]:
        cam_paths = []
        try:
            doc = ezdxf.readfile(self.filepath)
            msp = doc.modelspace()
            
            # Чтение единиц измерения DXF ($INSUNITS)
            # 1 = дюймы (Inches), 4 = миллиметры (mm), 5 = сантиметры (cm), 6 = метры (m)
            insunits = doc.header.get('$INSUNITS', 4)
            scale = 1.0
            if insunits == 1:
                scale = 25.4
            elif insunits == 5:
                scale = 10.0
            elif insunits == 6:
                scale = 1000.0
                
        except Exception as e: 
            raise RuntimeError(f"Ошибка при чтении DXF файла: {e}")

        for entity in msp:
            if entity.dxftype() in {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}:
                try:
                    dxf_path = make_path(entity)
                    vertices = list(dxf_path.flattening(distance=0.05))
                    if not vertices: continue
                    cam_path = CamPath(layer_name=entity.dxf.layer, is_closed=dxf_path.is_closed)
                    for v in vertices: 
                        # Применяем масштаб к координатам
                        cam_path.add_point(v.x * scale, v.y * scale)
                    cam_paths.append(cam_path)
                except Exception: 
                    continue
        return cam_paths