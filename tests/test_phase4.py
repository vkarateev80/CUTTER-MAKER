import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import httpx
import uvicorn
from fastapi.testclient import TestClient

from src.core.service_client import ServiceClient
from src.db.db_manager import DatabaseManager
from src.db.models import Tool
from src.parser.geometry import CamPath


# ============================================================
# вспомогательные
# ============================================================

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(app, port: int):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn не стартовал"
    return server, t


def stop_server(server, t):
    server.should_exit = True
    t.join(timeout=5)


class EnvSaver:
    """Временная подмена env-переменных с восстановлением."""

    def __init__(self, **values: str):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def crossing_lines() -> list[CamPath]:
    a = CamPath(layer_name="CUT"); a.add_point(0, 0); a.add_point(10, 10)
    b = CamPath(layer_name="CUT"); b.add_point(0, 10); b.add_point(10, 0)
    return [a, b]


# ============================================================
# 1. state (TestClient): tools + проект-документ
# ============================================================

def test_state_http():
    print("[1] state (TestClient): save/load tools + project-doc, 404...")
    import services.state as state_mod

    root = tempfile.mkdtemp(prefix="cutter_state_")
    with EnvSaver(CUTTER_STATE_ROOT=root):
        client = TestClient(state_mod.app)

        # tools: пусто → дефолтная БД из _ensure_defaults (корень=root)
        r = client.post("/v1/tools/load")
        assert r.status_code == 200, r.text

        # сохраняем инструмент и загружаем обратно
        tool = Tool(name="Тестовая 60°", angle_deg=60.0, feedrate=999)
        r = client.post("/v1/tools/save", json={"tools": [tool.to_dto().model_dump()]})
        assert r.status_code == 200 and r.json()["count"] == 1, r.text

        r = client.post("/v1/tools/load")
        loaded = r.json()["tools"]
        assert len(loaded) == 1 and loaded[0]["name"] == "Тестовая 60°" and loaded[0]["feedrate"] == 999

        # файл реально записан в КОРЕНЬ (не в data/ репозитория)
        assert (Path(root) / "data" / "tools.json").exists(), "tools.json не в CUTTER_STATE_ROOT"

        # project-doc: save → load
        doc_path = str(Path(root) / "Проекты" / "П_1" / "project_state.json")
        payload = {"path": doc_path, "data": {"ui": {"z": "96"}, "flags": {"is_distorted": True}}}
        r = client.post("/v1/project/save", json=payload)
        assert r.status_code == 200, r.text

        r = client.post("/v1/project/load", json={"path": doc_path})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["flags"]["is_distorted"] is True
        assert r.json()["data"]["ui"]["z"] == "96"

        # 404 на отсутствующий документ
        r = client.post("/v1/project/load", json={"path": str(Path(root) / "нет.json")})
        assert r.status_code == 404, r.status_code

        assert client.get("/health").json()["service"] == "state"
    print("      OK: tools roundtrip, документ проекта, 404, корень через env")


# ============================================================
# 2. ServiceClient ↔ живой state; FileNotFoundError на живом сервисе
# ============================================================

def test_state_client_live():
    print("[2] ServiceClient ↔ живой state: roundtrip + FileNotFoundError...")
    import services.state as state_mod

    root = tempfile.mkdtemp(prefix="cutter_state_live_")
    port = free_port()
    with EnvSaver(CUTTER_STATE_ROOT=root):
        server, t = start_server(state_mod.app, port)
        try:
            sc = ServiceClient(
                ingest_url="", render_url="", geometry_url="", math_url="", cam_url="",
                state_url=f"http://127.0.0.1:{port}",
            )

            # tools через HTTP
            tool = Tool(name="HTTP-фреза", tip_diameter=0.05)
            sc.save_tools([tool])
            loaded = sc.load_tools()
            assert len(loaded) == 1 and loaded[0].name == "HTTP-фреза" and loaded[0].id == tool.id

            # документ проекта через HTTP
            doc = Path(root) / "proj" / "project_state.json"
            sc.save_project_doc(doc, {"layers": {"raw": []}})
            data = sc.load_project_doc(doc)
            assert data["layers"]["raw"] == []

            # сервис жив, файла нет → FileNotFoundError (не молчаливый fallback)
            try:
                sc.load_project_doc(Path(root) / "missing.json")
                raise AssertionError("Ожидался FileNotFoundError")
            except FileNotFoundError:
                pass
        finally:
            stop_server(server, t)
    print("      OK: roundtrip идентичен, 404 → FileNotFoundError")


# ============================================================
# 3. ServiceClient: state мёртв → локальный fallback
# ============================================================

