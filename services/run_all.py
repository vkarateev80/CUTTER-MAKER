"""Супервизор: запускает ВСЕ сервисы CUTTER MAKER одним процессом (desktop-профиль).

    python -m services.run_all

Каждый сервис — отдельный uvicorn.Server в потоке (разные FastAPI-приложения,
разные JobStore). Ctrl+C останавливает всё. Server-профиль (docker-compose)
запускает сервисы отдельными контейнерами — код сервисов при этом не меняется.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from services import cam, eta, gateway, geometry, ingest, math, pricing, render, state

# (имя, порт, FastAPI-приложение)
SERVERS: list[tuple[str, int]] = [
    ("ingest", 8765, ingest.app),
    ("render", 8766, render.app),
    ("geometry", 8767, geometry.app),
    ("math", 8768, math.app),
    ("cam", 8769, cam.app),
    ("state", 8770, state.app),
    ("pricing", 8774, pricing.app),
    ("eta", 8775, eta.app),
    ("gateway", 8771, gateway.app),
]


def start_all() -> list[tuple[str, uvicorn.Server, threading.Thread]]:
    """Поднимает все сервисы; возвращает (имя, server, thread) для остановки."""
    started = []
    for name, port, app in SERVERS:
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True, name=f"svc-{name}")
        thread.start()
        started.append((name, server, thread))
    return started


def wait_ready(started, timeout: float = 15.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    for name, server, _ in started:
        while not server.started:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Сервис {name} не стартовал за {timeout} с")
            time.sleep(0.05)


def stop_all(started) -> None:
    for _, server, thread in started:
        server.should_exit = True
    for _, _, thread in started:
        thread.join(timeout=5)


def main() -> None:
    print("=" * 60)
    print("CUTTER MAKER — запуск всех сервисов")
    print("=" * 60)
    for name, port, _ in SERVERS:
        print(f"  {name:<10} http://127.0.0.1:{port}")
    print("Gateway (единая точка входа): http://127.0.0.1:8771")
    print("Ctrl+C — остановить всё")
    print("=" * 60)

    started = start_all()
    try:
        wait_ready(started)
        print("Все сервисы запущены.")
        # Блокируемся, пока не придёт Ctrl+C ( KeyboardInterrupt в главном потоке)
        for _, _, thread in started:
            while thread.is_alive():
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        stop_all(started)
    print("Остановлено.")


if __name__ == "__main__":
    main()
