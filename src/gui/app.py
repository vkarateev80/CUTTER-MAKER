import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import sys
import math
import shutil
import datetime
import tempfile
import os
import subprocess

from src.pipeline.cam_pipeline import CamPipeline
from src.parser.geometry import CamPath
from src.db.db_manager import DatabaseManager

class CamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CUTTER MAKER - Производство Гибких Штампов")
        self.root.geometry("1300x850") 
        
        self.input_filepath = None
        self.raw_paths, self.ready_paths, self.paths_to_draw = [], [], []
        self.mask_geom = None 
        
        self.layers = {"raw": [], "healed": [], "mask": [], "ideal": [], "cnc": []}
        self.show_raw = tk.BooleanVar(value=True)
        self.show_healed = tk.BooleanVar(value=True)
        self.show_mask = tk.BooleanVar(value=True)
        self.show_ideal = tk.BooleanVar(value=False)
        self.show_cnc = tk.BooleanVar(value=True)
        
        self.enable_sharpening = tk.BooleanVar(value=True)
        
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.current_scale, self.current_tx, self.current_ty, self.canvas_h = 1.0, 0.0, 0.0, 0
        self.is_measuring, self.measure_pt1 = False, None 
        self.current_project_dir = None 
        
        # Переменные для редактирования векторов и узлов
        self.selected_path = None
        self.selected_node_idx = None
        self.hovered_node_idx = None
        
        # Отслеживание позиции мыши для хоткеев
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        
        self.db = DatabaseManager()
        self.tools_list = []
        self.posts_list = []
        
        self._build_ui()
        self.refresh_comboboxes()
        
        # Бинды на удаление вектора
        self.root.bind("<Delete>", self.on_delete_key)
        self.root.bind("<BackSpace>", self.on_delete_key)
        
        # Общий бинд на нажатие любой клавиши (для обработки I, D, R на разных раскладках)
        self.root.bind("<Key>", self.on_key_press)

    def refresh_comboboxes(self):
        self.tools_list = self.db.load_tools()
        self.posts_list = self.db.load_postprocessors()
        
        self.combo_tool['values'] = [t.name for t in self.tools_list]
        if self.tools_list: self.combo_tool.current(0)
            
        self.combo_post['values'] = [p.name for p in self.posts_list]
        if self.posts_list: self.combo_post.current(0)

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

    def _build_ui(self):
        self.frame_left = tk.Frame(self.root, width=450)
        self.frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        self.frame_right = tk.Frame(self.root)
        self.frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        frame_proj = tk.LabelFrame(self.frame_left, text="1. Управление Проектом", padx=10, pady=10)
        frame_proj.pack(fill=tk.X, pady=5)
        self.btn_create_proj = tk.Button(frame_proj, text="📁 СОЗДАТЬ ПРОЕКТ И ВЫБРАТЬ МАКЕТ", bg="#FFD700", font=("Arial", 10, "bold"), command=self.create_project)
        self.btn_create_proj.pack(fill=tk.X, pady=(0, 5))
        self.lbl_proj_info = tk.Label(frame_proj, text="Проект не создан", fg="gray", justify=tk.LEFT, wraplength=400)
        self.lbl_proj_info.pack(anchor=tk.W)

        frame_prep = tk.LabelFrame(self.frame_left, text="2. Анализ и Лечение", padx=10, pady=10)
        frame_prep.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_prep, text="Допуск лечения (мм):").pack(anchor=tk.W)
        self.entry_tolerance = tk.Entry(frame_prep, width=15)
        self.entry_tolerance.insert(0, "2.0")
        self.entry_tolerance.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_prep, text="Удалять пыль/петли < (мм/мм²):").pack(anchor=tk.W)
        self.entry_loop_area = tk.Entry(frame_prep, width=15)
        self.entry_loop_area.insert(0, "1.0")
        self.entry_loop_area.pack(anchor=tk.W, pady=(0, 10))

        self.btn_step1 = tk.Button(frame_prep, text="ШАГ 1: Извлечь векторы", bg="#e0e0e0", command=self.do_step1)
        self.btn_step1.pack(fill=tk.X, pady=2)
        self.btn_step2 = tk.Button(frame_prep, text="ШАГ 2: Анализ ошибок", bg="#e0e0e0", command=self.do_step2)
        self.btn_step2.pack(fill=tk.X, pady=2)
        self.btn_step3 = tk.Button(frame_prep, text="ШАГ 3: Вылечить (Автосохранение)", bg="#87CEEB", font=("Arial", 9, "bold"), command=self.do_step3)
        self.btn_step3.pack(fill=tk.X, pady=2)

        self.btn_reset = tk.Button(frame_prep, text="↺ Сбросить к исходнику", bg="#FFDAB9", command=self.do_reset)
        self.btn_reset.pack(fill=tk.X, pady=2)

        frame_edit = tk.LabelFrame(self.frame_left, text="3. Ручное Редактирование", padx=10, pady=10)
        frame_edit.pack(fill=tk.X, pady=5)
        
        help_text = "• ЛКМ: Выделить контур / Переместить узел\n" \
                    "• [ I ]: Добавить узел на линии\n" \
                    "• [ D ]: Удалить узел\n" \
                    "• [ R ]: Разрезать/Удалить отрезок\n" \
                    "• [ Delete ]: Удалить весь контур"
        tk.Label(frame_edit, text=help_text, fg="#333333", font=("Arial", 9, "bold"), justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 5))
        
        self.btn_live_edit = tk.Button(frame_edit, text="✏️ Открыть в Inkscape (Live Edit)", bg="#FFB6C1", font=("Arial", 9, "bold"), command=self.do_live_edit)
        self.btn_live_edit.pack(fill=tk.X, pady=2)

        frame_export = tk.LabelFrame(self.frame_left, text="4. Производство (Экспорт)", padx=10, pady=10)
        frame_export.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_export, text="Компенсация подтравливания (Офсет, мм):", fg="blue", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.entry_offset = tk.Entry(frame_export, width=15, bg="#E6F2FF")
        self.entry_offset.insert(0, "0.2")
        self.entry_offset.pack(anchor=tk.W, pady=(0, 5))
        
        tk.Label(frame_export, text="Реперные метки D / Отступ (мм):").pack(anchor=tk.W)
        frame_marks_inputs = tk.Frame(frame_export)
        frame_marks_inputs.pack(fill=tk.X, pady=(0, 5))
        self.entry_mark_d = tk.Entry(frame_marks_inputs, width=6); self.entry_mark_d.insert(0, "4.0"); self.entry_mark_d.pack(side=tk.LEFT, padx=(0, 5))
        self.entry_mark_margin = tk.Entry(frame_marks_inputs, width=6); self.entry_mark_margin.insert(0, "10.0"); self.entry_mark_margin.pack(side=tk.LEFT)

        self.btn_mask = tk.Button(frame_export, text="🖨 Создать УФ-Маску (.PDF)", bg="#9370DB", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_uv_mask)
        self.btn_mask.pack(fill=tk.X, pady=(0, 10))
        
        frame_cnc_tools = tk.LabelFrame(frame_export, text="🛠 Настройки ЧПУ", padx=5, pady=5, bg="#f9f9f9")
        frame_cnc_tools.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame_cnc_tools, text="Инструмент:", bg="#f9f9f9", font=("Arial", 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.combo_tool = ttk.Combobox(frame_cnc_tools, state="readonly", width=22)
        self.combo_tool.grid(row=0, column=1, padx=5, pady=2)
        tk.Button(frame_cnc_tools, text="⚙️", command=self.open_tool_manager).grid(row=0, column=2, padx=2)

        tk.Label(frame_cnc_tools, text="Постпроцессор:", bg="#f9f9f9", font=("Arial", 9)).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.combo_post = ttk.Combobox(frame_cnc_tools, state="readonly", width=22)
        self.combo_post.grid(row=1, column=1, padx=5, pady=2)
        tk.Button(frame_cnc_tools, text="⚙️", command=self.open_postprocessor_manager).grid(row=1, column=2, padx=2)

        tk.Checkbutton(frame_cnc_tools, text="🔪 3D-Подрезка (Только внутр. углы)", bg="#f9f9f9", fg="#FF4500", font=("Arial", 9, "bold"), variable=self.enable_sharpening).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(5,0))

        self.btn_cnc = tk.Button(frame_export, text="⚙️ Сгенерировать УП (.TXT)", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.export_cnc)
        self.btn_cnc.pack(fill=tk.X, pady=2)

        frame_log = tk.LabelFrame(self.frame_left, text="Лог работы", padx=10, pady=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        frame_log_btns = tk.Frame(frame_log)
        frame_log_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_clear_log = tk.Button(frame_log_btns, text="🗑 Очистить", command=self.clear_logs); self.btn_clear_log.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_copy_log = tk.Button(frame_log_btns, text="📋 Копировать", command=self.copy_logs); self.btn_copy_log.pack(side=tk.RIGHT)
        self.text_log = tk.Text(frame_log, height=8, width=45, state=tk.DISABLED, bg="#f0f0f0")
        self.text_log.pack(fill=tk.BOTH, expand=True)

        frame_tools = tk.Frame(self.frame_right)
        frame_tools.pack(fill=tk.X, pady=(0, 5))
        self.btn_measure = tk.Button(frame_tools, text="📏 Замер", bg="#e0e0e0", command=self.toggle_measure); self.btn_measure.pack(side=tk.LEFT)
        frame_layers = tk.LabelFrame(self.frame_right, text="Слои видимости", padx=5, pady=5)
        frame_layers.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(frame_layers, text="Исходник (Серый)", fg="#555555", font=("Arial", 9, "bold"), variable=self.show_raw, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Вылеченный (Синий)", fg="#008888", font=("Arial", 9, "bold"), variable=self.show_healed, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="УФ-Маска (Пурпурный)", fg="#880088", font=("Arial", 9, "bold"), variable=self.show_mask, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Идеальное лезвие (Желтый)", fg="#CCCC00", font=("Arial", 9, "bold"), variable=self.show_ideal, command=self.render_canvas).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(frame_layers, text="Траектория УП (Зеленый/Бирюзовый)", fg="#008800", font=("Arial", 9, "bold"), variable=self.show_cnc, command=self.render_canvas).pack(side=tk.LEFT, padx=10)

        frame_canvas = tk.LabelFrame(self.frame_right, text="Предпросмотр (ЛКМ - Выделить / Двигать | Колесико - Масштаб)", padx=5, pady=5)
        frame_canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame_canvas, bg="#1e1e1e", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_left_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<Motion>", self.on_mouse_move) 
        self.canvas.bind("<ButtonPress-3>", self.on_right_click) 
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)

    # --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
    def toggle_measure(self):
        self.is_measuring = not self.is_measuring
        if self.is_measuring: 
            self.btn_measure.config(bg="#FFD700", relief=tk.SUNKEN)
            self.canvas.config(cursor="target")
            self.selected_path = None 
            self.render_canvas()
        else: 
            self.btn_measure.config(bg="#e0e0e0", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        return (sx - self.current_tx) / self.current_scale, (self.canvas_h - sy - self.current_ty) / self.current_scale

    def get_visible_paths(self):
        visible = []
        if self.show_raw.get(): visible.extend(self.layers["raw"])
        if self.show_healed.get(): visible.extend(self.layers["healed"])
        if self.show_mask.get(): visible.extend(self.layers["mask"])
        if self.show_ideal.get(): visible.extend(self.layers["ideal"])
        if self.show_cnc.get(): visible.extend(self.layers["cnc"])
        return visible

    def get_snapped_coords(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        if not visible_paths: return wx, wy, None, None
        
        snap_threshold_world = 15 / self.current_scale
        closest_dist, closest_pt, closest_layer = float('inf'), None, None
        
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist <= closest_dist and dist < snap_threshold_world: 
                    closest_dist = dist
                    closest_pt = pt
                    closest_layer = path.layer_name
                    
        if closest_pt:
            return closest_pt[0], closest_pt[1], closest_pt, closest_layer
        return wx, wy, None, None

    def get_closest_path(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        if not visible_paths: return None
        
        snap_threshold_world = 10 / self.current_scale
        closest_dist = float('inf')
        closest_path = None
        
        for path in visible_paths:
            for pt in path.points:
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < closest_dist and dist <= snap_threshold_world:
                    closest_dist = dist
                    closest_path = path
        return closest_path

    def invalidate_downstream(self):
        self.mask_geom = None
        self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], []
        self.btn_mask.config(state=tk.DISABLED)
        self.btn_cnc.config(state=tk.DISABLED)

    def get_node_at(self, sx, sy, radius=6):
        if not self.selected_path: return None
        for i, pt in enumerate(self.selected_path.points):
            px = pt[0] * self.current_scale + self.current_tx
            py = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
            if math.hypot(px - sx, py - sy) <= radius:
                return i
        return None

    def get_segment_at(self, sx, sy, radius=5):
        if not self.selected_path or len(self.selected_path.points) < 2: return None, None
        wx, wy = self.screen_to_world(sx, sy)
        world_radius = radius / self.current_scale if self.current_scale > 0 else 0
        
        pts = self.selected_path.points
        n = len(pts)
        best_i, best_dist, best_proj = None, float('inf'), None
        
        for i in range(n - 1):
            p1, p2 = pts[i], pts[i+1]
            l2 = (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2
            if l2 == 0: continue
            t = max(0, min(1, ((wx - p1[0]) * (p2[0] - p1[0]) + (wy - p1[1]) * (p2[1] - p1[1])) / l2))
            proj_x = p1[0] + t * (p2[0] - p1[0])
            proj_y = p1[1] + t * (p2[1] - p1[1])
            dist = math.hypot(wx - proj_x, wy - proj_y)
            
            if dist < best_dist and dist <= world_radius:
                best_dist, best_i, best_proj = dist, i, (proj_x, proj_y)
                
        if self.selected_path.is_closed and n > 2:
            p1, p2 = pts[-1], pts[0]
            l2 = (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2
            if l2 != 0:
                t = max(0, min(1, ((wx - p1[0]) * (p2[0] - p1[0]) + (wy - p1[1]) * (p2[1] - p1[1])) / l2))
                proj_x = p1[0] + t * (p2[0] - p1[0])
                proj_y = p1[1] + t * (p2[1] - p1[1])
                dist = math.hypot(wx - proj_x, wy - proj_y)
                if dist < best_dist and dist <= world_radius:
                    best_dist, best_i, best_proj = dist, n - 1, (proj_x, proj_y)
                    
        return best_i, best_proj

    # --- ХОТКЕИ (KEYBOARD SHORTCUTS) ---
    def on_delete_key(self, event):
        if not self.selected_path: return
        if self.selected_path in self.raw_paths: self.raw_paths.remove(self.selected_path)
        if self.selected_path in self.ready_paths: self.ready_paths.remove(self.selected_path)
        for layer_paths in self.layers.values():
            if self.selected_path in layer_paths: layer_paths.remove(self.selected_path)
        self.selected_path = None
        self.invalidate_downstream()
        self.render_canvas()
        self.log("Вектор удален вручную.")

    def on_key_press(self, event):
        # Игнорируем нажатия, если фокус находится в поле ввода (Entry или Text)
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
            
        char = getattr(event, 'char', '').lower()
        
        if char in ('i', 'ш'):
            self.on_key_insert_node()
        elif char in ('d', 'в'):
            self.on_key_delete_node()
        elif char in ('r', 'к'):
            self.on_key_remove_segment()

    def on_key_insert_node(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, proj_pt = self.get_segment_at(self.last_mouse_x, self.last_mouse_y)
        if seg_i is not None and proj_pt:
            new_pt = (proj_pt[0], proj_pt[1])
            self.selected_path.points.insert(seg_i + 1, new_pt)
            self.invalidate_downstream()
            self.render_canvas()
            self.log(f"Узел добавлен (Индекс: {seg_i + 1}).")

    def on_key_delete_node(self):
        if self.is_measuring or not self.selected_path: return
        if self.hovered_node_idx is not None:
            idx = self.hovered_node_idx
            self.selected_path.points.pop(idx)
            self.hovered_node_idx = None
            if len(self.selected_path.points) < 2:
                self.on_delete_key(None)
            else:
                self.invalidate_downstream()
                self.render_canvas()
                self.log(f"Узел удален (Индекс: {idx}).")

    def on_key_remove_segment(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, _ = self.get_segment_at(self.last_mouse_x, self.last_mouse_y)
        if seg_i is None: return

        pts = self.selected_path.points.copy()
        
        if self.selected_path.is_closed:
            # БАГФИКС: Очищаем дублирующуюся точку замыкания, если она есть
            if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4:
                pts.pop()
            
            self.selected_path.is_closed = False
            
            # Защита индекса
            if seg_i >= len(pts):
                seg_i = len(pts) - 1
                
            self.selected_path.points = pts[seg_i+1:] + pts[:seg_i+1]
            self.log("Замкнутый контур разорван.")
        else:
            pts1 = pts[:seg_i+1]
            pts2 = pts[seg_i+1:]
            
            target_list = self.ready_paths if self.selected_path in self.ready_paths else self.raw_paths
            layer_name = self.selected_path.layer_name
            
            if self.selected_path in target_list:
                target_list.remove(self.selected_path)
                
            target_layer = self.layers.get("raw")
            for layer_paths in self.layers.values():
                if self.selected_path in layer_paths:
                    layer_paths.remove(self.selected_path)
                    target_layer = layer_paths
                    break
            
            self.selected_path = None
            self.hovered_node_idx = None
            
            if len(pts1) >= 2:
                cp1 = CamPath(points=pts1, is_closed=False, layer_name=layer_name)
                target_list.append(cp1)
                if target_layer is not None: target_layer.append(cp1)
                
            if len(pts2) >= 2:
                cp2 = CamPath(points=pts2, is_closed=False, layer_name=layer_name)
                target_list.append(cp2)
                if target_layer is not None: target_layer.append(cp2)
                
            self.log("Открытый контур разделен на две части.")

        self.invalidate_downstream()
        self.render_canvas()

    # --- ОБРАБОТКА СОБЫТИЙ МЫШИ ---
    def on_left_click(self, event):
        # БАГФИКС: Принудительно обновляем координаты мыши при клике для хоткеев
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        
        # Забираем фокус у полей ввода
        self.canvas.focus_set()
        
        self.canvas_h = self.canvas.winfo_height()
        if self.is_measuring:
            wx, wy, snapped_pt, _ = self.get_snapped_coords(event.x, event.y)
            if not self.measure_pt1: 
                self.measure_pt1 = (wx, wy)
                self.log(f"-> Замер от: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.log(f"=== РАССТОЯНИЕ: {dist:.4f} мм ===")
                self.measure_pt1 = None
                self.canvas.delete("measure_dynamic")
                sx, sy = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00FF00", tags="measure_dynamic")
            return
            
        # Проверяем, кликнули ли мы по узлу выделенного вектора
        if self.selected_path:
            node_idx = self.get_node_at(event.x, event.y)
            if node_idx is not None:
                self.selected_node_idx = node_idx
                return

        # Иначе просто выделяем вектор или начинаем панорамирование
        clicked_path = self.get_closest_path(event.x, event.y)
        if clicked_path != self.selected_path:
            self.selected_path = clicked_path
            self.render_canvas()
            
        self.pan_start_x, self.pan_start_y = event.x, event.y

    def on_left_release(self, event):
        self.selected_node_idx = None

    def on_right_click(self, event):
        if self.is_measuring and self.measure_pt1: 
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")
        else:
            self.selected_path = None
            self.render_canvas()

    def on_mouse_move(self, event):
        # Обновляем координаты для хоткеев
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        
        self.canvas.delete("hover_tooltip")
        wx, wy, snapped_pt, layer_name = self.get_snapped_coords(event.x, event.y)
        
        if self.is_measuring and self.measure_pt1:
            self.canvas.delete("measure_dynamic")
            dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
            sx1, sy1 = self.measure_pt1[0] * self.current_scale + self.current_tx, self.canvas_h - (self.measure_pt1[1] * self.current_scale + self.current_ty)
            sx2, sy2 = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FFD700", dash=(4, 4), tags="measure_dynamic")
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#FFD700", width=2, tags="measure_dynamic")
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")
            return
            
        # Подсветка узла при наведении
        if self.selected_path and self.selected_node_idx is None:
            hover_idx = self.get_node_at(event.x, event.y)
            if hover_idx != self.hovered_node_idx:
                self.hovered_node_idx = hover_idx
                self.render_canvas()
        
        if snapped_pt and not self.selected_path:
            sx2 = wx * self.current_scale + self.current_tx
            sy2 = self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#00FFFF", width=2, tags="hover_tooltip")
            text = f"Слой: {layer_name}\nX: {snapped_pt[0]:.3f}\nY: {snapped_pt[1]:.3f}"
            text_id = self.canvas.create_text(event.x + 15, event.y - 15, text=text, fill="#00FFFF", font=("Arial", 10, "bold"), anchor=tk.SW, tags="hover_tooltip")
            bbox = self.canvas.bbox(text_id)
            if bbox:
                self.canvas.create_rectangle(bbox[0]-3, bbox[1]-3, bbox[2]+3, bbox[3]+3, fill="#1e1e1e", outline="#00FFFF", tags="hover_tooltip")
                self.canvas.tag_raise(text_id)

    def on_pan_move(self, event):
        if self.is_measuring: return 
        
        # Перетаскивание узла
        if self.selected_node_idx is not None and self.selected_path:
            wx, wy = self.screen_to_world(event.x, event.y)
            old_pt = self.selected_path.points[self.selected_node_idx]
            
            new_pt = (wx, wy, old_pt[2]) if len(old_pt) > 2 else (wx, wy)
            self.selected_path.points[self.selected_node_idx] = new_pt
            
            if self.selected_path.is_closed and len(self.selected_path.points) > 1:
                if self.selected_node_idx == 0:
                    last_pt = self.selected_path.points[-1]
                    if math.hypot(old_pt[0] - last_pt[0], old_pt[1] - last_pt[1]) < 1e-4:
                        self.selected_path.points[-1] = (wx, wy, last_pt[2]) if len(last_pt) > 2 else (wx, wy)
                elif self.selected_node_idx == len(self.selected_path.points) - 1:
                    first_pt = self.selected_path.points[0]
                    if math.hypot(old_pt[0] - first_pt[0], old_pt[1] - first_pt[1]) < 1e-4:
                        self.selected_path.points[0] = (wx, wy, first_pt[2]) if len(first_pt) > 2 else (wx, wy)
            
            self.invalidate_downstream()
            self.render_canvas()
            return

        self.current_tx += event.x - self.pan_start_x
        self.current_ty -= event.y - self.pan_start_y 
        self.pan_start_x, self.pan_start_y = event.x, event.y
        self.render_canvas()

    def on_mousewheel(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0: zoom = 1.1 
        elif event.num == 5 or getattr(event, 'delta', 0) < 0: zoom = 0.9 
        else: return
        wx, wy = (event.x - self.current_tx) / self.current_scale, (self.canvas_h - event.y - self.current_ty) / self.current_scale
        self.current_scale *= zoom
        self.current_tx, self.current_ty = event.x - wx * self.current_scale, self.canvas_h - event.y - wy * self.current_scale
        self.render_canvas()

    def fit_to_screen(self):
        visible = self.get_visible_paths()
        if not visible: return
        all_x, all_y = [pt[0] for p in visible for pt in p.points], [pt[1] for p in visible for pt in p.points]
        if not all_x or not all_y: return
        w_mm, h_mm = max(all_x) - min(all_x), max(all_y) - min(all_y)
        if w_mm == 0: w_mm = 1
        if h_mm == 0: h_mm = 1
        self.root.update() 
        self.canvas_h = self.canvas.winfo_height()
        pad = 30 
        self.current_scale = min((self.canvas.winfo_width() - 2 * pad) / w_mm, (self.canvas_h - 2 * pad) / h_mm)
        self.current_tx = (self.canvas.winfo_width() - w_mm * self.current_scale) / 2 - min(all_x) * self.current_scale
        self.current_ty = (self.canvas_h - h_mm * self.current_scale) / 2 - min(all_y) * self.current_scale

    def render_canvas(self):
        self.canvas.delete("all")
        self.canvas_h = self.canvas.winfo_height()
        
        layers_to_draw = [
            (self.show_raw, self.layers["raw"], "#555555", 1.0, None),
            (self.show_healed, self.layers["healed"], "#00FFFF", 1.5, None),
            (self.show_mask, self.layers["mask"], "#FF1493", 2.0, None),
            (self.show_ideal, self.layers["ideal"], "#FFFF00", 2.0, None), 
            (self.show_cnc, self.layers["cnc"], "#00FF00", 1.5, (5, 5))
        ]
        
        for show_var, paths, color, width, dash in layers_to_draw:
            if show_var.get() and paths:
                for path in paths:
                    if len(path.points) < 2: continue
                    coords = []
                    for pt in path.points: 
                        x, y = pt[0], pt[1]
                        coords.extend([x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)])
                    
                    is_selected = (path is self.selected_path)
                    draw_color = "#FF4500" if is_selected else color
                    draw_width = 3.0 if is_selected else width
                    
                    if path.layer_name == "SHARPEN":
                        self.canvas.create_line(coords, fill="#FF0000" if not is_selected else "#FF4500", width=2.0 if not is_selected else 3.0, capstyle=tk.ROUND)
                    else:
                        if dash and not is_selected:
                            self.canvas.create_line(coords, fill=draw_color, width=draw_width, capstyle=tk.ROUND, dash=dash)
                        else:
                            self.canvas.create_line(coords, fill=draw_color, width=draw_width, capstyle=tk.ROUND)
                            
                    # Отрисовка узлов для выделенного вектора
                    if is_selected:
                        for i, pt in enumerate(path.points):
                            nx = pt[0] * self.current_scale + self.current_tx
                            ny = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
                            fill_color = "#FF0000" if self.hovered_node_idx == i else "#FFFFFF"
                            self.canvas.create_rectangle(nx-3, ny-3, nx+3, ny+3, fill=fill_color, outline="#FF4500", tags="node")
        
        colors = {"red": "#FF0000", "orange": "#FFA500", "magenta": "#FF00FF", "yellow": "#FFFF00"}
        for k, pts in self.error_markers.items():
            for x, y in pts:
                sx, sy = x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-5, sy-5, sx+5, sy+5, outline=colors[k], width=2, tags="error_marker")

    def log(self, message: str):
        self.text_log.config(state=tk.NORMAL); self.text_log.insert(tk.END, message + "\n"); self.text_log.see(tk.END); self.text_log.config(state=tk.DISABLED); self.root.update()

    def copy_logs(self):
        content = self.text_log.get("1.0", tk.END).strip()
        if content: self.root.clipboard_clear(); self.root.clipboard_append(content); messagebox.showinfo("Скопировано", "Логи скопированы!")
            
    def clear_logs(self):
        self.text_log.config(state=tk.NORMAL); self.text_log.delete("1.0", tk.END); self.text_log.config(state=tk.DISABLED); self.root.update()

    def _run_with_redirect(self, func, *args):
        class StdoutRedirector:
            def __init__(self, app): self.app = app
            def write(self, string):
                if string.strip(): self.app.log(string.strip())
            def flush(self): pass
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirector(self)
        try: return func(*args)
        except Exception as e: self.log(f"ОШИБКА: {e}"); messagebox.showerror("Ошибка", str(e))
        finally: sys.stdout = old_stdout

    def do_live_edit(self):
        paths_to_edit = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths_to_edit: 
            return messagebox.showwarning("Внимание", "Нет векторов для редактирования! Сначала выполните ШАГ 1.")
            
        temp_dir = Path(tempfile.gettempdir())
        safe_svg = temp_dir / f"cam_live_edit_{os.getpid()}.svg"
        
        self.log("Экспорт геометрии во временный SVG...")
        pipeline = CamPipeline()
        pipeline.export_paths_to_svg(paths_to_edit, safe_svg)
        
        project_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(os.getcwd())
        inkscape_exe = project_root / 'inkscape_engine' / 'bin' / 'inkscape.exe' if os.name == 'nt' else Path('inkscape')
        
        self.log("Ожидание завершения работы Inkscape...")
        self.log("-> Внесите изменения, нажмите Ctrl+S и закройте Inkscape.")
        self.root.update()
        
        try:
            subprocess.run([str(inkscape_exe), str(safe_svg)])
            self.log("Inkscape закрыт. Чтение изменений...")
            new_paths = pipeline.step1_parse(safe_svg)
            
            if new_paths:
                self.selected_path = None
                if self.ready_paths:
                    self.ready_paths = new_paths
                    self.layers["healed"] = new_paths
                else:
                    self.raw_paths = new_paths
                    self.layers["raw"] = new_paths
                    
                self.invalidate_downstream()
                self.fit_to_screen()
                self.render_canvas()
                self.log("Векторы успешно обновлены из Inkscape!")
                messagebox.showinfo("Live Edit", "Изменения успешно применены!")
            else:
                self.log("Внимание: Файл пуст или сохранен некорректно.")
        except Exception as e:
            self.log(f"Ошибка Live Edit: {e}")
            messagebox.showerror("Ошибка", f"Не удалось выполнить Live Edit:\n{e}")
        finally:
            if safe_svg.exists():
                try: safe_svg.unlink()
                except: pass

    def do_step1(self):
        if not self.input_filepath: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ!")
        self.raw_paths = self._run_with_redirect(CamPipeline().step1_parse, self.input_filepath)
        if self.raw_paths:
            self.selected_path = None
            self.layers["raw"] = self.raw_paths; self.layers["healed"], self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], [], []
            self.mask_geom = None
            self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
            self.fit_to_screen(); self.render_canvas()

    def do_step2(self):
        paths = self.ready_paths if self.ready_paths else self.raw_paths
        if not paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: loop_area = float(self.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        stats = self._run_with_redirect(CamPipeline(min_loop_area=loop_area).step2_check_errors, paths)
        if stats:
            self.error_markers = {"red": stats.get("error_nodes", []), "orange": stats.get("intersection_nodes", []), "magenta": stats.get("duplicate_nodes", []), "yellow": stats.get("dust_nodes", [])}
            self.render_canvas()

    def do_step3(self):
        if not self.raw_paths: return messagebox.showwarning("Внимание", "Сначала выполните ШАГ 1!")
        try: tol, loop_area = float(self.entry_tolerance.get()), float(self.entry_loop_area.get())
        except: return messagebox.showerror("Ошибка", "Неверный формат чисел!")
        self.ready_paths = self._run_with_redirect(CamPipeline(tolerance=tol, min_loop_area=loop_area).step3_heal_and_optimize, self.ready_paths if self.ready_paths else self.raw_paths)
        if self.ready_paths:
            self.selected_path = None
            self.layers["healed"] = self.ready_paths; self.render_canvas()
            self.btn_mask.config(state=tk.NORMAL); self.btn_cnc.config(state=tk.NORMAL)
            if self.current_project_dir: self._run_with_redirect(CamPipeline().save_source_dxf, self.ready_paths, self.current_project_dir / "02_Вылеченный_Мастер.dxf")

    def do_reset(self):
        if not self.raw_paths: return
        self.ready_paths, self.mask_geom = [], None
        self.selected_path = None
        self.layers["healed"], self.layers["mask"], self.layers["ideal"], self.layers["cnc"] = [], [], [], []
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.render_canvas(); self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)

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
        self.lbl_proj_info.config(text=f"Папка: {proj_name}\nМакет: {Path(filepath).name}", fg="black")
        
        self.canvas.delete("all")
        self.raw_paths, self.ready_paths = [], []
        self.mask_geom = None
        self.selected_path = None
        self.layers = {"raw": [], "healed": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        self.show_raw.set(True); self.show_healed.set(True); self.show_mask.set(True); self.show_ideal.set(False); self.show_cnc.set(True)
        self.btn_mask.config(state=tk.DISABLED); self.btn_cnc.config(state=tk.DISABLED)
        self.log(f"\n=== ПРОЕКТ {proj_name} СОЗДАН ===")

    def export_uv_mask(self):
        if not self.current_project_dir or not self.ready_paths: return messagebox.showwarning("Внимание", "Сначала СОЗДАЙТЕ ПРОЕКТ и ВЫЛЕЧИТЕ деталь!")
        
        try: 
            offset = float(self.entry_offset.get())
            mark_d = float(self.entry_mark_d.get())
            mark_margin = float(self.entry_mark_margin.get())
        except ValueError: 
            return messagebox.showerror("Ошибка", "Неверный формат чисел!")

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

        def on_cancel():
            dialog.destroy()

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
        
        result_paths = self._run_with_redirect(CamPipeline().generate_uv_mask_pdf, self.ready_paths, offset, mask_file, final_badge_text, mark_d, mark_margin)
        
        if result_paths:
            visual_paths, pure_paths, mask_geom = result_paths
            self.layers["mask"] = visual_paths
            self.mask_geom = mask_geom
            
            self.show_mask.set(True)
            self.fit_to_screen()
            self.render_canvas()
            messagebox.showinfo("Готово", "УФ-Маска с метками и кастомной инфо-панелью успешно сохранена.")

    def export_cnc(self):
        if not self.mask_geom: 
            return messagebox.showwarning("Внимание", "Сначала создайте УФ-Маску!\nЧПУ использует контуры маски как базовые для расчета лезвия.")
            
        try: 
            offset = float(self.entry_offset.get())
        except ValueError: 
            return messagebox.showerror("Ошибка", "Неверный формат офсета!")
            
        idx_tool = self.combo_tool.current()
        idx_post = self.combo_post.current()
        
        if idx_tool < 0 or idx_post < 0:
            return messagebox.showerror("Ошибка", "Выберите инструмент и постпроцессор!")
            
        selected_tool = self.tools_list[idx_tool]
        selected_post = self.posts_list[idx_post]
        
        ext = selected_post.extension
        if not ext.startswith('.'): ext = '.' + ext
        cnc_file = self.current_project_dir / "ЧПУ" / f"04_УП_Фрезер{ext}"
        sharpen = self.enable_sharpening.get()
        
        generated_paths = self._run_with_redirect(CamPipeline().generate_gcode, self.mask_geom, cnc_file, selected_tool, selected_post, offset, sharpen)
        
        if generated_paths:
            ideal_paths, cnc_paths = generated_paths
            self.layers["ideal"] = ideal_paths
            self.layers["cnc"] = cnc_paths
            self.show_ideal.set(True)
            self.show_cnc.set(True)
            self.render_canvas()
            messagebox.showinfo("Готово", f"УП сохранена как {cnc_file.name}!")