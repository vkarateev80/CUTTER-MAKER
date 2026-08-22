import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import sys
import os
import shutil
import datetime
import tempfile
import subprocess
import threading
import math

from src.pipeline.cam_pipeline import CamPipeline
from src.db.db_manager import DatabaseManager
from src.optimizer.distortion import DistortionCalculator, LayoutAnalyzer
from src.optimizer.pattern_recognition import PatternRecognizer
from src.gui.ui_builder import UIBuilder
from src.gui.canvas_manager import CanvasManager

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1400x900") 
        
        # --- СОСТОЯНИЕ ПРОЕКТА (Модель) ---
        self.input_filepath = None
        self.current_project_dir = None 
        
        self.raw_paths = []
        self.ready_paths = []
        self.distorted_paths = []
        self.mask_geom = None 
        
        # --- УМНЫЙ МАССИВ (Мастер-Штамп) ---
        self.is_array_layout = False
        self.array_offsets = []      # Смещения (dx, dy) для клонирования
        self.master_raw_paths = []   # Изолированные векторы одной этикетки
        
        self.layers = {"raw": [], "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.is_distorted = False
        self.applied_dist_axis = ""
        self.current_rapport = 0.0
        self.current_dist_factor = 1.0
        self.layout_mismatch = False
        self.layout_len_val = 0.0
        
        self.db = DatabaseManager()
        self.tools_list = []
        self.posts_list = []

        # --- ИНИЦИАЛИЗАЦИЯ VIEW И VIEWPORT ---
        self.ui = UIBuilder(self.root, self)
        self.canvas_manager = CanvasManager(self.ui.frame_canvas, self)
        self.canvas_manager.bind_keys(self.root)
        
        # Маппинг переменных UI для удобного доступа
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
        self.update_distortion_stats()

    # --- UI ХЕЛПЕРЫ И МЕНЕДЖЕРЫ ---
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
        self.tools_list = self.db.load_tools()
        self.posts_list = self.db.load_postprocessors()
        
        self.ui.combo_tool['values'] = [t.name for t in self.tools_list]
        if self.tools_list: self.ui.combo_tool.current(0)
            
        self.ui.combo_post['values'] = [p.name for p in self.posts_list]
        if self.posts_list: self.ui.combo_post.current(0)
        
        self._update_cnc_btn_text()

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
        self.distorted_paths = []
        self.layers["distorted"] = []
        self.ui.show_distorted.set(False)
        try:
            self.ui.btn_apply_dist.config(text="Сжать", bg="#4169E1", state=tk.NORMAL)
        except AttributeError: pass 

    def toggle_measure(self):
        if self.canvas_manager.is_delete_node_mode: self.toggle_delete_node_mode()
        state = not self.canvas_manager.is_measuring
        self.canvas_manager.set_measure_mode(state)
        if state: self.ui.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
        else: self.ui.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)

    def toggle_delete_node_mode(self):
        if self.canvas_manager.is_measuring: self.toggle_measure()
        state = not self.canvas_manager.is_delete_node_mode
        self.canvas_manager.set_delete_node_mode(state)
        if state:
            self.ui.btn_delete_node.config(bg="#FF6347", fg="white", relief=tk.SUNKEN)
            self.log("Режим удаления узлов Включен (Кликайте ЛКМ по узлам).")
        else:
            self.ui.btn_delete_node.config(bg="#e0e0e0", fg="black", relief=tk.RAISED)
            self.log("Режим удаления узлов Выключен.")

    def invalidate_downstream(self):
        self.mask_geom = None
        self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], []
        if self.ready_paths or self.raw_paths: self.ui.btn_mask.config(state=tk.NORMAL)
        else: self.ui.btn_mask.config(state=tk.DISABLED)
        self.ui.btn_cnc.config(state=tk.DISABLED)
        self.update_distortion_stats()

    # --- АСИНХРОННОСТЬ И ЛОГИРОВАНИЕ ---
    def _run_async(self, func, callback, *args):
        self.ui.lock_ui()
        self.canvas_manager.canvas.config(cursor="watch")
        self.ui.progress.start(15)

        def worker():
            class StdoutRedirector:
                def __init__(self, app): self.app = app
                def write(self, string):
                    if string.strip(): self.app.log(string.strip())
                def flush(self): pass
            
            old_stdout = sys.stdout
            sys.stdout = StdoutRedirector(self)
            try:
                res = func(*args)
                err = None
            except Exception as e:
                res = None
                err = e
            finally:
                sys.stdout = old_stdout
            self.root.after(0, self._on_async_done, callback, res, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_async_done(self, callback, res, err):
        self.ui.progress.stop()
        self.ui.unlock_ui()
        
        if self.canvas_manager.is_measuring: self.canvas_manager.canvas.config(cursor="target")
        elif self.canvas_manager.is_delete_node_mode: self.canvas_manager.canvas.config(cursor="X_cursor")
        else: self.canvas_manager.canvas.config(cursor="crosshair")
            
        if err:
            self.log(f"ОШИБКА: {err}")
            messagebox.showerror("Ошибка", str(err))
        elif callback:
            callback(res)

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

    # --- БИЗНЕС-ЛОГИКА (МЕТОДЫ ПАЙПЛАЙНА) ---
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
        self.ui.lbl_proj_info.config(text=f"Папка: {proj_name}\nМакет: {Path(filepath).name}", fg="black")
        
        self.canvas_manager.canvas.delete("all")
        self.raw_paths, self.ready_paths, self.distorted_paths = [], [], []
        self.master_raw_paths = []
        self.array_offsets = []
        self.is_array_layout = False
        
        self.mask_geom = None
        self.canvas_manager.selected_path = None
        self.canvas_manager.weld_anchor = None
        self.layers = {"raw": [], "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.ui.show_raw.set(True)
        self.ui.show_healed.set(True)
        self.ui.show_array.set(False)
        self.ui.show_distorted.set(False)
        self.ui.show_mask.set(True)
        self.ui.show_ideal.set(False)
        self.ui.show_cnc.set(True)
        self.ui.show_rapids.set(True)
        
        self.reset_distortion_state()
        self.update_distortion_stats()
        self.ui.lbl_array_info.config(text="Массив: Не анализировался", fg="#555555")
        self.invalidate_downstream()
        self.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths, self.mask_geom = [], None
        self.distorted_paths = []
        self.canvas_manager.selected_path = None
        self.canvas_manager.weld_anchor = None
        self.layers["healed"], self.layers["array"], self.layers["distorted"], self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], [], [], [], []
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.reset_distortion_state()
        self.ui.show_raw.set(True)
        self.ui.show_array.set(False)
        self.canvas_manager.render_canvas()
        self.update_distortion_stats()
        self.ui.lbl_array_info.config(text="Массив: Не анализировался", fg="#555555")
        self.invalidate_downstream()

    def update_distortion_stats(self, *args):
        try:
            z = int(self.ui.var_z.get())
            cp = float(self.ui.var_cp.get())
            undercut = float(self.ui.var_undercut.get())
            tp = float(self.ui.var_tp.get())
            tb = float(self.ui.var_tb.get())
            
            res = DistortionCalculator.calculate_factor(z, cp, undercut, tp, tb)
            self.ui.lbl_dist_stats.config(text=f"D_cyl: {res['d_cyl']} мм | K: {res['k_dist_percent']}%", fg="#00008B")
            self.current_dist_factor = res['k_dist']
            self.current_rapport = res['rapport']
            
            paths = self.ready_paths if self.ready_paths else self.raw_paths
            if paths and not self.is_distorted:
                axis = self.ui.var_dist_axis.get()
                layout_res = LayoutAnalyzer.analyze(paths, axis)
                layout_len = layout_res['layout_length']
                rows = layout_res['rows']
                
                if layout_len == 0:
                    self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: Не распознан", fg="gray")
                    self.layout_mismatch = False
                else:
                    diff = abs(self.current_rapport - layout_len)
                    if diff <= 0.15:
                        self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: {rows} ряд., {layout_len:.2f} мм (OK)", fg="#008800")
                        self.layout_mismatch = False
                    else:
                        self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: {layout_len:.2f} мм (ОШИБКА!)", fg="#FF0000")
                        self.layout_mismatch = True
                        self.layout_len_val = layout_len
            elif self.is_distorted:
                self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Сжато", fg="gray")
                self.layout_mismatch = False
            else:
                self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.current_rapport:.2f} мм | Макет: Нет данных", fg="gray")
                self.layout_mismatch = False
        except Exception:
            self.ui.lbl_dist_stats.config(text="D_cyl: Ошибка | K: Ошибка", fg="red")
            self.ui.lbl_layout_stats.config(text="Рапорт: Ошибка | Макет: Ошибка", fg="red")
            self.current_dist_factor = 1.0
            self.current_rapport = 0.0
            self.layout_mismatch = False

    # --- ШАГ 1: Извлечение и АВТО-АНАЛИЗ ---
    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self._run_async(CamPipeline().step1_parse, self._on_step1_done, self.input_filepath)

    def _on_step1_done(self, raw_paths):
        if raw_paths:
            self.raw_paths = raw_paths
            self.master_raw_paths = raw_paths
            self.is_array_layout = False
            self.array_offsets = []
            
            self.canvas_manager.selected_path = None
            self.canvas_manager.weld_anchor = None
            self.layers = {"raw": self.raw_paths, "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
            self.ready_paths = []
            self.distorted_paths = []
            self.mask_geom = None
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.reset_distortion_state()
            
            self.ui.show_raw.set(True)
            self.ui.show_array.set(False)
            
            self.log("Авто-анализ макета на наличие массива...")
            self._run_async(PatternRecognizer(tolerance=0.5).analyze, self._on_analyze_array_done, self.raw_paths)

    # --- АНАЛИЗ МАССИВА ---
    def do_analyze_array(self):
        paths = self.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет векторов для анализа! Сначала выполните ШАГ 1.")
        self.log("Запуск анализа массивов и межэтикеточных зазоров...")
        self._run_async(PatternRecognizer(tolerance=0.5).analyze, self._on_analyze_array_done, paths)

    def _on_analyze_array_done(self, result):
        if result and result.get("is_array"):
            self.is_array_layout = True
            self.array_offsets = result["offsets"]
            self.master_raw_paths = result["master_paths"]
            
            msg = (f"Массив: {result['cols']} колонок х {result['rows']} рядов (Всего: {result['count']} шт)\n"
                   f"Шаг: X = {result['step_x']} мм | Y = {result['step_y']} мм\n"
                   f"Зазор: X = {result['gap_x']} мм | Y = {result['gap_y']} мм")
            self.ui.lbl_array_info.config(text=msg, fg="#008800")
            self.log(f"Умный Мастер-Штамп активирован! Выделен 1 эталон, сохранено {len(self.array_offsets)} смещений.")
        else:
            self.is_array_layout = False
            self.array_offsets = []
            self.master_raw_paths = self.raw_paths
            self.ui.lbl_array_info.config(text="Массив: Не найден (одиночный штамп или хаос)", fg="#FF4500")
            self.log("Анализ массива: Закономерная сетка не найдена. Работаем как с обычным макетом.")
            
        self.canvas_manager.fit_to_screen()
        self.canvas_manager.render_canvas()
        self.update_distortion_stats()
        self.invalidate_downstream()

    # --- ГЕНЕРАТОР МАССИВОВ (Step & Repeat) ---
    def open_array_generator(self):
        paths = self.master_raw_paths if self.master_raw_paths else self.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет векторов для размножения! Сначала выполните ШАГ 1.")
            
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x or not all_y: return
            
        label_w = max(all_x) - min(all_x)
        label_h = max(all_y) - min(all_y)

        dialog = tk.Toplevel(self.root)
        dialog.title("Генератор массива (Step & Repeat)")
        dialog.geometry("400x320")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text=f"Габарит штампа: {label_w:.2f} x {label_h:.2f} мм", fg="blue", font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky=tk.W)
        tk.Label(frame, text=f"Рапорт шестерни (Z={self.ui.var_z.get()}): {self.current_rapport:.2f} мм", fg="gray", font=("Arial", 9)).grid(row=1, column=0, columnspan=2, pady=(0, 15), sticky=tk.W)

        tk.Label(frame, text="Колонки (X):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ent_cols = tk.Entry(frame, width=10)
        ent_cols.insert(0, "5")
        ent_cols.grid(row=2, column=1, sticky=tk.W, pady=5)

        tk.Label(frame, text="Зазор по X (мм):").grid(row=3, column=0, sticky=tk.W, pady=5)
        ent_gap_x = tk.Entry(frame, width=10)
        ent_gap_x.insert(0, "3.0")
        ent_gap_x.grid(row=3, column=1, sticky=tk.W, pady=5)

        tk.Label(frame, text="Ряды (Y):").grid(row=4, column=0, sticky=tk.W, pady=5)
        ent_rows = tk.Entry(frame, width=10)
        ent_rows.insert(0, "1")
        ent_rows.grid(row=4, column=1, sticky=tk.W, pady=5)

        tk.Label(frame, text="Зазор по Y (мм):").grid(row=5, column=0, sticky=tk.W, pady=5)
        ent_gap_y = tk.Entry(frame, width=10)
        ent_gap_y.insert(0, "3.0")
        ent_gap_y.grid(row=5, column=1, sticky=tk.W, pady=5)

        # --- АВТОРАСЧЕТ ПО Y (БЕСШОВНЫЙ СТЫК) ---
        def auto_calc_y():
            try:
                min_gap = 3.0
                rapport = self.current_rapport
                if rapport <= 0:
                    messagebox.showerror("Ошибка", "Рапорт не рассчитан! Проверьте параметры шестерни Z и CP.")
                    return
                
                max_rows = int(rapport // (label_h + min_gap))
                
                if max_rows < 1:
                    messagebox.showerror("Ошибка", f"Этикетка ({label_h:.2f} мм) слишком большая для рапорта {rapport:.2f} мм!")
                    return
                
                actual_step = rapport / max_rows
                actual_gap = actual_step - label_h
                
                ent_rows.delete(0, tk.END)
                ent_rows.insert(0, str(max_rows))
                
                ent_gap_y.delete(0, tk.END)
                ent_gap_y.insert(0, f"{actual_gap:.3f}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        btn_auto = tk.Button(frame, text="✨ Авто-подбор Y (под шестерню)", bg="#E6E6FA", font=("Arial", 8, "bold"), command=auto_calc_y)
        btn_auto.grid(row=4, column=2, rowspan=2, padx=10, sticky=tk.NS)

        def on_generate():
            try:
                cols = int(ent_cols.get())
                rows = int(ent_rows.get())
                gap_x = float(ent_gap_x.get())
                gap_y = float(ent_gap_y.get())
            except ValueError:
                messagebox.showerror("Ошибка", "Введите корректные числа!")
                return
                
            if cols < 1 or rows < 1:
                messagebox.showerror("Ошибка", "Количество должно быть >= 1")
                return

            step_x = label_w + gap_x
            step_y = label_h + gap_y

            offsets = []
            for c in range(cols):
                for r in range(rows):
                    offsets.append((c * step_x, -r * step_y))

            self.is_array_layout = True
            self.array_offsets = offsets
            self.master_raw_paths = paths
            
            msg = (f"Сгенерирован массив: {cols} кол х {rows} ряд (Всего: {cols*rows} шт)\n"
                   f"Шаг: X = {step_x:.3f} мм | Y = {step_y:.3f} мм\n"
                   f"Зазор: X = {gap_x:.3f} мм | Y = {gap_y:.3f} мм")
            self.ui.lbl_array_info.config(text=msg, fg="#FFA500")
            
            dialog.destroy()
            
            self.log("Генерация сетки массива...")
            self._run_async(CamPipeline().multiply_paths, self._on_generate_array_done, self.master_raw_paths, self.array_offsets)

        btn_gen = tk.Button(frame, text="✅ Применить", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), command=on_generate)
        btn_gen.grid(row=6, column=0, columnspan=3, pady=(15, 0), sticky=tk.EW)

    def _on_generate_array_done(self, preview_paths):
        if preview_paths:
            self.raw_paths = preview_paths
            self.layers["raw"] = preview_paths
            
            self.ready_paths = []
            self.layers["healed"] = []
            self.layers["array"] = []
            self.layers["distorted"] = []
            self.reset_distortion_state()
            self.invalidate_downstream()

            self.ui.show_raw.set(True)
            self.ui.show_array.set(False)
            
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()
            self.update_distortion_stats()
            self.log("Успех: Массив сгенерирован. Нажмите ШАГ 3 для умного лечения.")

    # --- ШАГ 2: Проверка ---
    def do_step2(self):
        paths = self.master_raw_paths if self.master_raw_paths else self.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: loop_area = float(self.ui.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        
        def task(): return CamPipeline(min_loop_area=loop_area).step2_check_errors(paths)
        self._run_async(task, self._on_step2_done)

    def _on_step2_done(self, stats):
        if stats:
            self.error_markers = {"red": stats.get("error_nodes", []), "orange": stats.get("intersection_nodes", []), "magenta": stats.get("duplicate_nodes", []), "yellow": stats.get("dust_nodes", [])}
            self.canvas_manager.render_canvas()

    # --- ШАГ 3: УМНОЕ ЛЕЧЕНИЕ ---
    def do_step3(self):
        if not self.raw_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: 
            tol = float(self.ui.entry_tolerance.get())
            loop_area = float(self.ui.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        
        def task(master_paths, offsets, t, a, proj_dir):
            pipeline = CamPipeline(tolerance=t, min_loop_area=a)
            healed_master = pipeline.step3_heal_and_optimize(master_paths)
            array_paths = pipeline.multiply_paths(healed_master, offsets) if offsets else []
            final_geom = array_paths if array_paths else healed_master
            if final_geom and proj_dir:
                pipeline.save_source_dxf(final_geom, proj_dir / "02_Вылеченный_Мастер.dxf")
            return healed_master, array_paths
            
        self._run_async(task, self._on_step3_done, self.master_raw_paths, self.array_offsets, tol, loop_area, self.current_project_dir)

    def _on_step3_done(self, result):
        if result:
            healed_master, array_paths = result
            self.canvas_manager.selected_path = None
            self.canvas_manager.weld_anchor = None
            self.layers["healed"] = healed_master
            self.layers["array"] = array_paths
            self.ready_paths = array_paths if array_paths else healed_master
            
            self.ui.show_raw.set(False) 
            if array_paths:
                self.ui.show_healed.set(False)
                self.ui.show_array.set(True)
            else:
                self.ui.show_healed.set(True)
                self.ui.show_array.set(False)
                
            self.canvas_manager.render_canvas()
            self.update_distortion_stats()
            self.invalidate_downstream()

    # --- ОСТАЛЬНЫЕ МЕТОДЫ ---
    def do_apply_distortion(self):
        if self.is_distorted:
            if not messagebox.askyesno("Внимание", "Дисторсия уже применена. Пересчитать и обновить слой сжатия?"): return
            
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Нет векторов для масштабирования! Сначала выполните ШАГ 1.")
            
        if self.layout_mismatch:
            msg = f"Внимание! Распознанный шаг макета по оси {self.ui.var_dist_axis.get()} ({self.layout_len_val:.2f} мм)\n" \
                  f"не совпадает с рапортом шестерни Z{self.ui.var_z.get()} ({self.current_rapport:.2f} мм).\n\n" \
                  f"Штамп не сойдется на цилиндре (зазор или нахлест).\n" \
                  f"Вы уверены, что хотите применить дисторсию принудительно?"
            if not messagebox.askyesno("Критическое несовпадение", msg, icon='warning'): return
            
        axis = self.ui.var_dist_axis.get()
        base_paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        
        self._run_async(CamPipeline().apply_distortion, lambda res: self._on_apply_distortion_done(res, axis), base_paths, self.current_dist_factor, axis)

    def _on_apply_distortion_done(self, new_paths, axis):
        if new_paths:
            self.canvas_manager.selected_path = None
            self.distorted_paths = new_paths
            self.layers["distorted"] = new_paths
            self.is_distorted = True
            self.applied_dist_axis = axis
            self.ui.btn_apply_dist.config(text=f"✅ Сжато ({axis})", bg="#2E8B57")
            
            self.ui.show_healed.set(False)
            self.ui.show_array.set(False)
            self.ui.show_distorted.set(True)
            
            self.invalidate_downstream()
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()
            self.log(f"Успех: Дисторсия ({self.current_dist_factor:.4f}) по оси {axis} применена на отдельный слой.")

    def do_rotate_90(self):
        def task(raw, ready, dist, array):
            pipeline = CamPipeline()
            res_raw = pipeline.rotate_geometry(raw, 90.0) if raw else []
            res_ready = pipeline.rotate_geometry(ready, 90.0) if ready else []
            res_dist = pipeline.rotate_geometry(dist, 90.0) if dist else []
            res_array = pipeline.rotate_geometry(array, 90.0) if array else []
            return res_raw, res_ready, res_dist, res_array
        self._run_async(task, self._on_rotate_90_done, self.raw_paths, self.layers["healed"], self.distorted_paths, self.layers["array"])

    def _on_rotate_90_done(self, result):
        if result:
            self.raw_paths, healed_paths, self.distorted_paths, array_paths = result
            
            if self.raw_paths: self.layers["raw"] = self.raw_paths
            if healed_paths: self.layers["healed"] = healed_paths
            if array_paths: self.layers["array"] = array_paths
            if self.distorted_paths: self.layers["distorted"] = self.distorted_paths
                
            self.ready_paths = array_paths if array_paths else healed_paths
                
            if self.is_distorted:
                self.applied_dist_axis = "X" if self.applied_dist_axis == "Y" else "Y"
                self.ui.btn_apply_dist.config(text=f"✅ Сжато ({self.applied_dist_axis})")
                
            self.invalidate_downstream()
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()

    def do_add_crop_marks(self):
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Нет макета для добавления меток! Выполните ШАГ 1.")
        
        try: margin = float(self.ui.entry_crop_margin.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат отступа!")
        
        if self.current_rapport <= 0: return messagebox.showwarning("Внимание", "Рапорт не рассчитан! Проверьте параметры шестерни.")
            
        paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        axis = self.applied_dist_axis if self.is_distorted else self.ui.var_dist_axis.get()
        
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x or not all_y: return messagebox.showwarning("Внимание", "Векторы не содержат точек!")
        
        if axis.upper() == 'Y':
            actual_width = max(all_x) - min(all_x)
        else:
            actual_width = max(all_y) - min(all_y)
            
        total_width = actual_width + (2.0 * margin)
        self.log(f"Авто-расчет меток: Габарит {actual_width:.2f}мм + Отступы {margin*2}мм = Ширина {total_width:.2f}мм")
        
        self._run_async(CamPipeline().add_crop_marks, self._on_add_crop_marks_done, paths, self.current_rapport, total_width, axis)

    def _on_add_crop_marks_done(self, new_paths):
        if new_paths:
            self.canvas_manager.selected_path = None
            if self.ready_paths:
                self.ready_paths = new_paths
                if self.layers["array"]: self.layers["array"] = new_paths
                else: self.layers["healed"] = new_paths
            else:
                self.raw_paths = new_paths
                self.layers["raw"] = new_paths
            self.invalidate_downstream()
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()
            self.log("Успех: Обрезные метки добавлены.")

    def export_uv_mask(self):
        if not self.current_project_dir or not (self.ready_paths or self.raw_paths): 
            return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ и ВЫЛЕЧИТЕ деталь!")
        try: 
            offset = float(self.ui.entry_offset.get())
            mark_d = float(self.ui.entry_mark_d.get())
            mark_margin = float(self.ui.entry_mark_margin.get())
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
        
        if self.is_distorted and self.distorted_paths: main_paths = self.distorted_paths
        else: main_paths = [p for p in (self.ready_paths if self.ready_paths else self.raw_paths) if p.layer_name != "CROP_MARKS"]
            
        crop_marks = [p for p in (self.ready_paths if self.ready_paths else self.raw_paths) if p.layer_name == "CROP_MARKS"]
        paths_for_mask = main_paths + crop_marks
        
        if not paths_for_mask: return messagebox.showwarning("Внимание", "Нет векторов для создания маски!")
        self._run_async(CamPipeline().generate_uv_mask_pdf, self._on_export_uv_mask_done, paths_for_mask, offset, mask_file, final_badge_text, mark_d, mark_margin)

    def _on_export_uv_mask_done(self, result_paths):
        if result_paths:
            visual_paths, pure_paths, mask_geom = result_paths
            self.layers["mask"] = visual_paths
            self.mask_geom = mask_geom
            self.ui.show_mask.set(True)
            self.ui.btn_cnc.config(state=tk.NORMAL)
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска с метками и кастомной инфо-панелью успешно сохранена.")

    def export_cnc(self):
        if not self.mask_geom: return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску!\nЧПУ использует контуры маски как базовые для расчета лезвия.")
        try: 
            offset = float(self.ui.entry_offset.get())
            lead_radius = float(self.ui.entry_lead_radius.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат чисел в настройках!")
            
        idx_tool = self.ui.combo_tool.current()
        idx_post = self.ui.combo_post.current()
        if idx_tool < 0 or idx_post < 0: return messagebox.showerror("Ошибка", "Выберите инструмент и постпроцессор!")
            
        selected_tool = self.tools_list[idx_tool]
        selected_post = self.posts_list[idx_post]
        ext = selected_post.extension
        if not ext.startswith('.'): ext = '.' + ext
        
        initial_dir = self.current_project_dir / "ЧПУ"
        initial_file = f"04_УП_Фрезер{ext}"
        
        filepath = filedialog.asksaveasfilename(
            title="Сохранить управляющую программу",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=ext,
            filetypes=[(f"G-code файлы ({ext})", f"*{ext}"), ("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
        )
        if not filepath:
            self.log("Сохранение УП отменено пользователем.")
            return
            
        cnc_file = Path(filepath)
        sharpen = self.ui.enable_sharpening.get()
        
        # Извлекаем направление фрезеровки (Climb или Conventional)
        milling_dir_raw = self.ui.var_milling_dir.get()
        milling_dir = "Conventional" if "Conventional" in milling_dir_raw else "Climb"
        
        self._run_async(CamPipeline().generate_gcode, lambda res: self._on_export_cnc_done(res, cnc_file), self.mask_geom, cnc_file, selected_tool, selected_post, offset, sharpen, lead_radius, milling_dir)

    def _on_export_cnc_done(self, result_data, cnc_file):
        if result_data:
            ideal_paths, cnc_paths, time_min = result_data
            self.layers["ideal"] = ideal_paths
            self.layers["cnc"] = cnc_paths
            self.ui.show_ideal.set(True)
            self.ui.show_cnc.set(True)
            self.canvas_manager.render_canvas()
            
            hours = int(time_min // 60)
            minutes = int(time_min % 60)
            seconds = int((time_min * 60) % 60)
            
            if hours > 0:
                time_str = f"{hours} ч {minutes} мин"
            else:
                time_str = f"{minutes} мин {seconds} сек"
                
            self.log(f"Расчетное время фрезеровки: {time_str}")
            
            msg = f"УП успешно сохранена:\n{cnc_file.name}\n\n⏱ Примерное время фрезеровки: {time_str}"
            messagebox.showinfo("Готово", msg)

    def do_live_edit(self):
        paths_to_edit = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths_to_edit: return messagebox.showwarning("Внимание", "Нет векторов для редактирования! Сначала выполните ШАГ 1.")
        
        def task():
            temp_dir = Path(tempfile.gettempdir())
            safe_svg = temp_dir / f"cam_live_edit_{os.getpid()}.svg"
            print("Экспорт геометрии во временный SVG...")
            pipeline = CamPipeline()
            pipeline.export_paths_to_svg(paths_to_edit, safe_svg)
            project_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(os.getcwd())
            inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe' if os.name == 'nt' else Path('inkscape')
            print("Ожидание завершения работы Inkscape...")
            print("-> Внесите изменения, нажмите Ctrl+S и закройте Inkscape.")
            
            subprocess.run([str(inkscape_exe), str(safe_svg)])
            print("Inkscape закрыт. Чтение изменений...")
            new_paths = pipeline.step1_parse(safe_svg)
            if safe_svg.exists():
                try: safe_svg.unlink()
                except: pass
            return new_paths

        self._run_async(task, self._on_live_edit_done)

    def _on_live_edit_done(self, new_paths):
        if new_paths:
            self.canvas_manager.selected_path = None
            self.canvas_manager.weld_anchor = None
            
            if self.is_array_layout:
                self.layers["array"] = new_paths
                self.ready_paths = new_paths
            elif self.ready_paths:
                self.layers["healed"] = new_paths
                self.ready_paths = new_paths
            else:
                self.raw_paths = new_paths
                self.layers["raw"] = new_paths
                
            self.invalidate_downstream()
            self.canvas_manager.fit_to_screen()
            self.canvas_manager.render_canvas()
            self.log("Векторы успешно обновлены из Inkscape!")
            messagebox.showinfo("Live Edit", "Изменения успешно применены!")
        else:
            self.log("Внимание: Файл пуст или сохранен некорректно.")