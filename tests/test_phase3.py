import contextlib
import io
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import uvicorn
from fastapi.testclient import TestClient
from shapely.geometry import box

from contracts import PathsResultDTO
from src.core.service_client import ServiceClient
from src.db.models import PostProcessor, Tool
from src.parser.geometry import CamPath
from src.pipeline.cam_pipeline import CamPipeline


# ============================================================
# вспомогательные
# ============================================================

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(app, port: int):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn не стартовал"
    return server, t


def stop_server(server, t):
    server.should_exit = True
    t.join(timeout=5)


def poll(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/v1/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} завис")


def assert_paths_eq(a: list[CamPath], b: list[CamPath], label: str = ""):
    assert len(a) == len(b), f"{label}: {len(a)} != {len(b)} контуров"
    for i, (pa, pb) in enumerate(zip(a, b)):
        assert pa.is_closed == pb.is_closed, f"{label}[{i}]: is_closed"
        assert pa.layer_name == pb.layer_name, f"{label}[{i}]: layer {pa.layer_name} != {pb.layer_name}"
        assert len(pa.points) == len(pb.points), f"{label}[{i}]: {len(pa.points)} != {len(pb.points)} точек"
        for j, (qa, qb) in enumerate(zip(pa.points, pb.points)):
            assert len(qa) == len(qb), f"{label}[{i}][{j}]: размерность"
            for va, vb in zip(qa, qb):
                assert abs(va - vb) < 1e-9, f"{label}[{i}][{j}]: {va} != {vb}"


def square(size: float = 10.0, ox: float = 0.0, oy: float = 0.0, layer: str = "CUT") -> CamPath:
    p = CamPath(layer_name=layer, is_closed=True)
    for pt in [(ox, oy), (ox + size, oy), (ox + size, oy + size), (ox, oy + size), (ox, oy)]:
        p.add_point(*pt)
    return p


# фикстуры
def grid_2x2() -> list[CamPath]:
    """Сетка 2×2 из квадратов 10×10 с шагом 20."""
    return [square(10.0, x, y) for y in (0.0, 20.0) for x in (0.0, 20.0)]


def gap_square() -> list[CamPath]:
    """Квадрат с микроразрывом 0.005 мм (как в test_healer)."""
    a = CamPath(layer_name="CUT")
    a.add_point(0, 0); a.add_point(0, 10); a.add_point(10, 10)
    b = CamPath(layer_name="CUT")
    b.add_point(10, 9.995); b.add_point(10, 0); b.add_point(0, 0)
    return [a, b]


def crossing_lines() -> list[CamPath]:
    a = CamPath(layer_name="CUT"); a.add_point(0, 0); a.add_point(10, 10)
    b = CamPath(layer_name="CUT"); b.add_point(0, 10); b.add_point(10, 0)
    return [a, b]


def norm_stats(stats: dict) -> dict:
    """Нормализация: DTO приводит int к float, порядок узлов не гарантирован."""
    out = {}
    for k, v in stats.items():
        if isinstance(v, list):
            out[k] = sorted(str(tuple(float(c) for c in pt)) for pt in v)
        else:
            out[k] = v
    return out


# ============================================================
# 1. geometry через TestClient
# ============================================================

def test_geometry_http():
    print("[1] geometry (TestClient): check-errors + heal...")
    import services.geometry as geo_mod

    client = TestClient(geo_mod.app)

    r = client.post("/v1/check-errors", json={
        "paths": [p.to_dto().model_dump() for p in crossing_lines()],
        "min_loop_area": 0.0,
    })
    assert r.status_code == 200, r.text
    data = poll(client, r.json()["job_id"])
    assert data["status"] == "done", data
    stats = data["result"]
    assert stats["intersections"] == 1, f"ожидалось 1 пересечение, got {stats['intersections']}"
    assert stats["open_paths"] == 2, stats["open_paths"]

    r = client.post("/v1/heal", json={
        "paths": [p.to_dto().model_dump() for p in gap_square()],
        "tolerance": 0.01,
        "min_loop_area": 0.0,
    })
    data = poll(client, r.json()["job_id"])
    assert data["status"] == "done", data
    healed = PathsResultDTO.model_validate(data["result"]).paths
    healed = [CamPath.from_dto(p) for p in healed]
    assert healed, "лечение не вернуло контуров"
    assert any(p.is_closed for p in healed), "разрыв не сомкнулся в замкнутый контур"
    print(f"      OK: пересечение найдено, лечение -> {len(healed)} контуров (замкнутых {sum(p.is_closed for p in healed)})")


