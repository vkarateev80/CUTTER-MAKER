"""Сервис pricing: расчёт стоимости заказа (машина + наладка + материал).

Синхронный API (как state): тривиальный расчёт без job-store.
Тарифы — state-артефакт data/pricing.json в CUTTER_STATE_ROOT.

Запуск: python -m services.pricing   (http://127.0.0.1:8774)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException

from contracts import PriceConfigDTO, PriceRequestDTO, PriceResultDTO
from services.common import add_common_routes
from services.jobstore import JobStore

app = FastAPI(title="CUTTER MAKER — pricing", version="1.0")
store = JobStore()
add_common_routes(app, store, "pricing")


def _config_file() -> Path:
    root = Path(os.environ.get("CUTTER_STATE_ROOT") or os.getcwd())
    return root / "data" / "pricing.json"


def _load_config() -> PriceConfigDTO:
    path = _config_file()
    if path.exists():
        try:
            return PriceConfigDTO.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — битый конфиг не должен валить сервис
            pass
    return PriceConfigDTO()


@app.post("/v1/config/load", response_model=PriceConfigDTO)
def config_load() -> PriceConfigDTO:
    return _load_config()


@app.post("/v1/config/save", response_model=PriceConfigDTO)
def config_save(cfg: PriceConfigDTO) -> PriceConfigDTO:
    path = _config_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Не удалось записать {path}: {e}")
    return cfg


@app.post("/v1/price", response_model=PriceResultDTO)
def price(req: PriceRequestDTO) -> PriceResultDTO:
    cfg = req.config or _load_config()
    hours = max(req.time_min, 0.0) / 60.0
    setup = cfg.setup_cost
    machine = hours * cfg.rate_per_hour
    material = max(req.area_mm2, 0.0) * cfg.material_per_mm2
    subtotal = setup + machine + material
    total = max(subtotal, cfg.min_price) if subtotal > 0 else 0.0
    return PriceResultDTO(
        setup=round(setup, 2),
        machine=round(machine, 2),
        material=round(material, 2),
        subtotal=round(subtotal, 2),
        total=round(total, 2),
        currency=cfg.currency,
        hours=round(hours, 3),
        time_min=round(req.time_min, 3),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8774, log_level="warning")
