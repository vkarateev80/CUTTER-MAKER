"""Главный контроллер приложения: инфраструктура асинхронных задач + сборка миксинов действий."""
import sys
import threading
from tkinter import messagebox

from src.core.export_actions import ExportActions
from src.core.pipeline_actions import PipelineActions
from src.core.project_actions import ProjectActions
from src.core.transform_actions import TransformActions


class AppController(ProjectActions, PipelineActions, TransformActions, ExportActions):
    def __init__(self, app):
        self.app = app

    @property
    def project(self): return self.app.project

    @property
    def ui(self): return self.app.ui

    @property
    def canvas(self): return self.app.canvas_manager

    def _run_async(self, func, callback, *args):
        self.ui.lock_ui()
        self.canvas.canvas.config(cursor="watch")
        self.ui.progress.start(15)

        def worker():
            class StdoutRedirector:
                def __init__(self, app): self.app = app
                def write(self, string):
                    if string.strip(): self.app.log(string.strip())
                def flush(self): pass
            
            old_stdout = sys.stdout
            sys.stdout = StdoutRedirector(self.app)
            try:
                res = func(*args)
                err = None
            except Exception as e:
                res = None
                err = e
            finally:
                sys.stdout = old_stdout
            # ВАЖНО: прямой root.after из фонового потока на Tk 9 (macOS)
            # молча теряет callback → вечная "загрузка". Только через очередь UI.
            self.app.post_to_ui(self._on_async_done, callback, res, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_async_done(self, callback, res, err):
        self.ui.progress.stop()
        self.ui.unlock_ui()
        
        if self.canvas.is_measuring: self.canvas.canvas.config(cursor="target")
        elif self.canvas.is_delete_node_mode: self.canvas.canvas.config(cursor="X_cursor")
        else: self.canvas.canvas.config(cursor="crosshair")
            
        if err:
            self.app.log(f"ОШИБКА: {err}")
            messagebox.showerror("Ошибка", str(err))
        elif callback:
            callback(res)
