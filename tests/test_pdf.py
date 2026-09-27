import sys
import os
from pathlib import Path
import fitz  # PyMuPDF
from shapely.geometry import LineString, MultiLineString

sys.path.insert(0, os.getcwd())
from src.pipeline.cam_pipeline import CamPipeline
from src.db.models import Tool, PostProcessor

def create_mock_pdf(filepath: Path):
    """Создает простой PDF-файл с одним векторным прямоугольником."""
    doc = fitz.open()
    page = doc.new_page()
    
    # Инструмент для рисования векторной графики в PDF
    shape = page.new_shape()
    
    # Рисуем прямоугольник от точки (10,10) до (60,60)
    shape.draw_rect(fitz.Rect(10, 10, 60, 60))
    shape.finish(color=(1, 0, 0)) # Делаем контур красным
    shape.commit()
    
    doc.save(filepath)
    doc.close()

def main():
    data_dir = Path("data")
    input_pdf = data_dir / "rectangle.pdf"
    output_gcode = data_dir / "rectangle_pdf.gcode"
    
    print("Создаем тестовый PDF-файл...")
    create_mock_pdf(input_pdf)
    
    # Конвейер: парсинг -> лечение -> геометрия маски -> G-код
    pipeline = CamPipeline()
    paths = pipeline.step1_parse(input_pdf)
    assert paths, "Парсер PDF не вернул ни одного контура!"
    print(f"Шаг 1: PDF распарсен, контуров: {len(paths)}")

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
