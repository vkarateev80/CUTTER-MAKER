import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import sys
import math
import shutil
import datetime

from src.pipeline.cam_pipeline import CamPipeline
from src.parser.geometry import CamPath

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1300x850") 
        
        self.input_filepath = None
        self.raw_paths, self.ready_paths, self.paths_to_draw = [], [], []
        self.cnc_base_paths = [] 
        
        self.layers = {"raw": [], "healed": [], "mask": [], "cnc": []}
        self.show_raw, self.show_healed, self.show_mask, self.show_cnc = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        # Переменная для галочки "Подрезка углов" (по умолчанию включена)
        self.enable_sharpening = tk.BooleanVar(value=True)
        
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.current_scale, self.current_tx, self.current_ty, self.canvas_h = 1.0, 0.0, 0.0, 0
        self.is_measuring, self.measure_pt1 = False, None 
        self.current_project_dir = None 
        self._build_ui()

    def _build_ui(self):
        self.frame_left = tk.Frame(self.root, width=450)
        self.frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        frame_proj = tk.LabelFrame(self.frame_left, text="1. Управление Проектом", padx=10, pady=10)
        frame_proj.pack(fill=tk.X, pady=5)
        self.btn_create_proj = tk.Button(frame_proj, text="📁 СОЗДАТЬ ПРОЕКТ И ВЫБРАТЬ МАКЕТ", bg="#FFD700", font=("Arial", 10, "bold"), command=self.create_project)
        self.btn_create_proj.pack(fill=tk.X, pady=(0, 5))
        self.lbl_proj_info = tk.Label(frame_proj, text="Проект не создан", fg="gray", justify=tk.LEFT, wraplength=400)
        self.lbl_proj_info.pack(anchor=tk.W)

        frame_prep = tk.LabelFrame(self.frame_left, text="2. Анализ и Лечение", padx=10, pady=10)
        frame_prep.pack(fill=tk.X, pady=5)
        tk.Label(frame_prep, text="Допуск лечения (мм):").pack(anchor=tk.W)
        self.entry_tolerance = tk.Entry(frame_prep, width=15); self.entry_tolerance.insert(0, "0.01"); self.entry_tolerance.pack(anchor=tk.W, pady=(0, 5))
        tk.Label(frame_prep, text="Удалять пыль/петли < (мм/мм²):").pack(anchor=tk.W)
        self.entry_loop_area = tk.Entry(frame_prep, width=15); self.entry_loop_area.insert(0, "1.0"); self.entry_loop_area.pack(anchor=tk.W, pady=(0, 10))

        self.btn_step1 = tk.Button(frame_prep, text="ШАГ 1: Извлечь векторы", bg="#e0e0e0", command=self.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        self.btn_step2 = tk.Button(frame_prep, text="ШАГ 2: Анализ ошибок", bg="#e0e0e0", command=self.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        self.btn_step3 = tk.Button(frame_prep, text="ШАГ 3: Вылечить (Автосохранение)", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)

        self.btn_reset = tk.Button(frame_prep, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=2)

        frame_export = tk.LabelFrame(self.frame_left, text="3. Производство (Экспорт)", padx=10, pady=10)
        frame_export.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_export, text="Компенсация подтравливания (Офсет, мм):", fg="blue", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.entry_offset = tk.Entry(frame_export, width=15, bg="#E6F2FF"); self.entry_offset.insert(0, "0.05"); self.entry_offset.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_export, text="Реперные метки D / Отступ (мм):").pack(anchor=tk.W)
        frame_marks_inputs = tk.Frame(frame_export)
        frame_marks_inputs.pack(fill=tk.X, pady=(0, 5))
        self.entry_mark_d = tk.Entry(frame_marks_inputs, width=6)
        self.entry_mark_d.insert(0, "4.0")
        self.entry_mark_d.pack(side=tk.LEFT, padx=(0, 5))
        self.entry_mark_margin = tk.Entry(frame_marks_inputs, width=6)
        self.entry_mark_margin.insert(0, "10.0")
        self.entry_mark_margin.pack(side=tk.LEFT)

        self.btn_mask = tk.Button(frame_export, text="🖨 Создать УФ-Маску (.PDF)", bg="#9370DB", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_uv_mask)
        self.btn_mask.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame_export, text="V-Фреза (Угол° / Пятно / Глуб. Z / Шаг Z):").pack(anchor=tk.W, pady=(5, 0))
        frame_cnc_inputs = tk.Frame(frame_export)
        frame_cnc_inputs.pack(fill=tk.X, pady=(0, 5))
        
        self.entry_cnc_angle = tk.Entry(frame_cnc_inputs, width=5)
        self.entry_cnc_angle.insert(0, "60.0")
        self.entry_cnc_angle.pack(side=tk.LEFT, padx=(0, 5))
        
        self.entry_cnc_tip = tk.Entry(frame_cnc_inputs, width=5)
        self.entry_cnc_tip.insert(0, "0.1")
        self.entry_cnc_tip.pack(side=tk.LEFT, padx=(0, 5))
        
        self.entry_cnc_depth = tk.Entry(frame_cnc_inputs, width=5)
        self.entry_cnc_depth.insert(0, "0.5")
        self.entry_cnc_depth.pack(side=tk.LEFT, padx=(0, 5))
        
        self.entry_cnc_step = tk.Entry(frame_cnc_inputs, width=5)
        self.entry_cnc_step.insert(0, "0.2") 
        self.entry_cnc_step.pack(side=tk.LEFT)

        # Чекбокс для вкл/выкл подрезки углов
        tk.Checkbutton(frame_export, text="Включить 3D-подрезку внутренних углов", fg="#FF4500", font=("Arial", 9, "bold"), variable=self.enable_sharpening).pack(anchor=tk.W, pady=(2, 5))

        tk.Label(frame_export, text="Скорость реза ЧПУ (F):").pack(anchor=tk.W)
        self.entry_feedrate = tk.Entry(frame_export, width=15); self.entry_feedrate.insert(0, "1500"); self.entry_feedrate.pack(anchor=tk.W, pady=(0, 5))
        self.btn_cnc = tk.Button(frame_export, text="⚙️ Сгенерировать УП (.TXT)", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_cnc)
        self.btn_cnc.pack(fill=tk.X, pady=2)

        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_clear_log = tk.Button(frame_log_btns, text="🗑 Очистить", command=self.clear_logs); self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_copy_log = tk.Button(frame_log_btns, text="📋 Копировать", command=self.copy_logs); self.btn_copy_log.pack(side=tk.RIGHT)
        self.text_log = tk.Text(frame_log, height=8, width=45, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X, pady=(0, 5))
        self.btn_measure = tk.Button(frame_tools, text="📏 Замер", bg="#e0e0e0", command=self.toggle_measure); self.btn_measure.pack(side=tk.LEFT)
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
        self.raw_paths, self.ready_paths, self.cnc_base_paths = [], [], []
        self.layers = {"raw": [], "healed": [], "mask": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.show_raw.set(True); self.show_healed.set(True); self.show_mask.set(True); self.show_cnc.set(True)
        self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)
        self.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")

    def export_uv_mask(self):
        if not self.current_project_dir or not self.ready_paths: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ и ВЫЛЕЧИТЕ деталь!")
        
        try: 
            offset = float(self.entry_offset.get())
            mark_d = float(self.entry_mark_d.get())
            mark_margin = float(self.entry_mark_margin.get())
        except ValueError: 
            return messagebox.showerror("Ошибка", "Неверный формат чисел!")

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

        def on_cancel():
            dialog.destroy()

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
            visual_paths, pure_paths = result_paths
            self.layers["mask"] = visual_paths
            self.cnc_base_paths = pure_paths 
            
            self.show_mask.set(True)
            self.fit_to_screen()
            self.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска с метками и кастомной инфо-панелью успешно сохранена.")

    def export_cnc(self):
        if not self.cnc_base_paths: 
            return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску!\nЧПУ использует контуры маски как базовые для расчета лезвия.")
            
        try: 
            f_rate = int(self.entry_feedrate.get())
            angle = float(self.entry_cnc_angle.get())
            tip = float(self.entry_cnc_tip.get())
            depth = float(self.entry_cnc_depth.get())
            step_z = float(self.entry_cnc_step.get())
        except ValueError: 
            return messagebox.showerror("Ошибка", "Неверный формат чисел в настройках инструмента ЧПУ!")
            
        cnc_file = self.current_project_dir / "ЧПУ" / "04_УП_Фрезер.txt"
        
        # Получаем значение галочки
        sharpen = self.enable_sharpening.get()
        
        generated_paths = self._run_with_redirect(CamPipeline(feedrate=f_rate).generate_gcode, self.cnc_base_paths, cnc_file, angle, tip, depth, step_z, sharpen)
        
        if generated_paths:
            self.layers["cnc"] = generated_paths
            self.show_cnc.set(True)
            self.render_canvas()
            messagebox.showinfo("Готово", "УП сохранена! Зеленая траектория построена на основе УФ-Маски.")

    def toggle_measure(self):
        self.is_measuring = not self.is_measuring
        if self.is_measuring: self.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN); self.canvas.config(cursor="target")
        else: self.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED); self.canvas.config(cursor="crosshair"); self.measure_pt1 = None; self.canvas.delete("measure_dynamic")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        return (sx - self.current_tx) / self.current_scale, (self.canvas_h - sy - self.current_ty) / self.current_scale

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
        closest_dist, closest_pt = float('inf'), None
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < closest_dist and dist < snap_threshold_world: closest_dist, closest_pt = dist, pt
        return (closest_pt[0], closest_pt[1]) if closest_pt else (wx, wy)

    def on_left_click(self, event):
        self.canvas_h = self.canvas.winfo_height()
        if self.is_measuring:
            wx, wy = self.get_snapped_coords(event.x, event.y)
            if not self.measure_pt1: self.measure_pt1 = (wx, wy); self.log(f"-> Замер от: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.log(f"=== РАССТОЯНИЕ: {dist:.4f} мм ===")
                self.measure_pt1 = None
                self.canvas.delete("measure_dynamic")
                sx, sy = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00FF00", tags="measure_dynamic")
            return
        self.pan_start_x, self.pan_start_y = event.x, event.y

    def on_right_click(self, event):
        if self.is_measuring and self.measure_pt1: self.measure_pt1 = None; self.canvas.delete("measure_dynamic")

    def on_mouse_move(self, event):
        if self.is_measuring and self.measure_pt1:
            self.canvas.delete("measure_dynamic")
            wx, wy = self.get_snapped_coords(event.x, event.y)
            dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
            sx1, sy1 = self.measure_pt1[0] * self.current_scale + self.current_tx, self.canvas_h - (self.measure_pt1[1] * self.current_scale + self.current_ty)
            sx2, sy2 = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FFD700", dash=(4, 4), tags="measure_dynamic")
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#FFD700", width=2, tags="measure_dynamic")
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")

    def on_pan_move(self, event):
        if self.is_measuring: return 
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
        for show_var, paths, color, width, dash in [(self.show_mask, self.layers["mask"], "#FF1493", 3.0, None), (self.show_raw, self.layers["raw"], "#AAAAAA", 1.0, None), (self.show_healed, self.layers["healed"], "#00FFFF", 1.5, None), (self.show_cnc, self.layers["cnc"], "#00FF00", 1.5, (5, 5))]:
            if show_var.get() and paths:
                for path in paths:
                    if len(path.points) < 2: continue
                    coords = []
                    for pt in path.points: 
                        x, y = pt[0], pt[1]
                        coords.extend([x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)])
                    
                    if path.layer_name == "SHARPEN":
                        self.canvas.create_line(coords, fill="#FF0000", width=2.0, capstyle=tk.ROUND)
                    else:
                        self.canvas.create_line(coords, fill=color, width=width, capstyle=tk.ROUND, dash=dash) if dash else self.canvas.create_line(coords, fill=color, width=width, capstyle=tk.ROUND)
        
        colors = {"red": "#FF0000", "orange": "#FFA500", "magenta": "#FF00FF", "yellow": "#FFFF00"}
        for k, pts in self.error_markers.items():
            for x, y in pts:
                sx, sy = x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-5, sy-5, sx+5, sy+5, outline=colors[k], width=2, tags="error_marker")

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

    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self.raw_paths = self._run_with_redirect(CamPipeline().step1_parse, self.input_filepath)
        if self.raw_paths:
            self.layers["raw"] = self.raw_paths; self.layers["healed"], self.layers["mask"], self.layers["cnc"], self.cnc_base_paths = [], [], [], []
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.fit_to_screen(); self.render_canvas()

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
            self.layers["healed"] = self.ready_paths; self.render_canvas()
            self.btn_mask.config(state=tk.NORMAL); self.btn_cnc.config(state=tk.NORMAL)
            if self.current_project_dir: self._run_with_redirect(CamPipeline().save_source_dxf, self.ready_paths, self.current_project_dir / "02_Вылеченный_Мастер.dxf")

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths, self.cnc_base_paths, self.layers["healed"], self.layers["mask"], self.layers["cnc"] = [], [], [], [], []
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.render_canvas(); self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)