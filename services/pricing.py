"""Сервис pricing: расчёт стоимости заказа (HTTP-обёртка над src/biz/pricing).

Синхронный API (как state): тривиальный расчёт без job-store.
Тарифы — state-артефакт data/pricing.json в CUTTER_STATE_ROOT.

Запуск: python -m services.pricing   (http://127.0.0.1:8774)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException

from contracts import PriceConfigDTO, PriceRequestDTO, PriceResultDTO
from services.common import add_common_routes
from services.jobstore import JobStore
from src.biz import pricing as core

app = FastAPI(title="CUTTER MAKER — pricing", version="1.0")
store = JobStore()
add_common_routes(app, store, "pricing")


@app.post("/v1/config/load", response_model=PriceConfigDTO)
def config_load() -> PriceConfigDTO:
    return core.load_config()


@app.post("/v1/config/save", response_model=PriceConfigDTO)
def config_save(cfg: PriceConfigDTO) -> PriceConfigDTO:
    try:
        core.save_config(cfg)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Не удалось записать конфиг тарифов: {e}")
    return cfg


@app.post("/v1/price", response_model=PriceResultDTO)
def price(req: PriceRequestDTO) -> PriceResultDTO:
    return core.calc_price(req.time_min, req.area_mm2, req.config)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8774, log_level="warning")
