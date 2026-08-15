import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import sys
import math
import os
import shutil

from src.pipeline.cam_pipeline import CamPipeline
from src.parser.geometry import CamPath

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1300x850") 
        
        self.input_filepath = None
        self.raw_paths: list[CamPath] = []
        self.ready_paths: list[CamPath] = []
        
        self.layers = {
            "raw": [],
            "healed": [],
            "mask": [],
            "cnc": []
        }
        
        self.show_raw = tk.BooleanVar(value=True)
        self.show_healed = tk.BooleanVar(value=True)
        self.show_mask = tk.BooleanVar(value=True)
        self.show_cnc = tk.BooleanVar(value=True)
        
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.current_scale = 1.0
        self.current_tx = 0.0 
        self.current_ty = 0.0 
        self.canvas_h = 0
        self.pan_start_x = 0
        self.pan_start_y = 0
        
        self.is_measuring = False
        self.measure_pt1 = None 
        
        self.current_project_dir = None 
        
        self._build_ui()

    def _build_ui(self):
        self.frame_left = tk.Frame(self.root, width=450)
        self.frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # === БЛОК 1: УПРАВЛЕНИЕ ПРОЕКТОМ ===
        frame_proj = tk.LabelFrame(self.frame_left, text="1. Управление Проектом", padx=10, pady=10)
        frame_proj.pack(fill=tk.X, pady=5)
        
        self.btn_create_proj = tk.Button(frame_proj, text="📁 СОЗДАТЬ ПРОЕКТ И ВЫБРАТЬ МАКЕТ", bg="#FFD700", font=("Arial", 10, "bold"), command=self.create_project)
        self.btn_create_proj.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_proj_info = tk.Label(frame_proj, text="Проект не создан", fg="gray", justify=tk.LEFT, wraplength=400)
        self.lbl_proj_info.pack(anchor=tk.W)

        # === БЛОК 2: АНАЛИЗ И ЛЕЧЕНИЕ ===
        frame_prep = tk.LabelFrame(self.frame_left, text="2. Анализ и Лечение", padx=10, pady=10)
        frame_prep.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_prep, text="Допуск лечения (мм):").pack(anchor=tk.W)
        self.entry_tolerance = tk.Entry(frame_prep, width=15)
        self.entry_tolerance.insert(0, "0.01")
        self.entry_tolerance.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_prep, text="Удалять пыль/петли < (мм/мм²):").pack(anchor=tk.W)
        self.entry_loop_area = tk.Entry(frame_prep, width=15)
        self.entry_loop_area.insert(0, "1.0") 
        self.entry_loop_area.pack(anchor=tk.W, pady=(0, 10))

        self.btn_step1 = tk.Button(frame_prep, text="ШАГ 1: Извлечь векторы", bg="#e0e0e0", command=self.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        
        self.btn_step2 = tk.Button(frame_prep, text="ШАГ 2: Анализ ошибок", bg="#e0e0e0", command=self.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        
        self.btn_step3 = tk.Button(frame_prep, text="ШАГ 3: Вылечить (Автосохранение мастера)", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)
        
        self.btn_reset = tk.Button(frame_prep, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=2)

        # === БЛОК 3: ПРОИЗВОДСТВО ===
        frame_export = tk.LabelFrame(self.frame_left, text="3. Производство (Экспорт)", padx=10, pady=10)
        frame_export.pack(fill=tk.X, pady=5)

        lbl_offset = tk.Label(frame_export, text="Компенсация подтравливания (Офсет, мм):", fg="blue", font=("Arial", 9, "bold"))
        lbl_offset.pack(anchor=tk.W)
        self.entry_offset = tk.Entry(frame_export, width=15, bg="#E6F2FF")
        self.entry_offset.insert(0, "0.05") 
        self.entry_offset.pack(anchor=tk.W, pady=(0, 5))
        
        self.btn_mask = tk.Button(frame_export, text="🖨 Создать УФ-Маску (.PDF)", bg="#9370DB", fg="white", font=("Arial", 10, "bold"), command=self.export_uv_mask)
        self.btn_mask.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame_export, text="Скорость реза ЧПУ (F):").pack(anchor=tk.W)
        self.entry_feedrate = tk.Entry(frame_export, width=15)
        self.entry_feedrate.insert(0, "1500")
        self.entry_feedrate.pack(anchor=tk.W, pady=(0, 5))

        self.btn_cnc = tk.Button(frame_export, text="⚙️ Сгенерировать УП (.TXT)", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=self.export_cnc)
        self.btn_cnc.pack(fill=tk.X, pady=2)

        # --- ЛОГИ ---
        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_clear_log = tk.Button(frame_log_btns, text="🗑 Очистить", command=self.clear_logs)
        self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_copy_log = tk.Button(frame_log_btns, text="📋 Копировать", command=self.copy_logs)
        self.btn_copy_log.pack(side=tk.RIGHT)
        self.text_log = tk.Text(frame_log, height=8, width=45, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        # === ПРАВАЯ ПАНЕЛЬ (ВИЗУАЛИЗАТОР И СЛОИ) ===
        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X, pady=(0, 5))
        self.btn_measure = tk.Button(frame_tools, text="📏 Инструмент: Замер расстояния", bg="#e0e0e0", command=self.toggle_measure)
        self.btn_measure.pack(side=tk.LEFT)

        frame_layers = tk.LabelFrame(self.frame_right, text="Слои видимости", padx=5, pady=5)
        frame_layers.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(frame_layers, text="Исходник (Серый)", fg="#555555", font=("Arial", 9, "bold"), variable=self.show_raw, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Вылеченный (Синий)", fg="#008888", font=("Arial", 9, "bold"), variable=self.show_healed, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="УФ-Маска (Пурпурный)", fg="#880088", font=("Arial", 9, "bold"), variable=self.show_mask, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Траектория УП (Зеленый)", fg="#008800", font=("Arial", 9, "bold"), variable=self.show_cnc, command=self.render_canvas).pack(side=tk.LEFT, padx=10)

        frame_canvas = tk.LabelFrame(self.frame_right, text="Предпросмотр (ЛКМ - Двигать | Колесико - Масштаб)", padx=5, pady=5)
        frame_canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame_canvas, bg="#1e1e1e", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<Motion>", self.on_mouse_move) 
        self.canvas.bind("<ButtonPress-3>", self.on_right_click) 
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)

    # --- ЛОГИКА ПРОЕКТОВ ---
    def create_project(self):
        filepath = filedialog.askopenfilename(
            title="Выберите исходный векторный макет",
            filetypes=(("Поддерживаемые макеты", "*.dxf *.svg *.pdf *.ai *.cdr *.eps"), ("Все файлы", "*.*"))
        )
        if not filepath: return
        
        proj_root = Path("Проекты")
        proj_root.mkdir(exist_ok=True)
        
        existing = [d.name for d in proj_root.iterdir() if d.is_dir() and d.name.startswith("Проект_")]
        nums = [int(n.split("_")[1]) for n in existing if n.split("_")[1].isdigit()]
        next_num = max(nums) + 1 if nums else 1
        
        proj_name = f"Проект_{next_num:03d}"
        self.current_project_dir = proj_root / proj_name
        self.current_project_dir.mkdir()
        
        (self.current_project_dir / "Травление").mkdir()
        (self.current_project_dir / "ЧПУ").mkdir()
        
        source_ext = Path(filepath).suffix
        project_source_file = self.current_project_dir / f"01_Исходник{source_ext}"
        shutil.copy2(filepath, project_source_file)
        
        self.input_filepath = project_source_file
        self.lbl_proj_info.config(text=f"Папка: {proj_name}\nМакет: {Path(filepath).name}", fg="black")
        
        self.canvas.delete("all")
        self.raw_paths = []
        self.ready_paths = []
        self.layers = {"raw": [], "healed": [], "mask": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.show_raw.set(True)
        self.show_healed.set(True)
        self.show_mask.set(True)
        self.show_cnc.set(True)
        
        self.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")
        self.log(f"-> Исходный макет скопирован в папку проекта.")
        self.log("-> Нажмите 'ШАГ 1' для извлечения векторов.")

    def export_uv_mask(self):
        # ЗАЩИТА: Проверяем, создан ли проект и пройдено ли лечение
        if not self.current_project_dir:
            return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ (Желтая кнопка)!")
        if not self.ready_paths:
            return messagebox.showwarning("Внимание", "Сначала вылечите деталь (ШАГ 3)!")
            
        try: offset = float(self.entry_offset.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат офсета!")
        
        mask_file = self.current_project_dir / "Травление" / "03_УФ_Маска.pdf"
        pipeline = CamPipeline()
        
        mask_paths = self._run_with_redirect(pipeline.generate_uv_mask_pdf, self.ready_paths, offset, mask_file)
        
        if mask_paths:
            self.layers["mask"] = mask_paths
            self.show_mask.set(True)
            self.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска успешно сгенерирована и сохранена в проект!")

    def export_cnc(self):
        # ЗАЩИТА: Проверяем, создан ли проект
        if not self.current_project_dir:
            return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ (Желтая кнопка)!")
        if not self.ready_paths:
            return messagebox.showwarning("Внимание", "Сначала вылечите деталь (ШАГ 3)!")
            
        try: f_rate = int(self.entry_feedrate.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат скорости!")
        
        cnc_file = self.current_project_dir / "ЧПУ" / "04_УП_Фрезер.txt"
        pipeline = CamPipeline(feedrate=f_rate)
        self._run_with_redirect(pipeline.generate_gcode, self.ready_paths, cnc_file)
        
        self.layers["cnc"] = self.ready_paths
        self.show_cnc.set(True)
        self.render_canvas()
        messagebox.showinfo("Готово", "Управляющая программа сохранена в папку ЧПУ.")

    # --- ИНСТРУМЕНТ ЗАМЕРА И ОТРИСОВКА ---
    def toggle_measure(self):
        self.is_measuring = not self.is_measuring
        if self.is_measuring:
            self.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
            self.canvas.config(cursor="target")
        else:
            self.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        x = (sx - self.current_tx) / self.current_scale
        y = (self.canvas_h - sy - self.current_ty) / self.current_scale
        return x, y

    def get_visible_paths(self):
        visible = []
        if self.show_raw.get(): visible.extend(self.layers["raw"])
        if self.show_healed.get(): visible.extend(self.layers["healed"])
        if self.show_mask.get(): visible.extend(self.layers["mask"])
        if self.show_cnc.get(): visible.extend(self.layers["cnc"])
        return visible

    def get_snapped_coords(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        if not visible_paths: return wx, wy
        
        snap_threshold_world = 15 / self.current_scale
        closest_dist = float('inf')
        closest_pt = None
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < closest_dist and dist < snap_threshold_world:
                    closest_dist = dist
                    closest_pt = pt
        return (closest_pt[0], closest_pt[1]) if closest_pt else (wx, wy)

    def on_left_click(self, event):
        self.canvas_h = self.canvas.winfo_height()
        if self.is_measuring:
            wx, wy = self.get_snapped_coords(event.x, event.y)
            if not self.measure_pt1:
                self.measure_pt1 = (wx, wy)
                self.log(f"-> Замер от: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.log(f"=== РАССТОЯНИЕ: {dist:.4f} мм ===")
                self.measure_pt1 = None
                self.canvas.delete("measure_dynamic")
                sx = wx * self.current_scale + self.current_tx
                sy = self.canvas_h - (wy * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00FF00", tags="measure_dynamic")
            return
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def on_right_click(self, event):
        if self.is_measuring and self.measure_pt1:
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")

    def on_mouse_move(self, event):
        if self.is_measuring and self.measure_pt1:
            self.canvas.delete("measure_dynamic")
            wx, wy = self.get_snapped_coords(event.x, event.y)
            dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
            sx1 = self.measure_pt1[0] * self.current_scale + self.current_tx
            sy1 = self.canvas_h - (self.measure_pt1[1] * self.current_scale + self.current_ty)
            sx2 = wx * self.current_scale + self.current_tx
            sy2 = self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FFD700", dash=(4, 4), tags="measure_dynamic")
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#FFD700", width=2, tags="measure_dynamic")
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")

    def on_pan_move(self, event):
        if self.is_measuring: return 
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y
        self.current_tx += dx
        self.current_ty -= dy 
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.render_canvas()

    def on_mousewheel(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0: zoom_factor = 1.1 
        elif event.num == 5 or getattr(event, 'delta', 0) < 0: zoom_factor = 0.9 
        else: return
        mx, my = event.x, event.y
        wx = (mx - self.current_tx) / self.current_scale
        wy = (self.canvas_h - my - self.current_ty) / self.current_scale
        self.current_scale *= zoom_factor
        self.current_tx = mx - wx * self.current_scale
        self.current_ty = self.canvas_h - my - wy * self.current_scale
        self.render_canvas()

    def fit_to_screen(self):
        visible_paths = self.get_visible_paths()
        if not visible_paths: return
        
        all_x = [pt[0] for path in visible_paths for pt in path.points]
        all_y = [pt[1] for path in visible_paths for pt in path.points]
        if not all_x or not all_y: return
        
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        width_mm, height_mm = max_x - min_x, max_y - min_y
        if width_mm == 0: width_mm = 1
        if height_mm == 0: height_mm = 1
        
        self.root.update() 
        canvas_w = self.canvas.winfo_width()
        self.canvas_h = self.canvas.winfo_height()
        pad = 30 
        scale_x = (canvas_w - 2 * pad) / width_mm
        scale_y = (self.canvas_h - 2 * pad) / height_mm
        self.current_scale = min(scale_x, scale_y)
        self.current_tx = (canvas_w - width_mm * self.current_scale) / 2 - min_x * self.current_scale
        self.current_ty = (self.canvas_h - height_mm * self.current_scale) / 2 - min_y * self.current_scale

    def render_canvas(self):
        self.canvas.delete("all")
        self.canvas_h = self.canvas.winfo_height()
        
        draw_order = [
            (self.show_mask, self.layers["mask"], "#FF1493", 3.0, None),      
            (self.show_raw, self.layers["raw"], "#AAAAAA", 1.0, None),        
            (self.show_healed, self.layers["healed"], "#00FFFF", 1.5, None),  
            (self.show_cnc, self.layers["cnc"], "#00FF00", 1.5, (5, 5))       
        ]
        
        for show_var, paths, color, width, dash in draw_order:
            if show_var.get() and paths:
                for path in paths:
                    if len(path.points) < 2: continue
                    screen_coords = []
                    for x, y in path.points:
                        sx = x * self.current_scale + self.current_tx
                        sy = self.canvas_h - (y * self.current_scale + self.current_ty)
                        screen_coords.extend([sx, sy])
                    if dash:
                        self.canvas.create_line(screen_coords, fill=color, width=width, capstyle=tk.ROUND, dash=dash)
                    else:
                        self.canvas.create_line(screen_coords, fill=color, width=width, capstyle=tk.ROUND)
            
        radius = 5
        colors = {"red": "#FF0000", "orange": "#FFA500", "magenta": "#FF00FF", "yellow": "#FFFF00"}
        for color_key, points in self.error_markers.items():
            color_hex = colors[color_key]
            for x, y in points:
                sx = x * self.current_scale + self.current_tx
                sy = self.canvas_h - (y * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius, outline=color_hex, width=2, tags="error_marker")

    # --- СИСТЕМНЫЕ ФУНКЦИИ ЛОГИРОВАНИЯ ---
    def log(self, message: str):
        self.text_log.config(state=tk.NORMAL)
        self.text_log.insert(tk.END, message + "\n")
        self.text_log.see(tk.END)
        self.text_log.config(state=tk.DISABLED)
        self.root.update()

    def copy_logs(self):
        log_content = self.text_log.get("1.0", tk.END).strip()
        if log_content:
            self.root.clipboard_clear()
            self.root.clipboard_append(log_content)
            messagebox.showinfo("Скопировано", "Логи скопированы!")
            
    def clear_logs(self):
        self.text_log.config(state=tk.NORMAL)
        self.text_log.delete("1.0", tk.END)
        self.text_log.config(state=tk.DISABLED)
        self.root.update()

    def _run_with_redirect(self, func, *args):
        class StdoutRedirector:
            def __init__(self, app): self.app = app
            def write(self, string):
                if string.strip(): self.app.log(string.strip())
            def flush(self): pass
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirector(self)
        try:
            return func(*args)
        except Exception as e:
            self.log(f"ОШИБКА: {e}")
            messagebox.showerror("Ошибка", str(e))
        finally:
            sys.stdout = old_stdout

    # --- ШАГИ ОБРАБОТКИ ---
    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        pipeline = CamPipeline()
        self.raw_paths = self._run_with_redirect(pipeline.step1_parse, self.input_filepath)
        
        if self.raw_paths:
            self.layers["raw"] = self.raw_paths
            self.layers["healed"] = []
            self.layers["mask"] = []
            self.layers["cnc"] = []
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.fit_to_screen()
            self.render_canvas()

    def do_step2(self):
        paths_to_check = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths_to_check: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        
        try: loop_area = float(self.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
            
        pipeline = CamPipeline(min_loop_area=loop_area)
        stats = self._run_with_redirect(pipeline.step2_check_errors, paths_to_check)
        
        if stats:
            self.error_markers = {
                "red": stats.get("error_nodes", []),
                "orange": stats.get("intersection_nodes", []),
                "magenta": stats.get("duplicate_nodes", []),
                "yellow": stats.get("dust_nodes", [])
            }
            self.render_canvas()

    def do_step3(self):
        if not self.raw_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try:
            tol = float(self.entry_tolerance.get())
            loop_area = float(self.entry_loop_area.get())
        except:
            return messagebox.showerror("Ошибка", "Неверный формат чисел!")
            
        pipeline = CamPipeline(tolerance=tol, min_loop_area=loop_area)
        paths_to_heal = self.ready_paths if self.ready_paths else self.raw_paths
        self.ready_paths = self._run_with_redirect(pipeline.step3_heal_and_optimize, paths_to_heal)
        
        if self.ready_paths:
            self.layers["healed"] = self.ready_paths
            self.render_canvas()
            
            if self.current_project_dir:
                healed_file = self.current_project_dir / "02_Вылеченный_Мастер.dxf"
                self._run_with_redirect(pipeline.save_source_dxf, self.ready_paths, healed_file)

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths = []
        self.layers["healed"] = []
        self.layers["mask"] = []
        self.layers["cnc"] = []
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.log("\n-> СБРОС: Геометрия возвращена к исходному состоянию.")
        self.render_canvas()