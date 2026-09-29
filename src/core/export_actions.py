"""Миксин экспорта: УФ-маска PDF, калибровка ЧПУ, G-код, техкарта, live edit в Inkscape."""
import datetime
import os
import shapely.affinity
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from src.parser.engines import require_inkscape
from src.pipeline.cam_pipeline import CamPipeline
from src.gui.widgets import Button


class ExportActions:
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
        Button(btn_frame, text="✅ Сгенерировать PDF", width=20, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=on_ok).pack(side=tk.LEFT, padx=10)
        Button(btn_frame, text="❌ Отмена", width=10, bg="#f44336", fg="white", font=("Arial", 10, "bold"), command=on_cancel).pack(side=tk.LEFT, padx=10)

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
        self._run_async(self.app.services.generate_uv_mask_pdf, self._on_export_uv_mask_done, paths_for_mask, offset, mask_file, final_badge_text, mark_d, mark_margin)

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
        
        self._run_async(self.app.services.generate_gcode, lambda res: self._on_export_cnc_done(res, cnc_file), self.project.mask_geom, cnc_file, selected_tool, selected_post, offset, sharpen, lead_radius, milling_dir)

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

        self._run_async(self.app.services.generate_report, lambda res: self._on_generate_report_done(output_pdf), self.project.current_project_dir.name, stats, paths_to_draw, output_pdf)

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
            inkscape_exe = require_inkscape()
            print("Ожидание завершения работы Inkscape...")
            print("-> Внесите изменения, нажмите Ctrl+S и закройте Inkscape.")
            
            subprocess.run([str(inkscape_exe), str(safe_svg)])
            print("Inkscape закрыт. Чтение изменений...")
            new_paths = self.app.services.parse(safe_svg)
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