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
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении DXF файла: {e}")

        for entity in msp:
            if entity.dxftype() in {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'}:
                try:
                    dxf_path = make_path(entity)
                    # ОПТИМИЗАЦИЯ: Допуск сглаживания кривых 0.05 мм
                    vertices = list(dxf_path.flattening(distance=0.05))
                    if not vertices: continue
                        
                    cam_path = CamPath(layer_name=entity.dxf.layer, is_closed=dxf_path.is_closed)
                    for v in vertices:
                        cam_path.add_point(v.x, v.y)
                    cam_paths.append(cam_path)
                except Exception:
                    continue
        return cam_paths