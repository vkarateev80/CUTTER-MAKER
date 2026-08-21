import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import math
from pathlib import Path
from src.db.models import Tool
from src.db.db_manager import DatabaseManager

class FeedsSpeedsCalculator(tk.Toplevel):
    def __init__(self, parent, angle: float, tip: float, depth: float):
        super().__init__(parent)
        self.title("Калькулятор режимов резания")
        self.geometry("450x380")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        
        self.result_rpm = None
        self.result_feed = None
        
        # Расчет эффективного диаметра на рабочей глубине
        angle_rad = math.radians(angle / 2.0)
        self.d_eff = tip + (2.0 * depth * math.tan(angle_rad))
        if self.d_eff < 0.01: 
            self.d_eff = 0.01

        # База материалов: {Название: (Скорость резания Vc [м/мин], Подача на зуб fz [мм/зуб])}
        self.materials = {
            "Латунь / Бронза (Brass)": (150.0, 0.02),
            "Сталь (Steel)": (50.0, 0.01),
            "Алюминий / Магний (Alu)": (200.0, 0.03),
            "Пластик / Акрил (Plastic)": (100.0, 0.04)
        }

        self.var_material = tk.StringVar(value="Латунь / Бронза (Brass)")
        self.var_flutes = tk.IntVar(value=1) # Для граверов обычно 1 режущая кромка
        self.var_max_rpm = tk.IntVar(value=24000) # Максимальные обороты шпинделя станка

        for var in (self.var_material, self.var_flutes, self.var_max_rpm):
            var.trace_add("write", self._calculate)

        self._build_ui()
        self._calculate()

    def _build_ui(self):
        info_frame = tk.LabelFrame(self, text="Параметры инструмента", padx=10, pady=10, bg="#f9f9f9")
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(info_frame, text=f"Эффективный диаметр (на глубине):", bg="#f9f9f9").pack(anchor=tk.W)
        tk.Label(info_frame, text=f"{self.d_eff:.3f} мм", font=("Arial", 12, "bold"), fg="#00008B", bg="#f9f9f9").pack(anchor=tk.W)

        calc_frame = tk.LabelFrame(self, text="Вводные данные", padx=10, pady=10)
        calc_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(calc_frame, text="Обрабатываемый материал:").grid(row=0, column=0, sticky=tk.W, pady=5)
        combo_mat = ttk.Combobox(calc_frame, textvariable=self.var_material, values=list(self.materials.keys()), state="readonly", width=25)
        combo_mat.grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(calc_frame, text="Кол-во режущих кромок (Z):").grid(row=1, column=0, sticky=tk.W, pady=5)
        tk.Entry(calc_frame, textvariable=self.var_flutes, width=10).grid(row=1, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(calc_frame, text="Макс. обороты шпинделя:").grid(row=2, column=0, sticky=tk.W, pady=5)
        tk.Entry(calc_frame, textvariable=self.var_max_rpm, width=10).grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)

        res_frame = tk.LabelFrame(self, text="Оптимальные режимы", padx=10, pady=10, bg="#E6F2FF")
        res_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(res_frame, text="Обороты шпинделя (S):", bg="#E6F2FF", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.lbl_rpm = tk.Label(res_frame, text="-- об/мин", bg="#E6F2FF", font=("Arial", 12, "bold"), fg="#FF4500")
        self.lbl_rpm.grid(row=0, column=1, sticky=tk.W, pady=2, padx=10)
        
        tk.Label(res_frame, text="Рабочая подача (F):", bg="#E6F2FF", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_feed = tk.Label(res_frame, text="-- мм/мин", bg="#E6F2FF", font=("Arial", 12, "bold"), fg="#2E8B57")
        self.lbl_feed.grid(row=1, column=1, sticky=tk.W, pady=2, padx=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10, padx=10)
        tk.Button(btn_frame, text="✅ Применить", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=self._apply).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(btn_frame, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)

    def _calculate(self, *args):
        try:
            mat = self.var_material.get()
            if mat not in self.materials: return
            vc, fz = self.materials[mat]
            
            flutes = self.var_flutes.get()
            max_rpm = self.var_max_rpm.get()
            
            if flutes <= 0 or max_rpm <= 0: return

            # Теоретические обороты: RPM = (Vc * 1000) / (Pi * D)
            rpm_theoretical = (vc * 1000) / (math.pi * self.d_eff)
            
            # Ограничиваем обороты физическими возможностями шпинделя
            rpm_actual = min(rpm_theoretical, max_rpm)
            
            # Подача: Feed = RPM * fz * Z
            feedrate = rpm_actual * fz * flutes
            
            self.calc_rpm = int(rpm_actual)
            self.calc_feed = int(feedrate)
            
            self.lbl_rpm.config(text=f"{self.calc_rpm} об/мин")
            self.lbl_feed.config(text=f"{self.calc_feed} мм/мин")
            
        except Exception:
            self.lbl_rpm.config(text="Ошибка")
            self.lbl_feed.config(text="Ошибка")

    def _apply(self):
        if hasattr(self, 'calc_rpm') and hasattr(self, 'calc_feed'):
            self.result_rpm = self.calc_rpm
            self.result_feed = self.calc_feed
            self.destroy()


class ToolManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Менеджер библиотеки инструментов (Фрезы)")
        self.geometry("750x480") # Слегка увеличили высоту окна под новую кнопку
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.db = DatabaseManager()
        self.tools = self.db.load_tools()
        self.current_index = None
        self._is_updating = False

        self.var_name = tk.StringVar()
        self.var_type = tk.StringVar(value="V-Bit")
        self.var_angle = tk.DoubleVar()
        self.var_tip = tk.DoubleVar()
        self.var_depth = tk.DoubleVar()
        self.var_step = tk.DoubleVar()
        self.var_feedrate = tk.IntVar()
        self.var_spindle = tk.IntVar()

        for var in (self.var_name, self.var_type, self.var_angle, self.var_tip, self.var_depth, self.var_step, self.var_feedrate, self.var_spindle):
            var.trace_add("write", self._on_form_change)

        self._build_ui()
        self._refresh_listbox()

    def _build_ui(self):
        frame_left = tk.Frame(self, width=250, bg="#f0f0f0")
        frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        tk.Label(frame_left, text="Доступные фрезы:", font=("Arial", 10, "bold"), bg="#f0f0f0").pack(anchor=tk.W)
        
        list_frame = tk.Frame(frame_left)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.scrollbar = tk.Scrollbar(list_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=self.scrollbar.set, font=("Arial", 10), exportselection=False)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        btn_frame = tk.Frame(frame_left, bg="#f0f0f0")
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="➕ Добавить", bg="#4CAF50", fg="white", command=self._add_tool).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(btn_frame, text="🗑 Удалить", bg="#f44336", fg="white", command=self._delete_tool).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        io_frame = tk.Frame(frame_left, bg="#f0f0f0")
        io_frame.pack(fill=tk.X, pady=5)
        tk.Button(io_frame, text="📥 Импорт", command=self._import_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(io_frame, text="📤 Экспорт", command=self._export_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        self.frame_right = tk.LabelFrame(self, text="Параметры инструмента", padx=15, pady=15, font=("Arial", 10, "bold"))
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        grid_frame = tk.Frame(self.frame_right)
        grid_frame.pack(fill=tk.X)
        tk.Label(grid_frame, text="Название:", font=("Arial", 9)).grid(row=0, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_name, width=25).grid(row=0, column=1, columnspan=3, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Тип фрезы:").grid(row=1, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_type, width=25, state="disabled").grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Угол (°):").grid(row=2, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_angle, width=10).grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Пятно (мм):").grid(row=2, column=2, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_tip, width=10).grid(row=2, column=3, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Глубина (мм):").grid(row=3, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_depth, width=10).grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Шаг по Z (мм):").grid(row=3, column=2, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_step, width=10).grid(row=3, column=3, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Подача (F):").grid(row=4, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_feedrate, width=10).grid(row=4, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Обороты (S):").grid(row=4, column=2, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_spindle, width=10).grid(row=4, column=3, sticky=tk.W, pady=5, padx=5)

        # Кнопка вызова калькулятора
        btn_calc = tk.Button(grid_frame, text="🧮 Авто-расчет режимов (Калькулятор)", bg="#FFD700", font=("Arial", 9, "bold"), command=self._open_calculator)
        btn_calc.grid(row=5, column=0, columnspan=4, sticky=tk.EW, pady=(15, 5), padx=5)

        bot_frame = tk.Frame(self.frame_right)
        bot_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(bot_frame, text="💾 Сохранить и Закрыть", bg="#2196F3", fg="white", font=("Arial", 10, "bold"), command=self._save_and_close).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(bot_frame, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)
        self._toggle_form_state(tk.DISABLED)

    def _open_calculator(self):
        try:
            angle = float(self.var_angle.get())
            tip = float(self.var_tip.get())
            depth = abs(float(self.var_depth.get()))
            
            calc = FeedsSpeedsCalculator(self, angle, tip, depth)
            self.wait_window(calc)
            
            if calc.result_rpm is not None and calc.result_feed is not None:
                self.var_spindle.set(calc.result_rpm)
                self.var_feedrate.set(calc.result_feed)
                self.log_update = True
        except ValueError:
            messagebox.showerror("Ошибка", "Сначала введите корректные Угол, Пятно и Глубину фрезы!")

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for t in self.tools: self.listbox.insert(tk.END, t.name)
        if self.tools:
            if self.current_index is None or self.current_index >= len(self.tools): self.current_index = 0
            self.listbox.selection_set(self.current_index)
            self._load_into_form(self.current_index)
            self._toggle_form_state(tk.NORMAL)
        else:
            self._toggle_form_state(tk.DISABLED)
            self.current_index = None

    def _toggle_form_state(self, state):
        for child in self.frame_right.winfo_children():
            if isinstance(child, tk.Frame):
                for widget in child.winfo_children():
                    if not (isinstance(widget, tk.Button) and widget.cget("text") == "Отмена"):
                        try: widget.config(state=state)
                        except: pass
            else:
                try: child.config(state=state)
                except: pass

    def _on_list_select(self, event):
        selection = self.listbox.curselection()
        if not selection: return
        self.current_index = selection[0]
        self._load_into_form(self.current_index)

    def _load_into_form(self, index: int):
        if index < 0 or index >= len(self.tools): return
        self._is_updating = True
        tool = self.tools[index]
        self.var_name.set(tool.name)
        self.var_type.set(tool.tool_type)
        self.var_angle.set(tool.angle_deg)
        self.var_tip.set(tool.tip_diameter)
        self.var_depth.set(tool.depth)
        self.var_step.set(tool.step_down)
        self.var_feedrate.set(tool.feedrate)
        self.var_spindle.set(tool.spindle_speed)
        self._is_updating = False

    def _on_form_change(self, *args):
        if self._is_updating or self.current_index is None: return
        try:
            tool = self.tools[self.current_index]
            tool.name = self.var_name.get()
            tool.tool_type = self.var_type.get()
            tool.angle_deg = self.var_angle.get()
            tool.tip_diameter = self.var_tip.get()
            tool.depth = self.var_depth.get()
            tool.step_down = self.var_step.get()
            tool.feedrate = self.var_feedrate.get()
            tool.spindle_speed = self.var_spindle.get()
            self.listbox.delete(self.current_index)
            self.listbox.insert(self.current_index, tool.name)
            self.listbox.selection_set(self.current_index)
        except tk.TclError: pass

    def _add_tool(self):
        self.tools.append(Tool(name="Новая фреза"))
        self.current_index = len(self.tools) - 1
        self._refresh_listbox()
        self.var_name.set("Новая фреза")

    def _delete_tool(self):
        if self.current_index is None: return
        if messagebox.askyesno("Подтверждение", "Удалить выбранную фрезу?"):
            self.tools.pop(self.current_index)
            self.current_index = None
            self._refresh_listbox()

    def _import_db(self):
        filepath = filedialog.askopenfilename(title="Импорт базы инструментов", filetypes=[("JSON Files", "*.json")])
        if filepath:
            try:
                self.db.import_tools(filepath)
                self.tools = self.db.load_tools()
                self.current_index = None
                self._refresh_listbox()
                messagebox.showinfo("Успех", "Инструменты успешно импортированы!")
            except Exception as e: messagebox.showerror("Ошибка", str(e))

    def _export_db(self):
        filepath = filedialog.asksaveasfilename(title="Экспорт базы инструментов", defaultextension=".json", filetypes=[("JSON Files", "*.json")], initialfile="tools_backup.json")
        if filepath:
            try:
                self.db.save_tools(self.tools)
                self.db.export_tools(filepath)
                messagebox.showinfo("Успех", "База инструментов успешно экспортирована!")
            except Exception as e: messagebox.showerror("Ошибка", str(e))

    def _save_and_close(self):
        try:
            self.db.save_tools(self.tools)
            self.destroy()
        except Exception as e: messagebox.showerror("Ошибка", str(e))