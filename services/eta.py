"""Сервис eta: очередь ЧПУ и срок изготовления заказа.

Синхронный API. Очередь — state-артефакт data/eta_queue.json
в CUTTER_STATE_ROOT (переживает рестарты, тот же приём, что и tools.json).

Запуск: python -m services.eta   (http://127.0.0.1:8775)
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException

from contracts import (
    EtaBookRequestDTO,
    EtaRequestDTO,
    EtaResultDTO,
    QueueDTO,
    QueueItemDTO,
)
from services.common import add_common_routes
from services.jobstore import JobStore

app = FastAPI(title="CUTTER MAKER — eta", version="1.0")
store = JobStore()
add_common_routes(app, store, "eta")

_lock = Lock()


def _queue_file() -> Path:
    root = Path(os.environ.get("CUTTER_STATE_ROOT") or os.getcwd())
    return root / "data" / "eta_queue.json"


def _load_queue() -> list[QueueItemDTO]:
    path = _queue_file()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [QueueItemDTO.model_validate(x) for x in raw]
    except Exception:  # noqa: BLE001 — битый артефакт → пустая очередь
        return []


def _save_queue(items: list[QueueItemDTO]) -> None:
    path = _queue_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _snapshot(items: list[QueueItemDTO]) -> QueueDTO:
    return QueueDTO(
        items=items,
        total_minutes=round(sum(i.time_min for i in items), 3),
    )


@app.get("/v1/queue", response_model=QueueDTO)
def queue_get() -> QueueDTO:
    with _lock:
        return _snapshot(_load_queue())


@app.post("/v1/book", response_model=QueueDTO)
def book(req: EtaBookRequestDTO) -> QueueDTO:
    if req.time_min <= 0:
        raise HTTPException(status_code=400, detail="time_min должен быть > 0")
    item = QueueItemDTO(
        id=uuid.uuid4().hex[:12],
        label=req.label,
        time_min=round(req.time_min, 3),
        booked_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _lock:
        items = _load_queue()
        items.append(item)
        _save_queue(items)
        return _snapshot(items)


@app.delete("/v1/queue/{item_id}", response_model=QueueDTO)
def queue_delete(item_id: str) -> QueueDTO:
    with _lock:
        items = _load_queue()
        rest = [i for i in items if i.id != item_id]
        if len(rest) == len(items):
            raise HTTPException(status_code=404, detail=f"Элемент очереди не найден: {item_id}")
        _save_queue(rest)
        return _snapshot(rest)


@app.post("/v1/eta", response_model=EtaResultDTO)
def eta(req: EtaRequestDTO) -> EtaResultDTO:
    with _lock:
        queue_minutes = sum(i.time_min for i in _load_queue())
    machine = max(req.time_min, 0.0)
    ready_from_now = queue_minutes + machine
    ready_at = datetime.now() + timedelta(minutes=ready_from_now)
    return EtaResultDTO(
        queue_minutes=round(queue_minutes, 3),
        machine_minutes=round(machine, 3),
        ready_minutes_from_now=round(ready_from_now, 3),
        ready_at=ready_at.isoformat(timespec="minutes"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8775, log_level="warning")