def test_state_client_fallback():
    print("[3] ServiceClient: state мёртв → локальный DatabaseManager...")
    dead = f"http://127.0.0.1:{free_port()}"
    root = tempfile.mkdtemp(prefix="cutter_state_fb_")

    with EnvSaver(CUTTER_STATE_ROOT=root):
        sc = ServiceClient(state_url=dead, gateway_url="")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tool = Tool(name="Локальная-фреза")
            sc.save_tools([tool])
            loaded = sc.load_tools()
        assert "выполняю локально" in buf.getvalue()
        assert len(loaded) == 1 and loaded[0].name == "Локальная-фреза"

        # fallback-запись попала в корень
        assert (Path(root) / "data" / "tools.json").exists()

        # документ проекта: fallback локальный JSON
        doc = Path(root) / "p.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sc.save_project_doc(doc, {"a": 1})
            data = sc.load_project_doc(doc)
        assert data == {"a": 1}
        assert buf.getvalue().count("выполняю локально") >= 2

        # локальный fallback отсутствующего файла → FileNotFoundError
        try:
            sc.load_project_doc(Path(root) / "nope.json")
            raise AssertionError("Ожидался FileNotFoundError")
        except FileNotFoundError:
            pass
    print("      OK: оба fallback'а идентичны локальному поведению")


# ============================================================
# 4. gateway: прокси на живой бэкенд + агрегированный health
# ============================================================

def test_gateway_proxy():
    print("[4] gateway: прокси на живой geometry, агрегированный /health...")
    import services.gateway as gw_mod
    import services.geometry as geo_mod

    geo_port = free_port()
    gw_port = free_port()
    dead = f"http://127.0.0.1:{free_port()}"
    # Изоляция: геометрия живёт на geo_port, ВСЕ остальные бэкенды мертвы —
    # иначе запущенный рядом run_all сделает ok=true и оборвёт проверку.
    env = {
        "CUTTER_GEOMETRY_URL": f"http://127.0.0.1:{geo_port}",
        "CUTTER_INGEST_URL": dead,
        "CUTTER_RENDER_URL": dead,
        "CUTTER_MATH_URL": dead,
        "CUTTER_CAM_URL": dead,
        "CUTTER_STATE_URL": dead,
    }
    with EnvSaver(**env):
        geo_server, geo_t = start_server(geo_mod.app, geo_port)
        gw_server, gw_t = start_server(gw_mod.app, gw_port)
        try:
            # агрегированный health: geometry жив (true), остальные мертвы (false)
            r = httpx.get(f"http://127.0.0.1:{gw_port}/health", timeout=5)
            hb = r.json()
            assert hb["service"] == "gateway"
            assert hb["backends"]["geometry"] is True
            assert hb["ok"] is False, "ok не может быть true при мёртвых бэкендах"

            # прокси compute-задачи через gateway
            payload = {
                "paths": [p.to_dto().model_dump() for p in crossing_lines()],
                "min_loop_area": 0.0,
            }
            r = httpx.post(f"http://127.0.0.1:{gw_port}/geometry/v1/check-errors", json=payload, timeout=10)
            assert r.status_code == 200, r.text
            job_id = r.json()["job_id"]
            for _ in range(100):
                j = httpx.get(f"http://127.0.0.1:{gw_port}/geometry/v1/jobs/{job_id}", timeout=5).json()
                if j["status"] in ("done", "error"):
                    break
                time.sleep(0.1)
            assert j["status"] == "done", j
            assert j["result"]["intersections"] == 1, j["result"]

            # неизвестный сервис → 404
            r = httpx.get(f"http://127.0.0.1:{gw_port}/unknown/v1/x", timeout=5)
            assert r.status_code == 404

            # мёртвый бэкенд → 503 (триггер fallback у клиента)
            r = httpx.post(f"http://127.0.0.1:{gw_port}/cam/v1/gcode", json={}, timeout=5)
            assert r.status_code == 503, r.status_code
        finally:
            stop_server(gw_server, gw_t)
            stop_server(geo_server, geo_t)
    print("      OK: health-агрегация, прокси-задача, 404, 503")


# ============================================================
# 5. ServiceClient в gateway-режиме: все операции через один URL
# ============================================================

