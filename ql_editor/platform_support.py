"""Unterschiede zwischen Linux und macOS an einer Stelle.

Alle Funktionen fragen :func:`current` bei jedem Aufruf. Ein Test setzt die
Plattform ueber ``_override`` (Fixture ``platform`` in ``tests/conftest.py``),
ohne ``sys.platform`` fuer fremden Code zu verbiegen.
"""

from __future__ import annotations

import functools
import os
import re
import sys
from pathlib import Path

from . import APP_NAME

#: Nur fuer Tests: ersetzt ``sys.platform``.
_override: str | None = None


def current() -> str:
    """``sys.platform`` - oder der Wert, den ein Test gesetzt hat."""
    return _override or sys.platform


def is_mac() -> bool:
    """Laeuft das Programm auf macOS?"""
    return current() == "darwin"


def supports_udev() -> bool:
    """Gibt es udev und polkit? Nur unter Linux: dort richtet das Programm
    die USB-Rechte ein, auf dem Mac braucht der Drucker keine Regel."""
    return current().startswith("linux")


def user_data_dir() -> Path:
    """Ordner der eigenen Daten (Vorlagen).

    Linux: ``$XDG_CONFIG_HOME/QLInux`` bzw. ``~/.config/QLInux``, dieselbe
    Ecke wie die Einstellungen. macOS: ``~/Library/Application Support/QLInux``.
    """
    if is_mac():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


# -- Tasten in Mac-Schreibweise --------------------------------------------- #
_MODIFIER = r"(?:Strg|Ctrl|Umschalt|Shift|Alt)\b"
#: Eine oder mehrere Modifier-Tasten, optional mit einer Taste dahinter.
_COMBO = re.compile(
    rf"\b({_MODIFIER}(?:\s?\+\s?{_MODIFIER})*)"
    r"(?:\s?\+\s?(F\d{1,2}\b|Tab\b|Entf\b|Del\b|[A-Za-z0-9]\b|[+\-]|[A-Za-zÄÖÜäöüß]+))?"
)
_MAC_SYMBOL = {
    "strg": "⌘",
    "ctrl": "⌘",
    "umschalt": "⇧",
    "shift": "⇧",
    "alt": "⌥",
}
#: Reihenfolge der Symbole auf dem Mac: Control, Option, Shift, Command.
_MAC_ORDER = "⌃⌥⇧⌘"
#: macOS belegt Strg+Tab und Strg+F4 nicht wie Linux. Diese Kuerzel gehen vor.
_MAC_SPECIAL = (
    (re.compile(r"\b(?:Strg|Ctrl)\+(?:Umschalt|Shift)\+Tab\b"), "⌃⇧Tab"),
    (re.compile(r"\b(?:Strg|Ctrl)\+Tab\b"), "⌃Tab"),
    (re.compile(r"\b(?:Strg|Ctrl)\+F4\b"), "⌘W"),
    (re.compile(r"\b(?:Strg|Ctrl)\+Y\b"), "⇧⌘Z"),
)


def _combo(match: re.Match[str]) -> str:
    modifiers = re.split(r"\s?\+\s?", match.group(1))
    symbols = {_MAC_SYMBOL[name.lower()] for name in modifiers}
    text = "".join(sorted(symbols, key=_MAC_ORDER.index))
    key = match.group(2)
    if key is None:
        return text
    if key in ("Entf", "Del"):
        return text + "⌫"
    if len(key) == 1 or key == "Tab" or re.fullmatch(r"F\d{1,2}", key):
        return text + key
    return f"{text}-{key}"


@functools.lru_cache(maxsize=2048)
def mac_keys(text: str) -> str:
    """Tasten eines Textes in Mac-Schreibweise: ``Strg+Umschalt+S`` -> ``⇧⌘S``.

    Gemeint sind die deutschen und englischen Texte der Oberflaeche. ``Strg``
    und ``Ctrl`` werden zu ⌘, ``Umschalt`` und ``Shift`` zu ⇧, ``Alt`` zu ⌥,
    ``Entf`` und ``Del`` zu ⌫. Kombinationen mit einer Taste werden
    zusammengezogen, mit einem Wort bekommen sie einen Strich (``⌘-Klick``).
    """
    for pattern, replacement in _MAC_SPECIAL:
        text = pattern.sub(replacement, text)
    text = text.replace("Umschalttaste", "⇧-Taste")
    text = _COMBO.sub(_combo, text)
    return re.sub(r"\b(?:Entf|Del)\b", "⌫", text)
