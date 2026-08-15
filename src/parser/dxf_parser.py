import ezdxf
from ezdxf.path import make_path
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath

class DxfParser(BaseParser):
    """
    Парсер DXF-файлов для CAM-системы.
    Читает чертеж, извлекает графические примитивы и преобразует их в единую 
    векторную модель (полилинии), разбивая кривые на отрезки (линеаризация).
    """

    def parse(self) -> list[CamPath]:
        cam_paths = []
        
        try:
            # Читаем DXF-документ
            doc = ezdxf.readfile(self.filepath)
            # Извлекаем "Пространство модели" (именно там рисуют чертежи)
            msp = doc.modelspace()
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении DXF файла: {e}")

        # Проходим по всем графическим элементам в чертеже
        for entity in msp:
            # Отбираем только те объекты, которые имеют физический контур
            if entity.dxftype() in {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'SPLINE'}:
                try:
                    # Функция make_path конвертирует любой примитив в абстрактный путь ezdxf
                    dxf_path = make_path(entity)
                    
                    # ДИСКРЕТИЗАЦИЯ (Линеаризация)
                    # flattening разбивает дуги и сплайны на прямые отрезки.
                    # distance=0.01 означает, что хорда отрезка может отклоняться 
                    # от идеальной кривой не более чем на 0.01 единиц (обычно миллиметров).
                    vertices = list(dxf_path.flattening(distance=0.01))
                    
                    # Если путь пустой, пропускаем
                    if not vertices:
                        continue
                        
                    # Создаем наш универсальный контур
                    cam_path = CamPath(
                        layer_name=entity.dxf.layer,
                        is_closed=dxf_path.is_closed
                    )
                    
                    # Заполняем контур точками (берем только X и Y, Z для 2D-обработки обнуляем/игнорируем)
                    for v in vertices:
                        cam_path.add_point(v.x, v.y)
                        
                    cam_paths.append(cam_path)
                    
                except Exception as e:
                    # Если попался поврежденный примитив, просто выводим предупреждение и идем дальше
                    print(f"Предупреждение: не удалось обработать {entity.dxftype()}: {e}")
                    continue
                    
        return cam_paths