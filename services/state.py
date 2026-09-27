"""Сервис state: БД фрез/постпроцессоров и документы проектов (project_state.json).

В отличие от compute-сервисов — СИНХРОННЫЙ API (мгновенные файловые операции,
без job-store): load/save возвращают результат сразу.

Корень БД задаётся env CUTTER_STATE_ROOT (иначе cwd — как у GUI-клиента
при запуске из корня репозитория). Пути документов проектов разрешаются
относительно cwd сервиса — desktop-профиль запускает всё из одного каталога.

Запуск: python -m services.state   (http://127.0.0.1:8770)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException

from contracts import (
    PostsPayloadDTO,
    SaveResultDTO,
    StateDocDTO,
    StatePathDTO,
    ToolsPayloadDTO,
)
from src.db.db_manager import DatabaseManager
from src.db.models import PostProcessor, Tool

app = FastAPI(title="CUTTER MAKER — state", version="1.0")


def _db() -> DatabaseManager:
    # Корень читаем на каждый запрос — тесты подменяют env, не перезапуская сервис
    return DatabaseManager(root=os.environ.get("CUTTER_STATE_ROOT") or None)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "state"}


# ============================================================
# Инструменты (фрезы)
# ============================================================

@app.post("/v1/tools/load", response_model=ToolsPayloadDTO)
def tools_load() -> ToolsPayloadDTO:
    return ToolsPayloadDTO(tools=[t.to_dto() for t in _db().load_tools()])


@app.post("/v1/tools/save", response_model=SaveResultDTO)
def tools_save(req: ToolsPayloadDTO) -> SaveResultDTO:
    tools = [Tool.from_dto(t) for t in req.tools]
    _db().save_tools(tools)
    return SaveResultDTO(count=len(tools))


# ============================================================
# Постпроцессоры
# ============================================================

@app.post("/v1/posts/load", response_model=PostsPayloadDTO)
def posts_load() -> PostsPayloadDTO:
    return PostsPayloadDTO(posts=[p.to_dto() for p in _db().load_postprocessors()])


@app.post("/v1/posts/save", response_model=SaveResultDTO)
def posts_save(req: PostsPayloadDTO) -> SaveResultDTO:
    posts = [PostProcessor.from_dto(p) for p in req.posts]
    _db().save_postprocessors(posts)
    return SaveResultDTO(count=len(posts))


# ============================================================
# Документы проектов (project_state.json)
# ============================================================

@app.post("/v1/project/save", response_model=StatePathDTO)
def project_save(req: StateDocDTO) -> StatePathDTO:
    path = Path(req.path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(req.data, f, ensure_ascii=False, indent=4)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Не удалось записать {path}: {e}")
    return StatePathDTO(path=str(path))


@app.post("/v1/project/load", response_model=StateDocDTO)
def project_load(req: StatePathDTO) -> StateDocDTO:
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Документ не найден: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Не удалось прочитать {path}: {e}")
    return StateDocDTO(path=str(path), data=data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")
