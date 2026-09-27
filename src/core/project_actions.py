"""Миксин действий над проектом: создание/сохранение/загрузка, сброс, режимы, статистика дисторсии."""
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from src.optimizer.distortion import DistortionCalculator, LayoutAnalyzer


class ProjectActions:
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
            self.app.services.save_project_doc(state_file, data)
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
            data = self.app.services.load_project_doc(state_file)
                
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

