"""Расчёт стоимости заказа + тарифы (state-артефакт data/pricing.json)."""

import json
import os
from pathlib import Path

from contracts import PriceConfigDTO, PriceResultDTO


def _config_file(root: str | Path | None = None) -> Path:
    base = Path(root) if root else Path(os.environ.get("CUTTER_STATE_ROOT") or os.getcwd())
    return base / "data" / "pricing.json"


def load_config(root: str | Path | None = None) -> PriceConfigDTO:
    path = _config_file(root)
    if path.exists():
        try:
            return PriceConfigDTO.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — битый конфиг → дефолты, не падение
            pass
    return PriceConfigDTO()


def save_config(cfg: PriceConfigDTO, root: str | Path | None = None) -> Path:
    path = _config_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return path


def calc_price(
    time_min: float,
    area_mm2: float = 0.0,
    cfg: PriceConfigDTO | None = None,
    root: str | Path | None = None,
) -> PriceResultDTO:
    cfg = cfg or load_config(root)
    hours = max(time_min, 0.0) / 60.0
    setup = cfg.setup_cost
    machine = hours * cfg.rate_per_hour
    material = max(area_mm2, 0.0) * cfg.material_per_mm2
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
        time_min=round(time_min, 3),
    )
