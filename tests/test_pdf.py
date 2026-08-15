import sys
import os
from pathlib import Path
import fitz  # PyMuPDF

sys.path.insert(0, os.getcwd())
from src.pipeline.cam_pipeline import CamPipeline

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
    
    # Запускаем конвейер
    pipeline = CamPipeline()
    pipeline.process_file_to_gcode(input_pdf, output_gcode)

if __name__ == "__main__":
    main()