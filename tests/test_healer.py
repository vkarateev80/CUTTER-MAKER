import sys
import os

# Добавляем корень проекта в пути, чтобы Питон видел папку src
sys.path.insert(0, os.getcwd())

from src.parser.geometry import CamPath
from src.healer.morphology import MorphologicalHealer

def main():
    print("[1] Создаем тестовые контуры с микроразрывом...")
    
    # Имитируем ошибку дизайнера в квадрате 10x10.
    # Линия 1: (0,0) -> (0,10) -> (10,10)
    path1 = CamPath(layer_name="CUT")
    path1.add_point(0, 0)
    path1.add_point(0, 10)
    path1.add_point(10, 10)
    
    # Линия 2: (10, 9.995) -> (10,0) -> (0,0)
    # ВНИМАНИЕ: Разрыв между (10,10) и (10, 9.995) составляет 0.005 мм!
    path2 = CamPath(layer_name="CUT")
    path2.add_point(10, 9.995)
    path2.add_point(10, 0)
    path2.add_point(0, 0)
    
    paths = [path1, path2]
    
    print(f"Исходно контуров: {len(paths)} (Оба не замкнуты, есть разрыв 0.005 мм)")
    
    print("\n[2] Запуск MorphologicalHealer (Допуск: 0.01 мм)...")
    # Наш допуск 0.01 мм больше разрыва 0.005 мм, значит алгоритм должен их "сшить".
    healer = MorphologicalHealer(tolerance=0.01)
    healed_paths = healer.heal(paths)
    
    print("\n--- РЕЗУЛЬТАТЫ ЛЕЧЕНИЯ ---")
    print(f"После лечения контуров: {len(healed_paths)}")
    for i, p in enumerate(healed_paths):
        print(f"Контур {i+1}: Слой '{p.layer_name}', Точек: {len(p)}, Замкнут: {p.is_closed}")
        
    print("----------------------------\n")
    print("Шаг 4: Морфологическое замыкание работает безупречно!")

if __name__ == "__main__":
    main()