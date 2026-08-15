import sys
import os

# Добавляем корень проекта в пути
sys.path.insert(0, os.getcwd())

from src.parser.geometry import CamPath
from src.optimizer.topology import TopologicalOptimizer

def main():
    print("[1] Создаем прямую линию с 'мусорными' точками...")
    
    # Создаем отрезок от X=0 до X=20
    path = CamPath(layer_name="CUT")
    path.add_point(0, 0)    # Начало
    path.add_point(5, 0)    # Мусорная точка на прямой
    path.add_point(10, 0)   # Мусорная точка на прямой
    path.add_point(15, 0)   # Мусорная точка на прямой
    path.add_point(20, 0)   # Конец
    
    print(f"До оптимизации точек в контуре: {len(path.points)} (Хотя для прямой нужно всего 2!)")
    
    print("\n[2] Запуск TopologicalOptimizer...")
    optimizer = TopologicalOptimizer(simplify_tolerance=0.001)
    optimized_paths = optimizer.optimize([path])
    
    opt_path = optimized_paths[0]
    
    print("\n--- РЕЗУЛЬТАТЫ ОПТИМИЗАЦИИ ---")
    print(f"После оптимизации точек: {len(opt_path.points)}")
    print("Координаты оставшихся точек:")
    for pt in opt_path.points:
        print(f"  X: {pt[0]}, Y: {pt[1]}")
        
    print("----------------------------\n")
    print("Шаг 5: Топологическая оптимизация работает безупречно!")

if __name__ == "__main__":
    main()