"""Очередь ЧПУ и срок изготовления — ядро (state-артефакт data/eta_queue.json)."""

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from contracts import EtaResultDTO, QueueDTO, QueueItemDTO

_lock = Lock()


def _queue_file(root: str | Path | None = None) -> Path:
    base = Path(root) if root else Path(os.environ.get("CUTTER_STATE_ROOT") or os.getcwd())
    return base / "data" / "eta_queue.json"


def load_queue(root: str | Path | None = None) -> list[QueueItemDTO]:
    path = _queue_file(root)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [QueueItemDTO.model_validate(x) for x in raw]
    except Exception:  # noqa: BLE001 — битый артефакт → пустая очередь
        return []


def save_queue(items: list[QueueItemDTO], root: str | Path | None = None) -> None:
    path = _queue_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def queue_snapshot(items: list[QueueItemDTO]) -> QueueDTO:
    return QueueDTO(
        items=items,
        total_minutes=round(sum(i.time_min for i in items), 3),
    )


def book(time_min: float, label: str = "", root: str | Path | None = None) -> QueueDTO:
    if time_min <= 0:
        raise ValueError("time_min должен быть > 0")
    item = QueueItemDTO(
        id=uuid.uuid4().hex[:12],
        label=label,
        time_min=round(time_min, 3),
        booked_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _lock:
        items = load_queue(root)
        items.append(item)
        save_queue(items, root)
        return queue_snapshot(items)


def queue_delete(item_id: str, root: str | Path | None = None) -> QueueDTO:
    with _lock:
        items = load_queue(root)
        rest = [i for i in items if i.id != item_id]
        if len(rest) == len(items):
            raise KeyError(f"Элемент очереди не найден: {item_id}")
        save_queue(rest, root)
        return queue_snapshot(rest)


def eta_now(time_min: float, root: str | Path | None = None) -> EtaResultDTO:
    with _lock:
        queue_minutes = sum(i.time_min for i in load_queue(root))
    machine = max(time_min, 0.0)
    ready_from_now = queue_minutes + machine
    ready_at = datetime.now() + timedelta(minutes=ready_from_now)
    return EtaResultDTO(
        queue_minutes=round(queue_minutes, 3),
        machine_minutes=round(machine, 3),
        ready_minutes_from_now=round(ready_from_now, 3),
        ready_at=ready_at.isoformat(timespec="minutes"),
    )
