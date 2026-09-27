"""Сервис gateway: единая точка входа — тонкий прокси всех бэкенд-сервисов.

Маршрутизация: ANY /{service}/{path} → {CUTTER_<SERVICE>_URL}/{path}.
/service/health и GET /health → агрегированный статус всех бэкендов.

Gateway НЕ исполняет вычислений — только проксирует (роль оркестратора
планируется в более поздней фазе: цепочки шагов через очередь).

Запуск: python -m services.gateway   (http://127.0.0.1:8771)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="CUTTER MAKER — gateway", version="1.0")

# Имя сервиса → (env URL, дефолт)
BACKENDS: dict[str, tuple[str, str]] = {
    "ingest": ("CUTTER_INGEST_URL", "http://127.0.0.1:8765"),
    "render": ("CUTTER_RENDER_URL", "http://127.0.0.1:8766"),
    "geometry": ("CUTTER_GEOMETRY_URL", "http://127.0.0.1:8767"),
    "math": ("CUTTER_MATH_URL", "http://127.0.0.1:8768"),
    "cam": ("CUTTER_CAM_URL", "http://127.0.0.1:8769"),
    "state": ("CUTTER_STATE_URL", "http://127.0.0.1:8770"),
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8771, log_level="warning")