# ============================================================
# 2. math через TestClient
# ============================================================

def test_math_http():
    print("[2] math (TestClient): pattern/multiply/distortion/rotate/crop-marks...")
    import services.math as math_mod

    client = TestClient(math_mod.app)

    def run(path: str, payload: dict) -> dict:
        r = client.post(path, json=payload)
        assert r.status_code == 200, f"{path}: {r.text}"
        data = poll(client, r.json()["job_id"])
        assert data["status"] == "done", f"{path}: {data}"
        return data["result"]

    grid = grid_2x2()
    pat = run("/v1/pattern", {"paths": [p.to_dto().model_dump() for p in grid], "tolerance": 0.5})
    assert pat["is_array"] and pat["count"] == 4 and pat["rows"] == 2 and pat["cols"] == 2, pat

    mult = run("/v1/multiply", {
        "paths": [p.to_dto().model_dump() for p in [square()]],
        "offsets": [(0.0, 0.0), (30.0, 0.0)],
    })
    assert len(mult["paths"]) == 2, mult

    dist = run("/v1/distortion", {
        "paths": [p.to_dto().model_dump() for p in [square(10.0)]],
        "factor": 0.5, "axis": "Y",
    })
    ys = [pt[1] for p in dist["paths"] for pt in p["points"]]
    assert abs(min(ys) - 2.5) < 1e-6 and abs(max(ys) - 7.5) < 1e-6, f"дисторсия: y={min(ys)}..{max(ys)}"

    rot = run("/v1/rotate", {
        "paths": [p.to_dto().model_dump() for p in [square(20.0, 0.0, 0.0)]],  # 20x10
        "angle_deg": 90.0,
    })
    # после поворота 20x10 -> 10x20
    rect = CamPath(layer_name="x", is_closed=True)
    for pt in [(0, 0), (20, 0), (20, 10), (0, 10)]:
        rect.add_point(*pt)
    rot2 = run("/v1/rotate", {"paths": [rect.to_dto().model_dump()], "angle_deg": 90.0})
    xs = [pt[0] for p in rot2["paths"] for pt in p["points"]]
    ys2 = [pt[1] for p in rot2["paths"] for pt in p["points"]]
    assert abs((max(xs) - min(xs)) - 10.0) < 1e-6, f"ширина после поворота: {max(xs)-min(xs)}"
    assert abs((max(ys2) - min(ys2)) - 20.0) < 1e-6, f"высота после поворота: {max(ys2)-min(ys2)}"

    marks = run("/v1/crop-marks", {
        "paths": [p.to_dto().model_dump() for p in [square(10.0)]],
        "rapport": 50.0, "width": 100.0, "axis": "Y",
    })
    layers = [p["layer_name"] for p in marks["paths"]]
    assert layers.count("CROP_MARKS") == 4, layers
    print("      OK: сетка 2x2, размножение, дисторсия 0.5, поворот 90°, 4 метки")


# ============================================================
# 3. cam через TestClient
# ============================================================

def test_cam_http():
    print("[3] cam (TestClient): генерация G-кода...")
    import services.cam as cam_mod

    client = TestClient(cam_mod.app)
    out = Path("/tmp/cutter_phase3_test.nc")
    out.unlink(missing_ok=True)

    r = client.post("/v1/gcode", json={
        "mask_geom_wkt": box(0, 0, 20, 20).wkt,
        "output_path": str(out),
        "tool": Tool().to_dto().model_dump(),
        "post": PostProcessor().to_dto().model_dump(),
        "mask_offset": 0.5,
        "enable_sharpening": False,
        "lead_radius": 1.5,
        "milling_dir": "Climb",
    })
    assert r.status_code == 200, r.text
    data = poll(client, r.json()["job_id"])
    assert data["status"] == "done", data
    assert out.exists() and "G1" in out.read_text(encoding="utf-8")
    assert data["result"]["time_min"] > 0
    assert data["result"]["cnc_paths"], "нет контуров ЧПУ"
    print(f"      OK: {out.name} записан, время {data['result']['time_min']:.3f} мин, контуров ЧПУ {len(data['result']['cnc_paths'])}")


# ============================================================
# 4. ServiceClient: fallback (все сервисы недоступны)
# ============================================================

