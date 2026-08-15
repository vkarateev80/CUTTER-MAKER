import sys
import os
import tkinter as tk

# Гарантируем, что Питон видит папку src
sys.path.insert(0, os.getcwd())

from src.gui.app import CamApp

def main():
    # Создаем главное окно Windows/macOS
    root = tk.Tk()
    
    # Инициализируем наше приложение
    app = CamApp(root)
    
    # Запускаем бесконечный цикл обработки событий (клики мышки, ввод с клавиатуры)
    root.mainloop()

if __name__ == "__main__":
    main()