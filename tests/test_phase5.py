"""Тест фазы 5: server-профиль — docker-compose (7 сервисов) + веб-клиент.

Проверяет:
 1. Файлы профиля (Dockerfile, compose, .dockerignore, web/) и валидность compose.
 2. Сборка образа и `compose up --wait` (healthcheck каждого сервиса).
 3. Агрегированный /health шлюза на тестовом порту (CUTTER_GW_PORT=8772,
    чтобы не конфликтовать с локальным desktop-профилем на :8771).
 4. Статика веб-клиента: / (index.html) и /app.js.
 5. Полная цепочка через шлюз: parse → heal → uv-mask → gcode (gcode_text).

Запуск: DOCKER_HOST=unix://$HOME/.colima/default/docker.sock \
        .venv/bin/python tests/test_phase5.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GW = "http://127.0.0.1:8772"
ENV = dict(os.environ)
ENV.setdefault("DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock")
ENV["CUTTER_GW_PORT"] = "8772"


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), *args]
    return subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True,
                          text=True, check=check)


def poll(svc: str, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = httpx.get(f"{GW}/{svc}/v1/jobs/{job_id}", timeout=10)
        st = r.json()
        if st["status"] == "done":
            return st.get("result") or {}
        if st["status"] == "error":
            raise RuntimeError(st.get("error"))
        time.sleep(0.25)
    raise TimeoutError(f"job {job_id}")


def test_profile_files() -> None:
    print("[1] Файлы server-профиля...")
    for name in ("Dockerfile", "docker-compose.yml", ".dockerignore",
                 "web/index.html", "web/app.js", "web/app.css"):
        assert (ROOT / name).exists(), f"нет файла {name}"
    compose("config", "--quiet")
    print("      OK: все файлы на месте, compose валиден")


def test_build_up() -> None:
    print("[2] Сборка образа и запуск (healthchecks, ~минуты)...")
    compose("build")
    compose("up", "-d", "--wait", "--wait-timeout", "300")
    print("      OK: образ собран, все сервисы health-зелёные")


def test_gateway_health() -> None:
    print("[3] Агрегированный /health шлюза :8772...")
    deadline = time.monotonic() + 30
    last = None
    while time.monotonic() < deadline:
        try:
            last = httpx.get(f"{GW}/health", timeout=5).json()
            if last.get("ok"):
                break
        except Exception as e:  # noqa: BLE001
            last = {"error": str(e)}
        time.sleep(1)
    assert last and last.get("ok") is True, f"health: {last}"
    assert all(last["backends"].values()), f"бэкенды: {last['backends']}"
    print("      OK: ok=true, все 7 бэкендов онлайн")


def test_web_static() -> None:
    print("[4] Статика веб-клиента через шлюз...")
    r = httpx.get(f"{GW}/", timeout=5)
    assert r.status_code == 200, r.status_code
    assert "CUTTER MAKER" in r.text and "app.js" in r.text
    r2 = httpx.get(f"{GW}/app.js", timeout=5)
    assert r2.status_code == 200 and "uvMask" in r2.text
    r3 = httpx.get(f"{GW}/app.css", timeout=5)
    assert r3.status_code == 200
    print("      OK: index.html, app.js, app.css отдаются шлюзом")


def test_chain() -> None:
    print("[5] Цепочка через контейнеры: parse → heal → uv-mask → gcode...")
    with open(ROOT / "data" / "quadroring.dxf", "rb") as f:
        r = httpx.post(f"{GW}/ingest/v1/parse",
                       files={"file": ("quadroring.dxf", f)}, timeout=60)
    assert r.status_code == 200, r.text
    paths = poll("ingest", r.json()["job_id"])["paths"]
    assert len(paths) >= 1, "нет путей"
    print(f"      parse: {len(paths)} контуров")

    r = httpx.post(f"{GW}/geometry/v1/heal",
                   json={"paths": paths, "tolerance": 2.0, "min_loop_area": 1.0},
                   timeout=30)
    healed = poll("geometry", r.json()["job_id"])["paths"]
    assert healed, "лечение вернуло пустоту"

    r = httpx.post(f"{GW}/render/v1/uv-mask",
                   json={"paths": healed, "offset": 0.2,
                         "output_path": "/tmp/t5_mask.pdf", "badge_text": "T5"},
                   timeout=30)
    mask = poll("render", r.json()["job_id"])
    assert mask["mask_geom_wkt"], "пустой WKT маски"
    print(f"      mask: wkt={len(mask['mask_geom_wkt'])} симв.")

    tools = httpx.post(f"{GW}/state/v1/tools/load", json={}, timeout=10).json()["tools"]
    posts = httpx.post(f"{GW}/state/v1/posts/load", json={}, timeout=10).json()["posts"]
    assert tools and posts, "БД не засеяна в контейнере"

    r = httpx.post(f"{GW}/cam/v1/gcode", json={
        "mask_geom_wkt": mask["mask_geom_wkt"], "output_path": "/tmp/t5.nc",
        "tool": tools[0], "post": posts[0], "mask_offset": 0.2,
        "enable_sharpening": True, "lead_radius": 1.5,
        "milling_dir": "Climb (Попутное)",
    }, timeout=30)
    g = poll("cam", r.json()["job_id"])
    assert len(g["gcode_text"]) > 500, "gcode_text пустой/мелкий"
    assert g["time_min"] > 0
    print(f"      gcode: {len(g['gcode_text'])} симв., {g['time_min']:.2f} мин")


def test_pipeline_orchestrator() -> None:
    print("[6] Оркестратор /v1/pipeline: одна задача макет → G-код...")
    with open(ROOT / "data" / "quadroring.dxf", "rb") as f:
        r = httpx.post(f"{GW}/v1/pipeline",
                       files={"file": ("quadroring.dxf", f)},
                       data={"badge_text": "T5", "tolerance": "2.0",
                             "min_loop_area": "1.0", "offset": "0.2"},
                       timeout=60)
    assert r.status_code == 200, r.text
    res = poll_root(r.json()["job_id"], timeout=300)
    assert res.get("source_paths"), "нет исходных контуров"
    assert res.get("healed_paths"), "нет вылеченных контуров"
    assert res.get("mask_geom_wkt"), "нет маски"
    assert res.get("gcode_text") and len(res["gcode_text"]) > 500, "нет G-кода"
    assert res.get("check_stats") is not None, "нет статистики анализа"
    assert res.get("time_min", 0) > 0
    print(f"      OK: {len(res['source_paths'])}→{len(res['healed_paths'])} контуров, "
          f"gcode {len(res['gcode_text'])} симв., {res['time_min']:.2f} мин")


def poll_root(job_id: str, timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = httpx.get(f"{GW}/v1/jobs/{job_id}", timeout=10)
        st = r.json()
        if st["status"] == "done":
            return st.get("result") or {}
        if st["status"] == "error":
            raise RuntimeError(st.get("error"))
        time.sleep(0.4)
    raise TimeoutError(f"orch job {job_id}")


def main() -> None:
    print("=" * 60)
    print("ФАЗА 5 — server-профиль (docker-compose + веб-клиент)")
    print("=" * 60)
    test_profile_files()
    try:
        test_build_up()
        test_gateway_health()
        test_web_static()
        test_chain()
        test_pipeline_orchestrator()
    finally:
        print("[·] compose down (volume сохраняется)...")
        compose("down", check=False)
    print("Фаза 5: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"ПРОВАЛ: команда {e.cmd}\n{e.stdout}\n{e.stderr}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"ПРОВАЛ: {type(e).__name__}: {e}")
        sys.exit(1)
