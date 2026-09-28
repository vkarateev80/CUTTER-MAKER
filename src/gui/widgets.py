"""Кнопки CUTTER MAKER, устойчивые к тёмной теме macOS.

Диагноз (2026-09-28): на Tk 9 / macOS tk.Button ИГНОРИРУЕТ bg/fg — все цветные
кнопки рендерятся белыми, а белый текст (fg="white") становится нечитаемым.
Тест: ttk.Button в clam-теме рисует цвет корректно.

Поэтому все кнопки приложения — это этот класс: внешне API tk.Button
(bg/fg/font/relief/config(state=...)), внутри ttk + лениво регистрируемые стили.
"""

import tkinter as tk
from tkinter import ttk

# macOS-дефолт — тема "aqua": она игнорирует background стилей (кнопки остаются
# белыми). clam рисует заданные цвета — фиксируем тему ДО первой кнопки.
_THEME_LOCKED = False


def _lock_theme(master) -> None:
    global _THEME_LOCKED
    if _THEME_LOCKED:
        return
    try:
        ttk.Style(master.winfo_toplevel()).theme_use("clam")
    except tk.TclError:
        pass
    _THEME_LOCKED = True


# (bg, fg, font, relief) -> имя стиля; стили регистрируются один раз на процесс
_STYLE_CACHE: dict[tuple, str] = {}
_STYLE_SEQ = [0]


def _blend(c1: str, c2: str, t: float) -> str:
    """Смешать два hex-цвета: t=1 → c1 полностью."""
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{int(x * t + y * (1 - t)):02x}" for x, y in zip(a, b))


class Button(ttk.Button):
    """Кнопка с API tk.Button, отрисовываемая через ttk/clam-стили."""

    def __init__(self, master, bg=None, fg=None, relief=None, font=None, **kw):
        _lock_theme(master)
        # Истекшее «состояние внешнего вида» — переживает .config(bg=...)
        self._look = {"bg": bg, "fg": fg, "relief": relief, "font": font}
        if any(v is not None for v in self._look.values()):
            kw["style"] = self._ensure_style(master.winfo_toplevel(), self._look)
        super().__init__(master, **kw)

    @staticmethod
    def _ensure_style(master, look: dict) -> str:
        key = (look["bg"], look["fg"], look["relief"], look["font"])
        name = _STYLE_CACHE.get(key)
        if name:
            return name

        _STYLE_SEQ[0] += 1
        name = f"Cm{_STYLE_SEQ[0]}.TButton"
        style = ttk.Style(master)

        bg, fg, relief, font = key
        # Панель светлая: цветной фон без явного fg получает тёмный текст
        if bg and not fg:
            fg = "#111111"
        cfg = {}
        if bg:
            cfg["background"] = bg
            cfg["activebackground"] = _blend(bg, "#000000", 0.85)
        if fg:
            cfg["foreground"] = fg
            cfg["activeforeground"] = fg
        if relief:
            cfg["relief"] = relief
        if font:
            cfg["font"] = font
        style.configure(name, **cfg)

        if bg:
            # Disabled: приглушённый фон + контрастный серый текст (не слипается)
            style.map(
                name,
                background=[("disabled", _blend(bg, "#ECECEC", 0.45))],
                foreground=[("disabled", "#7A7A7A")],
            )
        _STYLE_CACHE[key] = name
        return name

    def configure(self, cnf=None, **kw):
        merged = dict(cnf or {})
        merged.update(kw)
        # ttk-кнопка не знает bg/fg/font/relief — перекладываем в стиль
        changed = {}
        for tk_key, look_key in (
            ("bg", "bg"), ("background", "bg"),
            ("fg", "fg"), ("foreground", "fg"),
            ("relief", "relief"), ("font", "font"),
        ):
            if tk_key in merged:
                changed[look_key] = merged.pop(tk_key)
        if changed:
            self._look.update(changed)
            merged["style"] = self._ensure_style(self.winfo_toplevel(), self._look)
        if merged:
            return super().configure(**merged)

    # ttk-виджет наследует config=configure из ttk.Widget (старую функцию) —
    # перепривязываем alias на наш переопределённый метод
    config = configure
