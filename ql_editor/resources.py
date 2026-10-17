"""Pfade zu mitgelieferten Dateien (App-Symbol, Vorlagen-Grafiken).

Drei Faelle, die alle vorkommen:

* aus dem Quelltext gestartet (Entwicklung): ``assets/`` neben dem Paket
* aus einem PyInstaller-Bundle gestartet (AppImage): ``assets/`` im Bundle,
  das PyInstaller ueber ``sys._MEIPASS`` bekannt gibt
* Tests: ueber ``QLINUX_ASSETS_DIR`` umgebogen

Kein Qt in diesem Modul - nur Pfade.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Umgebungsvariable, die das Verzeichnis uebersteuert (Tests).
ASSETS_ENV = "QLINUX_ASSETS_DIR"

#: Name des App-Symbols (siehe ``packaging/make_icon.py``).
APP_ICON = "ql-editor.png"


def assets_dir() -> Path:
    """Verzeichnis mit den mitgelieferten Dateien."""
    override = os.environ.get(ASSETS_ENV)
    if override:
        return Path(override)
    bundled = getattr(sys, "_MEIPASS", None)   # PyInstaller (AppImage)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def asset(name: str) -> Path:
    """Pfad einer mitgelieferten Datei (auch wenn sie fehlt - Aufrufer prueft)."""
    return assets_dir() / name
