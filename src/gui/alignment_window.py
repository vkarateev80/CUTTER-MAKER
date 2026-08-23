import tkinter as tk
from tkinter import ttk, messagebox
from src.compiler.alignment_math import AlignmentTransform

class AlignmentWindow(tk.Toplevel):
    def __init__(self, parent, ideal_marks: list[tuple[float, float]]):
        super().__init__(parent)
        self.title("Калибровка ЧПУ (Регистрация по меткам)")
        self.geometry("750x550")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.ideal_marks = ideal_marks
        self.actual_entries = []  # Хранит кортежи (Entry_X, Entry_Y)
        
        self.result_transform = None  # Сюда запишем объект AlignmentTransform при успехе
        self.result_stats = None      # Сюда запишем словарь со статистикой

        self._build_ui()

    def _build_ui(self):
        # --- Инструкция ---
        frame_info = tk.Frame(self, bg="#E6F2FF", padx=10, pady=10)
        frame_info.pack(fill=tk.X)
        
        lbl_title = tk.Label(frame_info, text="Ввод фактических машинных координат", font=("Arial", 12, "bold"), bg="#E6F2FF", fg="#000080")
        lbl_title.pack(anchor=tk.W)
        
        desc = ("1. Подведите камеру или центроискатель станка к центру каждой метки.\n"
                "2. Впишите фактические координаты X и Y с пульта станка в правые столбцы.\n"
                "3. Нажмите «Рассчитать погрешность» для проверки, затем «Применить».")
        tk.Label(frame_info, text=desc, justify=tk.LEFT, bg="#E6F2FF", font=("Arial", 9)).pack(anchor=tk.W, pady=(5, 0))

        # --- Таблица координат ---
        frame_table = tk.LabelFrame(self, text="Таблица меток", padx=10, pady=10)
        frame_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Заголовки таблицы
        headers = ["№ Метки", "Теория X (мм)", "Теория Y (мм)", "ФАКТ X (мм)", "ФАКТ Y (мм)"]
        for col, text in enumerate(headers):
            tk.Label(frame_table, text=text, font=("Arial", 9, "bold"), fg="#333").grid(row=0, column=col, padx=10, pady=5)

        # Генерация строк
        for i, (ix, iy) in enumerate(self.ideal_marks):
            tk.Label(frame_table, text=f"Метка {i+1}").grid(row=i+1, column=0, pady=5)
            tk.Label(frame_table, text=f"{ix:.3f}", fg="gray").grid(row=i+1, column=1, pady=5)
            tk.Label(frame_table, text=f"{iy:.3f}", fg="gray").grid(row=i+1, column=2, pady=5)

            ent_x = tk.Entry(frame_table, width=15, font=("Courier New", 10))
            ent_x.insert(0, f"{ix:.3f}")  # Предзаполняем теорией
            ent_x.grid(row=i+1, column=3, padx=10, pady=5)

            ent_y = tk.Entry(frame_table, width=15, font=("Courier New", 10))
            ent_y.insert(0, f"{iy:.3f}")  # Предзаполняем теорией
            ent_y.grid(row=i+1, column=4, padx=10, pady=5)

            self.actual_entries.append((ent_x, ent_y))

        # --- Результаты расчета ---
        self.frame_res = tk.LabelFrame(self, text="Результаты калибровки", padx=10, pady=10, fg="#008800")
        self.frame_res.pack(fill=tk.X, padx=10, pady=5)

        self.lbl_offset = tk.Label(self.frame_res, text="Смещение (X, Y): --", font=("Arial", 10))
        self.lbl_offset.grid(row=0, column=0, sticky=tk.W, padx=(0, 20), pady=2)
        
        self.lbl_angle = tk.Label(self.frame_res, text="Угол поворота: --", font=("Arial", 10))
        self.lbl_angle.grid(row=0, column=1, sticky=tk.W, padx=(0, 20), pady=2)
        
        self.lbl_scale = tk.Label(self.frame_res, text="Масштаб (Усадка): --", font=("Arial", 10))
        self.lbl_scale.grid(row=0, column=2, sticky=tk.W, pady=2)

        # --- Кнопки ---
        frame_btns = tk.Frame(self)
        frame_btns.pack(fill=tk.X, padx=10, pady=10)

        btn_calc = tk.Button(frame_btns, text="🧮 Рассчитать погрешность", bg="#FFD700", font=("Arial", 10, "bold"), command=self._calculate)
        btn_calc.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_apply = tk.Button(frame_btns, text="✅ Применить трансформацию", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self._apply)
        self.btn_apply.pack(side=tk.RIGHT)

        btn_cancel = tk.Button(frame_btns, text="Отмена", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=10)

    def _calculate(self):
        actual_pts = []
        for ex, ey in self.actual_entries:
            try:
                x = float(ex.get().replace(',', '.'))
                y = float(ey.get().replace(',', '.'))
                actual_pts.append((x, y))
            except ValueError:
                messagebox.showerror("Ошибка", "Координаты должны быть числами!")
                return

        try:
            transform = AlignmentTransform()
            stats = transform.compute_from_points(self.ideal_marks, actual_pts)
            
            self.lbl_offset.config(text=f"Смещение: X={stats['offset_x']} мм, Y={stats['offset_y']} мм", fg="black")
            
            angle = stats['angle_deg']
            angle_color = "#FF0000" if abs(angle) > 2.0 else "black"
            self.lbl_angle.config(text=f"Угол поворота: {angle}°", fg=angle_color)
            
            sx, sy = stats['scale_x'], stats['scale_y']
            self.lbl_scale.config(text=f"Масштаб: X={sx}, Y={sy}", fg="black")

            self.result_transform = transform
            self.result_stats = stats
            self.btn_apply.config(state=tk.NORMAL)

        except Exception as e:
            messagebox.showerror("Математическая ошибка", f"Невозможно вычислить матрицу:\n{str(e)}")

    def _apply(self):
        if self.result_transform:
            self.destroy()