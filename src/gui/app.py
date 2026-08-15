import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import sys
import math

from src.pipeline.cam_pipeline import CamPipeline
from src.parser.geometry import CamPath

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LaserCAM Pro - Итеративная обработка")
        self.root.geometry("1200x700") 
        
        self.input_filepath = None
        self.raw_paths: list[CamPath] = []
        self.ready_paths: list[CamPath] = []
        
        self.paths_to_draw: list[CamPath] = []
        self.path_color = "#00FFFF"
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.current_scale = 1.0
        self.current_tx = 0.0 
        self.current_ty = 0.0 
        self.canvas_h = 0
        self.pan_start_x = 0
        self.pan_start_y = 0
        
        self.is_measuring = False
        self.measure_pt1 = None 
        
        self._build_ui()

    def _build_ui(self):
        self.frame_left = tk.Frame(self.root, width=450)
        self.frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        frame_file = tk.LabelFrame(self.frame_left, text="Файл и Настройки", padx=10, pady=10)
        frame_file.pack(fill=tk.X, pady=5)
        
        self.btn_select = tk.Button(frame_file, text="Выбрать вектор", command=self.select_file)
        self.btn_select.pack(anchor=tk.W, pady=(0, 5))
        
        self.lbl_filepath = tk.Label(frame_file, text="Файл не выбран", fg="gray", wraplength=400, justify=tk.LEFT)
        self.lbl_filepath.pack(anchor=tk.W, pady=(0, 10))
        
        tk.Label(frame_file, text="Скорость реза (F):").pack(anchor=tk.W)
        self.entry_feedrate = tk.Entry(frame_file, width=15)
        self.entry_feedrate.insert(0, "1500")
        self.entry_feedrate.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_file, text="Допуск лечения (мм):").pack(anchor=tk.W)
        self.entry_tolerance = tk.Entry(frame_file, width=15)
        self.entry_tolerance.insert(0, "0.01")
        self.entry_tolerance.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_file, text="Удалять пыль/петли < (мм/мм²):").pack(anchor=tk.W)
        self.entry_loop_area = tk.Entry(frame_file, width=15)
        self.entry_loop_area.insert(0, "1.0") 
        self.entry_loop_area.pack(anchor=tk.W)

        frame_steps = tk.LabelFrame(self.frame_left, text="Пошаговая Итеративная Обработка", padx=10, pady=10)
        frame_steps.pack(fill=tk.X, pady=10)
        
        self.btn_step1 = tk.Button(frame_steps, text="ШАГ 1: Открыть и извлечь векторы", bg="#e0e0e0", command=self.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        
        self.btn_step2 = tk.Button(frame_steps, text="ШАГ 2: Анализ геометрии (Поиск ошибок)", bg="#e0e0e0", command=self.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        
        self.btn_step3 = tk.Button(frame_steps, text="ШАГ 3: Вылечить и Оптимизировать", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)
        
        self.btn_reset = tk.Button(frame_steps, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=2)
        
        self.btn_step4 = tk.Button(frame_steps, text="ШАГ 4: Сгенерировать G-код (.TXT)", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=self.do_step4)
        self.btn_step4.pack(fill=tk.X, pady=10)

        # --- ОБНОВЛЕННЫЙ ФРЕЙМ ЛОГОВ С ДВУМЯ КНОПКАМИ ---
        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        
        self.btn_clear_log = tk.Button(frame_log_btns, text="🗑 Очистить", command=self.clear_logs)
        self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.btn_copy_log = tk.Button(frame_log_btns, text="📋 Копировать", command=self.copy_logs)
        self.btn_copy_log.pack(side=tk.RIGHT)
        
        self.text_log = tk.Text(frame_log, height=10, width=45, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        # --- ПРАВАЯ ПАНЕЛЬ ---
        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X)
        self.btn_measure = tk.Button(frame_tools, text="📏 Инструмент: Замер расстояния", bg="#e0e0e0", command=self.toggle_measure)
        self.btn_measure.pack(side=tk.LEFT, pady=5)

        frame_canvas = tk.LabelFrame(self.frame_right, text="Предпросмотр (Навигация: ЛКМ - Двигать | Колесико - Масштаб | ПКМ - Отмена замера)", padx=5, pady=5)
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

    # --- ЛОГИКА ИНСТРУМЕНТА ЗАМЕРА ---
    def toggle_measure(self):
        self.is_measuring = not self.is_measuring
        if self.is_measuring:
            self.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
            self.canvas.config(cursor="target")
            self.log("\n-> ИНСТРУМЕНТ ЗАМЕРА ВКЛЮЧЕН.")
            self.log("-> Кликните на любую точку чертежа.")
        else:
            self.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")
            self.log("\n-> ИНСТРУМЕНТ ЗАМЕРА ВЫКЛЮЧЕН.")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        x = (sx - self.current_tx) / self.current_scale
        y = (self.canvas_h - sy - self.current_ty) / self.current_scale
        return x, y

    def get_snapped_coords(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        if not self.paths_to_draw:
            return wx, wy
            
        snap_threshold_screen = 15 
        snap_threshold_world = snap_threshold_screen / self.current_scale
        
        closest_dist = float('inf')
        closest_pt = None
        
        for path in self.paths_to_draw:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < closest_dist and dist < snap_threshold_world:
                    closest_dist = dist
                    closest_pt = pt
                    
        if closest_pt:
            return closest_pt[0], closest_pt[1] 
        return wx, wy 

    def on_left_click(self, event):
        self.canvas_h = self.canvas.winfo_height()
        
        if self.is_measuring:
            wx, wy = self.get_snapped_coords(event.x, event.y)
            
            if not self.measure_pt1:
                self.measure_pt1 = (wx, wy)
                self.log(f"-> Точка 1: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.log(f"-> Точка 2: X={wx:.3f}, Y={wy:.3f}")
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
            self.log("-> Замер отменен.")

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
            
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", 
                                    fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")

    def on_pan_move(self, event):
        if self.is_measuring: return 
        if not self.paths_to_draw: return
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y
        self.current_tx += dx
        self.current_ty -= dy 
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.render_canvas()

    def on_mousewheel(self, event):
        if not self.paths_to_draw: return
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
        if not self.paths_to_draw: return
        all_x = [pt[0] for path in self.paths_to_draw for pt in path.points]
        all_y = [pt[1] for path in self.paths_to_draw for pt in path.points]
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
        if not self.paths_to_draw: return
        self.canvas_h = self.canvas.winfo_height()
        
        for path in self.paths_to_draw:
            if len(path.points) < 2: continue
            screen_coords = []
            for x, y in path.points:
                sx = x * self.current_scale + self.current_tx
                sy = self.canvas_h - (y * self.current_scale + self.current_ty)
                screen_coords.extend([sx, sy])
            self.canvas.create_line(screen_coords, fill=self.path_color, width=1.5, capstyle=tk.ROUND)
            
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
        """Очищает текстовое окно логов."""
        self.text_log.config(state=tk.NORMAL)
        self.text_log.delete("1.0", tk.END)
        self.text_log.config(state=tk.DISABLED)
        self.root.update()

    def select_file(self):
        filepath = filedialog.askopenfilename(
            title="Выберите векторный файл",
            filetypes=(("Поддерживаемые макеты", "*.dxf *.svg *.pdf *.ai *.cdr *.eps"), ("Все файлы", "*.*"))
        )
        if filepath:
            self.input_filepath = Path(filepath)
            self.lbl_filepath.config(text=self.input_filepath.name, fg="black")
            self.log(f"\n--- Выбран новый файл: {self.input_filepath.name} ---")
            self.canvas.delete("all")
            self.raw_paths = []
            self.ready_paths = []
            self.paths_to_draw = []
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}

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

    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Выберите файл!")
        pipeline = CamPipeline()
        self.raw_paths = self._run_with_redirect(pipeline.step1_parse, self.input_filepath)
        self.ready_paths = []
        if self.raw_paths:
            self.paths_to_draw = self.raw_paths
            self.path_color = "#AAAAAA" 
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.fit_to_screen()
            self.render_canvas()

    def do_step2(self):
        paths_to_check = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths_to_check: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        
        try:
            loop_area = float(self.entry_loop_area.get())
        except:
            return messagebox.showerror("Ошибка", "Неверный формат чисел!")
            
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
            
            if any(self.error_markers.values()):
                msg = []
                if stats["open_paths"] > 0: msg.append(f"Разрывов: {stats['open_paths']}")
                if stats["intersections"] > 0: msg.append(f"Пересечений: {stats['intersections']}")
                if stats["duplicates"] > 0: msg.append(f"Задвоений: {stats['duplicates']}")
                if stats["dust"] > 0: msg.append(f"Мусор/Артефакты: {stats['dust']}")
                messagebox.showwarning("Найдены конфликты", " | ".join(msg) + "\n\nОни подсвечены маркерами на чертеже.")
            else:
                messagebox.showinfo("Анализ завершен", "Геометрия идеальна, ошибок нет.")

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
            self.paths_to_draw = self.ready_paths
            self.path_color = "#00FFFF" 
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.render_canvas()
            self.log(f"-> Итерация лечения завершена (Допуск: {tol}, Пыль: {loop_area})")

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths = []
        self.paths_to_draw = self.raw_paths
        self.path_color = "#AAAAAA"
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.log("\n-> СБРОС: Геометрия возвращена к исходному состоянию.")
        self.render_canvas()

    def do_step4(self):
        if not self.ready_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 3!")
        try:
            f_rate = int(self.entry_feedrate.get())
        except:
            return messagebox.showerror("Ошибка", "Неверный формат скорости!")
        output_filepath = self.input_filepath.with_suffix('.txt')
        pipeline = CamPipeline(feedrate=f_rate)
        self._run_with_redirect(pipeline.step4_generate_gcode, self.ready_paths, output_filepath)
        messagebox.showinfo("Готово", f"G-код сохранен:\n{output_filepath.name}")