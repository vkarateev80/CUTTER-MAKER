import tkinter as tk
from tkinter import messagebox
from src.core.project import ProjectState
from src.core.controller import AppController
from src.core.service_client import ServiceClient
from src.gui.ui_builder import UIBuilder
from src.gui.canvas_manager import CanvasManager

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1400x900")

        # 1. Инициализация Модели (Хранилище данных)
        self.project = ProjectState()
        self.tools_list = []
        self.posts_list = []

        # HTTP-клиент сервисов ingest/render/geometry/math/cam/state с локальным fallback
        self.services = ServiceClient()

        # 2. Инициализация Контроллера (Бизнес-логика)
        self.controller = AppController(self)

        # 3. Инициализация Представления (View)
        self.ui = UIBuilder(self.root, self)
        self.canvas_manager = CanvasManager(self.ui.frame_canvas, self)
        self.canvas_manager.bind_keys(self.root)
        
        # Алиасы для холста
        self.show_raw = self.ui.show_raw
        self.show_healed = self.ui.show_healed
        self.show_array = self.ui.show_array
        self.show_distorted = self.ui.show_distorted
        self.show_mask = self.ui.show_mask
        self.show_ideal = self.ui.show_ideal
        self.show_cnc = self.ui.show_cnc
        self.show_rapids = self.ui.show_rapids
        self.var_dist_axis = self.ui.var_dist_axis
        
        self.refresh_comboboxes()
        self.controller.update_distortion_stats()

    def trigger_render(self):
        self.canvas_manager.render_canvas()

    def _update_cnc_btn_text(self, event=None):
        idx = self.ui.combo_post.current()
        if idx >= 0 and idx < len(self.posts_list):
            ext = self.posts_list[idx].extension
            if not ext.startswith('.'): ext = '.' + ext
            self.ui.btn_cnc.config(text=f"⚙️ Сгенерировать УП ({ext.upper()})")
        else:
            self.ui.btn_cnc.config(text="⚙️ Сгенерировать УП")

    def refresh_comboboxes(self):
        self.tools_list = self.services.load_tools()
        self.posts_list = self.services.load_postprocessors()
        
        self.ui.combo_tool['values'] = [t.name for t in self.tools_list]
        if self.tools_list: self.ui.combo_tool.current(0)
            
        self.ui.combo_post['values'] = [p.name for p in self.posts_list]
        if self.posts_list: self.ui.combo_post.current(0)
        
        self._update_cnc_btn_text()

    def open_tool_manager(self):
        from src.gui.tool_manager import ToolManagerWindow
        win = ToolManagerWindow(self.root, self.services)
        self.root.wait_window(win)
        self.refresh_comboboxes()

    def open_postprocessor_manager(self):
        from src.gui.postprocessor_manager import PostprocessorManagerWindow
        win = PostprocessorManagerWindow(self.root, self.services)
        self.root.wait_window(win)
        self.refresh_comboboxes()

    def log(self, message: str):
        def append():
            self.ui.text_log.config(state=tk.NORMAL)
            self.ui.text_log.insert(tk.END, message + "\n")
            self.ui.text_log.see(tk.END)
            self.ui.text_log.config(state=tk.DISABLED)
            self.root.update_idletasks()
        self.root.after(0, append)

    def clear_logs(self):
        self.ui.text_log.config(state=tk.NORMAL)
        self.ui.text_log.delete("1.0", tk.END)
        self.ui.text_log.config(state=tk.DISABLED)
        self.root.update()

    def copy_logs(self):
        content = self.ui.text_log.get("1.0", tk.END).strip()
        if content: 
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            messagebox.showinfo("Скопировано", "Логи скопированы!")