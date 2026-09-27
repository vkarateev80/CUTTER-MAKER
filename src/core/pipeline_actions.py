"""Миксин шагов конвейера: парсинг, анализ массива, генерация Step&Repeat, проверка, лечение."""
import tkinter as tk
from tkinter import messagebox

from src.optimizer.pattern_recognition import PatternRecognizer
from src.pipeline.cam_pipeline import CamPipeline


class PipelineActions:
    def do_step1(self):
        if not self.project.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self._run_async(self.app.services.parse, self._on_step1_done, self.project.input_filepath)

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

