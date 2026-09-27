"""Схемы обмена (DTO) CUTTER MAKER.

Единый источник правды для формата данных между будущими сервисами.
Пакет намеренно не зависит от src/ — только от pydantic,— чтобы ядра,
GUI и сервисы могли импортировать контракты без связывания с доменом.
"""

from contracts.models import CamPathDTO, PostProcessorDTO, ToolDTO

__all__ = ["CamPathDTO", "ToolDTO", "PostProcessorDTO"]