def test_client_gateway_mode():
    print("[5] ServiceClient (CUTTER_GATEWAY_URL): compute и state через gateway...")
    import services.gateway as gw_mod
    import services.geometry as geo_mod
    import services.state as state_mod

    root = tempfile.mkdtemp(prefix="cutter_gw_")
    geo_port = free_port()
    state_port = free_port()
    gw_port = free_port()
    env = {
        "CUTTER_GEOMETRY_URL": f"http://127.0.0.1:{geo_port}",
        "CUTTER_STATE_URL": f"http://127.0.0.1:{state_port}",
        "CUTTER_STATE_ROOT": root,
        "CUTTER_GATEWAY_URL": f"http://127.0.0.1:{gw_port}",
    }
    with EnvSaver(**env):
        geo_server, geo_t = start_server(geo_mod.app, geo_port)
        state_server, state_t = start_server(state_mod.app, state_port)
        gw_server, gw_t = start_server(gw_mod.app, gw_port)
        try:
            sc = ServiceClient(job_timeout=60)

            # health подтверждает gateway-конфигурацию
            assert sc.gateway_url == f"http://127.0.0.1:{gw_port}"

            # compute через gateway (пути: gateway/geometry/v1/...)
            local_stats = sc.check_errors(crossing_lines(), 0.0)
            assert local_stats["intersections"] == 1, local_stats

            # state через gateway
            sc.save_tools([Tool(name="Через-gateway")])
            loaded = sc.load_tools()
            assert len(loaded) == 1 and loaded[0].name == "Через-gateway"
        finally:
            stop_server(gw_server, gw_t)
            stop_server(state_server, state_t)
            stop_server(geo_server, geo_t)

    # gateway мёртв → даже при заданном URL всё падает в локальный fallback
    with EnvSaver(CUTTER_GATEWAY_URL=f"http://127.0.0.1:{free_port()}", CUTTER_STATE_ROOT=root):
        sc = ServiceClient()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stats = sc.check_errors(crossing_lines(), 0.0)
            sc.save_tools([Tool(name="После- gateway-сбоя")])
        assert buf.getvalue().count("выполняю локально") >= 2, buf.getvalue()
        assert stats["intersections"] == 1
    print("      OK: единый URL для compute+state, gateway мёртв → fallback")


# ============================================================
# 6. run_all: супервизор поднимает все 7 сервисов
# ============================================================

def _port_busy(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


def test_run_all():
    print("[6] run_all: все 7 сервисов, агрегированный health=true...")
    import services.run_all as run_mod

    # Порты уже заняты (например, работает desktop-супервизор) →
    # не пытаемся поднять второй экземпляр, а проверяем существующий стек.
    already_running = _port_busy(8765) or _port_busy(8771)
    started = []
    if not already_running:
        started = run_mod.start_all()
        run_mod.wait_ready(started, timeout=20)
    try:
        assert len(started) == 7 or already_running

        # health каждого сервиса напрямую
        for port, name in [(8765, "ingest"), (8766, "render"), (8767, "geometry"),
                           (8768, "math"), (8769, "cam"), (8770, "state"), (8771, "gateway")]:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3)
            body = r.json()
            assert body.get("ok") is True, f"{name}: {body}"

        # gateway видит ВСЕ бэкенды живыми
        r = httpx.get("http://127.0.0.1:8771/health", timeout=5)
        hb = r.json()
        assert hb["ok"] is True, hb
        assert all(hb["backends"].values()), hb

        # сквозной вызов: ServiceClient через прямые URL (дефолт) к живым сервисам
        sc = ServiceClient(job_timeout=60)
        stats = sc.check_errors(crossing_lines(), 0.0)
        assert stats["intersections"] == 1
    finally:
        if started:
            run_mod.stop_all(started)

            # дожидаемся освобождения портов
            for _ in range(60):
                try:
                    socket.create_connection(("127.0.0.1", 8771), timeout=0.2).close()
                    time.sleep(0.1)
                except OSError:
                    break
    note = " (порты были заняты — проверен существующий стек)" if already_running else ""
    print(f"      OK: 7 сервисов, gateway ok=true, сквозной вызов работает{note}")


# ============================================================
# 7. GUI smoke
# ============================================================

def test_gui_smoke():
    print("[7] GUI smoke: CamApp + менеджеры через services...")
    import tkinter as tk
    from src.gui.app import CamApp
    from src.gui.tool_manager import ToolManagerWindow
    from src.gui.postprocessor_manager import PostprocessorManagerWindow

    root = tk.Tk()
    root.withdraw()
    app = CamApp(root)
    for name in ("load_tools", "save_tools", "load_postprocessors", "save_postprocessors",
                 "save_project_doc", "load_project_doc", "import_tools", "export_tools"):
        assert callable(getattr(app.services, name)), name

    # окна менеджеров принимают services и читают через него
    tw = ToolManagerWindow(root, app.services)
    assert tw.services is app.services
    tw.destroy()
    pw = PostprocessorManagerWindow(root, app.services)
    assert pw.services is app.services
    pw.destroy()

    root.destroy()
    print("      OK: GUI и оба менеджера работают через ServiceClient")


def main():
    test_state_http()
    test_state_client_live()
    test_state_client_fallback()
    test_gateway_proxy()
    test_client_gateway_mode()
    test_run_all()
    test_gui_smoke()
    print("\nФаза 4: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
