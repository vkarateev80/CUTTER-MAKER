import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import sys
import math
import shutil
import datetime
import tempfile
import os
import subprocess

from src.pipeline.cam_pipeline import CamPipeline
from src.parser.geometry import CamPath
from src.db.db_manager import DatabaseManager
from src.optimizer.distortion import DistortionCalculator, LayoutAnalyzer

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1400x900") 
        
        self.input_filepath = None
        self.raw_paths, self.ready_paths, self.paths_to_draw = [], [], []
        self.mask_geom = None 
        
        self.layers = {"raw": [], "healed": [], "mask": [], "ideal": [], "cnc": []}
        self.show_raw = tk.BooleanVar(value=True)
        self.show_healed = tk.BooleanVar(value=True)
        self.show_mask = tk.BooleanVar(value=True)
        self.show_ideal = tk.BooleanVar(value=False)
        self.show_cnc = tk.BooleanVar(value=True)
        
        self.enable_sharpening = tk.BooleanVar(value=True)
        
        # Переменные состояния дисторсии
        self.is_distorted = False
        self.applied_dist_axis = ""
        self.current_rapport = 0.0
        self.layout_mismatch = False
        self.layout_len_val = 0.0
        
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.current_scale, self.current_tx, self.current_ty, self.canvas_h = 1.0, 0.0, 0.0, 0
        self.is_measuring, self.measure_pt1 = False, None 
        self.current_project_dir = None 
        
        self.selected_path = None
        self.selected_node_idx = None
        self.hovered_node_idx = None
        self.weld_anchor = None
        self.is_delete_node_mode = False
        
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        
        self.db = DatabaseManager()
        self.tools_list = []
        self.posts_list = []
        
        self._build_ui()
        self.refresh_comboboxes()
        self.update_distortion_stats()
        
        self.root.bind("<Delete>", self.on_delete_key)
        self.root.bind("<BackSpace>", self.on_delete_key)
        self.root.bind("<Key>", self.on_key_press)

    def refresh_comboboxes(self):
        self.tools_list = self.db.load_tools()
        self.posts_list = self.db.load_postprocessors()
        
        self.combo_tool['values'] = [t.name for t in self.tools_list]
        if self.tools_list: self.combo_tool.current(0)
            
        self.combo_post['values'] = [p.name for p in self.posts_list]
        if self.posts_list: self.combo_post.current(0)

    def open_tool_manager(self):
        from src.gui.tool_manager import ToolManagerWindow
        win = ToolManagerWindow(self.root)
        self.root.wait_window(win)
        self.refresh_comboboxes()

    def open_postprocessor_manager(self):
        from src.gui.postprocessor_manager import PostprocessorManagerWindow
        win = PostprocessorManagerWindow(self.root)
        self.root.wait_window(win)
        self.refresh_comboboxes()

    def reset_distortion_state(self):
        self.is_distorted = False
        self.applied_dist_axis = ""
        try:
            self.btn_apply_dist.config(text="Сжать", bg="#4169E1", state=tk.NORMAL)
        except AttributeError:
            pass 

    def _build_ui(self):
        self.frame_left_container = tk.Frame(self.root, width=450)
        self.frame_left_container.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        self.left_canvas = tk.Canvas(self.frame_left_container, width=430, highlightthickness=0)
        self.left_scrollbar = tk.Scrollbar(self.frame_left_container, orient="vertical", command=self.left_canvas.yview)
        self.frame_left = tk.Frame(self.left_canvas)
        
        self.frame_left.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self.left_canvas.create_window((0, 0), window=self.frame_left, anchor="nw")
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. Проект
        frame_proj = tk.LabelFrame(self.frame_left, text="1. Управление Проектом", padx=10, pady=10)
        frame_proj.pack(fill=tk.X, pady=5)
        self.btn_create_proj = tk.Button(frame_proj, text="📁 СОЗДАТЬ ПРОЕКТ И ВЫБРАТЬ МАКЕТ", bg="#FFD700", font=("Arial", 10, "bold"), command=self.create_project)
        self.btn_create_proj.pack(fill=tk.X, pady=(0, 5))
        self.lbl_proj_info = tk.Label(frame_proj, text="Проект не создан", fg="gray", justify=tk.LEFT, wraplength=400)
        self.lbl_proj_info.pack(anchor=tk.W)

        # 2. Анализ и Лечение
        frame_prep = tk.LabelFrame(self.frame_left, text="2. Анализ и Лечение", padx=10, pady=10)
        frame_prep.pack(fill=tk.X, pady=5)
        
        grid_prep = tk.Frame(frame_prep)
        grid_prep.pack(fill=tk.X, pady=(0, 5))
        tk.Label(grid_prep, text="Допуск лечения (мм):").grid(row=0, column=0, sticky=tk.W)
        self.entry_tolerance = tk.Entry(grid_prep, width=10); self.entry_tolerance.insert(0, "2.0"); self.entry_tolerance.grid(row=0, column=1, sticky=tk.W, padx=5)
        tk.Label(grid_prep, text="Удалять пыль < (мм²):").grid(row=1, column=0, sticky=tk.W)
        self.entry_loop_area = tk.Entry(grid_prep, width=10); self.entry_loop_area.insert(0, "1.0"); self.entry_loop_area.grid(row=1, column=1, sticky=tk.W, padx=5)

        self.btn_step1 = tk.Button(frame_prep, text="ШАГ 1: Извлечь векторы", bg="#e0e0e0", command=self.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        self.btn_step2 = tk.Button(frame_prep, text="ШАГ 2: Анализ ошибок", bg="#e0e0e0", command=self.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        self.btn_step3 = tk.Button(frame_prep, text="ШАГ 3: Вылечить (Автосохранение)", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)

        # --- БЛОК ОБРЕЗНЫХ МЕТОК ---
        frame_crop = tk.Frame(frame_prep)
        frame_crop.pack(fill=tk.X, pady=(6, 6))
        tk.Label(frame_crop, text="Ширина пластины:").pack(side=tk.LEFT)
        self.entry_plate_width = tk.Entry(frame_crop, width=6)
        self.entry_plate_width.insert(0, "300.0")
        self.entry_plate_width.pack(side=tk.LEFT, padx=5)
        self.btn_crop_marks = tk.Button(frame_crop, text="✂️ Добавить метки", bg="#FFDAB9", font=("Arial", 8, "bold"), command=self.do_add_crop_marks)
        self.btn_crop_marks.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        # ---------------------------

        self.btn_reset = tk.Button(frame_prep, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=(2, 0))

        # 3. ДИСТОРСИЯ
        frame_dist = tk.LabelFrame(self.frame_left, text="3. Расчет Дисторсии (Сжатие)", padx=10, pady=10, bg="#F0F8FF")
        frame_dist.pack(fill=tk.X, pady=5)
        
        self.var_z = tk.StringVar(value="96")
        self.var_cp = tk.StringVar(value="3.175")
        self.var_undercut = tk.StringVar(value="0.48")
        self.var_tp = tk.StringVar(value="0.44")
        self.var_tb = tk.StringVar(value="0.24")
        self.var_dist_axis = tk.StringVar(value="Y")

        for v in (self.var_z, self.var_cp, self.var_undercut, self.var_tp, self.var_tb, self.var_dist_axis):
            v.trace_add("write", self.update_distortion_stats)

        grid_dist = tk.Frame(frame_dist, bg="#F0F8FF")
        grid_dist.pack(fill=tk.X)
        tk.Label(grid_dist, text="Зубья (Z):", bg="#F0F8FF").grid(row=0, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_z, width=8).grid(row=0, column=1, padx=(0, 10), pady=2)
        tk.Label(grid_dist, text="Шаг (CP):", bg="#F0F8FF").grid(row=0, column=2, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_cp, width=8).grid(row=0, column=3, pady=2)
        
        tk.Label(grid_dist, text="Толщина (tp):", bg="#F0F8FF").grid(row=1, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_tp, width=8).grid(row=1, column=1, padx=(0, 10), pady=2)
        tk.Label(grid_dist, text="Основа (tb):", bg="#F0F8FF").grid(row=1, column=2, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_tb, width=8).grid(row=1, column=3, pady=2)
        
        tk.Label(grid_dist, text="Зазор (Undercut):", bg="#F0F8FF").grid(row=2, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_undercut, width=8).grid(row=2, column=1, padx=(0, 10), pady=2)

        axis_frame = tk.Frame(frame_dist, bg="#F0F8FF")
        axis_frame.pack(fill=tk.X, pady=5)
        tk.Label(axis_frame, text="Ось сжатия:", bg="#F0F8FF").pack(side=tk.LEFT)
        tk.Radiobutton(axis_frame, text="Y (↕)", variable=self.var_dist_axis, value="Y", bg="#F0F8FF").pack(side=tk.LEFT)
        tk.Radiobutton(axis_frame, text="X (↔)", variable=self.var_dist_axis, value="X", bg="#F0F8FF").pack(side=tk.LEFT)

        self.lbl_dist_stats = tk.Label(frame_dist, text="D_cyl: -- мм | K: -- %", fg="#00008B", bg="#F0F8FF", font=("Arial", 9, "bold"))
        self.lbl_dist_stats.pack(anchor=tk.W, pady=(2, 0))
        
        self.lbl_layout_stats = tk.Label(frame_dist, text="Рапорт: -- | Макет: --", fg="gray", bg="#F0F8FF", font=("Arial", 9, "bold"))
        self.lbl_layout_stats.pack(anchor=tk.W, pady=(0, 5))

        dist_btns = tk.Frame(frame_dist, bg="#F0F8FF")
        dist_btns.pack(fill=tk.X, pady=(5, 0))
        self.btn_apply_dist = tk.Button(dist_btns, text="Сжать", bg="#4169E1", fg="white", font=("Arial", 9, "bold"), command=self.do_apply_distortion)
        self.btn_apply_dist.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        self.btn_rotate = tk.Button(dist_btns, text="↻ Поворот 90°", bg="#e0e0e0", command=self.do_rotate_90)
        self.btn_rotate.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        # 4. Ручное Редактирование
        frame_edit = tk.LabelFrame(self.frame_left, text="4. Ручное Редактирование", padx=10, pady=10)
        frame_edit.pack(fill=tk.X, pady=5)
        
        help_text = "• ЛКМ: Выделить контур / Переместить узел\n" \
                    "• [ I ]: Добавить узел  • [ D ]: Удалить узел\n" \
                    "• [ R ]: Разрезать     • [ C ]: Замкнуть\n" \
                    "• [ J ]: Сшить два разных вектора"
        tk.Label(frame_edit, text=help_text, fg="#333333", font=("Arial", 9, "bold"), justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 5))
        
        btn_frame_edit = tk.Frame(frame_edit)
        btn_frame_edit.pack(fill=tk.X, pady=2)
        self.btn_delete_path = tk.Button(btn_frame_edit, text="🗑 Удалить контур", bg="#e0e0e0", command=lambda: self.on_delete_key(None))
        self.btn_delete_path.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        self.btn_delete_node = tk.Button(btn_frame_edit, text="❌ Режим: Удалить узел", bg="#e0e0e0", command=self.toggle_delete_node_mode)
        self.btn_delete_node.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))
        
        self.btn_live_edit = tk.Button(frame_edit, text="✏️ Открыть в Inkscape (Live Edit)", bg="#FFB6C1", font=("Arial", 9, "bold"), command=self.do_live_edit)
        self.btn_live_edit.pack(fill=tk.X, pady=(5, 2))

        # 5. Экспорт
        frame_export = tk.LabelFrame(self.frame_left, text="5. Производство (Экспорт)", padx=10, pady=10)
        frame_export.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_export, text="Компенсация подтравливания (Офсет, мм):", fg="blue", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.entry_offset = tk.Entry(frame_export, width=15, bg="#E6F2FF"); self.entry_offset.insert(0, "0.2"); self.entry_offset.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_export, text="Реперные метки D / Отступ (мм):").pack(anchor=tk.W)
        frame_marks_inputs = tk.Frame(frame_export)
        frame_marks_inputs.pack(fill=tk.X, pady=(0, 5))
        self.entry_mark_d = tk.Entry(frame_marks_inputs, width=6); self.entry_mark_d.insert(0, "4.0"); self.entry_mark_d.pack(side=tk.LEFT, padx=(0, 5))
        self.entry_mark_margin = tk.Entry(frame_marks_inputs, width=6); self.entry_mark_margin.insert(0, "10.0"); self.entry_mark_margin.pack(side=tk.LEFT)

        self.btn_mask = tk.Button(frame_export, text="🖨 Создать УФ-Маску (.PDF)", bg="#9370DB", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_uv_mask)
        self.btn_mask.pack(fill=tk.X, pady=(0, 10))
        
        frame_cnc_tools = tk.LabelFrame(frame_export, text="🛠 Настройки ЧПУ", padx=5, pady=5, bg="#f9f9f9")
        frame_cnc_tools.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame_cnc_tools, text="Инструмент:", bg="#f9f9f9", font=("Arial", 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.combo_tool = ttk.Combobox(frame_cnc_tools, state="readonly", width=18)
        self.combo_tool.grid(row=0, column=1, padx=5, pady=2)
        tk.Button(frame_cnc_tools, text="⚙️", command=self.open_tool_manager).grid(row=0, column=2, padx=2)

        tk.Label(frame_cnc_tools, text="Постпроцессор:", bg="#f9f9f9", font=("Arial", 9)).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.combo_post = ttk.Combobox(frame_cnc_tools, state="readonly", width=18)
        self.combo_post.grid(row=1, column=1, padx=5, pady=2)
        tk.Button(frame_cnc_tools, text="⚙️", command=self.open_postprocessor_manager).grid(row=1, column=2, padx=2)

        tk.Checkbutton(frame_cnc_tools, text="🔪 3D-Подрезка углов", bg="#f9f9f9", fg="#FF4500", font=("Arial", 9, "bold"), variable=self.enable_sharpening).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(5,0))

        self.btn_cnc = tk.Button(frame_export, text="⚙️ Сгенерировать УП (.TXT)", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_cnc)
        self.btn_cnc.pack(fill=tk.X, pady=2)

        # Логи
        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_clear_log = tk.Button(frame_log_btns, text="🗑 Очистить", command=self.clear_logs); self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_copy_log = tk.Button(frame_log_btns, text="📋 Копировать", command=self.copy_logs); self.btn_copy_log.pack(side=tk.RIGHT)
        self.text_log = tk.Text(frame_log, height=6, width=40, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        # Правая часть (Тулбар и Canvas с Линейками)
        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X, pady=(0, 5))
        self.btn_measure = tk.Button(frame_tools, text="📏 Замер", bg="#e0e0e0", command=self.toggle_measure); self.btn_measure.pack(side=tk.LEFT)
        frame_layers = tk.LabelFrame(self.frame_right, text="Слои видимости", padx=5, pady=5)
        frame_layers.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(frame_layers, text="Исходник", fg="#555555", font=("Arial", 9, "bold"), variable=self.show_raw, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Вылеченный", fg="#008888", font=("Arial", 9, "bold"), variable=self.show_healed, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Маска", fg="#880088", font=("Arial", 9, "bold"), variable=self.show_mask, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Лезвие", fg="#CCCC00", font=("Arial", 9, "bold"), variable=self.show_ideal, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="УП (ЧПУ)", fg="#008800", font=("Arial", 9, "bold"), variable=self.show_cnc, command=self.render_canvas).pack(side=tk.LEFT, padx=10)

        # Окно предпросмотра с линейками (Grid Layout)
        frame_canvas = tk.LabelFrame(self.frame_right, text="Предпросмотр (ЛКМ - Выделить/Двигать | Колесико - Масштаб)", padx=5, pady=5)
        frame_canvas.pack(fill=tk.BOTH, expand=True)
        
        frame_canvas.rowconfigure(1, weight=1)
        frame_canvas.columnconfigure(1, weight=1)

        self.corner_box = tk.Frame(frame_canvas, width=25, height=25, bg="#d0d0d0")
        self.corner_box.grid(row=0, column=0, sticky="nsew")

        self.ruler_x = tk.Canvas(frame_canvas, height=25, bg="#e0e0e0", highlightthickness=0)
        self.ruler_x.grid(row=0, column=1, sticky="nsew")

        self.ruler_y = tk.Canvas(frame_canvas, width=25, bg="#e0e0e0", highlightthickness=0)
        self.ruler_y.grid(row=1, column=0, sticky="nsew")

        self.canvas = tk.Canvas(frame_canvas, bg="#1e1e1e", cursor="crosshair", highlightthickness=0)
        self.canvas.grid(row=1, column=1, sticky="nsew")

        self.canvas.bind("<ButtonPress-1>", self.on_left_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<Motion>", self.on_mouse_move) 
        self.canvas.bind("<ButtonPress-3>", self.on_right_click) 
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<Configure>", lambda e: self.render_canvas())

        self._bind_mouse_scroll(self.frame_left_container)
        self._bind_mouse_scroll(self.frame_left)

    def _on_left_scroll(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.left_canvas.yview_scroll(-1, "units")
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.left_canvas.yview_scroll(1, "units")

    def _bind_mouse_scroll(self, widget):
        if not isinstance(widget, (tk.Text, ttk.Combobox, tk.Listbox)):
            widget.bind("<MouseWheel>", self._on_left_scroll)
            widget.bind("<Button-4>", self._on_left_scroll)
            widget.bind("<Button-5>", self._on_left_scroll)
        for child in widget.winfo_children():
            self._bind_mouse_scroll(child)

    def _draw_rulers(self):
        if not hasattr(self, 'ruler_x'): return
        self.ruler_x.delete("all")
        self.ruler_y.delete("all")

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1: return

        min_px_step = 50
        world_step = min_px_step / self.current_scale if self.current_scale > 0 else 1
        
        magnitude = 10 ** math.floor(math.log10(world_step)) if world_step > 0 else 1
        rel_step = world_step / magnitude
        if rel_step <= 1: step = 1 * magnitude
        elif rel_step <= 2: step = 2 * magnitude
        elif rel_step <= 5: step = 5 * magnitude
        else: step = 10 * magnitude
        
        if step <= 0: step = 10

        start_x_world = -self.current_tx / self.current_scale
        end_x_world = (w - self.current_tx) / self.current_scale
        first_tick_x = math.ceil(start_x_world / step) * step
        x_world = first_tick_x
        limit = 0
        
        while x_world <= end_x_world and limit < 1000:
            sx = x_world * self.current_scale + self.current_tx
            self.ruler_x.create_line(sx, 15, sx, 25, fill="black")
            self.ruler_x.create_text(sx + 2, 2, text=f"{x_world:g}", anchor=tk.NW, font=("Arial", 7))
            for i in range(1, 10):
                minor_x_world = x_world + i * (step / 10)
                if minor_x_world > end_x_world: break
                msx = minor_x_world * self.current_scale + self.current_tx
                tick_h = 20 if i == 5 else 22
                self.ruler_x.create_line(msx, tick_h, msx, 25, fill="gray")
            x_world += step
            limit += 1

        start_y_world = -self.current_ty / self.current_scale
        end_y_world = (h - self.current_ty) / self.current_scale
        first_tick_y = math.ceil(start_y_world / step) * step
        y_world = first_tick_y
        limit = 0
        
        while y_world <= end_y_world and limit < 1000:
            sy = h - (y_world * self.current_scale + self.current_ty)
            self.ruler_y.create_line(15, sy, 25, sy, fill="black")
            self.ruler_y.create_text(13, sy - 2, text=f"{y_world:g}", anchor=tk.SE, font=("Arial", 7), angle=90)
            for i in range(1, 10):
                minor_y_world = y_world + i * (step / 10)
                if minor_y_world > end_y_world: break
                msy = h - (minor_y_world * self.current_scale + self.current_ty)
                tick_w = 20 if i == 5 else 22
                self.ruler_y.create_line(tick_w, msy, 25, msy, fill="gray")
            y_world += step
            limit += 1

    def update_distortion_stats(self, *args):
        try:
            z = int(self.var_z.get())
            cp = float(self.var_cp.get())
            undercut = float(self.var_undercut.get())
            tp = float(self.var_tp.get())
            tb = float(self.var_tb.get())
            
            res = DistortionCalculator.calculate_factor(z, cp, undercut, tp, tb)
            self.lbl_dist_stats.config(text=f"D_cyl: {res['d_cyl']} мм | K: {res['k_dist_percent']}%", fg="#00008B")
            self.current_dist_factor = res['k_dist']
            self.current_rapport = res['rapport']
            
            paths = self.ready_paths if self.ready_paths else self.raw_paths
            if paths and not self.is_distorted:
                axis = self.var_dist_axis.get()
                layout_res = LayoutAnalyzer.analyze(paths, axis)
                layout_len = layout_res['layout_length']
                rows = layout_res['rows']
                
                if layout_len == 0:
                    self.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: Не распознан", fg="gray")
                    self.layout_mismatch = False
                else:
                    diff = abs(self.current_rapport - layout_len)
                    if diff <= 0.15:
                        self.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: {rows} ряд., {layout_len:.2f} мм (OK)", fg="#008800")
                        self.layout_mismatch = False
                    else:
                        self.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: {layout_len:.2f} мм (ОШИБКА!)", fg="#FF0000")
                        self.layout_mismatch = True
                        self.layout_len_val = layout_len
            elif self.is_distorted:
                self.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Сжато", fg="gray")
                self.layout_mismatch = False
            else:
                self.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: Нет данных", fg="gray")
                self.layout_mismatch = False
                
        except Exception:
            self.lbl_dist_stats.config(text="D_cyl: Ошибка | K: Ошибка", fg="red")
            self.lbl_layout_stats.config(text="Рапорт: Ошибка | Макет: Ошибка", fg="red")
            self.current_dist_factor = 1.0
            self.current_rapport = 0.0
            self.layout_mismatch = False
            
    def do_apply_distortion(self):
        if self.is_distorted:
            return messagebox.showwarning("Внимание", "Дисторсия уже применена! Сбросьте к исходнику или загрузите новый файл, чтобы применить заново.")
            
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет векторов для масштабирования! Сначала выполните ШАГ 1.")
            
        if self.layout_mismatch:
            msg = f"Внимание! Распознанный шаг макета по оси {self.var_dist_axis.get()} ({self.layout_len_val:.2f} мм)\n" \
                  f"не совпадает с рапортом шестерни Z{self.var_z.get()} ({self.current_rapport:.2f} мм).\n\n" \
                  f"Штамп не сойдется на цилиндре (зазор или нахлест).\n" \
                  f"Вы уверены, что хотите применить дисторсию принудительно?"
            if not messagebox.askyesno("Критическое несовпадение", msg, icon='warning'):
                return
            
        axis = self.var_dist_axis.get()
        new_paths = self._run_with_redirect(CamPipeline().apply_distortion, paths, self.current_dist_factor, axis)
        if new_paths:
            self.selected_path = None
            if self.ready_paths:
                self.ready_paths = new_paths
                self.layers["healed"] = new_paths
            else:
                self.raw_paths = new_paths
                self.layers["raw"] = new_paths
                
            self.is_distorted = True
            self.applied_dist_axis = axis
            self.btn_apply_dist.config(text=f"✅ Сжато ({axis})", bg="#2E8B57", state=tk.DISABLED)
            
            self.invalidate_downstream()
            self.fit_to_screen()
            self.render_canvas()
            self.log(f"Успех: Дисторсия ({self.current_dist_factor:.4f}) по оси {axis} применена.")

    def do_rotate_90(self):
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет векторов для поворота! Сначала выполните ШАГ 1.")
            
        new_paths = self._run_with_redirect(CamPipeline().rotate_geometry, paths, 90.0)
        if new_paths:
            self.selected_path = None
            if self.ready_paths:
                self.ready_paths = new_paths
                self.layers["healed"] = new_paths
            else:
                self.raw_paths = new_paths
                self.layers["raw"] = new_paths
                
            if self.is_distorted:
                self.applied_dist_axis = "X" if self.applied_dist_axis == "Y" else "Y"
                self.btn_apply_dist.config(text=f"✅ Сжато ({self.applied_dist_axis})")
                
            self.invalidate_downstream()
            self.fit_to_screen()
            self.render_canvas()

    def do_add_crop_marks(self):
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет макета для добавления меток! Выполните ШАГ 1.")
            
        try:
            width = float(self.entry_plate_width.get())
        except ValueError:
            return messagebox.showerror("Ошибка", "Неверный формат ширины пластины!")
            
        if self.current_rapport <= 0:
            return messagebox.showwarning("Внимание", "Рапорт не рассчитан! Проверьте параметры шестерни.")
            
        paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        axis = self.applied_dist_axis if self.is_distorted else self.var_dist_axis.get()
            
        new_paths = self._run_with_redirect(CamPipeline().add_crop_marks, paths, self.current_rapport, width, axis)
        if new_paths:
            self.selected_path = None
            if self.ready_paths:
                self.ready_paths = new_paths
                self.layers["healed"] = new_paths
            else:
                self.raw_paths = new_paths
                self.layers["raw"] = new_paths
            
            self.invalidate_downstream()
            self.fit_to_screen()
            self.render_canvas()
            self.log(f"Успех: Обрезные метки добавлены (Ширина: {width} мм, Рапорт: {self.current_rapport} мм, Ось: {axis}).")

    def toggle_measure(self):
        if self.is_delete_node_mode: self.toggle_delete_node_mode()
        self.is_measuring = not self.is_measuring
        if self.is_measuring: 
            self.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
            self.canvas.config(cursor="target")
            self.selected_path = None 
            self.render_canvas()
        else: 
            self.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")

    def toggle_delete_node_mode(self):
        if self.is_measuring: self.toggle_measure()
        self.is_delete_node_mode = not self.is_delete_node_mode
        if self.is_delete_node_mode:
            self.btn_delete_node.config(bg="#FF6347", fg="white", relief=tk.SUNKEN)
            self.canvas.config(cursor="X_cursor")
            self.selected_path = None
            self.render_canvas()
            self.log("Режим удаления узлов Включен (Кликайте ЛКМ по узлам).")
        else:
            self.btn_delete_node.config(bg="#e0e0e0", fg="black", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.log("Режим удаления узлов Выключен.")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        return (sx - self.current_tx) / self.current_scale, (self.canvas_h - sy - self.current_ty) / self.current_scale

    def get_visible_paths(self):
        visible = []
        if self.show_raw.get(): visible.extend(self.layers["raw"])
        if self.show_healed.get(): visible.extend(self.layers["healed"])
        if self.show_mask.get(): visible.extend(self.layers["mask"])
        if self.show_ideal.get(): visible.extend(self.layers["ideal"])
        if self.show_cnc.get(): visible.extend(self.layers["cnc"])
        return visible

    def get_snapped_coords(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        if not visible_paths: return wx, wy, None, None
        snap_threshold_world = 15 / self.current_scale
        closest_dist, closest_pt, closest_layer = float('inf'), None, None
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist <= closest_dist and dist < snap_threshold_world: 
                    closest_dist = dist
                    closest_pt = pt
                    closest_layer = path.layer_name
        if closest_pt: return closest_pt[0], closest_pt[1], closest_pt, closest_layer
        return wx, wy, None, None

    def get_closest_path(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        if not visible_paths: return None
        snap_threshold_world = 10 / self.current_scale
        closest_dist = float('inf')
        closest_path = None
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < closest_dist and dist <= snap_threshold_world:
                    closest_dist = dist
                    closest_path = path
        return closest_path

    def get_any_node_at(self, sx, sy, radius=15):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        best_dist = float('inf')
        best_match = None
        world_radius = radius / self.current_scale if self.current_scale > 0 else 0
        for path in visible_paths:
            for i, pt in enumerate(path.points):
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < best_dist and dist <= world_radius:
                    best_dist = dist
                    best_match = (path, i)
        return best_match

    def invalidate_downstream(self):
        self.mask_geom = None
        self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], []
        self.btn_mask.config(state=tk.DISABLED)
        self.btn_cnc.config(state=tk.DISABLED)
        self.update_distortion_stats()

    def get_node_at(self, sx, sy, radius=10):
        if not self.selected_path: return None
        for i, pt in enumerate(self.selected_path.points):
            px = pt[0] * self.current_scale + self.current_tx
            py = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
            if math.hypot(px - sx, py - sy) <= radius: return i
        return None

    def get_segment_at(self, sx, sy, radius=10):
        if not self.selected_path or len(self.selected_path.points) < 2: return None, None
        wx, wy = self.screen_to_world(sx, sy)
        world_radius = radius / self.current_scale if self.current_scale > 0 else 0
        pts = self.selected_path.points
        n = len(pts)
        best_i, best_dist, best_proj = None, float('inf'), None
        for i in range(n - 1):
            p1, p2 = pts[i], pts[i+1]
            l2 = (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2
            if l2 == 0: continue
            t = max(0, min(1, ((wx - p1[0]) * (p2[0] - p1[0]) + (wy - p1[1]) * (p2[1] - p1[1])) / l2))
            proj_x = p1[0] + t * (p2[0] - p1[0])
            proj_y = p1[1] + t * (p2[1] - p1[1])
            dist = math.hypot(wx - proj_x, wy - proj_y)
            if dist < best_dist and dist <= world_radius:
                best_dist, best_i, best_proj = dist, i, (proj_x, proj_y)
        if self.selected_path.is_closed and n > 2:
            p1, p2 = pts[-1], pts[0]
            l2 = (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2
            if l2 != 0:
                t = max(0, min(1, ((wx - p1[0]) * (p2[0] - p1[0]) + (wy - p1[1]) * (p2[1] - p1[1])) / l2))
                proj_x = p1[0] + t * (p2[0] - p1[0])
                proj_y = p1[1] + t * (p2[1] - p1[1])
                dist = math.hypot(wx - proj_x, wy - proj_y)
                if dist < best_dist and dist <= world_radius:
                    best_dist, best_i, best_proj = dist, n - 1, (proj_x, proj_y)
        return best_i, best_proj

    def on_delete_key(self, event):
        if not self.selected_path: return
        if self.weld_anchor and self.weld_anchor[0] == self.selected_path: self.weld_anchor = None
        if self.selected_path in self.raw_paths: self.raw_paths.remove(self.selected_path)
        if self.selected_path in self.ready_paths: self.ready_paths.remove(self.selected_path)
        for layer_paths in self.layers.values():
            if self.selected_path in layer_paths: layer_paths.remove(self.selected_path)
        self.selected_path = None
        self.invalidate_downstream()
        self.render_canvas()
        self.log("Вектор удален вручную.")

    def on_key_press(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text)): return
        char = getattr(event, 'char', '').lower()
        if char in ('i', 'ш'): self.on_key_insert_node()
        elif char in ('d', 'в'): self.on_key_delete_node()
        elif char in ('r', 'к'): self.on_key_remove_segment()
        elif char in ('j', 'о'): self.on_key_join_nodes()
        elif char in ('c', 'с'): self.on_key_close_path()

    def on_key_close_path(self):
        if self.is_measuring or not self.selected_path: return
        if self.selected_path.is_closed:
            self.log("Контур уже замкнут.")
            return
        pts = self.selected_path.points
        if len(pts) > 2:
            dist = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            if dist > 1e-4:
                first_pt = pts[0]
                new_pt = (first_pt[0], first_pt[1], first_pt[2]) if len(first_pt) > 2 else (first_pt[0], first_pt[1])
                self.selected_path.points.append(new_pt)
        self.selected_path.is_closed = True
        self.invalidate_downstream()
        self.render_canvas()
        self.log("Успех: Выделенный контур замкнут (клавиша C).")

    def on_key_insert_node(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, proj_pt = self.get_segment_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if seg_i is not None and proj_pt:
            new_pt = (proj_pt[0], proj_pt[1])
            self.selected_path.points.insert(seg_i + 1, new_pt)
            self.invalidate_downstream()
            self.render_canvas()
            self.log(f"Узел добавлен (Индекс: {seg_i + 1}).")

    def on_key_delete_node(self):
        if self.is_measuring or not self.selected_path: return
        idx = self.get_node_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if idx is not None:
            self.selected_path.points.pop(idx)
            if len(self.selected_path.points) < 2: self.on_delete_key(None)
            else:
                self.invalidate_downstream()
                self.render_canvas()
                self.log(f"Узел удален (Индекс: {idx}).")

    def on_key_remove_segment(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, _ = self.get_segment_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if seg_i is None: return
        pts = self.selected_path.points.copy()
        if self.selected_path.is_closed:
            if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4: pts.pop()
            self.selected_path.is_closed = False
            if seg_i >= len(pts): seg_i = len(pts) - 1
            self.selected_path.points = pts[seg_i+1:] + pts[:seg_i+1]
            self.log("Замкнутый контур разорван.")
        else:
            pts1 = pts[:seg_i+1]
            pts2 = pts[seg_i+1:]
            target_list = self.ready_paths if self.selected_path in self.ready_paths else self.raw_paths
            layer_name = self.selected_path.layer_name
            if self.selected_path in target_list: target_list.remove(self.selected_path)
            target_layer = self.layers.get("raw")
            for layer_paths in self.layers.values():
                if self.selected_path in layer_paths:
                    layer_paths.remove(self.selected_path)
                    target_layer = layer_paths
                    break
            self.selected_path = None
            if len(pts1) >= 2:
                cp1 = CamPath(points=pts1, is_closed=False, layer_name=layer_name)
                target_list.append(cp1)
                if target_layer is not None: target_layer.append(cp1)
            if len(pts2) >= 2:
                cp2 = CamPath(points=pts2, is_closed=False, layer_name=layer_name)
                target_list.append(cp2)
                if target_layer is not None: target_layer.append(cp2)
            self.log("Открытый контур разделен на две части.")
        self.invalidate_downstream()
        self.render_canvas()

    def on_key_join_nodes(self):
        if self.is_measuring: return
        match = self.get_any_node_at(self.last_mouse_x, self.last_mouse_y, radius=15)
        if not match:
            self.log("Ошибка: Наведите курсор ближе к узлу контура.")
            return
        p2, idx2 = match
        if p2.is_closed:
            self.log("Ошибка: Выбранный контур уже замкнут.")
            return
        is_end2 = (idx2 == len(p2.points) - 1)
        is_start2 = (idx2 == 0)
        if not (is_start2 or is_end2):
            self.log("Ошибка: Сшивать можно только начальные или конечные точки контура.")
            return
        if self.weld_anchor is None:
            self.weld_anchor = (p2, idx2)
            self.log("Точка 1 зафиксирована. Наведите на вторую точку и нажмите J.")
            self.render_canvas()
            return
        p1, idx1 = self.weld_anchor
        if p1 not in self.get_visible_paths():
            self.weld_anchor = (p2, idx2)
            self.log("Предыдущая точка была удалена. Зафиксирована новая точка 1.")
            self.render_canvas()
            return
        if p1 == p2:
            self.log("Ошибка: Для замыкания одного контура используйте клавишу C.")
            self.weld_anchor = None
            self.render_canvas()
            return
        else:
            is_end1 = (idx1 == len(p1.points) - 1)
            is_start1 = (idx1 == 0)
            pts1 = p1.points.copy()
            pts2 = p2.points.copy()
            if is_end1 and is_start2: merged = pts1 + pts2
            elif is_end1 and is_end2:
                pts2.reverse()
                merged = pts1 + pts2
            elif is_start1 and is_end2: merged = pts2 + pts1
            elif is_start1 and is_start2:
                pts1.reverse()
                merged = pts1 + pts2
            p1.points = merged
            if p2 in self.raw_paths: self.raw_paths.remove(p2)
            if p2 in self.ready_paths: self.ready_paths.remove(p2)
            for layer_paths in self.layers.values():
                if p2 in layer_paths: layer_paths.remove(p2)
            self.selected_path = p1
            self.log("Успех: Два вектора сшиты в один!")
        self.weld_anchor = None
        self.invalidate_downstream()
        self.render_canvas()

    def on_left_click(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.canvas.focus_set()
        self.canvas_h = self.canvas.winfo_height()
        
        if self.is_measuring:
            wx, wy, snapped_pt, _ = self.get_snapped_coords(event.x, event.y)
            if not self.measure_pt1: 
                self.measure_pt1 = (wx, wy)
                self.log(f"-> Замер от: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.log(f"=== РАССТОЯНИЕ: {dist:.4f} мм ===")
                self.measure_pt1 = None
                self.canvas.delete("measure_dynamic")
                sx, sy = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00FF00", tags="measure_dynamic")
            return
            
        if self.is_delete_node_mode:
            match = self.get_any_node_at(event.x, event.y, radius=10)
            if match:
                path, idx = match
                path.points.pop(idx)
                if len(path.points) < 2:
                    if path in self.raw_paths: self.raw_paths.remove(path)
                    if path in self.ready_paths: self.ready_paths.remove(path)
                    for layer_paths in self.layers.values():
                        if path in layer_paths: layer_paths.remove(path)
                    if self.selected_path == path: self.selected_path = None
                self.invalidate_downstream()
                self.render_canvas()
                self.log("Узел удален кликом.")
            return
            
        if self.selected_path:
            node_idx = self.get_node_at(event.x, event.y)
            if node_idx is not None:
                self.selected_node_idx = node_idx
                return

        clicked_path = self.get_closest_path(event.x, event.y)
        if clicked_path != self.selected_path:
            self.selected_path = clicked_path
            self.render_canvas()
            
        self.pan_start_x, self.pan_start_y = event.x, event.y

    def on_left_release(self, event):
        self.selected_node_idx = None

    def on_right_click(self, event):
        if self.is_measuring and self.measure_pt1: 
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")
        elif self.is_delete_node_mode: self.toggle_delete_node_mode()
        elif self.weld_anchor:
            self.weld_anchor = None
            self.log("Сварка отменена.")
            self.render_canvas()
        else:
            self.selected_path = None
            self.render_canvas()

    def on_mouse_move(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.canvas.delete("hover_tooltip")
        wx, wy, snapped_pt, layer_name = self.get_snapped_coords(event.x, event.y)
        
        if hasattr(self, 'ruler_x'):
            self.ruler_x.delete("tracker")
            self.ruler_y.delete("tracker")
            self.ruler_x.create_line(event.x, 0, event.x, 25, fill="red", tags="tracker")
            self.ruler_y.create_line(0, event.y, 25, event.y, fill="red", tags="tracker")

        if self.is_measuring and self.measure_pt1:
            self.canvas.delete("measure_dynamic")
            dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
            sx1, sy1 = self.measure_pt1[0] * self.current_scale + self.current_tx, self.canvas_h - (self.measure_pt1[1] * self.current_scale + self.current_ty)
            sx2, sy2 = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FFD700", dash=(4, 4), tags="measure_dynamic")
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#FFD700", width=2, tags="measure_dynamic")
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")
            return
            
        if self.selected_path and self.selected_node_idx is None:
            hover_idx = self.get_node_at(event.x, event.y)
            if hover_idx != self.hovered_node_idx:
                self.hovered_node_idx = hover_idx
                self.render_canvas()
        
        if snapped_pt and not self.selected_path:
            sx2 = wx * self.current_scale + self.current_tx
            sy2 = self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#00FFFF", width=2, tags="hover_tooltip")
            text = f"Слой: {layer_name}\nX: {snapped_pt[0]:.3f}\nY: {snapped_pt[1]:.3f}"
            text_id = self.canvas.create_text(event.x + 15, event.y - 15, text=text, fill="#00FFFF", font=("Arial", 10, "bold"), anchor=tk.SW, tags="hover_tooltip")
            bbox = self.canvas.bbox(text_id)
            if bbox:
                self.canvas.create_rectangle(bbox[0]-3, bbox[1]-3, bbox[2]+3, bbox[3]+3, fill="#1e1e1e", outline="#00FFFF", tags="hover_tooltip")
                self.canvas.tag_raise(text_id)

    def on_pan_move(self, event):
        if self.is_measuring or self.is_delete_node_mode: return 
        if self.selected_node_idx is not None and self.selected_path:
            wx, wy = self.screen_to_world(event.x, event.y)
            old_pt = self.selected_path.points[self.selected_node_idx]
            new_pt = (wx, wy, old_pt[2]) if len(old_pt) > 2 else (wx, wy)
            self.selected_path.points[self.selected_node_idx] = new_pt
            if self.selected_path.is_closed and len(self.selected_path.points) > 1:
                if self.selected_node_idx == 0:
                    last_pt = self.selected_path.points[-1]
                    if math.hypot(old_pt[0] - last_pt[0], old_pt[1] - last_pt[1]) < 1e-4:
                        self.selected_path.points[-1] = (wx, wy, last_pt[2]) if len(last_pt) > 2 else (wx, wy)
                elif self.selected_node_idx == len(self.selected_path.points) - 1:
                    first_pt = self.selected_path.points[0]
                    if math.hypot(old_pt[0] - first_pt[0], old_pt[1] - first_pt[1]) < 1e-4:
                        self.selected_path.points[0] = (wx, wy, first_pt[2]) if len(first_pt) > 2 else (wx, wy)
            self.invalidate_downstream()
            self.render_canvas()
            return

        self.current_tx += event.x - self.pan_start_x
        self.current_ty -= event.y - self.pan_start_y 
        self.pan_start_x, self.pan_start_y = event.x, event.y
        self.render_canvas()

    def on_mousewheel(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0: zoom = 1.1 
        elif event.num == 5 or getattr(event, 'delta', 0) < 0: zoom = 0.9 
        else: return
        wx, wy = (event.x - self.current_tx) / self.current_scale, (self.canvas_h - event.y - self.current_ty) / self.current_scale
        self.current_scale *= zoom
        self.current_tx, self.current_ty = event.x - wx * self.current_scale, self.canvas_h - event.y - wy * self.current_scale
        self.render_canvas()

    def fit_to_screen(self):
        visible = self.get_visible_paths()
        if not visible: return
        all_x, all_y = [pt[0] for p in visible for pt in p.points], [pt[1] for p in visible for pt in p.points]
        if not all_x or not all_y: return
        w_mm, h_mm = max(all_x) - min(all_x), max(all_y) - min(all_y)
        if w_mm == 0: w_mm = 1
        if h_mm == 0: h_mm = 1
        self.root.update() 
        self.canvas_h = self.canvas.winfo_height()
        pad = 30 
        self.current_scale = min((self.canvas.winfo_width() - 2 * pad) / w_mm, (self.canvas_h - 2 * pad) / h_mm)
        self.current_tx = (self.canvas.winfo_width() - w_mm * self.current_scale) / 2 - min(all_x) * self.current_scale
        self.current_ty = (self.canvas_h - h_mm * self.current_scale) / 2 - min(all_y) * self.current_scale

    def render_canvas(self):
        self.canvas.delete("all")
        self.canvas_h = self.canvas.winfo_height()
        
        layers_to_draw = [
            (self.show_raw, self.layers["raw"], "#555555", 1.0, None),
            (self.show_healed, self.layers["healed"], "#00FFFF", 1.5, None),
            (self.show_mask, self.layers["mask"], "#FF1493", 2.0, None),
            (self.show_ideal, self.layers["ideal"], "#FFFF00", 2.0, None), 
            (self.show_cnc, self.layers["cnc"], "#00FF00", 1.5, (5, 5))
        ]
        
        for show_var, paths, color, width, dash in layers_to_draw:
            if show_var.get() and paths:
                for path in paths:
                    if len(path.points) < 2: continue
                    coords = []
                    for pt in path.points: 
                        x, y = pt[0], pt[1]
                        coords.extend([x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)])
                    
                    is_selected = (path is self.selected_path)
                    draw_color = "#FF4500" if is_selected else color
                    draw_width = 3.0 if is_selected else width
                    
                    if path.layer_name == "SHARPEN":
                        self.canvas.create_line(coords, fill="#FF0000" if not is_selected else "#FF4500", width=2.0 if not is_selected else 3.0, capstyle=tk.ROUND)
                    else:
                        if dash and not is_selected:
                            self.canvas.create_line(coords, fill=draw_color, width=draw_width, capstyle=tk.ROUND, dash=dash)
                        else:
                            self.canvas.create_line(coords, fill=draw_color, width=draw_width, capstyle=tk.ROUND)
                            
                    if is_selected:
                        for i, pt in enumerate(path.points):
                            nx = pt[0] * self.current_scale + self.current_tx
                            ny = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
                            fill_color = "#FF0000" if self.hovered_node_idx == i else "#FFFFFF"
                            self.canvas.create_rectangle(nx-3, ny-3, nx+3, ny+3, fill=fill_color, outline="#FF4500", tags="node")
        
        if self.weld_anchor:
            wp, w_idx = self.weld_anchor
            if wp in self.get_visible_paths() and w_idx < len(wp.points):
                pt = wp.points[w_idx]
                nx = pt[0] * self.current_scale + self.current_tx
                ny = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
                self.canvas.create_oval(nx-6, ny-6, nx+6, ny+6, outline="#00FF00", width=2, tags="weld_anchor")

        colors = {"red": "#FF0000", "orange": "#FFA500", "magenta": "#FF00FF", "yellow": "#FFFF00"}
        for k, pts in self.error_markers.items():
            for x, y in pts:
                sx, sy = x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-5, sy-5, sx+5, sy+5, outline=colors[k], width=2, tags="error_marker")

        cx, cy = 40, self.canvas_h - 40
        axis = self.var_dist_axis.get()
        x_width = 4 if axis == "X" else 1
        y_width = 4 if axis == "Y" else 1
        
        self.canvas.create_line(cx, cy, cx + 45, cy, fill="#FF4500", width=x_width, arrow=tk.LAST, tags="ucs")
        self.canvas.create_text(cx + 55, cy, text="X", fill="#FF4500", font=("Arial", 10, "bold"), anchor=tk.W, tags="ucs")
        self.canvas.create_line(cx, cy, cx, cy - 45, fill="#32CD32", width=y_width, arrow=tk.LAST, tags="ucs")
        self.canvas.create_text(cx, cy - 55, text="Y", fill="#32CD32", font=("Arial", 10, "bold"), anchor=tk.S, tags="ucs")
        self.canvas.create_oval(cx-3, cy-3, cx+3, cy+3, fill="white", tags="ucs")
        
        if self.is_distorted:
            self.canvas.create_text(cx, cy - 80, text=f"⚠️ ДИСТОРСИЯ ПРИМЕНЕНА ({self.applied_dist_axis})", fill="#FF4500", font=("Arial", 10, "bold"), anchor=tk.SW, tags="ucs")

        self._draw_rulers()

    def log(self, message: str):
        self.text_log.config(state=tk.NORMAL); self.text_log.insert(tk.END, message + "\n"); self.text_log.see(tk.END); self.text_log.config(state=tk.DISABLED); self.root.update()

    def copy_logs(self):
        content = self.text_log.get("1.0", tk.END).strip()
        if content: self.root.clipboard_clear(); self.root.clipboard_append(content); messagebox.showinfo("Скопировано", "Логи скопированы!")
            
    def clear_logs(self):
        self.text_log.config(state=tk.NORMAL); self.text_log.delete("1.0", tk.END); self.text_log.config(state=tk.DISABLED); self.root.update()

    def _run_with_redirect(self, func, *args):
        class StdoutRedirector:
            def __init__(self, app): self.app = app
            def write(self, string):
                if string.strip(): self.app.log(string.strip())
            def flush(self): pass
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirector(self)
        try: return func(*args)
        except Exception as e: self.log(f"ОШИБКА: {e}"); messagebox.showerror("Ошибка", str(e))
        finally: sys.stdout = old_stdout

    def do_live_edit(self):
        paths_to_edit = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths_to_edit: return messagebox.showwarning("Внимание", "Нет векторов для редактирования! Сначала выполните ШАГ 1.")
        temp_dir = Path(tempfile.gettempdir())
        safe_svg = temp_dir / f"cam_live_edit_{os.getpid()}.svg"
        self.log("Экспорт геометрии во временный SVG...")
        pipeline = CamPipeline()
        pipeline.export_paths_to_svg(paths_to_edit, safe_svg)
        project_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(os.getcwd())
        inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe' if os.name == 'nt' else Path('inkscape')
        self.log("Ожидание завершения работы Inkscape...")
        self.log("-> Внесите изменения, нажмите Ctrl+S и закройте Inkscape.")
        self.root.update()
        try:
            subprocess.run([str(inkscape_exe), str(safe_svg)])
            self.log("Inkscape закрыт. Чтение изменений...")
            new_paths = pipeline.step1_parse(safe_svg)
            if new_paths:
                self.selected_path = None
                self.weld_anchor = None
                if self.ready_paths:
                    self.ready_paths = new_paths
                    self.layers["healed"] = new_paths
                else:
                    self.raw_paths = new_paths
                    self.layers["raw"] = new_paths
                self.invalidate_downstream()
                self.fit_to_screen()
                self.render_canvas()
                self.log("Векторы успешно обновлены из Inkscape!")
                messagebox.showinfo("Live Edit", "Изменения успешно применены!")
            else: self.log("Внимание: Файл пуст или сохранен некорректно.")
        except Exception as e:
            self.log(f"Ошибка Live Edit: {e}")
            messagebox.showerror("Ошибка", f"Не удалось выполнить Live Edit:\n{e}")
        finally:
            if safe_svg.exists():
                try: safe_svg.unlink()
                except: pass

    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self.raw_paths = self._run_with_redirect(CamPipeline().step1_parse, self.input_filepath)
        if self.raw_paths:
            self.selected_path = None
            self.weld_anchor = None
            self.layers["raw"] = self.raw_paths; self.layers["healed"], self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], [], []
            self.mask_geom = None
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.reset_distortion_state()
            self.fit_to_screen(); self.render_canvas()
            self.update_distortion_stats()

    def do_step2(self):
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: loop_area = float(self.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        stats = self._run_with_redirect(CamPipeline(min_loop_area=loop_area).step2_check_errors, paths)
        if stats:
            self.error_markers = {"red": stats.get("error_nodes", []), "orange": stats.get("intersection_nodes", []), "magenta": stats.get("duplicate_nodes", []), "yellow": stats.get("dust_nodes", [])}
            self.render_canvas()

    def do_step3(self):
        if not self.raw_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: tol, loop_area = float(self.entry_tolerance.get()), float(self.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        self.ready_paths = self._run_with_redirect(CamPipeline(tolerance=tol, min_loop_area=loop_area).step3_heal_and_optimize, self.ready_paths if self.ready_paths else self.raw_paths)
        if self.ready_paths:
            self.selected_path = None
            self.weld_anchor = None
            self.layers["healed"] = self.ready_paths; self.render_canvas()
            self.btn_mask.config(state=tk.NORMAL); self.btn_cnc.config(state=tk.NORMAL)
            self.update_distortion_stats()
            if self.current_project_dir: self._run_with_redirect(CamPipeline().save_source_dxf, self.ready_paths, self.current_project_dir / "02_Вылеченный_Мастер.dxf")

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths, self.mask_geom = [], None
        self.selected_path = None
        self.weld_anchor = None
        self.layers["healed"], self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], [], []
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.reset_distortion_state()
        self.render_canvas(); self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)
        self.update_distortion_stats()

    def create_project(self):
        filepath = filedialog.askopenfilename(title="Выберите макет", filetypes=(("Поддерживаемые макеты", "*.dxf *.svg *.pdf *.ai *.cdr *.eps"), ("Все файлы", "*.*")))
        if not filepath: return
        proj_root = Path("Проекты")
        proj_root.mkdir(exist_ok=True)
        existing = [d.name for d in proj_root.iterdir() if d.is_dir() and d.name.startswith("Проект_")]
        nums = [int(n.split("_")[1]) for n in existing if n.split("_")[1].isdigit()]
        proj_name = f"Проект_{max(nums) + 1 if nums else 1:03d}"
        self.current_project_dir = proj_root / proj_name
        self.current_project_dir.mkdir()
        (self.current_project_dir / "Травление").mkdir()
        (self.current_project_dir / "ЧПУ").mkdir()
        
        project_source_file = self.current_project_dir / f"01_Исходник{Path(filepath).suffix}"
        shutil.copy2(filepath, project_source_file)
        self.input_filepath = project_source_file
        self.lbl_proj_info.config(text=f"Папка: {proj_name}\nМакет: {Path(filepath).name}", fg="black")
        
        self.canvas.delete("all")
        self.raw_paths, self.ready_paths = [], []
        self.mask_geom = None
        self.selected_path = None
        self.weld_anchor = None
        self.layers = {"raw": [], "healed": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.show_raw.set(True); self.show_healed.set(True); self.show_mask.set(True); self.show_ideal.set(False); self.show_cnc.set(True)
        self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)
        self.reset_distortion_state()
        self.update_distortion_stats()
        self.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")

    def export_uv_mask(self):
        if not self.current_project_dir or not self.ready_paths: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ и ВЫЛЕЧИТЕ деталь!")
        try: 
            offset = float(self.entry_offset.get())
            mark_d = float(self.entry_mark_d.get())
            mark_margin = float(self.entry_mark_margin.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат чисел!")

        date_str = datetime.datetime.now().strftime("%d.%m.%Y")
        project_name = self.current_project_dir.name
        default_text = f"{project_name} | Офсет: {offset} мм | Метки: D{mark_d} мм | Дата: {date_str}"

        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка инфо-панели")
        dialog.geometry("700x150")
        dialog.transient(self.root) 
        dialog.grab_set() 
        dialog.resizable(False, False)

        tk.Label(dialog, text="Отредактируйте текст для выворотки на инфо-панели:", font=("Arial", 11, "bold")).pack(pady=(15, 5))
        entry_text = tk.Entry(dialog, width=80, font=("Arial", 11))
        entry_text.insert(0, default_text)
        entry_text.pack(pady=5, padx=20)

        result = [None] 
        def on_ok():
            result[0] = entry_text.get()
            dialog.destroy()
        def on_cancel(): dialog.destroy()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="✅ Сгенерировать PDF", width=20, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=on_ok).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="❌ Отмена", width=10, bg="#f44336", fg="white", font=("Arial", 10, "bold"), command=on_cancel).pack(side=tk.LEFT, padx=10)

        self.root.wait_window(dialog) 
        if result[0] is None:
            self.log("Генерация УФ-Маски отменена пользователем.")
            return 

        final_badge_text = result[0]
        mask_file = self.current_project_dir / "Травление" / "03_УФ_Маска.pdf"
        
        result_paths = self._run_with_redirect(CamPipeline().generate_uv_mask_pdf, self.ready_paths, offset, mask_file, final_badge_text, mark_d, mark_margin)
        if result_paths:
            visual_paths, pure_paths, mask_geom = result_paths
            self.layers["mask"] = visual_paths
            self.mask_geom = mask_geom
            self.show_mask.set(True)
            self.fit_to_screen()
            self.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска с метками и кастомной инфо-панелью успешно сохранена.")

    def export_cnc(self):
        if not self.mask_geom: return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску!\nЧПУ использует контуры маски как базовые для расчета лезвия.")
        try: offset = float(self.entry_offset.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат офсета!")
            
        idx_tool = self.combo_tool.current()
        idx_post = self.combo_post.current()
        if idx_tool < 0 or idx_post < 0: return messagebox.showerror("Ошибка", "Выберите инструмент и постпроцессор!")
            
        selected_tool = self.tools_list[idx_tool]
        selected_post = self.posts_list[idx_post]
        ext = selected_post.extension
        if not ext.startswith('.'): ext = '.' + ext
        cnc_file = self.current_project_dir / "ЧПУ" / f"04_УП_Фрезер{ext}"
        sharpen = self.enable_sharpening.get()
        
        generated_paths = self._run_with_redirect(CamPipeline().generate_gcode, self.mask_geom, cnc_file, selected_tool, selected_post, offset, sharpen)
        if generated_paths:
            ideal_paths, cnc_paths = generated_paths
            self.layers["ideal"] = ideal_paths
            self.layers["cnc"] = cnc_paths
            self.show_ideal.set(True)
            self.show_cnc.set(True)
            self.render_canvas()
            messagebox.showinfo("Готово", f"УП сохранена как {cnc_file.name}!")