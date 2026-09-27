import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.getcwd())

from pydantic import ValidationError

from contracts import CamPathDTO, PostProcessorDTO, ToolDTO
from src.parser.geometry import CamPath
from src.db.models import PostProcessor, Tool


def test_cam_path_roundtrip():
    print("[1] CamPath: roundtrip to_dict/from_dict (2D и 3D точки)...")
    p = CamPath(layer_name="HEALED_POLY", is_closed=True)
    p.add_point(0.0, 0.0)
    p.add_point(10.5, 0.0)
    p.add_point(10.5, 20.25, -0.5)  # точка с Z (V-Carve)

    d = p.to_dict()
    assert set(d.keys()) == {"points", "is_closed", "layer_name"}, f"Формат ключей изменился: {d.keys()}"

    # JSON-цикл, как в save/load проекта
    loaded = CamPath.from_dict(json.loads(json.dumps(d, ensure_ascii=False)))

    assert loaded.is_closed == p.is_closed
    assert loaded.layer_name == p.layer_name
    assert loaded.points == p.points, f"{loaded.points} != {p.points}"
    assert all(isinstance(pt, tuple) for pt in loaded.points), "Координаты после загрузки должны быть кортежами"
    print("      OK: ключи прежние, координаты кортежи, Z сохранён")


def test_cam_path_legacy_format():
    print("[2] CamPath: старый формат JSON (int-координаты, лишние ключи)...")
    legacy = {
        "points": [[0, 0], [10, 0], [10, 10]],  # списки, int — как писал старый код
        "is_closed": True,
        "layer_name": "CUT",
        "some_future_field": {"nested": 1},     # лишний ключ не должен ронять загрузку
    }
    p = CamPath.from_dict(legacy)
    assert p.points == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert p.is_closed and p.layer_name == "CUT"
    print("      OK: int приведён к float, лишний ключ игнорирован")


def test_cam_path_rejects_garbage():
    print("[3] CamPath: битые данные отклоняются...")
    for bad, why in [
        ({"points": [[1, 2, 3, 4]]}, "4-мерная точка"),
        ({"points": [["a", "b"]]}, "строки вместо чисел"),
        ({"points": [[1]]}, "одномерная точка"),
    ]:
        try:
            CamPathDTO.model_validate(bad)
            raise AssertionError(f"Должен был упасть: {why}")
        except ValidationError:
            pass
    print("      OK: ValidationError на мусоре (старый код молча брал как есть)")


def test_tool_roundtrip():
    print("[4] Tool: roundtrip + неизвестный ключ...")
    t = Tool(name="V60 0.1", angle_deg=60.0, feedrate=1200, spindle_speed=10000)
    loaded = Tool.from_dict(json.loads(json.dumps(t.to_dict())))
    assert loaded.to_dict() == t.to_dict()
    assert loaded.id == t.id

    with_extra = {**t.to_dict(), "legacy_junk": 42}
    assert Tool.from_dict(with_extra).name == t.name
    print("      OK: id сохраняется, legacy_junk игнорируется")


def test_postprocessor_roundtrip():
    print("[5] PostProcessor: roundtrip многострочных шаблонов...")
    pp = PostProcessor(name="GRBL", extension=".nc", header=";H\nG21", footer=";F\nM30", safe_z=7.5)
    loaded = PostProcessor.from_dict(json.loads(json.dumps(pp.to_dict(), ensure_ascii=False)))
    assert loaded.to_dict() == pp.to_dict()
    assert "\n" in loaded.header
    print("      OK: переводы строк в шаблонах не потеряны")


def test_legacy_project_file():
    print("[6] Совместимость: загрузка project_state.json в СТАРОМ формате...")
    # Воспроизводит то, что писал старый код: списки вместо кортежей,
    # int-координаты, отсутствующие поля с дефолтами
    legacy = {
        "input_filepath": None,
        "last_milling_time_min": 12.5,
        "ui": {"tolerance": "2.0", "z": "96"},
        "flags": {"is_array_layout": True, "array_offsets": [[0, 0], [15.5, 0]],
                  "is_distorted": False, "applied_dist_axis": ""},
        "paths": {
            "raw_paths": [
                {"points": [[0, 0], [20, 0], [20, 10], [0, 10]], "is_closed": True, "layer_name": "CUT"},
                {"points": [[5, 5, -0.4], [8, 5, -0.4]], "is_closed": False, "layer_name": "VCARVE"},
            ],
            "ready_paths": [{"points": [[1, 1], [2, 1]], "is_closed": True, "layer_name": "HEALED_POLY"}],
            "distorted_paths": [],
            "master_raw_paths": [{"points": [[0, 0], [1, 0]], "is_closed": False, "layer_name": "CUT"}],
        },
        "layers": {
            "raw": [{"points": [[0, 0], [3, 0]], "is_closed": True, "layer_name": "CUT"}],
            "healed": [], "array": [], "distorted": [],
            "mask": [{"points": [[0, 0], [4, 0], [4, 4]], "is_closed": True, "layer_name": "MASK_EXTERIOR"}],
            "ideal": [], "cnc": [],
        },
        "mask_geom_wkt": "POLYGON ((0 0, 10 0, 10 10, 0 0))",
    }

    from src.core.project import ProjectState
    proj = ProjectState()
    proj.from_dict(legacy)  # не должен бросить

    assert len(proj.raw_paths) == 2
    assert proj.raw_paths[0].points == [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)]
    assert proj.raw_paths[1].points == [(5.0, 5.0, -0.4), (8.0, 5.0, -0.4)], "3D-точки должны сохранить Z"
    assert proj.is_array_layout and len(proj.array_offsets) == 2
    assert proj.last_milling_time_min == 12.5
    assert proj.mask_geom is not None and not proj.mask_geom.is_empty

    # И обратно: сохранение -> загрузка без потерь
    reloaded = ProjectState()
    reloaded.from_dict(json.loads(json.dumps(proj.to_dict({"tolerance": "2.0"}), ensure_ascii=False)))
    assert len(reloaded.raw_paths) == 2
    assert reloaded.raw_paths[0].points == proj.raw_paths[0].points
    print("      OK: старый формат читается, Z и флаги сохранены, roundtrip без потерь")


def main():
    test_cam_path_roundtrip()
    test_cam_path_legacy_format()
    test_cam_path_rejects_garbage()
    test_tool_roundtrip()
    test_postprocessor_roundtrip()
    test_legacy_project_file()
    print("\nКонтракты: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
