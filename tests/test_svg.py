import sys
import os
from pathlib import Path
from shapely.geometry import LineString, MultiLineString

sys.path.insert(0, os.getcwd())
from src.pipeline.cam_pipeline import CamPipeline
from src.db.models import Tool, PostProcessor

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
    
    # Конвейер: парсинг -> лечение -> геометрия маски -> G-код
    pipeline = CamPipeline()
    paths = pipeline.step1_parse(input_svg)
    assert paths, "Парсер SVG не вернул ни одного контура!"
    print(f"Шаг 1: SVG распарсен, контуров: {len(paths)}")

    healed = pipeline.step3_heal_and_optimize(paths)
    assert healed, "Лечение геометрии не вернуло контуров!"
    print(f"Шаг 2: Геометрия вылечена, контуров: {len(healed)}")

    # Собираем геометрию маски (эквидистанта), как это делает generate_uv_mask_pdf
    lines = [LineString(p.points) for p in healed if len(p.points) > 1]
    mask_geom = MultiLineString(lines).buffer(0.05, cap_style=2, join_style=2, mitre_limit=50.0)
    assert not mask_geom.is_empty, "Геометрия маски пуста!"

    tool = Tool(name="Тестовая V-фреза")
    post = PostProcessor(name="Тестовый пост")
    ideal_paths, cnc_paths, time_min = pipeline.generate_gcode(
        mask_geom, output_gcode, tool, post, mask_offset=0.05, enable_sharpening=False
    )
    assert output_gcode.exists(), "Файл G-кода не создан!"
    assert "G1" in output_gcode.read_text(encoding="utf-8"), "В G-коде нет рабочих перемещений!"
    print(f"Шаг 3: G-код готов: {output_gcode} (контуров ЧПУ: {len(cnc_paths)}, время: {time_min:.2f} мин)")

if __name__ == "__main__":
    main()
