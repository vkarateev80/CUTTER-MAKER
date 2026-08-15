import subprocess
import tempfile
import os
import sys
import shutil
from pathlib import Path

from src.parser.base_parser import BaseParser
from src.parser.geometry import CamPath
from src.parser.svg_parser import SvgParser
from src.parser.pdf_parser import PdfParser

class EpsParser(BaseParser):
    def parse(self) -> list[CamPath]:
        if getattr(sys, 'frozen', False):
            project_root = Path(sys.executable).parent
        else:
            project_root = Path(os.getcwd())
        
        if os.name == 'nt':
            gs_exe = project_root / 'ghostscript_engine' / 'gs10.07.1' / 'bin' / 'gswin64c.exe'
            if not gs_exe.exists():
                gs_exe = project_root / 'ghostscript_engine' / 'gs10.07.1' / 'bin' / 'gswin32c.exe'
            inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe'
        else:
            gs_exe = Path('gs')
            inkscape_exe = Path('inkscape') 

        if os.name == 'nt' and not gs_exe.exists():
            raise RuntimeError("Не найден исполняемый файл Ghostscript!")

        temp_dir = Path(tempfile.gettempdir())
        
        # Безопасные пути
        safe_input = temp_dir / f"cam_safe_eps_in_{os.getpid()}{self.filepath.suffix}"
        safe_pdf = temp_dir / f"cam_safe_eps_mid_{os.getpid()}.pdf"
        safe_svg = temp_dir / f"cam_safe_eps_out_{os.getpid()}.svg"
        
        try:
            shutil.copy2(self.filepath, safe_input)
            cflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            # 1. GS -> PDF
            cmd_gs = [
                str(gs_exe), '-dNOPAUSE', '-dBATCH', '-dSAFER', '-dEPSCrop',
                '-sDEVICE=pdfwrite', f'-sOutputFile={safe_pdf}', str(safe_input)
            ]
            subprocess.run(cmd_gs, check=True, capture_output=True, text=True, creationflags=cflags)
            
            # 2. PDF -> SVG
            if os.name != 'nt' or inkscape_exe.exists():
                cmd_ink = [
                    str(inkscape_exe), str(safe_pdf),
                    '--export-type=svg', '--export-text-to-path', '-o', str(safe_svg)
                ]
                subprocess.run(cmd_ink, check=True, capture_output=True, text=True, creationflags=cflags)
                parser = SvgParser(safe_svg)
                return parser.parse()
            else:
                parser = PdfParser(safe_pdf)
                return parser.parse()
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else "Неизвестная ошибка Ghostscript/Inkscape"
            raise RuntimeError(f"Ошибка при конвертации EPS: {error_msg}")
        finally:
            for tmp in [safe_input, safe_pdf, safe_svg]:
                if tmp.exists():
                    try: tmp.unlink()
                    except: pass