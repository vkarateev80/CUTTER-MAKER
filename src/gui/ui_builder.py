import tkinter as tk
from tkinter import ttk
from src.gui.widgets import Button

class UIBuilder:
    def __init__(self, root: tk.Tk, app):
        self.root = root
        self.app = app

        # Приложение спроектировано под светлую палитру (явные светлые фоны секций,
        # кнопки #e0e0e0). В системной тёмной теме macOS Tk даёт СВЕТЛЫЙ дефолтный
        # текст — и он сливался со светлыми фонами (#F0F8FF, #f9f9f9, кнопки).
        # Фиксируем светлые дефолты ДО создания виджетов: явные цвета конструкторов
        # (холст #1e1e1e, цветные кнопки) option_add не затрагивает.
        self.root.configure(bg="#ECECEC")
        self.root.option_add("*Background", "#ECECEC")
        self.root.option_add("*Foreground", "#111111")
        self.root.option_add("*Entry*Background", "white")
        self.root.option_add("*Text*Background", "white")
        self.root.option_add("*Listbox*Background", "white")
        self.root.option_add("*selectBackground", "#4169E1")
        self.root.option_add("*selectForeground", "#FFFFFF")
        try:
            style = ttk.Style(root)
            style.configure("TCombobox", fieldbackground="white", foreground="#111111")
            style.configure("TCombobox.Listbox", background="white", foreground="#111111")
            style.configure("TProgressbar", troughcolor="#D8D8D8")
        except tk.TclError:
            pass

        self.show_raw = tk.BooleanVar(value=True)
        self.show_healed = tk.BooleanVar(value=True)
        self.show_array = tk.BooleanVar(value=False)
        self.show_distorted = tk.BooleanVar(value=False)
        self.show_mask = tk.BooleanVar(value=True)
        self.show_ideal = tk.BooleanVar(value=False)
        self.show_cnc = tk.BooleanVar(value=True)
        self.show_rapids = tk.BooleanVar(value=True) 
        
        self.enable_sharpening = tk.BooleanVar(value=True)
        self.var_milling_dir = tk.StringVar(value="Climb (Попутное)")
        
        self.var_z = tk.StringVar(value="96")
        self.var_cp = tk.StringVar(value="3.175")
        self.var_undercut = tk.StringVar(value="0.48")
        self.var_tp = tk.StringVar(value="0.44")
        self.var_tb = tk.StringVar(value="0.24")
        self.var_dist_axis = tk.StringVar(value="Y")

        for v in (self.var_z, self.var_cp, self.var_undercut, self.var_tp, self.var_tb, self.var_dist_axis):
            v.trace_add("write", self.app.controller.update_distortion_stats)

        self._build()
        self._bind_mouse_scroll(self.frame_left_container)
        self._bind_mouse_scroll(self.frame_left)

    def _build(self):
        self.frame_left_container = tk.Frame(self.root, width=450)
        self.frame_left_container.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        self.left_canvas = tk.Canvas(self.frame_left_container, width=430, highlightthickness=0)
        self.left_scrollbar = tk.Scrollbar(self.frame_left_container, orient="vertical", command=self.left_canvas.yview)
        self.frame_left = tk.Frame(self.left_canvas)
        
        self.frame_left.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self._left_win = self.left_canvas.create_window((0, 0), window=self.frame_left, anchor="nw")
        # frame_left должен быть ровно шириной canvas: иначе самая широкая
        # строка (4 кнопки в секции 3) распирает его шире canvas, правый край
        # секций уходит под обрез (горизонтального скролла нет).
        self.left_canvas.bind("<Configure>", lambda e: self.left_canvas.itemconfigure(self._left_win, width=e.width))
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        frame_proj = tk.LabelFrame(self.frame_left, text="1. Управление Проектом", padx=10, pady=10)
        frame_proj.pack(fill=tk.X, pady=5)
        
        self.btn_create_proj = Button(frame_proj, text="📁 НОВЫЙ ПРОЕКТ (ИЗ МАКЕТА)", bg="#FFD700", font=("Arial", 9, "bold"), command=self.app.controller.create_project)
        self.btn_create_proj.pack(fill=tk.X, pady=(0, 5))
        
        frame_io = tk.Frame(frame_proj)
        frame_io.pack(fill=tk.X, pady=(0, 5))
        self.btn_load_proj = Button(frame_io, text="📂 ЗАГРУЗИТЬ", bg="#e0e0e0", font=("Arial", 8, "bold"), command=self.app.controller.load_project)
        self.btn_load_proj.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        self.btn_save_proj = Button(frame_io, text="💾 СОХРАНИТЬ", bg="#87CEEB", font=("Arial", 8, "bold"), command=self.app.controller.save_project, state=tk.DISABLED)
        self.btn_save_proj.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        self.lbl_proj_info = tk.Label(frame_proj, text="Проект не загружен", fg="#555555", justify=tk.LEFT, wraplength=400)
        self.lbl_proj_info.pack(anchor=tk.W)

        frame_prep = tk.LabelFrame(self.frame_left, text="2. Анализ и Лечение", padx=10, pady=10)
        frame_prep.pack(fill=tk.X, pady=5)
        
        grid_prep = tk.Frame(frame_prep)
        grid_prep.pack(fill=tk.X, pady=(0, 5))
        tk.Label(grid_prep, text="Допуск лечения (мм):").grid(row=0, column=0, sticky=tk.W)
        self.entry_tolerance = tk.Entry(grid_prep, width=10)
        self.entry_tolerance.insert(0, "2.0")
        self.entry_tolerance.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        tk.Label(grid_prep, text="Удалять пыль < (мм²):").grid(row=1, column=0, sticky=tk.W)
        self.entry_loop_area = tk.Entry(grid_prep, width=10)
        self.entry_loop_area.insert(0, "1.0")
        self.entry_loop_area.grid(row=1, column=1, sticky=tk.W, padx=5)

        self.btn_step1 = Button(frame_prep, text="ШАГ 1: Извлечь векторы", bg="#e0e0e0", command=self.app.controller.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        self.btn_step2 = Button(frame_prep, text="ШАГ 2: Анализ ошибок", bg="#e0e0e0", command=self.app.controller.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        self.btn_step3 = Button(frame_prep, text="ШАГ 3: Вылечить (Автосохранение)", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.app.controller.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)

        frame_crop = tk.Frame(frame_prep)
        frame_crop.pack(fill=tk.X, pady=(6, 6))
        tk.Label(frame_crop, text="Отступ меток (мм):").pack(side=tk.LEFT)
        self.entry_crop_margin = tk.Entry(frame_crop, width=6)
        self.entry_crop_margin.insert(0, "10.0")
        self.entry_crop_margin.pack(side=tk.LEFT, padx=5)
        self.btn_crop_marks = Button(frame_crop, text="✂️ Добавить метки", bg="#FFDAB9", font=("Arial", 8, "bold"), command=self.app.controller.do_add_crop_marks)
        self.btn_crop_marks.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.btn_reset = Button(frame_prep, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.app.controller.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=(2, 0))

        frame_dist = tk.LabelFrame(self.frame_left, text="3. Расчет Дисторсии (Сжатие)", padx=10, pady=10, bg="#F0F8FF")
        frame_dist.pack(fill=tk.X, pady=5)
        
        grid_dist = tk.Frame(frame_dist, bg="#F0F8FF")
        grid_dist.pack(fill=tk.X)
        tk.Label(grid_dist, text="Зубья (Z):", bg="#F0F8FF").grid(row=0, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_z, width=8).grid(row=0, column=1, padx=(0, 10), pady=2)
        tk.Label(grid_dist, text="Шаг (CP):", bg="#F0F8FF").grid(row=0, column=2, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_cp, width=8).grid(row=0, column=3, pady=2)
        
        tk.Label(grid_dist, text="Толщина (tp):", bg="#F0F8FF").grid(row=1, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_tp, width=8).grid(row=1, column=1, padx=(0, 10), pady=2)
        tk.Label(grid_dist, text="Основа (tb):", bg="#F0F8FF").grid(row=1, column=2, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_tb, width=8).grid(row=1, column=3, pady=2)
        
        tk.Label(grid_dist, text="Зазор (Undercut):", bg="#F0F8FF").grid(row=2, column=0, sticky=tk.W)
        tk.Entry(grid_dist, textvariable=self.var_undercut, width=8).grid(row=2, column=1, padx=(0, 10), pady=2)

        axis_frame = tk.Frame(frame_dist, bg="#F0F8FF")
        axis_frame.pack(fill=tk.X, pady=5)
        tk.Label(axis_frame, text="Ось сжатия:", bg="#F0F8FF").pack(side=tk.LEFT)
        tk.Radiobutton(axis_frame, text="Y (↕)", variable=self.var_dist_axis, value="Y", bg="#F0F8FF").pack(side=tk.LEFT)
        tk.Radiobutton(axis_frame, text="X (↔)", variable=self.var_dist_axis, value="X", bg="#F0F8FF").pack(side=tk.LEFT)

        self.lbl_dist_stats = tk.Label(frame_dist, text="D_cyl: -- мм | K: -- %", fg="#00008B", bg="#F0F8FF", font=("Arial", 9, "bold"))
        self.lbl_dist_stats.pack(anchor=tk.W, pady=(2, 0))
        
        self.lbl_layout_stats = tk.Label(frame_dist, text="Рапорт: -- | Макет: --", fg="#555555", bg="#F0F8FF", font=("Arial", 9, "bold"))
        self.lbl_layout_stats.pack(anchor=tk.W, pady=(0, 5))

        self.lbl_array_info = tk.Label(frame_dist, text="Массив: Не анализировался", fg="#555555", bg="#F0F8FF", font=("Arial", 9, "bold"), justify=tk.LEFT)
        self.lbl_array_info.pack(anchor=tk.W, pady=(0, 5))

        dist_btns = tk.Frame(frame_dist, bg="#F0F8FF")
        dist_btns.pack(fill=tk.X, pady=(5, 0))
        
        self.btn_analyze_array = Button(dist_btns, text="🔍 Анализ", bg="#FFD700", font=("Arial", 9, "bold"), command=self.app.controller.do_analyze_array)
        self.btn_analyze_array.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        
        self.btn_generate_array = Button(dist_btns, text="🔲 Создать", bg="#FFA500", font=("Arial", 9, "bold"), command=self.app.controller.open_array_generator)
        self.btn_generate_array.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        
        self.btn_apply_dist = Button(dist_btns, text="Сжать", bg="#4169E1", fg="white", font=("Arial", 9, "bold"), command=self.app.controller.do_apply_distortion)
        self.btn_apply_dist.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        
        self.btn_rotate = Button(dist_btns, text="↻ 90°", bg="#e0e0e0", command=self.app.controller.do_rotate_90)
        self.btn_rotate.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 0))

        frame_edit = tk.LabelFrame(self.frame_left, text="4. Ручное Редактирование", padx=10, pady=10)
        frame_edit.pack(fill=tk.X, pady=5)
        
        help_text = "• ЛКМ: Выделить контур / Переместить узел\n" \
                    "• [ I ]: Добавить узел  • [ D ]: Удалить узел\n" \
                    "• [ R ]: Разрезать     • [ C ]: Замкнуть\n" \
                    "• [ J ]: Сшить два разных вектора"
        tk.Label(frame_edit, text=help_text, fg="#333333", font=("Arial", 9, "bold"), justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 5))
        
        btn_frame_edit = tk.Frame(frame_edit)
        btn_frame_edit.pack(fill=tk.X, pady=2)
        self.btn_delete_path = Button(btn_frame_edit, text="🗑 Удалить контур", bg="#e0e0e0", command=lambda: self.app.canvas_manager.on_delete_key(None))
        self.btn_delete_path.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        self.btn_delete_node = Button(btn_frame_edit, text="❌ Режим: Удалить узел", bg="#e0e0e0", command=self.app.controller.toggle_delete_node_mode)
        self.btn_delete_node.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))
        
        self.btn_live_edit = Button(frame_edit, text="✏️ Открыть в Inkscape (Live Edit)", bg="#FFB6C1", font=("Arial", 9, "bold"), command=self.app.controller.do_live_edit)
        self.btn_live_edit.pack(fill=tk.X, pady=(5, 2))

        frame_export = tk.LabelFrame(self.frame_left, text="5. Производство (Экспорт)", padx=10, pady=10)
        frame_export.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_export, text="Компенсация подтравливания (Офсет, мм):", fg="blue", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.entry_offset = tk.Entry(frame_export, width=15, bg="#E6F2FF")
        self.entry_offset.insert(0, "0.2")
        self.entry_offset.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_export, text="Реперные метки D / Отступ (мм):").pack(anchor=tk.W)
        frame_marks_inputs = tk.Frame(frame_export)
        frame_marks_inputs.pack(fill=tk.X, pady=(0, 5))
        self.entry_mark_d = tk.Entry(frame_marks_inputs, width=6)
        self.entry_mark_d.insert(0, "4.0")
        self.entry_mark_d.pack(side=tk.LEFT, padx=(0, 5))
        self.entry_mark_margin = tk.Entry(frame_marks_inputs, width=6)
        self.entry_mark_margin.insert(0, "10.0")
        self.entry_mark_margin.pack(side=tk.LEFT)

        self.btn_mask = Button(frame_export, text="🖨 Создать УФ-Маску (.PDF)", bg="#9370DB", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.app.controller.export_uv_mask)
        self.btn_mask.pack(fill=tk.X, pady=(0, 10))
        
        frame_cnc_tools = tk.LabelFrame(frame_export, text="🛠 Настройки ЧПУ", padx=5, pady=5, bg="#f9f9f9")
        frame_cnc_tools.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame_cnc_tools, text="Инструмент:", bg="#f9f9f9", font=("Arial", 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.combo_tool = ttk.Combobox(frame_cnc_tools, state="readonly", width=18)
        self.combo_tool.grid(row=0, column=1, padx=5, pady=2)
        # width=3: без него ttk-метрика эмодзи «⚙️» даёт req=115px и блок
        # ЧПУ вылезает за пределы frame_left (430px) поверх правой панели.
        Button(frame_cnc_tools, text="⚙️", width=3, command=self.app.open_tool_manager).grid(row=0, column=2, padx=2)

        tk.Label(frame_cnc_tools, text="Постпроцессор:", bg="#f9f9f9", font=("Arial", 9)).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.combo_post = ttk.Combobox(frame_cnc_tools, state="readonly", width=18)
        self.combo_post.grid(row=1, column=1, padx=5, pady=2)
        self.combo_post.bind("<<ComboboxSelected>>", self.app._update_cnc_btn_text)
        Button(frame_cnc_tools, text="⚙️", width=3, command=self.app.open_postprocessor_manager).grid(row=1, column=2, padx=2)

        tk.Checkbutton(frame_cnc_tools, text="🔪 3D-Подрезка углов", bg="#f9f9f9", fg="#FF4500", font=("Arial", 9, "bold"), variable=self.enable_sharpening).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(5,0))
        
        tk.Label(frame_cnc_tools, text="Вход/Выход по дуге R (мм):", bg="#f9f9f9", font=("Arial", 9)).grid(row=3, column=0, sticky=tk.W, pady=2)
        self.entry_lead_radius = tk.Entry(frame_cnc_tools, width=10)
        self.entry_lead_radius.insert(0, "1.5")
        self.entry_lead_radius.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

        tk.Label(frame_cnc_tools, text="Направление реза:", bg="#f9f9f9", font=("Arial", 9)).grid(row=4, column=0, sticky=tk.W, pady=2)
        self.combo_milling_dir = ttk.Combobox(frame_cnc_tools, textvariable=self.var_milling_dir, state="readonly", width=18, values=["Climb (Попутное)", "Conventional (Встречное)"])
        self.combo_milling_dir.grid(row=4, column=1, padx=5, pady=2)

        # НОВАЯ КНОПКА КАЛИБРОВКИ
        self.btn_calibrate = Button(frame_export, text="🎯 Калибровка ЧПУ по меткам", bg="#FFDAB9", font=("Arial", 9, "bold"), state=tk.DISABLED, command=self.app.controller.do_calibrate_cnc)
        self.btn_calibrate.pack(fill=tk.X, pady=(0, 5))

        self.btn_cnc = Button(frame_export, text="⚙️ Сгенерировать УП", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.app.controller.export_cnc)
        self.btn_cnc.pack(fill=tk.X, pady=2)
        
        self.btn_report = Button(frame_export, text="📄 Создать Техкарту (.PDF)", bg="#20B2AA", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.app.controller.generate_report)
        self.btn_report.pack(fill=tk.X, pady=(5, 2))

        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        
        self.progress = ttk.Progressbar(frame_log, orient="horizontal", mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 5))
        
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_clear_log = Button(frame_log_btns, text="🗑 Очистить", command=self.app.clear_logs)
        self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_copy_log = Button(frame_log_btns, text="📋 Копировать", command=self.app.copy_logs)
        self.btn_copy_log.pack(side=tk.RIGHT)
        self.text_log = tk.Text(frame_log, height=6, width=40, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X, pady=(0, 5))
        self.btn_measure = Button(frame_tools, text="📏 Замер", bg="#e0e0e0", command=self.app.controller.toggle_measure)
        self.btn_measure.pack(side=tk.LEFT)
        
        frame_layers = tk.LabelFrame(self.frame_right, text="Слои видимости", padx=5, pady=5)
        frame_layers.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(frame_layers, text="Исходник", fg="#555555", font=("Arial", 9, "bold"), variable=self.show_raw, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Вылеченный", fg="#008888", font=("Arial", 9, "bold"), variable=self.show_healed, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Массив", fg="#9370DB", font=("Arial", 9, "bold"), variable=self.show_array, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Сжатый", fg="#1E90FF", font=("Arial", 9, "bold"), variable=self.show_distorted, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Маска", fg="#880088", font=("Arial", 9, "bold"), variable=self.show_mask, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Лезвие", fg="#8B8B00", font=("Arial", 9, "bold"), variable=self.show_ideal, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="УП (ЧПУ)", fg="#008800", font=("Arial", 9, "bold"), variable=self.show_cnc, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Холостые (G0)", fg="#FF8C00", font=("Arial", 9, "bold"), variable=self.show_rapids, command=self.app.trigger_render).pack(side=tk.LEFT, padx=10)

        self.frame_canvas = tk.LabelFrame(self.frame_right, text="Предпросмотр (ЛКМ - Выделить/Двигать | Колесико - Масштаб)", padx=5, pady=5)
        self.frame_canvas.pack(fill=tk.BOTH, expand=True)

    def _on_left_scroll(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.left_canvas.yview_scroll(-1, "units")
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.left_canvas.yview_scroll(1, "units")

    def _bind_mouse_scroll(self, widget):
        if not isinstance(widget, (tk.Text, ttk.Combobox, tk.Listbox)):
            widget.bind("<MouseWheel>", self._on_left_scroll)
            widget.bind("<Button-4>", self._on_left_scroll)
            widget.bind("<Button-5>", self._on_left_scroll)
        for child in widget.winfo_children():
            self._bind_mouse_scroll(child)

    def lock_ui(self):
        buttons = [self.btn_step1, self.btn_step2, self.btn_step3, self.btn_crop_marks, self.btn_reset, 
                   self.btn_analyze_array, self.btn_generate_array, self.btn_apply_dist, self.btn_rotate, 
                   self.btn_live_edit, self.btn_mask, self.btn_cnc, self.btn_create_proj, self.btn_measure, 
                   self.btn_delete_path, self.btn_delete_node, self.btn_clear_log, self.btn_copy_log,
                   self.btn_load_proj, self.btn_save_proj, self.btn_report, self.btn_calibrate]
        for btn in buttons:
            try: btn.config(state=tk.DISABLED)
            except: pass
        self.combo_milling_dir.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def unlock_ui(self):
        buttons = [self.btn_step1, self.btn_step2, self.btn_step3, self.btn_crop_marks, self.btn_reset, 
                   self.btn_analyze_array, self.btn_generate_array, self.btn_apply_dist, self.btn_rotate, 
                   self.btn_live_edit, self.btn_create_proj, self.btn_measure, self.btn_delete_path, 
                   self.btn_delete_node, self.btn_clear_log, self.btn_copy_log, self.btn_load_proj, self.btn_save_proj]
        for btn in buttons:
            try: btn.config(state=tk.NORMAL)
            except: pass
        self.combo_milling_dir.config(state="readonly")
        if not self.app.project.current_project_dir: self.btn_save_proj.config(state=tk.DISABLED)
        if self.app.project.last_milling_time_min > 0: self.btn_report.config(state=tk.NORMAL)