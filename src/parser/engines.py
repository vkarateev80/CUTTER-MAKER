"""Резолюция внешних движков (Inkscape, Ghostscript) по платформе.

Windows: бандлы в репо (inkscape_engine/, ghostscript_engine/).
macOS/Linux: системная установка — PATH + типовые места установки
(app-бандл Inkscape, ~/.local/bin от нашей сборки gs).
"""
import os
import shutil
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(os.getcwd())


def resolve_inkscape() -> Path | None:
    if os.name == "nt":
        exe = project_root() / "inkscape_engine" / "bin" / "inkscape.exe"
        return exe if exe.exists() else None
    candidates = [
        Path("/Applications/Inkscape.app/Contents/MacOS/inkscape"),
        Path.home() / "Applications/Inkscape.app/Contents/MacOS/inkscape",
    ]
    for c in candidates:
        if c.exists():
            return c
    which = shutil.which("inkscape")
    return Path(which) if which else None


def resolve_gs() -> Path | None:
    if os.name == "nt":
        base = project_root() / "ghostscript_engine" / "gs10.07.1" / "bin"
        for name in ("gswin64c.exe", "gswin32c.exe"):
            exe = base / name
            if exe.exists():
                return exe
        return None
    candidates = [
        Path.home() / ".local" / "bin" / "gs",
        Path("/usr/local/bin/gs"),
        Path("/opt/homebrew/bin/gs"),
        Path("/opt/local/bin/gs"),
    ]
    for c in candidates:
        if c.exists():
            return c
    which = shutil.which("gs")
    return Path(which) if which else None


def require_inkscape() -> Path:
    exe = resolve_inkscape()
    if exe is None:
        raise RuntimeError(
            "Inkscape не найден: установите Inkscape (macOS: /Applications/Inkscape.app) "
            "или положите движок в inkscape_engine/bin (Windows)."
        )
    return exe


def require_gs() -> Path:
    exe = resolve_gs()
    if exe is None:
        raise RuntimeError(
            "Ghostscript (gs) не найден: установите Ghostscript "
            "(macOS: сборка в ~/.local/bin/gs или системный gs)."
        )
    return exe
