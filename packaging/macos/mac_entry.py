"""Точка входа macOS-приложения CUTTER MAKER (.app, PyInstaller).

Один процесс: сервисы (in-process, как services.run_all) + Tk-GUI.
Так Dock получает иконку приложения (процесс — исполняемый файл бандла).

Логика:
  * frozen → state-артефакты в ~/Library/Application Support/CUTTER MAKER;
  * порты заняты (идёт внешний run_all) → сервисы НЕ поднимаем, GUI работает
    с внешним стеком (как лаунчер при живых сервисах);
  * падение старта → ~/Library/Logs/CUTTER-MAKER.log (у windowed-сборки
    нет консоли, лог — единый канал диагностики).
"""

import os
import socket
import sys
import traceback
from pathlib import Path


def _port_busy(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


def _setup_state_root() -> None:
    if getattr(sys, "frozen", False):
        root = Path.home() / "Library" / "Application Support" / "CUTTER MAKER"
        root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("CUTTER_STATE_ROOT", str(root))


def _start_services():
    from services import run_all

    if _port_busy(8765) or _port_busy(8771):
        print("[APP] сервисы уже запущены внешне — работаю с ними")
        return []
    started = run_all.start_all()
    run_all.wait_ready(started, timeout=20)
    print(f"[APP] поднято сервисов in-process: {len(started)}")
    return started


def _run_gui() -> None:
    import tkinter as tk

    from src.gui.app import CamApp

    root = tk.Tk()
    CamApp(root)
    root.mainloop()


def main() -> int:
    _setup_state_root()
    started = []
    try:
        started = _start_services()
        _run_gui()
        return 0
    except Exception:
        log = Path.home() / "Library" / "Logs" / "CUTTER-MAKER.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("=== сбой запуска ===\n")
            traceback.print_exc(file=f)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "CUTTER MAKER — ошибка запуска",
                f"Подробности: {log}",
            )
        except Exception:
            pass
        return 1
    finally:
        if started:
            from services import run_all

            run_all.stop_all(started)


if __name__ == "__main__":
    sys.exit(main())
