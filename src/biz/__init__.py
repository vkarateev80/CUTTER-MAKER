"""Бизнес-логика (pricing/eta) — чистое ядро без FastAPI.

Одна и та же логика для: сервисов (HTTP), десктоп-клиента (локальный
fallback, когда сервисы недоступны) и тестов. State-артефакты — файлы
в `<root>/data/` (root = CUTTER_STATE_ROOT или cwd), как у DatabaseManager.
"""

from src.biz.eta_store import book, eta_now, load_queue, queue_delete, queue_snapshot
from src.biz.pricing import calc_price, load_config, save_config

__all__ = [
    "book",
    "calc_price",
    "eta_now",
    "load_config",
    "load_queue",
    "queue_delete",
    "queue_snapshot",
    "save_config",
]
