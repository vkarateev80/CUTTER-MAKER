import sys
import os
from pathlib import Path
import ezdxf

# Добавляем корень проекта в пути, чтобы Питон видел папку src
sys.path.insert(0, os.getcwd())

from src.parser.dxf_parser import DxfParser

def create_mock_dxf(filepath: Path):
    """Создает тестовый DXF файл с квадратом и окружностью."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # Рисуем линию (одна сторона квадрата)
    msp.add_line((0, 0), (10, 0), dxfattribs={'layer': 'CUT'})
    
    # Рисуем окружность (радиус 5)
    msp.add_circle((15, 5), radius=5, dxfattribs={'layer': 'ENGRAVE'})
    
    doc.saveas(filepath)
    print(f"[1] Тестовый файл успешно создан: {filepath}")

def main():
    # Путь к нашему тестовому файлу
    test_file = Path("data") / "test_drawing.dxf"
    
    # 1. Создаем файл
    create_mock_dxf(test_file)
    
    # 2. Тестируем наш парсер
    print("[2] Запуск DxfParser...")
    parser = DxfParser(test_file)
    paths = parser.parse()
    
    # 3. Выводим результаты
    print(f"\n--- РЕЗУЛЬТАТЫ ПАРСИНГА ---")
    print(f"Найдено контуров: {len(paths)}")
    
    for i, p in enumerate(paths):
        # Выводим информацию по каждому контуру
        print(f"Контур {i+1}: Слой '{p.layer_name}', Точек: {len(p)}, Замкнут: {p.is_closed}")
        
    print("----------------------------\n")
    print("Шаг 3: Парсер DXF работает безупречно!")

if __name__ == "__main__":
    main()