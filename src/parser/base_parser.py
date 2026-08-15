from abc import ABC, abstractmethod
from pathlib import Path
from src.parser.geometry import CamPath

class BaseParser(ABC):
    """
    Абстрактный базовый класс для всех парсеров (DXF, SVG, PDF).
    Наследуясь от ABC (Abstract Base Class), мы запрещаем создавать объекты 
    этого класса напрямую и обязываем наследников реализовать метод parse().
    """

    def __init__(self, filepath: str | Path):
        """
        Инициализация парсера.
        
        :param filepath: Путь к файлу, который нужно распарсить.
        """
        self.filepath = Path(filepath)
        
        # Сразу проверяем, существует ли файл, чтобы не упасть с ошибкой позже
        if not self.filepath.exists():
            raise FileNotFoundError(f"Ошибка: Файл не найден по пути: {self.filepath}")

    @abstractmethod
    def parse(self) -> list[CamPath]:
        """
        Основной метод парсинга. 
        Должен прочитать файл, извлечь векторы, дискретизировать кривые 
        и вернуть список объектов CamPath.
        
        Этот метод ОБЯЗАТЕЛЬНО должен быть написан внутри каждого конкретного парсера.
        """
        pass