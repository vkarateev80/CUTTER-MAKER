import json
import os
import sys
import shutil
from pathlib import Path
from src.db.models import Tool, PostProcessor

class DatabaseManager:
    def __init__(self):
        # Определяем корень проекта (работает как в исходниках, так и в скомпилированном .exe)
        if getattr(sys, 'frozen', False):
            self.project_root = Path(sys.executable).parent
        else:
            self.project_root = Path(os.getcwd())
            
        # Папка для хранения баз данных (в корне проекта)
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(exist_ok=True)
        
        self.tools_file = self.data_dir / "tools.json"
        self.posts_file = self.data_dir / "postprocessors.json"
        
        # Проверяем и создаем файлы по умолчанию при первом запуске
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Создает дефолтные файлы БД с базовыми настройками, если они отсутствуют."""
        if not self.tools_file.exists():
            default_tool = Tool(
                name="Стандартная V-фреза 60°",
                tool_type="V-Bit",
                angle_deg=60.0,
                tip_diameter=0.1,
                depth=0.5,
                step_down=0.2,
                feedrate=1500,
                spindle_speed=1000
            )
            self.save_tools([default_tool])
            
        if not self.posts_file.exists():
            default_post = PostProcessor(
                name="GRBL (Standard)",
                extension=".txt",
                header="; --- НАЧАЛО ПРОГРАММЫ ---\nG21\nG90\nG0 Z{safe_z}",
                footer="; --- КОНЕЦ ПРОГРАММЫ ---\nG0 Z{safe_z}\nG0 X0.000 Y0.000\nM30",
                tool_on="M3 S{rpm}",
                tool_off="M5",
                safe_z=5.0
            )
            self.save_postprocessors([default_post])

    # ==========================================
    # УПРАВЛЕНИЕ ИНСТРУМЕНТАМИ
    # ==========================================
    def load_tools(self) -> list[Tool]:
        """Загружает список инструментов из JSON."""
        if not self.tools_file.exists():
            return []
        try:
            with open(self.tools_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Tool.from_dict(item) for item in data]
        except Exception as e:
            print(f"Ошибка чтения БД инструментов: {e}")
            return []

    def save_tools(self, tools: list[Tool]) -> None:
        """Сохраняет список инструментов в JSON."""
        data = [t.to_dict() for t in tools]
        with open(self.tools_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def import_tools(self, filepath: str | Path) -> None:
        """Импортирует инструменты из внешнего файла, добавляя их к текущим."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_data = json.load(f)
            new_tools = [Tool.from_dict(item) for item in new_data]
            current_tools = self.load_tools()
            current_tools.extend(new_tools)
            self.save_tools(current_tools)
        except Exception as e:
            raise RuntimeError(f"Не удалось импортировать инструменты: {e}")

    def export_tools(self, filepath: str | Path) -> None:
        """Экспортирует (копирует) текущую базу инструментов во внешний файл."""
        try:
            shutil.copy2(self.tools_file, filepath)
        except Exception as e:
            raise RuntimeError(f"Не удалось экспортировать инструменты: {e}")

    # ==========================================
    # УПРАВЛЕНИЕ ПОСТПРОЦЕССОРАМИ
    # ==========================================
    def load_postprocessors(self) -> list[PostProcessor]:
        """Загружает список постпроцессоров из JSON."""
        if not self.posts_file.exists():
            return []
        try:
            with open(self.posts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [PostProcessor.from_dict(item) for item in data]
        except Exception as e:
            print(f"Ошибка чтения БД постпроцессоров: {e}")
            return []

    def save_postprocessors(self, posts: list[PostProcessor]) -> None:
        """Сохраняет список постпроцессоров в JSON."""
        data = [p.to_dict() for p in posts]
        with open(self.posts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def import_postprocessors(self, filepath: str | Path) -> None:
        """Импортирует постпроцессоры из внешнего файла."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_data = json.load(f)
            new_posts = [PostProcessor.from_dict(item) for item in new_data]
            current_posts = self.load_postprocessors()
            current_posts.extend(new_posts)
            self.save_postprocessors(current_posts)
        except Exception as e:
            raise RuntimeError(f"Не удалось импортировать постпроцессоры: {e}")

    def export_postprocessors(self, filepath: str | Path) -> None:
        """Экспортирует (копирует) текущую базу постпроцессоров во внешний файл."""
        try:
            shutil.copy2(self.posts_file, filepath)
        except Exception as e:
            raise RuntimeError(f"Не удалось экспортировать постпроцессоры: {e}")