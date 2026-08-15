import sys
import os
from pathlib import Path

sys.path.insert(0, os.getcwd())
from src.pipeline.cam_pipeline import CamPipeline

def create_mock_svg(filepath: Path):
    """Создает простой SVG-файл с одним кругом (через тег <path>)."""
    svg_content = """<?xml version="1.0" encoding="UTF-8"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <!-- Это круг, записанный командами SVG (M - move, A - arc) -->
        <path d="M 50, 50 m -25, 0 a 25,25 0 1,0 50,0 a 25,25 0 1,0 -50,0" />
    </svg>
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(svg_content)

def main():
    data_dir = Path("data")
    input_svg = data_dir / "circle.svg"
    output_gcode = data_dir / "circle_svg.gcode"
    
    print("Создаем тестовый SVG-файл...")
    create_mock_svg(input_svg)
    
    # Запускаем конвейер. Он сам должен понять, что это SVG и вызвать SvgParser!
    pipeline = CamPipeline()
    pipeline.process_file_to_gcode(input_svg, output_gcode)

if __name__ == "__main__":
    main()