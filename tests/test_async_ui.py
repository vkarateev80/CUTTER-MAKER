import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

# Регрессия: на Tk 9 (macOS) прямой root.after из фонового потока молча
# теряет callback → GUI навечно уходил в "загрузку" после импорта файла.
# Лечение: очередь + поллер (CamApp.post_to_ui / _drain_ui_queue).


def test_cross_thread_after_is_broken():
    """Доказательство проблемы: прямой after из потока НЕ работает на этом Tk."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    fired = []

    def worker():
        root.after(0, lambda: fired.append("direct-after"))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=2)
    root.after(800, root.quit)
    root.mainloop()
    root.destroy()
    # На сломанном Tk пусто; на исправном — сработает. Тест не проваливается,
    # это информационная проверка окружения.
    print(f"      [info] прямой cross-thread after: {fired or 'ПОТЕРЯН (Tk 9 bug)'}")


def test_post_to_ui_fires():
    """Лечение: callback через post_to_ui ДОЛЖЕН исполниться при работающем mainloop."""
    import tkinter as tk
    from src.gui.app import CamApp

    root = tk.Tk()
    root.withdraw()
    app = CamApp(root)

    results = []

    def worker():
        # имитация _run_async: воркер завершился и хочет вызвать callback
        time.sleep(0.1)
        app.post_to_ui(results.append, "done")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # ждём: mainloop + поллер каждые 50мс должны доставить callback
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not results:
        root.update()
        time.sleep(0.02)

    assert results == ["done"], f"post_to_ui не доставил callback: {results}"
    root.destroy()
    print("      OK: post_to_ui доставляет callback из фонового потока")


def test_run_async_unlocks_ui():
    """Сквозная: _run_async воркер завершается → _on_async_done разблокирует UI."""
    import tkinter as tk
    from src.gui.app import CamApp

    root = tk.Tk()
    root.withdraw()
    app = CamApp(root)

    got = []
    app.controller._run_async(lambda: 42, got.append)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not got:
        root.update()
        time.sleep(0.02)

    assert got == [42], f"callback _on_async_done не сработал: {got}"
    # UI должен быть разблокирован (unlock_ui отработал в _on_async_done).
    # btn_save_proj остаётся disabled без активного проекта — это штатное поведение.
    assert str(app.ui.btn_step1.cget("state")) == "normal", \
        f"кнопка ШАГ 1 осталась в состоянии {app.ui.btn_step1.cget('state')}"
    assert str(app.ui.btn_measure.cget("state")) == "normal", \
        "кнопка Замер осталась заблокированной"
    root.destroy()
    print("      OK: _run_async → unlock_ui, кнопки разблокированы")


def main():
    print("[1] Диагностика кросс-поточного after...")
    test_cross_thread_after_is_broken()
    print("[2] Лечение: очередь post_to_ui...")
    test_post_to_ui_fires()
    print("[3] Сквозная: разблокировка UI после async-задачи...")
    test_run_async_unlocks_ui()
    print("\nРегрессия async-UI: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
