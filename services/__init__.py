"""Пакет сервисов CUTTER MAKER.

Запуск всех сервисов сразу (desktop-профиль):
    python -m services.run_all        # 7 сервисов, Ctrl+C — остановить

По отдельности (из корня репозитория):
    python -m services.ingest    # парсинг макетов,           :8765
    python -m services.render    # УФ-маска + техкарта,       :8766
    python -m services.geometry  # проверка + лечение,        :8767
    python -m services.math      # массивы/дисторсия/метки,   :8768
    python -m services.cam       # генерация G-кода,          :8769
    python -m services.state     # БД tools/posts, проекты,   :8770
    python -m services.gateway   # единая точка входа,        :8771
"""
