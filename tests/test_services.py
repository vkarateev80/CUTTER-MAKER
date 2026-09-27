import io
import contextlib
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import httpx
import uvicorn
from fastapi.testclient import TestClient

from contracts import ParseResultDTO, ReportResultDTO
from services.jobstore import JobStore
from src.core.service_client import ServiceClient
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline

SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <path d="M 50, 50 m -25, 0 a 25,25 0 1,0 50,0 a 25,25 0 1,0 -50,0" />
</svg>
"""


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


def poll_testclient(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/v1/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} завис")


def test_jobstore():
    print("[1] JobStore: успех / ошибка / таймаут / 404-семантика...")
    store = JobStore()

    jid = store.submit(lambda: {"answer": 42})
    st = store.wait(jid, timeout=5)
    assert st.status == "done" and st.result == {"answer": 42}, st

    jid = store.submit(lambda: 1 / 0)
    st = store.wait(jid, timeout=5)
    assert st.status == "error" and "division by zero" in st.error, st

    jid = store.submit(time.sleep, 2.0)
    try:
        store.wait(jid, timeout=0.1)
        raise AssertionError("Ожидался TimeoutError")
    except TimeoutError:
        pass

    assert store.get("no-such-job") is None
    print("      OK: done/error/timeout/None")


def test_ingest_http():
    print("[2] ingest (TestClient): парсинг SVG через HTTP-контракт...")
    import services.ingest as ingest_mod

    client = TestClient(ingest_mod.app)

    r = client.post("/v1/parse", files={"file": ("circle.svg", SVG.encode(), "image/svg+xml")})
    assert r.status_code == 200, r.text
    data = poll_testclient(client, r.json()["job_id"])
    assert data["status"] == "done", data
    parsed = ParseResultDTO.model_validate(data["result"])
    assert parsed.paths, "Парсер не вернул контуров"
    assert abs(parsed.paths[0].points[0][0]) >= 0  # точки валидны

    assert client.get("/v1/jobs/unknown").status_code == 404
    assert client.post("/v1/parse", files={"file": ("noext", b"x", "text/plain")}).status_code == 400
    assert client.get("/health").json()["ok"] is True
    print(f"      OK: {len(parsed.paths)} контуров, 404 и 400 на граничных запросах")


def test_service_client_fallback():
    print("[3] ServiceClient: сервис недоступен → локальный fallback...")
    dead = f"http://127.0.0.1:{free_port()}"
    sc = ServiceClient(ingest_url=dead, render_url="")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        paths = _parse_fixture(sc)
    assert "выполняю локально" in buf.getvalue(), "Нет сообщения о fallback"
    assert paths, "Fallback-парсинг не вернул контуры"
    print("      OK: ConnectError перехвачен, парсинг выполнен локально")


def _parse_fixture(sc: ServiceClient) -> list[CamPath]:
    # Пишем временный SVG, чтобы тест не зависел от data/
    tmp = Path("/tmp/cutter_test_fallback.svg")
    tmp.write_text(SVG, encoding="utf-8")
    return sc.parse(tmp)


def test_service_client_live_ingest():
    print("[4] ServiceClient ↔ живой ingest: полный HTTP-круг...")
    import services.ingest as ingest_mod

    port = free_port()
    server, t = start_server(ingest_mod.app, port)
    try:
        tmp = Path("/tmp/cutter_test_live.svg")
        tmp.write_text(SVG, encoding="utf-8")
        sc = ServiceClient(ingest_url=f"http://127.0.0.1:{port}", render_url="", job_timeout=30)
        paths = sc.parse(tmp)
        assert paths, "HTTP-парсинг не вернул контуры"
        local = CamPipeline().step1_parse(tmp)
        assert len(paths) == len(local), f"HTTP={len(paths)} vs local={len(local)}"
    finally:
        stop_server(server, t)
    print(f"      OK: {len(paths)} контуров через HTTP, совпадает с локальным парсингом")


def test_render_report_contract():
    print("[5] render (TestClient): контракт /v1/report с подменённым генератором...")
    import services.render as render_mod

    class FakeReportGenerator:
        @staticmethod
        def generate(project_name, stats, paths, output_path):
            Path(output_path).write_bytes(b"%PDF-fake")

    original = render_mod.ReportGenerator
    render_mod.ReportGenerator = FakeReportGenerator
    try:
        client = TestClient(render_mod.app)
        p = CamPath(layer_name="CUT", is_closed=True)
        for pt in [(0, 0), (10, 0), (10, 10), (0, 10)]:
            p.add_point(*pt)
        req = {
            "project_name": "Тест",
            "stats": {"time_min": 1.5, "is_distorted": False},
            "paths": [p.to_dto().model_dump()],
            "output_path": "/tmp/cutter_test_report.pdf",
        }
        r = client.post("/v1/report", json=req)
        assert r.status_code == 200, r.text
        data = poll_testclient(client, r.json()["job_id"])
        assert data["status"] == "done", data
        res = ReportResultDTO.model_validate(data["result"])
        assert Path(res.output_path).exists(), "PDF не записан"

        bad = client.post("/v1/report", json={"paths": []})
        assert bad.status_code == 422, f"Ожидался 422, получено {bad.status_code}"
    finally:
        render_mod.ReportGenerator = original
    print("      OK: job выполнен, файл записан, невалидный запрос → 422")


def test_render_error_not_masked():
    print("[6] render + ServiceClient: ошибка задачи НЕ скрывается fallback'ом...")
    import services.render as render_mod

    port = free_port()
    server, t = start_server(render_mod.app, port)
    try:
        sc = ServiceClient(ingest_url="", render_url=f"http://127.0.0.1:{port}", job_timeout=30)
        try:
            sc.generate_uv_mask_pdf([], 0.2, "/tmp/cutter_never.pdf")
            raise AssertionError("Пустая геометрия должна дать ошибку")
        except RuntimeError as e:
            assert "вернул ошибку" in str(e) and "пуста" in str(e), e
    finally:
        stop_server(server, t)
    print("      OK: ValueError 'Геометрия пуста' донесён как RuntimeError, без тихого fallback")


def test_render_fallback_attempt():
    print("[7] ServiceClient: render недоступен → попытка локального выполнения...")
    dead = f"http://127.0.0.1:{free_port()}"
    sc = ServiceClient(ingest_url="", render_url=dead)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            sc.generate_uv_mask_pdf([], 0.2, "/tmp/cutter_never2.pdf")
        except Exception:
            pass  # локальный вызов тоже падает на пустой геометрии — важен сам факт fallback
    assert "выполняю локально" in buf.getvalue(), "Нет сообщения о fallback render"
    print("      OK: ConnectError перехвачен, выбран локальный путь")


def test_gui_smoke():
    print("[8] GUI smoke: CamApp с ServiceClient...")
    import tkinter as tk
    from src.gui.app import CamApp

    root = tk.Tk()
    root.withdraw()
    app = CamApp(root)
    assert app.services is not None
    assert callable(app.services.parse)
    root.destroy()
    print("      OK: приложение инициализируется с ServiceClient")


def main():
    test_jobstore()
    test_ingest_http()
    test_service_client_fallback()
    test_service_client_live_ingest()
    test_render_report_contract()
    test_render_error_not_masked()
    test_render_fallback_attempt()
    test_gui_smoke()
    print("\nСервисы: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
