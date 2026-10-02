"""Сервис gateway: единая точка входа — тонкий прокси всех бэкенд-сервисов.

Маршрутизация: ANY /{service}/{path} → {CUTTER_<SERVICE>_URL}/{path}.
/service/health и GET /health → агрегированный статус всех бэкендов.

Gateway НЕ исполняет вычислений — только проксирует (роль оркестратора
планируется в более поздней фазе: цепочки шагов через очередь).

Запуск: python -m services.gateway   (http://127.0.0.1:8771)
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from contracts import JobRefDTO, JobStatusDTO
from services.jobstore import JobStore

app = FastAPI(title="CUTTER MAKER — gateway", version="1.0")

# Имя сервиса → (env URL, дефолт)
BACKENDS: dict[str, tuple[str, str]] = {
    "ingest": ("CUTTER_INGEST_URL", "http://127.0.0.1:8765"),
    "render": ("CUTTER_RENDER_URL", "http://127.0.0.1:8766"),
    "geometry": ("CUTTER_GEOMETRY_URL", "http://127.0.0.1:8767"),
    "math": ("CUTTER_MATH_URL", "http://127.0.0.1:8768"),
    "cam": ("CUTTER_CAM_URL", "http://127.0.0.1:8769"),
    "state": ("CUTTER_STATE_URL", "http://127.0.0.1:8770"),
    "pricing": ("CUTTER_PRICING_URL", "http://127.0.0.1:8774"),
    "eta": ("CUTTER_ETA_URL", "http://127.0.0.1:8775"),
}

_PROXY_TIMEOUT = httpx.Timeout(60.0, connect=2.0)


def _backend_url(service: str) -> str:
    env_name, default = BACKENDS[service]
    return (os.environ.get(env_name, default) or "").rstrip("/")


@app.get("/health")
def health() -> dict:
    """Агрегированный статус: ok=true только когда все бэкенды отвечают."""
    backends: dict[str, bool] = {}
    for name in BACKENDS:
        url = _backend_url(name)
        if not url:
            backends[name] = False
            continue
        try:
            r = httpx.get(f"{url}/health", timeout=httpx.Timeout(1.0, connect=0.5))
            backends[name] = r.status_code == 200 and r.json().get("ok") is True
        except Exception:
            backends[name] = False
    return {"ok": all(backends.values()), "service": "gateway", "backends": backends}


# ============================================================
# Оркестратор цепочки «макет → G-код» (фаза 5, одна задача)
# Регистрируется ДО прокси-роута: иначе /v1/... матчится как сервис «v1».
# ============================================================

_orch_store = JobStore()
_ORCH_TIMEOUT = 180.0


def _backend_job(svc: str, path: str, payload: dict, timeout: float) -> dict:
    """POST задачи на бэкенд + опрос до done/error (без fallback — оркестратору тянуть нечего)."""
    url = _backend_url(svc)
    if not url:
        raise RuntimeError(f"Сервис {svc} отключён (пустой URL)")
    r = httpx.post(f"{url}{path}", json=payload, timeout=min(timeout, 30.0))
    r.raise_for_status()
    job_id = r.json()["job_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = httpx.get(f"{url}/v1/jobs/{job_id}", timeout=15.0)
        st.raise_for_status()
        data = st.json()
        if data["status"] == "done":
            return data.get("result") or {}
        if data["status"] == "error":
            raise RuntimeError(f"{svc}{path}: {data.get('error')}")
        time.sleep(0.25)
    raise TimeoutError(f"{svc}{path}: задача {job_id} не завершилась за {timeout:.0f} с")


def _backend_sync(svc: str, path: str, payload: dict) -> dict:
    """Синхронный вызов (state-сервис — без job-store)."""
    url = _backend_url(svc)
    if not url:
        raise RuntimeError(f"Сервис {svc} отключён (пустой URL)")
    r = httpx.post(f"{url}{path}", json=payload, timeout=30.0)
    r.raise_for_status()
    return r.json()


@app.post("/v1/pipeline", response_model=JobRefDTO)
async def pipeline(
    file: UploadFile = File(...),
    tolerance: float = Form(2.0),
    min_loop_area: float = Form(1.0),
    offset: float = Form(0.2),
    badge_text: str = Form(""),
    lead_radius: float = Form(1.5),
    milling_dir: str = Form("Climb (Попутное)"),
    enable_sharpening: bool = Form(True),
) -> JobRefDTO:
    """Цепочка: parse → check → heal → uv-mask → gcode одной задачей."""
    suffix = Path(file.filename or "").suffix
    if not suffix:
        raise HTTPException(status_code=400, detail="У файла нет расширения")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
    finally:
        tmp.close()
    params = {
        "tolerance": tolerance,
        "min_loop_area": min_loop_area,
        "offset": offset,
        "badge_text": badge_text,
        "lead_radius": lead_radius,
        "milling_dir": milling_dir,
        "enable_sharpening": enable_sharpening,
    }

    def worker() -> dict:
        try:
            parsed = _parse_multipart(Path(tmp.name), file.filename or "file")
            paths = parsed["paths"]
            check = _backend_job(
                "geometry", "/v1/check-errors",
                {"paths": paths, "min_loop_area": params["min_loop_area"]},
                _ORCH_TIMEOUT,
            )
            healed = _backend_job(
                "geometry", "/v1/heal",
                {"paths": paths, "tolerance": params["tolerance"],
                 "min_loop_area": params["min_loop_area"]},
                _ORCH_TIMEOUT,
            )["paths"]
            mask = _backend_job(
                "render", "/v1/uv-mask",
                {"paths": healed, "offset": params["offset"],
                 "output_path": "/tmp/orch_mask.pdf",
                 "badge_text": params["badge_text"]},
                _ORCH_TIMEOUT,
            )
            tools = _backend_sync("state", "/v1/tools/load", {}).get("tools") or []
            posts = _backend_sync("state", "/v1/posts/load", {}).get("posts") or []
            if not tools or not posts:
                raise RuntimeError("БД инструментов/постпроцессоров пуста")
            g = _backend_job(
                "cam", "/v1/gcode",
                {"mask_geom_wkt": mask["mask_geom_wkt"],
                 "output_path": "/tmp/orch_out.nc",
                 "tool": tools[0], "post": posts[0],
                 "mask_offset": params["offset"],
                 "enable_sharpening": params["enable_sharpening"],
                 "lead_radius": params["lead_radius"],
                 "milling_dir": params["milling_dir"]},
                _ORCH_TIMEOUT,
            )
            return {
                "source_paths": paths,
                "check_stats": check,
                "healed_paths": healed,
                "visual_paths": mask.get("visual_paths") or [],
                "mask_geom_wkt": mask.get("mask_geom_wkt") or "",
                "ideal_paths": g.get("ideal_paths") or [],
                "cnc_paths": g.get("cnc_paths") or [],
                "time_min": g.get("time_min", 0.0),
                "gcode_text": g.get("gcode_text", ""),
            }
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    return JobRefDTO(job_id=_orch_store.submit(worker))


def _parse_multipart(path: Path, filename: str) -> dict:
    """parse — multipart, поэтому отдельно от _backend_job (JSON)."""
    url = _backend_url("ingest")
    if not url:
        raise RuntimeError("Сервис ingest отключён (пустой URL)")
    with open(path, "rb") as f:
        r = httpx.post(f"{url}/v1/parse", files={"file": (filename, f)},
                       timeout=30.0)
    r.raise_for_status()
    job_id = r.json()["job_id"]
    deadline = time.monotonic() + _ORCH_TIMEOUT
    while time.monotonic() < deadline:
        st = httpx.get(f"{url}/v1/jobs/{job_id}", timeout=15.0)
        st.raise_for_status()
        data = st.json()
        if data["status"] == "done":
            return data.get("result") or {}
        if data["status"] == "error":
            raise RuntimeError(f"ingest/parse: {data.get('error')}")
        time.sleep(0.25)
    raise TimeoutError(f"ingest/parse: задача {job_id} не завершилась")


@app.get("/v1/jobs/{job_id}", response_model=JobStatusDTO)
def orch_job(job_id: str) -> JobStatusDTO:
    status = _orch_store.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return status


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    if service not in BACKENDS:
        raise HTTPException(status_code=404, detail=f"Неизвестный сервис: {service}")

    url = _backend_url(service)
    if not url:
        return JSONResponse(
            status_code=503,
            content={"detail": f"Сервис {service} отключён (пустой URL)"},
        )

    target = f"{url}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type

    try:
        async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
            resp = await client.request(
                request.method, target, content=await request.body(), headers=headers
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # 503 = бэкенд недоступен → ServiceClient уводит операцию в локальный fallback
        return JSONResponse(
            status_code=503,
            content={"detail": f"Сервис {service} недоступен ({url})"},
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )


# Веб-клиент (server-профиль): статика ПОСЛЕ прокси-роута, иначе mount "/"
# перехватит /{service}/{path}. Файлы — без подкаталогов: любые /x/y уходят
# в прокси (service "x" не в BACKENDS → 404), а односегментные /app.js — сюда.
_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if _WEB_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8771, log_level="warning")
