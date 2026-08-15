import tempfile
from pathlib import Path
import os

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath
from src.parser.pdf_parser import PdfParser
from src.parser.eps_parser import EpsParser

class AiBinaryParser(BaseParser):
    """
    Реверс-инжиниринговый парсер для закрытых .AI файлов.
    Читает файл на уровне байтов (raw binary mode), ищет "эмбеддинги" 
    (embedded streams) в виде скрытых PDF или EPS структур, 
    вырезает их и передает специализированным парсерам.
    """
    def parse(self) -> list[CamPath]:
        # Читаем файл в бинарном режиме ('rb' - read binary)
        try:
            with open(self.filepath, 'rb') as f:
                data = f.read()
        except Exception as e:
            raise RuntimeError(f"Ошибка бинарного чтения файла: {e}")

        # 1. Ищем вшитый (embedded) PDF
        # PDF файлы всегда начинаются с байтов %PDF- и заканчиваются %%EOF
        pdf_start = data.find(b'%PDF-')
        if pdf_start != -1:
            pdf_end = data.rfind(b'%%EOF')
            if pdf_end != -1:
                pdf_end += 5  # Добавляем длину самого слова %%EOF
                pdf_data = data[pdf_start:pdf_end]
                
                temp_dir = Path(tempfile.gettempdir())
                temp_pdf = temp_dir / f"embedded_{self.filepath.stem}.pdf"
                
                # Сохраняем вырезанный кусок как чистый PDF
                with open(temp_pdf, 'wb') as tf:
                    tf.write(pdf_data)
                    
                try:
                    print("      -> Найден вшитый PDF-эмбеддинг! Извлекаем векторы...")
                    parser = PdfParser(temp_pdf)
                    return parser.parse()
                finally:
                    if temp_pdf.exists():
                        try:
                            temp_pdf.unlink()
                        except:
                            pass

        # 2. Ищем вшитый (embedded) EPS / PostScript
        # EPS файлы начинаются с магических байтов %!PS-Adobe
        eps_start = data.find(b'%!PS-Adobe')
        if eps_start != -1:
            # Для EPS мы просто берем все данные от заголовка до конца файла
            eps_data = data[eps_start:]
            
            temp_dir = Path(tempfile.gettempdir())
            temp_eps = temp_dir / f"embedded_{self.filepath.stem}.eps"
            
            with open(temp_eps, 'wb') as tf:
                tf.write(eps_data)
                
            try:
                print("      -> Найден вшитый EPS-эмбеддинг! Извлекаем векторы...")
                parser = EpsParser(temp_eps)
                return parser.parse()
            finally:
                if temp_eps.exists():
                    try:
                        temp_eps.unlink()
                    except:
                        pass
                        
        # Если бинарный поиск ничего не дал
        print("      -> В бинарном коде файла не найдено векторных эмбеддингов.")
        return []