import tkinter as tk
import math
from src.parser.geometry import CamPath

class CanvasManager:
    def __init__(self, parent_frame: tk.Frame, app):
        self.parent = parent_frame
        self.app = app
        
        self.current_scale = 1.0
        self.current_tx = 0.0
        self.current_ty = 0.0
        self.canvas_h = 0
        
        self.is_measuring = False
        self.measure_pt1 = None
        
        self.selected_path = None
        self.selected_node_idx = None
        self.hovered_node_idx = None
        self.weld_anchor = None
        self.is_delete_node_mode = False
        
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        
        self._build_ui()

    def _build_ui(self):
        self.parent.rowconfigure(1, weight=1)
        self.parent.columnconfigure(1, weight=1)

        self.corner_box = tk.Frame(self.parent, width=25, height=25, bg="#d0d0d0")
        self.corner_box.grid(row=0, column=0, sticky="nsew")

        self.ruler_x = tk.Canvas(self.parent, height=25, bg="#e0e0e0", highlightthickness=0)
        self.ruler_x.grid(row=0, column=1, sticky="nsew")

        self.ruler_y = tk.Canvas(self.parent, width=25, bg="#e0e0e0", highlightthickness=0)
        self.ruler_y.grid(row=1, column=0, sticky="nsew")

        self.canvas = tk.Canvas(self.parent, bg="#1e1e1e", cursor="crosshair", highlightthickness=0)
        self.canvas.grid(row=1, column=1, sticky="nsew")

        self.canvas.bind("<ButtonPress-1>", self.on_left_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<Motion>", self.on_mouse_move) 
        self.canvas.bind("<ButtonPress-3>", self.on_right_click) 
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<Configure>", lambda e: self.render_canvas())

    def bind_keys(self, root):
        root.bind("<Delete>", self.on_delete_key)
        root.bind("<BackSpace>", self.on_delete_key)
        root.bind("<Key>", self.on_key_press)

    def set_measure_mode(self, state: bool):
        self.is_measuring = state
        if self.is_measuring:
            self.canvas.config(cursor="target")
            self.selected_path = None
            self.render_canvas()
        else:
            self.canvas.config(cursor="crosshair")
            self.measure_pt1 = None
            self.canvas.delete("measure_dynamic")

    def set_delete_node_mode(self, state: bool):
        self.is_delete_node_mode = state
        if self.is_delete_node_mode:
            self.canvas.config(cursor="X_cursor")
            self.selected_path = None
            self.render_canvas()
        else:
            self.canvas.config(cursor="crosshair")

    def screen_to_world(self, sx, sy):
        if self.current_scale == 0: return 0, 0
        return (sx - self.current_tx) / self.current_scale, (self.canvas_h - sy - self.current_ty) / self.current_scale

    def get_visible_paths(self):
        visible = []
        if self.app.ui.show_raw.get(): visible.extend(self.app.project.layers.get("raw", []))
        if self.app.ui.show_healed.get(): visible.extend(self.app.project.layers.get("healed", []))
        if self.app.ui.show_array.get(): visible.extend(self.app.project.layers.get("array", []))
        if self.app.ui.show_distorted.get(): visible.extend(self.app.project.layers.get("distorted", []))
        if self.app.ui.show_mask.get(): visible.extend(self.app.project.layers.get("mask", []))
        if self.app.ui.show_ideal.get(): visible.extend(self.app.project.layers.get("ideal", []))
        if self.app.ui.show_cnc.get(): visible.extend(self.app.project.layers.get("cnc", []))
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
        if closest_pt: return closest_pt[0], closest_pt[1], closest_pt, closest_layer
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

    def get_any_node_at(self, sx, sy, radius=15):
        wx, wy = self.screen_to_world(sx, sy)
        visible_paths = self.get_visible_paths()
        best_dist = float('inf')
        best_match = None
        world_radius = radius / self.current_scale if self.current_scale > 0 else 0
        for path in visible_paths:
            for i, pt in enumerate(path.points):
                dist = math.hypot(pt[0] - wx, pt[1] - wy)
                if dist < best_dist and dist <= world_radius:
                    best_dist = dist
                    best_match = (path, i)
        return best_match

    def get_node_at(self, sx, sy, radius=10):
        if not self.selected_path: return None
        for i, pt in enumerate(self.selected_path.points):
            px = pt[0] * self.current_scale + self.current_tx
            py = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
            if math.hypot(px - sx, py - sy) <= radius: return i
        return None

    def get_segment_at(self, sx, sy, radius=10):
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

    def on_delete_key(self, event):
        if not self.selected_path: return
        if self.weld_anchor and self.weld_anchor[0] == self.selected_path: self.weld_anchor = None
        if self.selected_path in self.app.project.raw_paths: self.app.project.raw_paths.remove(self.selected_path)
        if self.selected_path in self.app.project.ready_paths: self.app.project.ready_paths.remove(self.selected_path)
        if self.selected_path in self.app.project.distorted_paths: self.app.project.distorted_paths.remove(self.selected_path)
        for layer_paths in self.app.project.layers.values():
            if self.selected_path in layer_paths: layer_paths.remove(self.selected_path)
        self.selected_path = None
        self.app.controller.invalidate_downstream()
        self.render_canvas()
        self.app.log("Вектор удален вручную.")

    def on_key_press(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text)): return
        char = getattr(event, 'char', '').lower()
        if char in ('i', 'ш'): self.on_key_insert_node()
        elif char in ('d', 'в'): self.on_key_delete_node()
        elif char in ('r', 'к'): self.on_key_remove_segment()
        elif char in ('j', 'о'): self.on_key_join_nodes()
        elif char in ('c', 'с'): self.on_key_close_path()

    def on_key_close_path(self):
        if self.is_measuring or not self.selected_path: return
        if self.selected_path.is_closed:
            self.app.log("Контур уже замкнут.")
            return
        pts = self.selected_path.points
        if len(pts) > 2:
            dist = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            if dist > 1e-4:
                first_pt = pts[0]
                new_pt = (first_pt[0], first_pt[1], first_pt[2]) if len(first_pt) > 2 else (first_pt[0], first_pt[1])
                self.selected_path.points.append(new_pt)
        self.selected_path.is_closed = True
        self.app.controller.invalidate_downstream()
        self.render_canvas()
        self.app.log("Успех: Выделенный контур замкнут (клавиша C).")

    def on_key_insert_node(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, proj_pt = self.get_segment_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if seg_i is not None and proj_pt:
            new_pt = (proj_pt[0], proj_pt[1])
            self.selected_path.points.insert(seg_i + 1, new_pt)
            self.app.controller.invalidate_downstream()
            self.render_canvas()
            self.app.log(f"Узел добавлен (Индекс: {seg_i + 1}).")

    def on_key_delete_node(self):
        if self.is_measuring or not self.selected_path: return
        idx = self.get_node_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if idx is not None:
            self.selected_path.points.pop(idx)
            if len(self.selected_path.points) < 2: self.on_delete_key(None)
            else:
                self.app.controller.invalidate_downstream()
                self.render_canvas()
                self.app.log(f"Узел удален (Индекс: {idx}).")

    def on_key_remove_segment(self):
        if self.is_measuring or not self.selected_path: return
        seg_i, _ = self.get_segment_at(self.last_mouse_x, self.last_mouse_y, radius=10)
        if seg_i is None: return
        pts = self.selected_path.points.copy()
        if self.selected_path.is_closed:
            if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4: pts.pop()
            self.selected_path.is_closed = False
            if seg_i >= len(pts): seg_i = len(pts) - 1
            self.selected_path.points = pts[seg_i+1:] + pts[:seg_i+1]
            self.app.log("Замкнутый контур разорван.")
        else:
            pts1 = pts[:seg_i+1]
            pts2 = pts[seg_i+1:]
            
            target_list = self.app.project.distorted_paths if self.selected_path in self.app.project.distorted_paths else (self.app.project.ready_paths if self.selected_path in self.app.project.ready_paths else self.app.project.raw_paths)
            layer_name = self.selected_path.layer_name
            if self.selected_path in target_list: target_list.remove(self.selected_path)
            
            target_layer = self.app.project.layers.get("raw")
            for layer_paths in self.app.project.layers.values():
                if self.selected_path in layer_paths:
                    layer_paths.remove(self.selected_path)
                    target_layer = layer_paths
                    break
            self.selected_path = None
            if len(pts1) >= 2:
                cp1 = CamPath(points=pts1, is_closed=False, layer_name=layer_name)
                target_list.append(cp1)
                if target_layer is not None: target_layer.append(cp1)
            if len(pts2) >= 2:
                cp2 = CamPath(points=pts2, is_closed=False, layer_name=layer_name)
                target_list.append(cp2)
                if target_layer is not None: target_layer.append(cp2)
            self.app.log("Открытый контур разделен на две части.")
        self.app.controller.invalidate_downstream()
        self.render_canvas()

    def on_key_join_nodes(self):
        if self.is_measuring: return
        match = self.get_any_node_at(self.last_mouse_x, self.last_mouse_y, radius=15)
        if not match:
            self.app.log("Ошибка: Наведите курсор ближе к узлу контура.")
            return
        p2, idx2 = match
        if p2.is_closed:
            self.app.log("Ошибка: Выбранный контур уже замкнут.")
            return
        is_end2 = (idx2 == len(p2.points) - 1)
        is_start2 = (idx2 == 0)
        if not (is_start2 or is_end2):
            self.app.log("Ошибка: Сшивать можно только начальные или конечные точки контура.")
            return
        if self.weld_anchor is None:
            self.weld_anchor = (p2, idx2)
            self.app.log("Точка 1 зафиксирована. Наведите на вторую точку и нажмите J.")
            self.render_canvas()
            return
        p1, idx1 = self.weld_anchor
        if p1 not in self.get_visible_paths():
            self.weld_anchor = (p2, idx2)
            self.app.log("Предыдущая точка была удалена. Зафиксирована новая точка 1.")
            self.render_canvas()
            return
        if p1 == p2:
            self.app.log("Ошибка: Для замыкания одного контура используйте клавишу C.")
            self.weld_anchor = None
            self.render_canvas()
            return
        else:
            is_end1 = (idx1 == len(p1.points) - 1)
            is_start1 = (idx1 == 0)
            pts1 = p1.points.copy()
            pts2 = p2.points.copy()
            if is_end1 and is_start2: merged = pts1 + pts2
            elif is_end1 and is_end2:
                pts2.reverse()
                merged = pts1 + pts2
            elif is_start1 and is_end2: merged = pts2 + pts1
            elif is_start1 and is_start2:
                pts1.reverse()
                merged = pts1 + pts2
            p1.points = merged
            if p2 in self.app.project.raw_paths: self.app.project.raw_paths.remove(p2)
            if p2 in self.app.project.ready_paths: self.app.project.ready_paths.remove(p2)
            if p2 in self.app.project.distorted_paths: self.app.project.distorted_paths.remove(p2)
            for layer_paths in self.app.project.layers.values():
                if p2 in layer_paths: layer_paths.remove(p2)
            self.selected_path = p1
            self.app.log("Успех: Два вектора сшиты в один!")
        self.weld_anchor = None
        self.app.controller.invalidate_downstream()
        self.render_canvas()

    def on_left_click(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.canvas.focus_set()
        self.canvas_h = self.canvas.winfo_height()
        
        if self.is_measuring:
            wx, wy, snapped_pt, _ = self.get_snapped_coords(event.x, event.y)
            if not self.measure_pt1: 
                self.measure_pt1 = (wx, wy)
                self.app.log(f"-> Замер от: X={wx:.3f}, Y={wy:.3f}")
            else:
                dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
                self.app.log(f"=== РАССТОЯНИЕ: {dist:.4f} мм ===")
                self.measure_pt1 = None
                self.canvas.delete("measure_dynamic")
                sx, sy = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00FF00", tags="measure_dynamic")
            return
            
        if self.is_delete_node_mode:
            match = self.get_any_node_at(event.x, event.y, radius=10)
            if match:
                path, idx = match
                path.points.pop(idx)
                if len(path.points) < 2:
                    if path in self.app.project.raw_paths: self.app.project.raw_paths.remove(path)
                    if path in self.app.project.ready_paths: self.app.project.ready_paths.remove(path)
                    if path in self.app.project.distorted_paths: self.app.project.distorted_paths.remove(path)
                    for layer_paths in self.app.project.layers.values():
                        if path in layer_paths: layer_paths.remove(path)
                    if self.selected_path == path: self.selected_path = None
                self.app.controller.invalidate_downstream()
                self.render_canvas()
                self.app.log("Узел удален кликом.")
            return
            
        if self.selected_path:
            node_idx = self.get_node_at(event.x, event.y)
            if node_idx is not None:
                self.selected_node_idx = node_idx
                return

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
        elif self.is_delete_node_mode: 
            self.app.controller.toggle_delete_node_mode()
        elif self.weld_anchor:
            self.weld_anchor = None
            self.app.log("Сварка отменена.")
            self.render_canvas()
        else:
            self.selected_path = None
            self.render_canvas()

    def on_mouse_move(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.canvas.delete("hover_tooltip")
        self.canvas.delete("coord_tracker")
        
        wx, wy, snapped_pt, layer_name = self.get_snapped_coords(event.x, event.y)
        
        z_val = snapped_pt[2] if snapped_pt and len(snapped_pt) > 2 and snapped_pt[2] is not None else 0.000
        coord_text = f"X: {wx:.3f}   Y: {wy:.3f}   Z: {z_val:.3f}"
        self.canvas.create_text(self.canvas.winfo_width() - 15, self.canvas_h - 15, 
                                text=coord_text, fill="#00FFFF", font=("Courier New", 12, "bold"), 
                                anchor=tk.SE, tags="coord_tracker")
        
        if hasattr(self, 'ruler_x'):
            self.ruler_x.delete("tracker")
            self.ruler_y.delete("tracker")
            self.ruler_x.create_line(event.x, 0, event.x, 25, fill="red", tags="tracker")
            self.ruler_y.create_line(0, event.y, 25, event.y, fill="red", tags="tracker")

        if self.is_measuring and self.measure_pt1:
            self.canvas.delete("measure_dynamic")
            dist = math.hypot(wx - self.measure_pt1[0], wy - self.measure_pt1[1])
            sx1, sy1 = self.measure_pt1[0] * self.current_scale + self.current_tx, self.canvas_h - (self.measure_pt1[1] * self.current_scale + self.current_ty)
            sx2, sy2 = wx * self.current_scale + self.current_tx, self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FFD700", dash=(4, 4), tags="measure_dynamic")
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#FFD700", width=2, tags="measure_dynamic")
            self.canvas.create_text(event.x + 15, event.y - 15, text=f"{dist:.3f} мм", fill="#FFD700", font=("Arial", 11, "bold"), anchor=tk.SW, tags="measure_dynamic")
            return
            
        if self.selected_path and self.selected_node_idx is None:
            hover_idx = self.get_node_at(event.x, event.y)
            if hover_idx != self.hovered_node_idx:
                self.hovered_node_idx = hover_idx
                self.render_canvas()
        
        if snapped_pt and not self.selected_path:
            sx2 = wx * self.current_scale + self.current_tx
            sy2 = self.canvas_h - (wy * self.current_scale + self.current_ty)
            self.canvas.create_oval(sx2-4, sy2-4, sx2+4, sy2+4, outline="#00FFFF", width=2, tags="hover_tooltip")
            
            z_str = f"\nZ: {snapped_pt[2]:.3f}" if len(snapped_pt) > 2 and snapped_pt[2] is not None else ""
            text = f"Слой: {layer_name}\nX: {snapped_pt[0]:.3f}\nY: {snapped_pt[1]:.3f}{z_str}"
            
            text_id = self.canvas.create_text(event.x + 15, event.y - 15, text=text, fill="#00FFFF", font=("Arial", 10, "bold"), anchor=tk.SW, tags="hover_tooltip")
            bbox = self.canvas.bbox(text_id)
            if bbox:
                self.canvas.create_rectangle(bbox[0]-3, bbox[1]-3, bbox[2]+3, bbox[3]+3, fill="#1e1e1e", outline="#00FFFF", tags="hover_tooltip")
                self.canvas.tag_raise(text_id)

    def on_pan_move(self, event):
        if self.is_measuring or self.is_delete_node_mode: return 
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
            self.app.controller.invalidate_downstream()
            self.render_canvas()
            self.on_mouse_move(event)
            return

        self.current_tx += event.x - self.pan_start_x
        self.current_ty -= event.y - self.pan_start_y 
        self.pan_start_x, self.pan_start_y = event.x, event.y
        self.render_canvas()
        self.on_mouse_move(event)

    def on_mousewheel(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0: zoom = 1.1 
        elif event.num == 5 or getattr(event, 'delta', 0) < 0: zoom = 0.9 
        else: return
        wx, wy = (event.x - self.current_tx) / self.current_scale, (self.canvas_h - event.y - self.current_ty) / self.current_scale
        self.current_scale *= zoom
        self.current_tx, self.current_ty = event.x - wx * self.current_scale, self.canvas_h - event.y - wy * self.current_scale
        self.render_canvas()
        self.on_mouse_move(event)

    def fit_to_screen(self):
        visible = self.get_visible_paths()
        if not visible: return
        all_x, all_y = [pt[0] for p in visible for pt in p.points], [pt[1] for p in visible for pt in p.points]
        if not all_x or not all_y: return
        w_mm, h_mm = max(all_x) - min(all_x), max(all_y) - min(all_y)
        if w_mm == 0: w_mm = 1
        if h_mm == 0: h_mm = 1
        self.app.root.update() 
        self.canvas_h = self.canvas.winfo_height()
        pad = 30 
        self.current_scale = min((self.canvas.winfo_width() - 2 * pad) / w_mm, (self.canvas_h - 2 * pad) / h_mm)
        self.current_tx = (self.canvas.winfo_width() - w_mm * self.current_scale) / 2 - min(all_x) * self.current_scale
        self.current_ty = (self.canvas_h - h_mm * self.current_scale) / 2 - min(all_y) * self.current_scale

    def _draw_rulers(self):
        if not hasattr(self, 'ruler_x'): return
        self.ruler_x.delete("all")
        self.ruler_y.delete("all")

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1: return

        min_px_step = 50
        world_step = min_px_step / self.current_scale if self.current_scale > 0 else 1
        
        magnitude = 10 ** math.floor(math.log10(world_step)) if world_step > 0 else 1
        rel_step = world_step / magnitude
        if rel_step <= 1: step = 1 * magnitude
        elif rel_step <= 2: step = 2 * magnitude
        elif rel_step <= 5: step = 5 * magnitude
        else: step = 10 * magnitude
        
        if step <= 0: step = 10

        start_x_world = -self.current_tx / self.current_scale
        end_x_world = (w - self.current_tx) / self.current_scale
        first_tick_x = math.ceil(start_x_world / step) * step
        x_world = first_tick_x
        limit = 0
        
        while x_world <= end_x_world and limit < 1000:
            sx = x_world * self.current_scale + self.current_tx
            self.ruler_x.create_line(sx, 15, sx, 25, fill="black")
            self.ruler_x.create_text(sx + 2, 2, text=f"{x_world:g}", anchor=tk.NW, font=("Arial", 7))
            self.canvas.create_line(sx, 0, sx, h, fill="#2a2a2a", dash=(2, 4), tags="grid")
            for i in range(1, 10):
                minor_x_world = x_world + i * (step / 10)
                if minor_x_world > end_x_world: break
                msx = minor_x_world * self.current_scale + self.current_tx
                tick_h = 20 if i == 5 else 22
                self.ruler_x.create_line(msx, tick_h, msx, 25, fill="gray")
                if i == 5:
                    self.canvas.create_line(msx, 0, msx, h, fill="#222222", dash=(1, 5), tags="grid")
            x_world += step
            limit += 1

        start_y_world = -self.current_ty / self.current_scale
        end_y_world = (h - self.current_ty) / self.current_scale
        first_tick_y = math.ceil(start_y_world / step) * step
        y_world = first_tick_y
        limit = 0
        
        while y_world <= end_y_world and limit < 1000:
            sy = h - (y_world * self.current_scale + self.current_ty)
            self.ruler_y.create_line(15, sy, 25, sy, fill="black")
            self.ruler_y.create_text(13, sy - 2, text=f"{y_world:g}", anchor=tk.SE, font=("Arial", 7), angle=90)
            self.canvas.create_line(0, sy, w, sy, fill="#2a2a2a", dash=(2, 4), tags="grid")
            for i in range(1, 10):
                minor_y_world = y_world + i * (step / 10)
                if minor_y_world > end_y_world: break
                msy = h - (minor_y_world * self.current_scale + self.current_ty)
                tick_w = 20 if i == 5 else 22
                self.ruler_y.create_line(tick_w, msy, 25, msy, fill="gray")
                if i == 5:
                    self.canvas.create_line(0, msy, w, msy, fill="#222222", dash=(1, 5), tags="grid")
            y_world += step
            limit += 1
            
        self.canvas.tag_lower("grid")

    def render_canvas(self):
        self.canvas.delete("all")
        self.canvas_h = self.canvas.winfo_height()
        
        if self.app.ui.show_rapids.get() and self.app.project.layers.get("cnc", []):
            curr_pos = (0.0, 0.0)
            for path in self.app.project.layers["cnc"]:
                if not path.points: continue
                start_pt = path.points[0]
                sx1 = curr_pos[0] * self.current_scale + self.current_tx
                sy1 = self.canvas_h - (curr_pos[1] * self.current_scale + self.current_ty)
                sx2 = start_pt[0] * self.current_scale + self.current_tx
                sy2 = self.canvas_h - (start_pt[1] * self.current_scale + self.current_ty)
                
                if math.hypot(start_pt[0] - curr_pos[0], start_pt[1] - curr_pos[1]) > 0.1:
                    self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FF8C00", width=1.5, dash=(4, 4))
                
                curr_pos = path.points[-1]
                
            sx1 = curr_pos[0] * self.current_scale + self.current_tx
            sy1 = self.canvas_h - (curr_pos[1] * self.current_scale + self.current_ty)
            sx2 = 0.0 * self.current_scale + self.current_tx
            sy2 = self.canvas_h - (0.0 * self.current_scale + self.current_ty)
            if math.hypot(0.0 - curr_pos[0], 0.0 - curr_pos[1]) > 0.1:
                self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#FF8C00", width=1.5, dash=(4, 4))
        
        layers_to_draw = [
            (self.app.ui.show_raw, self.app.project.layers.get("raw", []), "#555555", 1.0, None),
            (self.app.ui.show_healed, self.app.project.layers.get("healed", []), "#00FFFF", 1.5, None),
            (self.app.ui.show_array, self.app.project.layers.get("array", []), "#9370DB", 1.5, None),
            (self.app.ui.show_distorted, self.app.project.layers.get("distorted", []), "#1E90FF", 1.5, None),
            (self.app.ui.show_mask, self.app.project.layers.get("mask", []), "#FF1493", 2.0, None),
            (self.app.ui.show_ideal, self.app.project.layers.get("ideal", []), "#FFFF00", 2.0, None), 
            (self.app.ui.show_cnc, self.app.project.layers.get("cnc", []), "#00FF00", 1.5, (5, 5))
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
                            
                    if is_selected:
                        for i, pt in enumerate(path.points):
                            nx = pt[0] * self.current_scale + self.current_tx
                            ny = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
                            fill_color = "#FF0000" if self.hovered_node_idx == i else "#FFFFFF"
                            self.canvas.create_rectangle(nx-3, ny-3, nx+3, ny+3, fill=fill_color, outline="#FF4500", tags="node")
        
        if self.weld_anchor:
            wp, w_idx = self.weld_anchor
            if wp in self.get_visible_paths() and w_idx < len(wp.points):
                pt = wp.points[w_idx]
                nx = pt[0] * self.current_scale + self.current_tx
                ny = self.canvas_h - (pt[1] * self.current_scale + self.current_ty)
                self.canvas.create_oval(nx-6, ny-6, nx+6, ny+6, outline="#00FF00", width=2, tags="weld_anchor")

        colors = {"red": "#FF0000", "orange": "#FFA500", "magenta": "#FF00FF", "yellow": "#FFFF00"}
        for k, pts in self.app.project.error_markers.items():
            for x, y in pts:
                sx, sy = x * self.current_scale + self.current_tx, self.canvas_h - (y * self.current_scale + self.current_ty)
                self.canvas.create_oval(sx-5, sy-5, sx+5, sy+5, outline=colors[k], width=2, tags="error_marker")

        cx, cy = 40, self.canvas_h - 40
        axis = self.app.ui.var_dist_axis.get()
        x_width = 4 if axis == "X" else 1
        y_width = 4 if axis == "Y" else 1
        
        self.canvas.create_line(cx, cy, cx + 45, cy, fill="#FF4500", width=x_width, arrow=tk.LAST, tags="ucs")
        self.canvas.create_text(cx + 55, cy, text="X", fill="#FF4500", font=("Arial", 10, "bold"), anchor=tk.W, tags="ucs")
        self.canvas.create_line(cx, cy, cx, cy - 45, fill="#32CD32", width=y_width, arrow=tk.LAST, tags="ucs")
        self.canvas.create_text(cx, cy - 55, text="Y", fill="#32CD32", font=("Arial", 10, "bold"), anchor=tk.S, tags="ucs")
        self.canvas.create_oval(cx-3, cy-3, cx+3, cy+3, fill="white", tags="ucs")
        
        if self.app.project.is_distorted:
            self.canvas.create_text(cx, cy - 80, text=f"⚠️ ДИСТОРСИЯ ПРИМЕНЕНА ({self.app.project.applied_dist_axis})", fill="#FF4500", font=("Arial", 10, "bold"), anchor=tk.SW, tags="ucs")

        self._draw_rulers()