def test_client_fallback():
    print("[4] ServiceClient: все URL мертвы → локальные результаты идентичны...")
    dead = f"http://127.0.0.1:{free_port()}"
    sc = ServiceClient(
        ingest_url="", render_url="", geometry_url=dead, math_url=dead, cam_url=dead
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # geometry
        s1 = sc.check_errors(crossing_lines(), 0.0)
        s2 = CamPipeline().step2_check_errors(crossing_lines())
        assert norm_stats(s1) == norm_stats(s2), f"check_errors: {norm_stats(s1)} != {norm_stats(s2)}"

        h1 = sc.heal(gap_square(), 0.01, 0.0)
        h2 = CamPipeline(tolerance=0.01).step3_heal_and_optimize(gap_square())
        assert_paths_eq(h1, h2, "heal-fallback")

        # math
        p1 = sc.analyze_pattern(grid_2x2())
        from src.optimizer.pattern_recognition import PatternRecognizer
        p2 = PatternRecognizer(tolerance=0.5).analyze(grid_2x2())
        assert p1["is_array"] == p2["is_array"] and p1["count"] == p2["count"]
        assert_paths_eq(p1["master_paths"], p2["master_paths"], "pattern-fallback")

        m1 = sc.multiply_paths([square()], [(0.0, 0.0), (30.0, 0.0)])
        m2 = CamPipeline().multiply_paths([square()], [(0.0, 0.0), (30.0, 0.0)])
        assert_paths_eq(m1, m2, "multiply-fallback")

        d1 = sc.apply_distortion([square()], 0.5, "Y")
        d2 = CamPipeline().apply_distortion([square()], 0.5, "Y")
        assert_paths_eq(d1, d2, "distortion-fallback")

        r1 = sc.rotate_geometry([square(20.0)], 90.0)
        r2 = CamPipeline().rotate_geometry([square(20.0)], 90.0)
        assert_paths_eq(r1, r2, "rotate-fallback")

        c1 = sc.add_crop_marks([square()], 50.0, 100.0, "Y")
        c2 = CamPipeline().add_crop_marks([square()], 50.0, 100.0, "Y")
        assert_paths_eq(c1, c2, "crop-fallback")

        # cam
        out1, out2 = Path("/tmp/cutter_fb1.nc"), Path("/tmp/cutter_fb2.nc")
        g1 = sc.generate_gcode(box(0, 0, 20, 20), out1, Tool(), PostProcessor(), 0.5, False)
        g2 = CamPipeline().generate_gcode(box(0, 0, 20, 20), out2, Tool(), PostProcessor(), 0.5, False)

    assert_paths_eq(g1[0], g2[0], "gcode-ideal-fallback")
    assert_paths_eq(g1[1], g2[1], "gcode-cnc-fallback")
    assert abs(g1[2] - g2[2]) < 1e-9, f"time {g1[2]} != {g2[2]}"
    assert out1.read_text() == out2.read_text(), "G-код fallback != локальный"

    log = buf.getvalue()
    assert log.count("выполняю локально") >= 8, f"сообщений о fallback: {log.count('выполняю локально')}"
    print(f"      OK: 8 операций упали в fallback ({log.count('выполняю локально')} сообщений), результаты идентичны")


# ============================================================
# 5. ServiceClient ↔ живые geometry/math/cam
# ============================================================

def test_client_live():
    print("[5] ServiceClient ↔ живые geometry/math/cam: HTTP == локальный результат...")
    import services.geometry as geo_mod
    import services.math as math_mod
    import services.cam as cam_mod

    pg, pm, pc = free_port(), free_port(), free_port()
    servers = [
        start_server(geo_mod.app, pg),
        start_server(math_mod.app, pm),
        start_server(cam_mod.app, pc),
    ]
    try:
        sc = ServiceClient(
            ingest_url="", render_url="",
            geometry_url=f"http://127.0.0.1:{pg}",
            math_url=f"http://127.0.0.1:{pm}",
            cam_url=f"http://127.0.0.1:{pc}",
            job_timeout=60.0,
        )

        # geometry
        s1 = sc.check_errors(crossing_lines(), 0.0)
        s2 = CamPipeline().step2_check_errors(crossing_lines())
        assert norm_stats(s1) == norm_stats(s2), f"check_errors: {norm_stats(s1)} != {norm_stats(s2)}"

        h1 = sc.heal(gap_square(), 0.01, 0.0)
        h2 = CamPipeline(tolerance=0.01).step3_heal_and_optimize(gap_square())
        assert_paths_eq(h1, h2, "heal-live")

        # math
        p1 = sc.analyze_pattern(grid_2x2())
        from src.optimizer.pattern_recognition import PatternRecognizer
        p2 = PatternRecognizer(tolerance=0.5).analyze(grid_2x2())
        assert p1["is_array"] and p1["count"] == p2["count"] and p1["rows"] == p2["rows"]
        assert_paths_eq(p1["master_paths"], p2["master_paths"], "pattern-live")
        assert len(p1["offsets"]) == len(p2["offsets"])

        m1 = sc.multiply_paths([square()], [(0.0, 0.0), (30.0, 15.0)])
        m2 = CamPipeline().multiply_paths([square()], [(0.0, 0.0), (30.0, 15.0)])
        assert_paths_eq(m1, m2, "multiply-live")

        d1 = sc.apply_distortion([square()], 0.5, "Y")
        d2 = CamPipeline().apply_distortion([square()], 0.5, "Y")
        assert_paths_eq(d1, d2, "distortion-live")

        r1 = sc.rotate_geometry([square(20.0)], 90.0)
        r2 = CamPipeline().rotate_geometry([square(20.0)], 90.0)
        assert_paths_eq(r1, r2, "rotate-live")

        c1 = sc.add_crop_marks([square()], 50.0, 100.0, "Y")
        c2 = CamPipeline().add_crop_marks([square()], 50.0, 100.0, "Y")
        assert_paths_eq(c1, c2, "crop-live")

        # cam
        out1, out2 = Path("/tmp/cutter_live1.nc"), Path("/tmp/cutter_live2.nc")
        g1 = sc.generate_gcode(box(0, 0, 20, 20), out1, Tool(), PostProcessor(), 0.5, False, 1.5, "Climb")
        g2 = CamPipeline().generate_gcode(box(0, 0, 20, 20), out2, Tool(), PostProcessor(), 0.5, False, 1.5, "Climb")
        assert_paths_eq(g1[0], g2[0], "gcode-ideal-live")
        assert_paths_eq(g1[1], g2[1], "gcode-cnc-live")
        assert abs(g1[2] - g2[2]) < 1e-9, f"time {g1[2]} != {g2[2]}"
        assert out1.read_text() == out2.read_text(), "G-код HTTP != локальный"
    finally:
        for server, t in servers:
            stop_server(server, t)
    print("      OK: 8 операций через HTTP идентичны локальным (включая байты G-кода)")


# ============================================================
# 6. cam: ошибка задачи НЕ маскируется fallback'ом
# ============================================================

def test_cam_error_not_masked():
    print("[6] cam: пустая маска → RuntimeError, без тихого fallback...")
    import services.cam as cam_mod

    port = free_port()
    server, t = start_server(cam_mod.app, port)
    try:
        sc = ServiceClient(
            ingest_url="", render_url="", geometry_url="", math_url="",
            cam_url=f"http://127.0.0.1:{port}", job_timeout=30.0,
        )
        from shapely.geometry import Polygon
        try:
            sc.generate_gcode(Polygon(), "/tmp/cutter_never.nc", Tool(), PostProcessor(), 0.5, False)
            raise AssertionError("Пустая маска должна дать ошибку")
        except RuntimeError as e:
            assert "вернул ошибку" in str(e) and "пуста" in str(e), e
    finally:
        stop_server(server, t)
    print("      OK: ValueError донесён как RuntimeError")


# ============================================================
# 7. GUI smoke
# ============================================================

def test_gui_smoke():
    print("[7] GUI smoke: CamApp со всеми 5 URL...")
    import tkinter as tk
    from src.gui.app import CamApp

    root = tk.Tk()
    root.withdraw()
    app = CamApp(root)
    for name in ("parse", "generate_uv_mask_pdf", "generate_report", "check_errors",
                 "heal", "analyze_pattern", "multiply_paths", "apply_distortion",
                 "rotate_geometry", "add_crop_marks", "generate_gcode"):
        assert callable(getattr(app.services, name)), name
    assert app.services.cam_url.endswith("8769")
    root.destroy()
    print("      OK: все 11 методов сервисного клиента на месте")


def main():
    test_geometry_http()
    test_math_http()
    test_cam_http()
    test_client_fallback()
    test_client_live()
    test_cam_error_not_masked()
    test_gui_smoke()
    print("\nФаза 3: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
