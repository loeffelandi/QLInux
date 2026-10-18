"""Eine Palette, die dem Farbschema der Arbeitsumgebung folgt.

Hell und dunkel kommen aus ``QStyleHints.colorScheme``. Eine Akzentfarbe
reicht: Auswahl, Links und die Accent-Rolle. Leiste, Knoepfe und die
Seitenleisten lesen diese Palette. Zeichenflaeche, Icons und Auswahlgriffe
behalten ihre eigenen Farben.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

#: Blau aus dem GNOME-/COSMIC-Umfeld. Hell und dunkel teilen sich die Farbe.
ACCENT = "#3584e4"

#: Manuelle Ausnahme. ``None`` heisst: das Farbschema der Arbeitsumgebung.
_explicit: Qt.ColorScheme | None = None
#: Welche Anwendung schon auf ``colorSchemeChanged`` hoert.
_listening_app_id: int | None = None


def palette_for(scheme: Qt.ColorScheme) -> QPalette:
    """Helle oder dunkle Palette. ``Unknown`` bleibt hell."""
    dark = scheme == Qt.ColorScheme.Dark
    accent = QColor(ACCENT)
    if dark:
        window = QColor("#242424")
        button = QColor("#303030")
        base = QColor("#1e1e1e")
        text = QColor("#ffffff")
        disabled_text = QColor("#8a8a8a")
        mid = QColor("#5e5c64")
    else:
        window = QColor("#fafafa")
        button = QColor("#ebebeb")
        base = QColor("#ffffff")
        text = QColor("#241f31")
        disabled_text = QColor("#929595")
        mid = QColor("#c0bfbc")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, button)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.BrightText, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Accent, accent)
    pal.setColor(QPalette.ColorRole.Link, accent)
    pal.setColor(QPalette.ColorRole.LinkVisited, accent)
    pal.setColor(QPalette.ColorRole.Mid, mid)
    pal.setColor(QPalette.ColorRole.Midlight, mid.lighter(110))
    pal.setColor(QPalette.ColorRole.Dark, window.darker(140))
    pal.setColor(QPalette.ColorRole.Light, button.lighter(108))
    pal.setColor(QPalette.ColorRole.Shadow, window.darker(150))
    pal.setColor(QPalette.ColorRole.ToolTipBase, button)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    placeholder = QColor(text)
    placeholder.setAlpha(140)
    pal.setColor(QPalette.ColorRole.PlaceholderText, placeholder)

    disabled = QPalette.ColorGroup.Disabled
    pal.setColor(disabled, QPalette.ColorRole.Text, disabled_text)
    pal.setColor(disabled, QPalette.ColorRole.WindowText, disabled_text)
    pal.setColor(disabled, QPalette.ColorRole.ButtonText, disabled_text)
    pal.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#919191"))
    pal.setColor(disabled, QPalette.ColorRole.Accent, QColor("#919191"))
    pal.setColor(disabled, QPalette.ColorRole.Base, window)
    return pal


def apply_theme(app: QApplication, scheme: Qt.ColorScheme | None = None) -> None:
    """Palette der Anwendung setzen.

    Ohne ``scheme`` gilt das Farbschema der Arbeitsumgebung. Ein gesetztes
    ``scheme`` bleibt, bis der naechste Aufruf ohne Ausnahme kommt.
    """
    global _explicit, _listening_app_id
    _explicit = scheme if scheme not in (None, Qt.ColorScheme.Unknown) else None
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    if _listening_app_id != id(app):
        app.styleHints().colorSchemeChanged.connect(_follow_desktop)
        _listening_app_id = id(app)
    _apply(app)


def _follow_desktop(_scheme: Qt.ColorScheme) -> None:
    if _explicit is not None:
        return
    app = QApplication.instance()
    if app is not None:
        _apply(app)


def _resolve(app: QApplication) -> Qt.ColorScheme:
    if _explicit is not None:
        return _explicit
    current = app.styleHints().colorScheme()
    if current == Qt.ColorScheme.Unknown:
        return Qt.ColorScheme.Light
    return current


def _apply(app: QApplication) -> None:
    app.setPalette(palette_for(_resolve(app)))
