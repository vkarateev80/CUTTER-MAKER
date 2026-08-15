import subprocess
import tempfile
import os
import sys
import shutil # <--- ДОБАВЛЕНО ДЛЯ КОПИРОВАНИЯ
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath
from src.parser.svg_parser import SvgParser

class InkscapeParser(BaseParser):
    def parse(self) -> list[CamPath]:
        if getattr(sys, 'frozen', False):
            project_root = Path(sys.executable).parent
        else:
            project_root = Path(os.getcwd())
        
        if os.name == 'nt':
            inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe'
        else:
            inkscape_exe = Path('inkscape') 

        if os.name == 'nt' and not inkscape_exe.exists():
            raise RuntimeError("Не найден исполняемый файл Inkscape!")

        temp_dir = Path(tempfile.gettempdir())
        
        # --- ИНЖЕНЕРНЫЙ ФИКС: Безопасные ASCII-пути ---
        # Используем os.getpid() чтобы имена были уникальными
        safe_input = temp_dir / f"cam_safe_in_{os.getpid()}{self.filepath.suffix}"
        safe_output = temp_dir / f"cam_safe_out_{os.getpid()}.svg"
        
        try:
            # Копируем исходный файл (даже если он с русским именем) в безопасный
            shutil.copy2(self.filepath, safe_input)
            
            command = [
                str(inkscape_exe),
                str(safe_input),
                '--export-type=svg',
                '--export-text-to-path',
                '-o', str(safe_output)
            ]
            
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(command, check=True, capture_output=True, text=True, creationflags=creation_flags)
            
            if not safe_output.exists():
                raise RuntimeError("Inkscape отработал, но векторный файл не создан.")
                
            svg_parser = SvgParser(safe_output)
            return svg_parser.parse()
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else "Неизвестная ошибка Inkscape"
            raise RuntimeError(f"Ошибка при конвертации через Inkscape: {error_msg}")
        finally:
            # Убираем за собой мусор
            if safe_input.exists():
                try: safe_input.unlink()
                except: pass
            if safe_output.exists():
                try: safe_output.unlink()
                except: pass