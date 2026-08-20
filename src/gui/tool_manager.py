import tkinter as tk
from tkinter import messagebox, filedialog
from pathlib import Path

from src.db.models import Tool
from src.db.db_manager import DatabaseManager

class ToolManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Менеджер библиотеки инструментов (Фрезы)")
        self.geometry("750x450")
        self.transient(parent) # Окно привязано к главному
        self.grab_set()        # Блокируем главное окно, пока открыто это
        self.resizable(False, False)

        self.db = DatabaseManager()
        self.tools = self.db.load_tools()
        self.current_index = None
        self._is_updating = False # Флаг для блокировки циклических обновлений

        # Переменные для формы ввода
        self.var_name = tk.StringVar()
        self.var_type = tk.StringVar(value="V-Bit")
        self.var_angle = tk.DoubleVar()
        self.var_tip = tk.DoubleVar()
        self.var_depth = tk.DoubleVar()
        self.var_step = tk.DoubleVar()
        self.var_feedrate = tk.IntVar()
        self.var_spindle = tk.IntVar()

        # Привязываем отслеживание изменений, чтобы сразу сохранять их в объект
        for var in (self.var_name, self.var_type, self.var_angle, self.var_tip, self.var_depth, self.var_step, self.var_feedrate, self.var_spindle):
            var.trace_add("write", self._on_form_change)

        self._build_ui()
        self._refresh_listbox()

    def _build_ui(self):
        # --- ЛЕВАЯ ПАНЕЛЬ (Список фрез) ---
        frame_left = tk.Frame(self, width=250, bg="#f0f0f0")
        frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        tk.Label(frame_left, text="Доступные фрезы:", font=("Arial", 10, "bold"), bg="#f0f0f0").pack(anchor=tk.W)
        
        # Список с прокруткой
        list_frame = tk.Frame(frame_left)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.scrollbar = tk.Scrollbar(list_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, yscrollcommand=self.scrollbar.set, font=("Arial", 10), exportselection=False)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.listbox.yview)
        
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        # Кнопки управления списком
        btn_frame = tk.Frame(frame_left, bg="#f0f0f0")
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="➕ Добавить", bg="#4CAF50", fg="white", command=self._add_tool).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(btn_frame, text="🗑 Удалить", bg="#f44336", fg="white", command=self._delete_tool).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        # Кнопки импорта/экспорта
        io_frame = tk.Frame(frame_left, bg="#f0f0f0")
        io_frame.pack(fill=tk.X, pady=5)
        tk.Button(io_frame, text="📥 Импорт", command=self._import_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(io_frame, text="📤 Экспорт", command=self._export_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        # --- ПРАВАЯ ПАНЕЛЬ (Настройки выбранной фрезы) ---
        self.frame_right = tk.LabelFrame(self, text="Параметры инструмента", padx=15, pady=15, font=("Arial", 10, "bold"))
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Сетка параметров
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

        # Кнопки сохранения и отмены в самом низу правой панели
        bot_frame = tk.Frame(self.frame_right)
        bot_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        tk.Button(bot_frame, text="💾 Сохранить и Закрыть", bg="#2196F3", fg="white", font=("Arial", 10, "bold"), command=self._save_and_close).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(bot_frame, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)

        self._toggle_form_state(tk.DISABLED)

    def _refresh_listbox(self):
        """Обновляет список инструментов в интерфейсе."""
        self.listbox.delete(0, tk.END)
        for t in self.tools:
            self.listbox.insert(tk.END, t.name)
        
        if self.tools:
            if self.current_index is None or self.current_index >= len(self.tools):
                self.current_index = 0
            self.listbox.selection_set(self.current_index)
            self._load_into_form(self.current_index)
            self._toggle_form_state(tk.NORMAL)
        else:
            self._toggle_form_state(tk.DISABLED)
            self.current_index = None

    def _toggle_form_state(self, state):
        """Блокирует или разблокирует правую панель (если нет фрез)."""
        for child in self.frame_right.winfo_children():
            if isinstance(child, tk.Frame):
                for widget in child.winfo_children():
                    if not (isinstance(widget, tk.Button) and widget.cget("text") == "Отмена"):
                        try:
                            widget.config(state=state)
                        except: pass
            else:
                try: child.config(state=state)
                except: pass

    def _on_list_select(self, event):
        """Обрабатывает клик по списку."""
        selection = self.listbox.curselection()
        if not selection: return
        self.current_index = selection[0]
        self._load_into_form(self.current_index)

    def _load_into_form(self, index: int):
        """Загружает данные инструмента в текстовые поля."""
        if index < 0 or index >= len(self.tools): return
        
        self._is_updating = True # Блокируем триггер сохранения при программном вводе
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
        """Срабатывает при вводе текста, сохраняет изменения в текущий объект Tool в памяти."""
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
            
            # Обновляем имя в списке "на лету"
            self.listbox.delete(self.current_index)
            self.listbox.insert(self.current_index, tool.name)
            self.listbox.selection_set(self.current_index)
        except tk.TclError:
            pass # Игнорируем ошибки при стирании цифр до пустой строки

    def _add_tool(self):
        new_tool = Tool(name="Новая фреза")
        self.tools.append(new_tool)
        self.current_index = len(self.tools) - 1
        self._refresh_listbox()
        self.var_name.set("Новая фреза") # Фокус на имя

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
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def _export_db(self):
        filepath = filedialog.asksaveasfilename(title="Экспорт базы инструментов", defaultextension=".json", filetypes=[("JSON Files", "*.json")], initialfile="tools_backup.json")
        if filepath:
            try:
                # Перед экспортом сохраняем текущие изменения
                self.db.save_tools(self.tools)
                self.db.export_tools(filepath)
                messagebox.showinfo("Успех", "База инструментов успешно экспортирована!")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def _save_and_close(self):
        try:
            self.db.save_tools(self.tools)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка при сохранении", str(e))