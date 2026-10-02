# CUTTER MAKER — server-профиль: один образ, семь сервисов
# (ingest/render/geometry/math/cam/state/gateway), команды задаёт docker-compose).
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CUTTER_STATE_ROOT=/app

# Движки мультиформатного импорта (Linux-ветка резолвера ищет их в PATH):
# Inkscape — CDR/мосты, Ghostscript — EPS/старый AI, шрифты — текст в кривые.
RUN apt-get update && apt-get install -y --no-install-recommends \
        inkscape \
        ghostscript \
        fonts-dejavu \
        fonts-liberation \
        fonts-noto-cjk \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY contracts/ contracts/
COPY services/ services/
COPY src/ src/
COPY web/ web/
# Сид БД: named volume монтируется на /app/data и при первом запуске
# наследует эти файлы (tools.json / postprocessors.json).
COPY data/tools.json data/postprocessors.json data/

EXPOSE 8771

CMD ["python", "-m", "uvicorn", "services.gateway:app", "--host", "0.0.0.0", "--port", "8771"]
