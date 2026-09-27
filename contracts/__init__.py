"""Схемы обмена (DTO) CUTTER MAKER.

Единый источник правды для формата данных между будущими сервисами.
Пакет намеренно не зависит от src/ — только от pydantic,— чтобы ядра,
GUI и сервисы могли импортировать контракты без связывания с доменом.
"""

from contracts.models import (
    CamPathDTO,
    CheckErrorsRequestDTO,
    CheckErrorsResultDTO,
    CropMarksRequestDTO,
    DistortionRequestDTO,
    GcodeRequestDTO,
    GcodeResultDTO,
    HealRequestDTO,
    JobRefDTO,
    JobStatusDTO,
    MultiplyRequestDTO,
    ParseResultDTO,
    PathsResultDTO,
    PatternRequestDTO,
    PatternResultDTO,
    PostProcessorDTO,
    ReportRequestDTO,
    ReportResultDTO,
    RotateRequestDTO,
    ToolDTO,
    UvMaskRequestDTO,
    UvMaskResultDTO,
)

__all__ = [
    "CamPathDTO",
    "ToolDTO",
    "PostProcessorDTO",
    "JobRefDTO",
    "JobStatusDTO",
    "ParseResultDTO",
    "UvMaskRequestDTO",
    "UvMaskResultDTO",
    "ReportRequestDTO",
    "ReportResultDTO",
    "PathsResultDTO",
    "CheckErrorsRequestDTO",
    "CheckErrorsResultDTO",
    "HealRequestDTO",
    "PatternRequestDTO",
    "PatternResultDTO",
    "MultiplyRequestDTO",
    "DistortionRequestDTO",
    "RotateRequestDTO",
    "CropMarksRequestDTO",
    "GcodeRequestDTO",
    "GcodeResultDTO",
]
