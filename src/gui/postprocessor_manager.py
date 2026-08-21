import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from pathlib import Path
from src.db.models import PostProcessor
from src.db.db_manager import DatabaseManager

class PostprocessorManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Менеджер библиотеки постпроцессоров")
        self.geometry("800x550")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.db = DatabaseManager()
        self.posts = self.db.load_postprocessors()
        self.current_index = None
        self._is_updating = False

        self.var_name = tk.StringVar()
        self.var_ext = tk.StringVar()
        self.var_tool_on = tk.StringVar()
        self.var_tool_off = tk.StringVar()
        self.var_safe_z = tk.DoubleVar()

        for var in (self.var_name, self.var_ext, self.var_tool_on, self.var_tool_off, self.var_safe_z):
            var.trace_add("write", self._on_form_change)

        self._build_ui()
        self._refresh_listbox()

    def _build_ui(self):
        frame_left = tk.Frame(self, width=250, bg="#f0f0f0")
        frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        tk.Label(frame_left, text="Постпроцессоры:", font=("Arial", 10, "bold"), bg="#f0f0f0").pack(anchor=tk.W)
        
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
        tk.Button(btn_frame, text="➕ Добавить", bg="#4CAF50", fg="white", command=self._add_post).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(btn_frame, text="🗑 Удалить", bg="#f44336", fg="white", command=self._delete_post).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        io_frame = tk.Frame(frame_left, bg="#f0f0f0")
        io_frame.pack(fill=tk.X, pady=5)
        tk.Button(io_frame, text="📥 Импорт", command=self._import_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        tk.Button(io_frame, text="📤 Экспорт", command=self._export_db).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        self.frame_right = tk.LabelFrame(self, text="Параметры постпроцессора", padx=15, pady=15, font=("Arial", 10, "bold"))
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        grid_frame = tk.Frame(self.frame_right)
        grid_frame.pack(fill=tk.X)
        tk.Label(grid_frame, text="Название:", font=("Arial", 9)).grid(row=0, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_name, width=30).grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Расширение (напр. .txt):").grid(row=1, column=0, sticky=tk.W, pady=5)
        # ИЗМЕНЕНИЕ: Используем Combobox для выбора популярных расширений
        self.combo_ext = ttk.Combobox(grid_frame, textvariable=self.var_ext, width=13, values=[".txt", ".nc", ".gcode", ".tap", ".iso", ".cnc"])
        self.combo_ext.grid(row=1, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(grid_frame, text="Безопасная Z (мм):").grid(row=2, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_safe_z, width=15).grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)
        tk.Label(grid_frame, text="Вкл. шпинделя ({rpm}):").grid(row=3, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_tool_on, width=15).grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)
        tk.Label(grid_frame, text="Выкл. шпинделя:").grid(row=4, column=0, sticky=tk.W, pady=5)
        tk.Entry(grid_frame, textvariable=self.var_tool_off, width=15).grid(row=4, column=1, sticky=tk.W, pady=5, padx=5)

        tk.Label(self.frame_right, text="Заголовок G-кода (Header):", font=("Arial", 9)).pack(anchor=tk.W, pady=(10, 0))
        self.text_header = tk.Text(self.frame_right, height=4, width=50, font=("Courier New", 9))
        self.text_header.pack(fill=tk.X, pady=2)
        self.text_header.bind("<KeyRelease>", self._on_text_change)

        tk.Label(self.frame_right, text="Подвал G-кода (Footer):", font=("Arial", 9)).pack(anchor=tk.W, pady=(5, 0))
        self.text_footer = tk.Text(self.frame_right, height=4, width=50, font=("Courier New", 9))
        self.text_footer.pack(fill=tk.X, pady=2)
        self.text_footer.bind("<KeyRelease>", self._on_text_change)

        bot_frame = tk.Frame(self.frame_right)
        bot_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(bot_frame, text="💾 Сохранить и Закрыть", bg="#2196F3", fg="white", font=("Arial", 10, "bold"), command=self._save_and_close).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(bot_frame, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)
        self._toggle_form_state(tk.DISABLED)

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for p in self.posts: self.listbox.insert(tk.END, p.name)
        if self.posts:
            if self.current_index is None or self.current_index >= len(self.posts): self.current_index = 0
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
            elif isinstance(child, tk.Text): child.config(state=state)
            else:
                try: child.config(state=state)
                except: pass

    def _on_list_select(self, event):
        selection = self.listbox.curselection()
        if not selection: return
        self.current_index = selection[0]
        self._load_into_form(self.current_index)

    def _load_into_form(self, index: int):
        if index < 0 or index >= len(self.posts): return
        self._is_updating = True
        post = self.posts[index]
        self.var_name.set(post.name)
        self.var_ext.set(post.extension)
        self.var_tool_on.set(post.tool_on)
        self.var_tool_off.set(post.tool_off)
        self.var_safe_z.set(post.safe_z)
        self.text_header.delete("1.0", tk.END)
        self.text_header.insert(tk.END, post.header)
        self.text_footer.delete("1.0", tk.END)
        self.text_footer.insert(tk.END, post.footer)
        self._is_updating = False

    def _on_form_change(self, *args):
        if self._is_updating or self.current_index is None: return
        try:
            post = self.posts[self.current_index]
            post.name = self.var_name.get()
            post.extension = self.var_ext.get()
            post.tool_on = self.var_tool_on.get()
            post.tool_off = self.var_tool_off.get()
            post.safe_z = self.var_safe_z.get()
            self.listbox.delete(self.current_index)
            self.listbox.insert(self.current_index, post.name)
            self.listbox.selection_set(self.current_index)
        except tk.TclError: pass

    def _on_text_change(self, event):
        if self._is_updating or self.current_index is None: return
        post = self.posts[self.current_index]
        post.header = self.text_header.get("1.0", "end-1c")
        post.footer = self.text_footer.get("1.0", "end-1c")

    def _add_post(self):
        self.posts.append(PostProcessor(name="Новый постпроцессор"))
        self.current_index = len(self.posts) - 1
        self._refresh_listbox()
        self.var_name.set("Новый постпроцессор")

    def _delete_post(self):
        if self.current_index is None: return
        if messagebox.askyesno("Подтверждение", "Удалить выбранный постпроцессор?"):
            self.posts.pop(self.current_index)
            self.current_index = None
            self._refresh_listbox()

    def _import_db(self):
        filepath = filedialog.askopenfilename(title="Импорт базы постпроцессоров", filetypes=[("JSON Files", "*.json")])
        if filepath:
            try:
                self.db.import_postprocessors(filepath)
                self.posts = self.db.load_postprocessors()
                self.current_index = None
                self._refresh_listbox()
                messagebox.showinfo("Успех", "Постпроцессоры успешно импортированы!")
            except Exception as e: messagebox.showerror("Ошибка", str(e))

    def _export_db(self):
        filepath = filedialog.asksaveasfilename(title="Экспорт базы постпроцессоров", defaultextension=".json", filetypes=[("JSON Files", "*.json")], initialfile="postprocessors_backup.json")
        if filepath:
            try:
                self.db.save_postprocessors(self.posts)
                self.db.export_postprocessors(filepath)
                messagebox.showinfo("Успех", "База постпроцессоров успешно экспортирована!")
            except Exception as e: messagebox.showerror("Ошибка", str(e))

    def _save_and_close(self):
        try:
            self.db.save_postprocessors(self.posts)
            self.destroy()
        except Exception as e: messagebox.showerror("Ошибка", str(e))