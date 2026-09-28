import subprocess
import tempfile
import os
import sys
import shutil
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath
from src.parser.pdf_parser import PdfParser
from src.parser.inkscape_parser import InkscapeParser
from src.parser.eps_parser import EpsParser
from src.parser.svg_parser import SvgParser

class AiParser(BaseParser):
    def parse(self) -> list[CamPath]:
        paths = []
        try:
            print("      [AI] Попытка 1: Прямое чтение внутреннего PDF-потока...")
            paths = PdfParser(self.filepath).parse()
            if sum(len(p) for p in paths) > 0:
                print("      [AI] Успех! Файл прочитан как PDF.")
                return paths
        except Exception: pass

        try:
            print("      [AI] Попытка 2: Глубокая трансляция через движок Inkscape...")
            paths = InkscapeParser(self.filepath).parse()
            if sum(len(p) for p in paths) > 0:
                print("      [AI] Успех! Файл расшифрован через Inkscape.")
                return paths
        except Exception: pass

        try:
            print("      [AI] Попытка 3: Чтение старого формата (v8) через Ghostscript...")
            paths = EpsParser(self.filepath).parse()
            if sum(len(p) for p in paths) > 0:
                print("      [AI] Успех! Файл прочитан как старый PostScript (EPS).")
                return paths
        except Exception: pass

        try:
            print("      [AI] Попытка 4: Двойной мост (GS -> PDF -> Inkscape -> SVG)...")
            paths = self._double_bridge()
            if sum(len(p) for p in paths) > 0:
                print("      [AI] Успех! Файл расшифрован через двойной мост!")
                return paths
        except Exception as e:
            print(f"      [AI] Попытка 4 не удалась: {e}")

        print("\n      [!!! КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ !!!]")
        print("      Ни один из 4-х методов не смог найти векторы в этом .AI файле.")
        print("      ПРИЧИНА: Файл сохранен в Illustrator БЕЗ галочки 'Create PDF Compatible File'")
        print("      РЕШЕНИЕ: Откройте файл в Adobe Illustrator и пересохраните его (Save As...),")
        print("      обязательно поставив галочку 'Создать PDF-совместимый файл', либо сохраните как .SVG")
        return []

    def _double_bridge(self) -> list[CamPath]:
        from src.parser.engines import require_gs, require_inkscape
        gs_exe = require_gs()
        inkscape_exe = require_inkscape()

        temp_dir = Path(tempfile.gettempdir())
        
        # Безопасные пути
        safe_input = temp_dir / f"cam_safe_ai_in_{os.getpid()}{self.filepath.suffix}"
        safe_pdf = temp_dir / f"cam_safe_ai_mid_{os.getpid()}.pdf"
        safe_svg = temp_dir / f"cam_safe_ai_out_{os.getpid()}.svg"
        
        try:
            shutil.copy2(self.filepath, safe_input)
            cflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            cmd_gs = [
                str(gs_exe), '-dNOPAUSE', '-dBATCH', '-dSAFER', 
                '-sDEVICE=pdfwrite', f'-sOutputFile={safe_pdf}', str(safe_input)
            ]
            subprocess.run(cmd_gs, check=True, capture_output=True, text=True, creationflags=cflags)
            
            cmd_ink = [
                str(inkscape_exe), str(safe_pdf), 
                '--export-type=svg', '--export-text-to-path', '-o', str(safe_svg)
            ]
            subprocess.run(cmd_ink, check=True, capture_output=True, text=True, creationflags=cflags)
            
            parser = SvgParser(safe_svg)
            return parser.parse()
            
        finally:
            for tmp in [safe_input, safe_pdf, safe_svg]:
                if tmp.exists():
                    try: tmp.unlink()
                    except: pass