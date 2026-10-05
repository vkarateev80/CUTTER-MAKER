"""Сервис eta: очередь ЧПУ и срок изготовления (HTTP-обёртка над src/biz/eta_store).

Синхронный API. Очередь — state-артефакт data/eta_queue.json
в CUTTER_STATE_ROOT (переживает рестарты, тот же приём, что и tools.json).

Запуск: python -m services.eta   (http://127.0.0.1:8775)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException

from contracts import (
    EtaBookRequestDTO,
    EtaRequestDTO,
    EtaResultDTO,
    QueueDTO,
)
from services.common import add_common_routes
from services.jobstore import JobStore
from src.biz import eta_store as core

app = FastAPI(title="CUTTER MAKER — eta", version="1.0")
store = JobStore()
add_common_routes(app, store, "eta")


@app.get("/v1/queue", response_model=QueueDTO)
def queue_get() -> QueueDTO:
    return core.queue_snapshot(core.load_queue())


@app.post("/v1/book", response_model=QueueDTO)
def book(req: EtaBookRequestDTO) -> QueueDTO:
    try:
        return core.book(req.time_min, req.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/v1/queue/{item_id}", response_model=QueueDTO)
def queue_delete(item_id: str) -> QueueDTO:
    try:
        return core.queue_delete(item_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0] if e.args else e))


@app.post("/v1/eta", response_model=EtaResultDTO)
def eta(req: EtaRequestDTO) -> EtaResultDTO:
    return core.eta_now(req.time_min)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8775, log_level="warning")
