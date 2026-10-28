"""Eine Palette, die dem Farbschema der Arbeitsumgebung folgt.

Hell und dunkel kommen aus ``QStyleHints.colorScheme``. Eine Akzentfarbe
reicht: Auswahl, Links und die Accent-Rolle. Leiste, Knoepfe und die
Seitenleisten lesen diese Palette. Die Zeichenflaeche und die Auswahlgriffe
behalten ihre eigenen Farben. Dunkle Flaechen sind blau-grau, wie die
COSMIC-Apps, damit Felder und Text sich vom Grund abheben.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

#: Blau aus dem GNOME-/COSMIC-Umfeld. Hell und dunkel teilen sich die Farbe.
ACCENT = "#3584e4"
#: Heller Fenstergrund. Unveraendert, damit Felder weiss bleiben.
LIGHT_WINDOW = "#fafafa"
#: Dunkler Grund mit etwas Blau, nicht neutrales Grau.
DARK_WINDOW = "#1e2430"
#: Fehlerrot auf hellem Grund. Auf Dunkel waere es kaum zu lesen.
ERROR_TEXT = "#b00020"
ERROR_TEXT_DARK = "#ff8a80"

#: Manuelle Ausnahme. ``None`` heisst: das Farbschema der Arbeitsumgebung.
_explicit: Qt.ColorScheme | None = None
#: Welche Anwendung schon auf ``colorSchemeChanged`` hoert.
_listening_app_id: int | None = None
#: Verhindert, dass ``setColorScheme`` ``_apply`` noch einmal anstoesst.
_applying = False


def palette_for(scheme: Qt.ColorScheme) -> QPalette:
    """Helle oder dunkle Palette. ``Unknown`` bleibt hell."""
    dark = scheme == Qt.ColorScheme.Dark
    accent = QColor(ACCENT)
    if dark:
        window = QColor(DARK_WINDOW)
        button = QColor("#2c3444")
        base = QColor("#262e3c")
        text = QColor("#e7edf6")
        disabled_text = QColor("#93a0b4")
        mid = QColor("#617089")
    else:
        window = QColor(LIGHT_WINDOW)
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


def error_text_color() -> QColor:
    """Fehlerrot, das auf dem aktuellen Fenstergrund lesbar bleibt."""
    app = QApplication.instance()
    window = (
        app.palette().color(QPalette.ColorRole.Window)
        if isinstance(app, QApplication)
        else QColor(LIGHT_WINDOW)
    )
    if window.lightness() < 128:
        return QColor(ERROR_TEXT_DARK)
    return QColor(ERROR_TEXT)


def scheme_for(name: str | None) -> Qt.ColorScheme | None:
    """Gespeicherte Wahl in ein Farbschema. ``system`` folgt der Arbeitsumgebung."""
    if name == "dark":
        return Qt.ColorScheme.Dark
    if name == "light":
        return Qt.ColorScheme.Light
    return None


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
    if _explicit is not None or _applying:
        return
    app = QApplication.instance()
    if isinstance(app, QApplication):
        _apply(app)


def _resolve(app: QApplication) -> Qt.ColorScheme:
    if _explicit is not None:
        return _explicit
    current = app.styleHints().colorScheme()
    if current == Qt.ColorScheme.Unknown:
        return Qt.ColorScheme.Light
    return current


def _apply(app: QApplication) -> None:
    """Palette setzen, und das Farbschema, damit Auswahllisten mitgehen.

    Nur die Palette reicht nicht: auf einem dunklen Desktop bleiben
    Combobox-Listen dunkel, auch wenn die Anwendung hell gezeichnet wird.
    ``setColorScheme`` zieht diese Listen mit. Danach kommt die eigene
    Palette, sonst ersetzt der Stil sie durch seine Standardfarben.
    """
    global _applying
    if _applying:
        return
    _applying = True
    try:
        scheme = _resolve(app)
        hints = app.styleHints()
        wanted = scheme if _explicit is not None else Qt.ColorScheme.Unknown
        if hints.colorScheme() != wanted:
            hints.setColorScheme(wanted)
        app.setPalette(palette_for(scheme))
    finally:
        _applying = False
