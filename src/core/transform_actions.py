"""Миксин трансформаций геометрии: дисторсия, поворот 90°, обрезные метки."""
from tkinter import messagebox

from src.pipeline.cam_pipeline import CamPipeline


class TransformActions:
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

