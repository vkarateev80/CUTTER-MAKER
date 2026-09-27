"""Пакет сервисов CUTTER MAKER.

Запуск (из корня репозитория):
    python -m services.ingest    # парсинг макетов,           :8765
    python -m services.render    # УФ-маска + техкарта,       :8766
    python -m services.geometry  # проверка + лечение,        :8767
    python -m services.math      # массивы/дисторсия/метки,   :8768
    python -m services.cam       # генерация G-кода,          :8769
"""
