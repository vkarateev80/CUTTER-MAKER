import tkinter as tk
from tkinter import filedialog, messagebox
import json
from pathlib import Path
import sys
import os
import shutil
import datetime
import tempfile
import subprocess
import threading
import math
import shapely.affinity

from src.pipeline.cam_pipeline import CamPipeline
from src.pipeline.report_generator import ReportGenerator
from src.optimizer.distortion import DistortionCalculator, LayoutAnalyzer
from src.optimizer.pattern_recognition import PatternRecognizer
from src.parser.geometry import CamPath

class AppController:
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
            self.app.root.after(0, self._on_async_done, callback, res, err)

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

    def save_project(self):
        if not self.project.current_project_dir:
            messagebox.showwarning("Внимание", "Нет активного проекта для сохранения.")
            return
        
        state_file = self.project.current_project_dir / "project_state.json"
        
        ui_data = {
            "tolerance": self.ui.entry_tolerance.get(),
            "loop_area": self.ui.entry_loop_area.get(),
            "crop_margin": self.ui.entry_crop_margin.get(),
            "z": self.ui.var_z.get(),
            "cp": self.ui.var_cp.get(),
            "tp": self.ui.var_tp.get(),
            "tb": self.ui.var_tb.get(),
            "undercut": self.ui.var_undercut.get(),
            "dist_axis": self.ui.var_dist_axis.get(),
            "offset": self.ui.entry_offset.get(),
            "mark_d": self.ui.entry_mark_d.get(),
            "mark_margin": self.ui.entry_mark_margin.get(),
            "lead_radius": self.ui.entry_lead_radius.get(),
            "milling_dir": self.ui.var_milling_dir.get(),
            "enable_sharpening": self.ui.enable_sharpening.get()
        }
        
        data = self.project.to_dict(ui_data)
        
        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.app.log("Проект успешно сохранен!")
            messagebox.showinfo("Успех", "Проект успешно сохранен!")
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))

    def load_project(self):
        filepath = filedialog.askopenfilename(title="Выберите файл проекта", filetypes=[("JSON Файлы проекта", "project_state.json")])
        if not filepath: return
            
        state_file = Path(filepath)
        self.project.current_project_dir = state_file.parent
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            self.project.from_dict(data)
            
            ui_data = data.get("ui", {})
            def set_entry(entry, val):
                entry.delete(0, tk.END)
                entry.insert(0, str(val))
                
            set_entry(self.ui.entry_tolerance, ui_data.get("tolerance", "2.0"))
            set_entry(self.ui.entry_loop_area, ui_data.get("loop_area", "1.0"))
            set_entry(self.ui.entry_crop_margin, ui_data.get("crop_margin", "10.0"))
            self.ui.var_z.set(ui_data.get("z", "96"))
            self.ui.var_cp.set(ui_data.get("cp", "3.175"))
            self.ui.var_tp.set(ui_data.get("tp", "0.44"))
            self.ui.var_tb.set(ui_data.get("tb", "0.24"))
            self.ui.var_undercut.set(ui_data.get("undercut", "0.48"))
            self.ui.var_dist_axis.set(ui_data.get("dist_axis", "Y"))
            set_entry(self.ui.entry_offset, ui_data.get("offset", "0.2"))
            set_entry(self.ui.entry_mark_d, ui_data.get("mark_d", "4.0"))
            set_entry(self.ui.entry_mark_margin, ui_data.get("mark_margin", "10.0"))
            set_entry(self.ui.entry_lead_radius, ui_data.get("lead_radius", "1.5"))
            self.ui.var_milling_dir.set(ui_data.get("milling_dir", "Climb (Попутное)"))
            self.ui.enable_sharpening.set(ui_data.get("enable_sharpening", True))
            
            self.ui.btn_save_proj.config(state=tk.NORMAL)
            if self.project.ready_paths or self.project.raw_paths: self.ui.btn_mask.config(state=tk.NORMAL)
            
            if self.project.mask_geom: 
                self.ui.btn_cnc.config(state=tk.NORMAL)
                self.ui.btn_calibrate.config(state=tk.NORMAL)
                
            if self.project.last_milling_time_min > 0: self.ui.btn_report.config(state=tk.NORMAL)
            
            self.update_distortion_stats()
            
            msg = (f"Массив: Загружен из сохранения\nВсего смещений: {len(self.project.array_offsets)}") if self.project.is_array_layout else "Массив: Не найден"
            self.ui.lbl_array_info.config(text=msg, fg="#008800" if self.project.is_array_layout else "#555555")
            
            if self.project.is_distorted: self.ui.btn_apply_dist.config(text=f"✅ Сжато ({self.project.applied_dist_axis})", bg="#2E8B57")
            else: self.ui.btn_apply_dist.config(text="Сжать", bg="#4169E1")

            self.canvas.selected_path = None
            self.canvas.weld_anchor = None
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            
            self.app.log(f"=== ПРОЕКТ {self.project.current_project_dir.name} УСПЕШНО ЗАГРУЖЕН ===")
            self.ui.lbl_proj_info.config(text=f"Папка: {self.project.current_project_dir.name}\nМакет загружен из сохранения", fg="black")
            messagebox.showinfo("Успех", "Проект успешно загружен!")
            
        except Exception as e:
            messagebox.showerror("Ошибка загрузки", str(e))
            self.app.log(f"Ошибка загрузки проекта: {e}")

    def create_project(self):
        filepath = filedialog.askopenfilename(title="Выберите макет", filetypes=(("Поддерживаемые макеты", "*.dxf *.svg *.pdf *.ai *.cdr *.eps"), ("Все файлы", "*.*")))
        if not filepath: return
        proj_root = Path("Проекты")
        proj_root.mkdir(exist_ok=True)
        existing = [d.name for d in proj_root.iterdir() if d.is_dir() and d.name.startswith("Проект_")]
        nums = [int(n.split("_")[1]) for n in existing if n.split("_")[1].isdigit()]
        proj_name = f"Проект_{max(nums) + 1 if nums else 1:03d}"
        self.project.current_project_dir = proj_root / proj_name
        self.project.current_project_dir.mkdir()
        (self.project.current_project_dir / "Травление").mkdir()
        (self.project.current_project_dir / "ЧПУ").mkdir()
        
        project_source_file = self.project.current_project_dir / f"01_Исходник{Path(filepath).suffix}"
        shutil.copy2(filepath, project_source_file)
        self.project.input_filepath = project_source_file
        self.ui.lbl_proj_info.config(text=f"Папка: {proj_name}\nМакет: {Path(filepath).name}", fg="black")
        
        self.canvas.canvas.delete("all")
        self.project.reset_data()
        
        self.canvas.selected_path = None
        self.canvas.weld_anchor = None
        
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
        
        self.ui.btn_save_proj.config(state=tk.NORMAL)
        self.app.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")

    def do_reset(self):
        if not self.project.raw_paths: return
        self.project.ready_paths = []
        self.project.mask_geom = None
        self.project.distorted_paths = []
        self.canvas.selected_path = None
        self.canvas.weld_anchor = None
        
        self.project.layers["healed"], self.project.layers["array"], self.project.layers["distorted"] = [], [], []
        self.project.layers["mask"], self.project.layers["ideal"], self.project.layers["cnc"] = [], [], []
        self.project.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.reset_distortion_state()
        self.ui.show_raw.set(True)
        self.ui.show_array.set(False)
        self.canvas.render_canvas()
        self.update_distortion_stats()
        self.ui.lbl_array_info.config(text="Массив: Не анализировался", fg="#555555")
        self.invalidate_downstream()

    def reset_distortion_state(self):
        self.project.is_distorted = False
        self.project.applied_dist_axis = ""
        self.project.distorted_paths = []
        self.project.layers["distorted"] = []
        self.ui.show_distorted.set(False)
        try:
            self.ui.btn_apply_dist.config(text="Сжать", bg="#4169E1", state=tk.NORMAL)
        except AttributeError: pass 

    def toggle_measure(self):
        if self.canvas.is_delete_node_mode: self.toggle_delete_node_mode()
        state = not self.canvas.is_measuring
        self.canvas.set_measure_mode(state)
        if state: self.ui.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
        else: self.ui.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)

    def toggle_delete_node_mode(self):
        if self.canvas.is_measuring: self.toggle_measure()
        state = not self.canvas.is_delete_node_mode
        self.canvas.set_delete_node_mode(state)
        if state:
            self.ui.btn_delete_node.config(bg="#FF6347", fg="white", relief=tk.SUNKEN)
            self.app.log("Режим удаления узлов Включен (Кликайте ЛКМ по узлам).")
        else:
            self.ui.btn_delete_node.config(bg="#e0e0e0", fg="black", relief=tk.RAISED)
            self.app.log("Режим удаления узлов Выключен.")

    def invalidate_downstream(self):
        self.project.mask_geom = None
        self.project.layers["mask"], self.project.layers["ideal"], self.project.layers["cnc"] = [], [], []
        if self.project.ready_paths or self.project.raw_paths: self.ui.btn_mask.config(state=tk.NORMAL)
        else: self.ui.btn_mask.config(state=tk.DISABLED)
        
        if self.project.mask_geom:
            self.ui.btn_cnc.config(state=tk.NORMAL)
            self.ui.btn_calibrate.config(state=tk.NORMAL)
        else:
            self.ui.btn_cnc.config(state=tk.DISABLED)
            self.ui.btn_calibrate.config(state=tk.DISABLED)
            
        self.project.last_milling_time_min = 0.0
        self.ui.btn_report.config(state=tk.DISABLED)
        self.update_distortion_stats()

    def auto_guess_z(self):
        """Автоматически подбирает зуб шестерни (Z) на основе высоты/ширины макета"""
        paths = self.project.ready_paths if self.project.ready_paths else self.project.raw_paths
        if not paths or self.project.is_distorted:
            return
            
        axis = self.ui.var_dist_axis.get()
        layout_res = LayoutAnalyzer.analyze(paths, axis)
        layout_len = layout_res['layout_length']
        
        # Если LayoutAnalyzer не нашел ряды, измеряем просто по Bounding Box всего макета
        if layout_len == 0:
            all_coords = []
            for p in paths:
                if p.layer_name == "CROP_MARKS": continue
                if axis.upper() == 'Y':
                    all_coords.extend([pt[1] for pt in p.points])
                else:
                    all_coords.extend([pt[0] for pt in p.points])
            if all_coords:
                layout_len = max(all_coords) - min(all_coords)

        if layout_len > 0:
            try:
                cp = float(self.ui.var_cp.get())
                if cp > 0:
                    estimated_z = max(1, int(round(layout_len / cp)))
                    current_z = self.ui.var_z.get()
                    if current_z != str(estimated_z):
                        self.ui.var_z.set(str(estimated_z))
                        self.app.log(f"Авто-настройка: Зуб шестерни установлен в Z={estimated_z} (под размер макета {layout_len:.2f} мм)")
            except ValueError:
                pass

    def update_distortion_stats(self, *args):
        try:
            z = int(self.ui.var_z.get())
            cp = float(self.ui.var_cp.get())
            undercut = float(self.ui.var_undercut.get())
            tp = float(self.ui.var_tp.get())
            tb = float(self.ui.var_tb.get())
            
            res = DistortionCalculator.calculate_factor(z, cp, undercut, tp, tb)
            self.ui.lbl_dist_stats.config(text=f"D_cyl: {res['d_cyl']} мм | K: {res['k_dist_percent']}%", fg="#00008B")
            self.project.current_dist_factor = res['k_dist']
            self.project.current_rapport = res['rapport']
            
            paths = self.project.ready_paths if self.project.ready_paths else self.project.raw_paths
            if paths and not self.project.is_distorted:
                axis = self.ui.var_dist_axis.get()
                layout_res = LayoutAnalyzer.analyze(paths, axis)
                layout_len = layout_res['layout_length']
                rows = layout_res['rows']
                
                if layout_len == 0:
                    self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.project.current_rapport:.2f} мм | Макет: Не распознан", fg="gray")
                    self.project.layout_mismatch = False
                else:
                    diff = abs(self.project.current_rapport - layout_len)
                    if diff <= 0.15:
                        self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.project.current_rapport:.2f} мм | Макет: {rows} ряд., {layout_len:.2f} мм (OK)", fg="#008800")
                        self.project.layout_mismatch = False
                    else:
                        self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.project.current_rapport:.2f} мм | Макет: {layout_len:.2f} мм (ОШИБКА!)", fg="#FF0000")
                        self.project.layout_mismatch = True
                        self.project.layout_len_val = layout_len
            elif self.project.is_distorted:
                self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.project.current_rapport:.2f} мм | Сжато", fg="gray")
                self.project.layout_mismatch = False
            else:
                self.ui.lbl_layout_stats.config(text=f"Рапорт: {self.project.current_rapport:.2f} мм | Макет: Нет данных", fg="gray")
                self.project.layout_mismatch = False
        except Exception:
            self.ui.lbl_dist_stats.config(text="D_cyl: Ошибка | K: Ошибка", fg="red")
            self.ui.lbl_layout_stats.config(text="Рапорт: Ошибка | Макет: Ошибка", fg="red")
            self.project.current_dist_factor = 1.0
            self.project.current_rapport = 0.0
            self.project.layout_mismatch = False

    def do_step1(self):
        if not self.project.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self._run_async(CamPipeline().step1_parse, self._on_step1_done, self.project.input_filepath)

    def _on_step1_done(self, raw_paths):
        if raw_paths:
            self.project.raw_paths = raw_paths
            self.project.master_raw_paths = raw_paths
            self.project.is_array_layout = False
            self.project.array_offsets = []
            
            self.canvas.selected_path = None
            self.canvas.weld_anchor = None
            self.project.layers = {"raw": self.project.raw_paths, "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
            self.project.ready_paths = []
            self.project.distorted_paths = []
            self.project.mask_geom = None
            self.project.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.reset_distortion_state()
            
            self.ui.show_raw.set(True)
            self.ui.show_array.set(False)
            
            self.auto_guess_z()
            self.update_distortion_stats()
            
            self.app.log("Авто-анализ макета на наличие массива...")
            self._run_async(PatternRecognizer(tolerance=0.5).analyze, self._on_analyze_array_done, self.project.raw_paths)

    def do_analyze_array(self):
        paths = self.project.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Нет векторов для анализа! Сначала выполните ШАГ 1.")
        self.app.log("Запуск анализа массивов и межэтикеточных зазоров...")
        self._run_async(PatternRecognizer(tolerance=0.5).analyze, self._on_analyze_array_done, paths)

    def _on_analyze_array_done(self, result):
        if result and result.get("is_array"):
            self.project.is_array_layout = True
            self.project.array_offsets = result["offsets"]
            self.project.master_raw_paths = result["master_paths"]
            
            msg = (f"Массив: {result['cols']} колонок х {result['rows']} рядов (Всего: {result['count']} шт)\n"
                   f"Шаг: X = {result['step_x']} мм | Y = {result['step_y']} мм\n"
                   f"Зазор: X = {result['gap_x']} мм | Y = {result['gap_y']} мм")
            self.ui.lbl_array_info.config(text=msg, fg="#008800")
            self.app.log(f"Умный Мастер-Штамп активирован! Выделен 1 эталон, сохранено {len(self.project.array_offsets)} смещений.")
        else:
            self.project.is_array_layout = False
            self.project.array_offsets = []
            self.project.master_raw_paths = self.project.raw_paths
            self.ui.lbl_array_info.config(text="Массив: Не найден (одиночный штамп или хаос)", fg="#FF4500")
            self.app.log("Анализ массива: Закономерная сетка не найдена. Работаем как с обычным макетом.")
            
        self.canvas.fit_to_screen()
        self.canvas.render_canvas()
        self.update_distortion_stats()
        self.invalidate_downstream()

    def open_array_generator(self):
        paths = self.project.master_raw_paths if self.project.master_raw_paths else self.project.raw_paths
        if not paths:
            return messagebox.showwarning("Внимание", "Нет векторов для размножения! Сначала выполните ШАГ 1.")
            
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x or not all_y: return
            
        label_w = max(all_x) - min(all_x)
        label_h = max(all_y) - min(all_y)

        dialog = tk.Toplevel(self.app.root)
        dialog.title("Генератор массива (Step & Repeat)")
        dialog.geometry("400x320")
        dialog.transient(self.app.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text=f"Габарит штампа: {label_w:.2f} x {label_h:.2f} мм", fg="blue", font=("Arial", 9, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky=tk.W)
        tk.Label(frame, text=f"Рапорт шестерни (Z={self.ui.var_z.get()}): {self.project.current_rapport:.2f} мм", fg="gray", font=("Arial", 9)).grid(row=1, column=0, columnspan=2, pady=(0, 15), sticky=tk.W)

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

        def auto_calc_y():
            try:
                min_gap = 3.0
                rapport = self.project.current_rapport
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
            except Exception as e: messagebox.showerror("Ошибка", str(e))

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

            self.project.is_array_layout = True
            self.project.array_offsets = offsets
            self.project.master_raw_paths = paths
            
            msg = (f"Сгенерирован массив: {cols} кол х {rows} ряд (Всего: {cols*rows} шт)\n"
                   f"Шаг: X = {step_x:.3f} мм | Y = {step_y:.3f} мм\n"
                   f"Зазор: X = {gap_x:.3f} мм | Y = {gap_y:.3f} мм")
            self.ui.lbl_array_info.config(text=msg, fg="#FFA500")
            
            dialog.destroy()
            self.app.log("Генерация сетки массива...")
            self._run_async(CamPipeline().multiply_paths, self._on_generate_array_done, self.project.master_raw_paths, self.project.array_offsets)

        btn_gen = tk.Button(frame, text="✅ Применить", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), command=on_generate)
        btn_gen.grid(row=6, column=0, columnspan=3, pady=(15, 0), sticky=tk.EW)

    def _on_generate_array_done(self, preview_paths):
        if preview_paths:
            self.project.raw_paths = preview_paths
            self.project.layers["raw"] = preview_paths
            self.project.ready_paths = []
            self.project.layers["healed"] = []
            self.project.layers["array"] = []
            self.project.layers["distorted"] = []
            self.reset_distortion_state()
            self.invalidate_downstream()

            self.ui.show_raw.set(True)
            self.ui.show_array.set(False)
            
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            
            self.auto_guess_z()
            self.update_distortion_stats()
            self.app.log("Успех: Массив сгенерирован. Нажмите ШАГ 3 для умного лечения.")

    def do_step2(self):
        paths = self.project.master_raw_paths if self.project.master_raw_paths else self.project.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: loop_area = float(self.ui.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        def task(): return CamPipeline(min_loop_area=loop_area).step2_check_errors(paths)
        self._run_async(task, self._on_step2_done)

    def _on_step2_done(self, stats):
        if stats:
            self.project.error_markers = {"red": stats.get("error_nodes", []), "orange": stats.get("intersection_nodes", []), "magenta": stats.get("duplicate_nodes", []), "yellow": stats.get("dust_nodes", [])}
            self.canvas.render_canvas()

    def do_step3(self):
        if not self.project.raw_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
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
            
        self._run_async(task, self._on_step3_done, self.project.master_raw_paths, self.project.array_offsets, tol, loop_area, self.project.current_project_dir)

    def _on_step3_done(self, result):
        if result:
            healed_master, array_paths = result
            self.canvas.selected_path = None
            self.canvas.weld_anchor = None
            self.project.layers["healed"] = healed_master
            self.project.layers["array"] = array_paths
            self.project.ready_paths = array_paths if array_paths else healed_master
            
            self.ui.show_raw.set(False) 
            if array_paths:
                self.ui.show_healed.set(False)
                self.ui.show_array.set(True)
            else:
                self.ui.show_healed.set(True)
                self.ui.show_array.set(False)
                
            self.canvas.render_canvas()
            self.update_distortion_stats()
            self.invalidate_downstream()

    def do_apply_distortion(self):
        if self.project.is_distorted:
            if not messagebox.askyesno("Внимание", "Дисторсия уже применена. Пересчитать и обновить слой сжатия?"): return
            
        paths = self.project.ready_paths if self.project.ready_paths else self.project.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Нет векторов для масштабирования! Сначала выполните ШАГ 1.")
            
        if self.project.layout_mismatch:
            msg = f"Внимание! Распознанный шаг макета по оси {self.ui.var_dist_axis.get()} ({self.project.layout_len_val:.2f} мм)\n" \
                  f"не совпадает с рапортом шестерни Z{self.ui.var_z.get()} ({self.project.current_rapport:.2f} мм).\n\n" \
                  f"Штамп не сойдется на цилиндре (зазор или нахлест).\n" \
                  f"Вы уверены, что хотите применить дисторсию принудительно?"
            if not messagebox.askyesno("Критическое несовпадение", msg, icon='warning'): return
            
        axis = self.ui.var_dist_axis.get()
        base_paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        
        self._run_async(CamPipeline().apply_distortion, lambda res: self._on_apply_distortion_done(res, axis), base_paths, self.project.current_dist_factor, axis)

    def _on_apply_distortion_done(self, new_paths, axis):
        if new_paths:
            self.canvas.selected_path = None
            self.project.distorted_paths = new_paths
            self.project.layers["distorted"] = new_paths
            self.project.is_distorted = True
            self.project.applied_dist_axis = axis
            self.ui.btn_apply_dist.config(text=f"✅ Сжато ({axis})", bg="#2E8B57")
            
            self.ui.show_healed.set(False)
            self.ui.show_array.set(False)
            self.ui.show_distorted.set(True)
            
            self.invalidate_downstream()
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            self.app.log(f"Успех: Дисторсия ({self.project.current_dist_factor:.4f}) по оси {axis} применена на отдельный слой.")

    def do_rotate_90(self):
        def task(raw, ready, dist, array):
            pipeline = CamPipeline()
            res_raw = pipeline.rotate_geometry(raw, 90.0) if raw else []
            res_ready = pipeline.rotate_geometry(ready, 90.0) if ready else []
            res_dist = pipeline.rotate_geometry(dist, 90.0) if dist else []
            res_array = pipeline.rotate_geometry(array, 90.0) if array else []
            return res_raw, res_ready, res_dist, res_array
        self._run_async(task, self._on_rotate_90_done, self.project.raw_paths, self.project.layers.get("healed", []), self.project.distorted_paths, self.project.layers.get("array", []))

    def _on_rotate_90_done(self, result):
        if result:
            self.project.raw_paths, healed_paths, self.project.distorted_paths, array_paths = result
            
            if self.project.raw_paths: self.project.layers["raw"] = self.project.raw_paths
            if healed_paths: self.project.layers["healed"] = healed_paths
            if array_paths: self.project.layers["array"] = array_paths
            if self.project.distorted_paths: self.project.layers["distorted"] = self.project.distorted_paths
                
            self.project.ready_paths = array_paths if array_paths else healed_paths
                
            if self.project.is_distorted:
                self.project.applied_dist_axis = "X" if self.project.applied_dist_axis == "Y" else "Y"
                self.ui.btn_apply_dist.config(text=f"✅ Сжато ({self.project.applied_dist_axis})")
                
            self.invalidate_downstream()
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            self.auto_guess_z()

    def do_add_crop_marks(self):
        paths = self.project.ready_paths if self.project.ready_paths else self.project.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Нет макета для добавления меток! Выполните ШАГ 1.")
        
        try: margin = float(self.ui.entry_crop_margin.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат отступа!")
        
        if self.project.current_rapport <= 0: return messagebox.showwarning("Внимание", "Рапорт не рассчитан! Проверьте параметры шестерни.")
            
        paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        axis = self.project.applied_dist_axis if self.project.is_distorted else self.ui.var_dist_axis.get()
        
        all_x = [pt[0] for p in paths for pt in p.points]
        all_y = [pt[1] for p in paths for pt in p.points]
        if not all_x or not all_y: return messagebox.showwarning("Внимание", "Векторы не содержат точек!")
        
        if axis.upper() == 'Y': actual_width = max(all_x) - min(all_x)
        else: actual_width = max(all_y) - min(all_y)
            
        total_width = actual_width + (2.0 * margin)
        self.app.log(f"Авто-расчет меток: Габарит {actual_width:.2f}мм + Отступы {margin*2}мм = Ширина {total_width:.2f}мм")
        
        self._run_async(CamPipeline().add_crop_marks, self._on_add_crop_marks_done, paths, self.project.current_rapport, total_width, axis)

    def _on_add_crop_marks_done(self, new_paths):
        if new_paths:
            self.canvas.selected_path = None
            if self.project.ready_paths:
                self.project.ready_paths = new_paths
                if self.project.layers["array"]: self.project.layers["array"] = new_paths
                else: self.project.layers["healed"] = new_paths
            else:
                self.project.raw_paths = new_paths
                self.project.layers["raw"] = new_paths
            self.invalidate_downstream()
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            self.app.log("Успех: Обрезные метки добавлены.")

    def export_uv_mask(self):
        if not self.project.current_project_dir or not (self.project.ready_paths or self.project.raw_paths): 
            return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ и ВЫЛЕЧИТЕ деталь!")
        try: 
            offset = float(self.ui.entry_offset.get())
            mark_d = float(self.ui.entry_mark_d.get())
            mark_margin = float(self.ui.entry_mark_margin.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат чисел!")

        date_str = datetime.datetime.now().strftime("%d.%m.%Y")
        project_name = self.project.current_project_dir.name
        default_text = f"{project_name} | Офсет: {offset} мм | Метки: D{mark_d} мм | Дата: {date_str}"

        dialog = tk.Toplevel(self.app.root)
        dialog.title("Настройка инфо-панели")
        dialog.geometry("700x150")
        dialog.transient(self.app.root) 
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

        self.app.root.wait_window(dialog) 
        if result[0] is None:
            self.app.log("Генерация УФ-Маски отменена пользователем.")
            return 

        final_badge_text = result[0]
        mask_file = self.project.current_project_dir / "Травление" / "03_УФ_Маска.pdf"
        
        if self.project.is_distorted and self.project.distorted_paths: main_paths = self.project.distorted_paths
        else: main_paths = [p for p in (self.project.ready_paths if self.project.ready_paths else self.project.raw_paths) if p.layer_name != "CROP_MARKS"]
            
        crop_marks = [p for p in (self.project.ready_paths if self.project.ready_paths else self.project.raw_paths) if p.layer_name == "CROP_MARKS"]
        paths_for_mask = main_paths + crop_marks
        
        if not paths_for_mask: return messagebox.showwarning("Внимание", "Нет векторов для создания маски!")
        self._run_async(CamPipeline().generate_uv_mask_pdf, self._on_export_uv_mask_done, paths_for_mask, offset, mask_file, final_badge_text, mark_d, mark_margin)

    def _on_export_uv_mask_done(self, result_paths):
        if result_paths:
            visual_paths, pure_paths, mask_geom = result_paths
            self.project.layers["mask"] = visual_paths
            self.project.mask_geom = mask_geom
            self.ui.show_mask.set(True)
            self.ui.btn_cnc.config(state=tk.NORMAL)
            self.ui.btn_calibrate.config(state=tk.NORMAL)
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска с метками и кастомной инфо-панелью успешно сохранена.")

    def do_calibrate_cnc(self):
        if not self.project.mask_geom:
            return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску! Калибровка применяется к готовой маске перед фрезеровкой.")
            
        try:
            mark_margin = float(self.ui.entry_mark_margin.get())
        except ValueError:
            return messagebox.showerror("Ошибка", "Неверный формат отступа реперных меток!")

        paths = self.project.distorted_paths if self.project.is_distorted and self.project.distorted_paths else (self.project.ready_paths if self.project.ready_paths else self.project.raw_paths)
        regular_paths = [p for p in paths if p.layer_name != "CROP_MARKS"]
        
        all_x = [pt[0] for p in regular_paths for pt in p.points]
        all_y = [pt[1] for p in regular_paths for pt in p.points]
        
        if not all_x or not all_y:
            return messagebox.showwarning("Внимание", "Нет геометрии для расчета реперных точек.")
            
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        # Точные математические центры реперных меток (как в УФ-маске)
        ideal_centers = [
            (min_x - mark_margin, min_y - mark_margin),
            (max_x + mark_margin, min_y - mark_margin),
            (max_x + mark_margin, max_y + mark_margin),
            (min_x - mark_margin, max_y + mark_margin)
        ]

        from src.gui.alignment_window import AlignmentWindow
        win = AlignmentWindow(self.app.root, ideal_centers)
        self.app.root.wait_window(win)
        
        if win.result_transform:
            self.app.log("Применение калибровочной матрицы (Affine Transform)...")
            
            if "mask" in self.project.layers:
                self.project.layers["mask"] = win.result_transform.apply(self.project.layers["mask"])
                
            m = win.result_transform.matrix
            shapely_matrix = [m[0,0], m[0,1], m[1,0], m[1,1], m[0,2], m[1,2]]
            self.project.mask_geom = shapely.affinity.affine_transform(self.project.mask_geom, shapely_matrix)
            
            stats = win.result_stats
            self.app.log(f"Калибровка успешно применена! (Смещение X={stats['offset_x']}, Y={stats['offset_y']}, Угол={stats['angle_deg']}°)")
            
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()

    def export_cnc(self):
        if not self.project.mask_geom: return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску!\nЧПУ использует контуры маски как базовые для расчета лезвия.")
        try: 
            offset = float(self.ui.entry_offset.get())
            lead_radius = float(self.ui.entry_lead_radius.get())
        except ValueError: return messagebox.showerror("Ошибка", "Неверный формат чисел в настройках!")
            
        idx_tool = self.ui.combo_tool.current()
        idx_post = self.ui.combo_post.current()
        if idx_tool < 0 or idx_post < 0: return messagebox.showerror("Ошибка", "Выберите инструмент и постпроцессор!")
            
        selected_tool = self.app.tools_list[idx_tool]
        selected_post = self.app.posts_list[idx_post]
        ext = selected_post.extension
        if not ext.startswith('.'): ext = '.' + ext
        
        initial_dir = self.project.current_project_dir / "ЧПУ"
        initial_file = f"04_УП_Фрезер{ext}"
        
        filepath = filedialog.asksaveasfilename(
            title="Сохранить управляющую программу",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=ext,
            filetypes=[(f"G-code файлы ({ext})", f"*{ext}"), ("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
        )
        if not filepath:
            self.app.log("Сохранение УП отменено пользователем.")
            return
            
        cnc_file = Path(filepath)
        sharpen = self.ui.enable_sharpening.get()
        
        milling_dir_raw = self.ui.var_milling_dir.get()
        milling_dir = "Conventional" if "Conventional" in milling_dir_raw else "Climb"
        
        self._run_async(CamPipeline().generate_gcode, lambda res: self._on_export_cnc_done(res, cnc_file), self.project.mask_geom, cnc_file, selected_tool, selected_post, offset, sharpen, lead_radius, milling_dir)

    def _on_export_cnc_done(self, result_data, cnc_file):
        if result_data:
            ideal_paths, cnc_paths, time_min = result_data
            self.project.layers["ideal"] = ideal_paths
            self.project.layers["cnc"] = cnc_paths
            self.ui.show_ideal.set(True)
            self.ui.show_cnc.set(True)
            self.canvas.render_canvas()
            
            self.project.last_milling_time_min = time_min
            self.ui.btn_report.config(state=tk.NORMAL)
            
            hours = int(time_min // 60)
            minutes = int(time_min % 60)
            seconds = int((time_min * 60) % 60)
            
            if hours > 0: time_str = f"{hours} ч {minutes} мин"
            else: time_str = f"{minutes} мин {seconds} сек"
                
            self.app.log(f"Расчетное время фрезеровки: {time_str}")
            msg = f"УП успешно сохранена:\n{cnc_file.name}\n\n⏱ Примерное время фрезеровки: {time_str}"
            messagebox.showinfo("Готово", msg)

    def generate_report(self):
        if not self.project.current_project_dir or self.project.last_milling_time_min <= 0:
            return messagebox.showwarning("Внимание", "Сначала сгенерируйте УП (ЧПУ)!")

        idx_tool = self.ui.combo_tool.current()
        selected_tool = self.app.tools_list[idx_tool]

        stats = {
            "is_distorted": self.project.is_distorted,
            "dist_axis": self.project.applied_dist_axis,
            "k_dist": round(self.project.current_dist_factor * 100, 4),
            "rapport": self.project.current_rapport,
            "z": self.ui.var_z.get(),
            "cp": self.ui.var_cp.get(),
            "tool_name": selected_tool.name,
            "tool_angle": selected_tool.angle_deg,
            "tool_tip": selected_tool.tip_diameter,
            "tool_depth": selected_tool.depth,
            "tool_rpm": selected_tool.spindle_speed,
            "tool_feed": selected_tool.feedrate,
            "milling_dir": self.ui.var_milling_dir.get(),
            "offset": self.ui.entry_offset.get(),
            "time_min": self.project.last_milling_time_min
        }

        paths_to_draw = self.project.distorted_paths if self.project.is_distorted and self.project.distorted_paths else (self.project.ready_paths if self.project.ready_paths else self.project.raw_paths)
        
        output_pdf = self.project.current_project_dir / "05_Техкарта.pdf"

        self._run_async(ReportGenerator.generate, lambda res: self._on_generate_report_done(output_pdf), self.project.current_project_dir.name, stats, paths_to_draw, output_pdf)

    def _on_generate_report_done(self, output_pdf):
        self.app.log(f"Техкарта успешно сохранена: {output_pdf.name}")
        messagebox.showinfo("Готово", f"Техкарта успешно сгенерирована!\nФайл: {output_pdf.name}")

    def do_live_edit(self):
        paths_to_edit = self.project.ready_paths if self.project.ready_paths else self.project.raw_paths
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
            self.canvas.selected_path = None
            self.canvas.weld_anchor = None
            
            if self.project.is_array_layout:
                self.project.layers["array"] = new_paths
                self.project.ready_paths = new_paths
            elif self.project.ready_paths:
                self.project.layers["healed"] = new_paths
                self.project.ready_paths = new_paths
            else:
                self.project.raw_paths = new_paths
                self.project.layers["raw"] = new_paths
                
            self.invalidate_downstream()
            self.canvas.fit_to_screen()
            self.canvas.render_canvas()
            self.app.log("Векторы успешно обновлены из Inkscape!")
            messagebox.showinfo("Live Edit", "Изменения успешно применены!")
        else:
            self.app.log("Внимание: Файл пуст или сохранен некорректно.")