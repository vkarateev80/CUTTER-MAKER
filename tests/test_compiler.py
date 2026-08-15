import sys
import os
from pathlib import Path

# Добавляем корень проекта в пути
sys.path.insert(0, os.getcwd())

from src.parser.geometry import CamPath
from src.compiler.gcode_compiler import GCodeCompiler

def main():
    print("[1] Подготовка тестового контура (Квадрат 10x10)...")
    
    # Создаем замкнутый квадрат
    path = CamPath(layer_name="CUT", is_closed=True)
    path.add_point(0, 0)
    path.add_point(0, 10)
    path.add_point(10, 10)
    path.add_point(10, 0)
    
    print("[2] Запуск GCodeCompiler...")
    compiler = GCodeCompiler(feedrate=1200)
    gcode_text = compiler.compile([path])
    
    # Сохраняем результат в файл
    output_dir = Path("data")
    output_file = output_dir / "square_cut.gcode"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(gcode_text)
        
    print("\n--- СГЕНЕРИРОВАННЫЙ G-КОД (Предпросмотр) ---")
    # Выводим первые 20 строк для наглядности
    lines = gcode_text.split('\n')
    for line in lines[:20]:
        print(line)
    print("...")
    print("--------------------------------------------\n")
    
    print(f"Шаг 6: G-код успешно сгенерирован и сохранен в файл: {output_file}")

if __name__ == "__main__":
    main()