"""Palette folgt dem Farbschema, ohne ein Fenster aufzubauen."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from ql_editor.theme import ACCENT, DARK_WINDOW, LIGHT_WINDOW, apply_theme, palette_for, scheme_for


def test_scheme_for_keeps_the_system_as_default():
    assert scheme_for(None) is None
    assert scheme_for("system") is None
    assert scheme_for("light") == Qt.ColorScheme.Light
    assert scheme_for("dark") == Qt.ColorScheme.Dark
    assert scheme_for("nope") is None


def test_dark_palette_is_darker_and_shares_one_accent():
    light = palette_for(Qt.ColorScheme.Light)
    dark = palette_for(Qt.ColorScheme.Dark)
    unknown = palette_for(Qt.ColorScheme.Unknown)
    window = QPalette.ColorRole.Window
    text = QPalette.ColorRole.WindowText
    assert light.color(window).lightness() > dark.color(window).lightness()
    assert dark.color(text).lightness() > light.color(text).lightness()
    assert unknown.color(window).name() == light.color(window).name()
    for palette in (light, dark):
        assert palette.color(QPalette.ColorRole.Highlight).name() == ACCENT
        assert palette.color(QPalette.ColorRole.Accent).name() == ACCENT
        assert palette.color(QPalette.ColorRole.Link).name() == ACCENT
        # Leiste und Knoepfe nutzen Button, die Flaeche Window.
        assert palette.color(QPalette.ColorRole.Button).name() != palette.color(window).name()


def test_apply_theme_uses_desktop_scheme_unless_overridden(qapp):
    original = QPalette(qapp.palette())
    try:
        apply_theme(qapp, Qt.ColorScheme.Dark)
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == DARK_WINDOW
        assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == ACCENT
        apply_theme(qapp)
        # Offscreen meldet Unknown: ohne Ausnahme bleibt die helle Palette.
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == LIGHT_WINDOW
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)


def _opaque_lightness(image) -> float:
    total = 0
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 40:
                continue
            total += color.lightness()
            count += 1
    assert count > 8
    return total / count


def test_colored_icons_get_lighter_on_the_dark_palette(qapp):
    """Feste Icon-Toene sind fuer hellen Grund. Auf Dunkel werden sie angehoben."""
    from ql_editor.icons import icon

    original = QPalette(qapp.palette())
    mark = icon("print")
    try:
        apply_theme(qapp, Qt.ColorScheme.Light)
        light = _opaque_lightness(mark.pixmap(24, 24).toImage())
        apply_theme(qapp, Qt.ColorScheme.Dark)
        dark = _opaque_lightness(mark.pixmap(24, 24).toImage())
        assert dark > light + 30
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)


def test_group_fields_follow_the_application_palette(qapp):
    """Felder im Kasten bleiben hell im Hellen und dunkel im Dunkeln."""
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QComboBox, QVBoxLayout

    from ql_editor.widgets import title_box

    original = QPalette(qapp.palette())

    def field_lightness() -> float:
        apply = title_box("Drucker")
        combo = QComboBox()
        combo.addItem("QL-820NWB")
        layout = QVBoxLayout(apply)
        layout.addWidget(combo)
        apply.resize(260, 90)
        apply.show()
        qapp.processEvents()
        image = QImage(apply.size(), QImage.Format.Format_ARGB32)
        apply.render(image)
        # Mitte des Feldes, unter der Ueberschrift.
        return image.pixelColor(image.width() // 2, image.height() // 2 + 8).lightness()

    try:
        apply_theme(qapp, Qt.ColorScheme.Dark)
        assert field_lightness() < 80
        apply_theme(qapp, Qt.ColorScheme.Light)
        assert field_lightness() > 200
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)


def test_error_text_stays_readable_on_both_palettes(qapp):
    """Das helle Fehlerrot verschwindet auf dem dunklen Grund."""
    from datetime import datetime

    from ql_editor.jobs import PrintJob, fill_history_table, make_history_table
    from ql_editor.media_panel import MediaPanel
    from ql_editor.theme import ERROR_TEXT, ERROR_TEXT_DARK

    original = QPalette(qapp.palette())
    job = PrintJob(datetime.now(), "Etikett", 1, "QL-820NWB", "usb", "failed")
    table = make_history_table()
    panel = MediaPanel()
    try:
        apply_theme(qapp, Qt.ColorScheme.Light)
        qapp.processEvents()
        fill_history_table(table, [job])
        assert table.item(0, 4).foreground().color().name() == ERROR_TEXT
        assert panel._access_label.styleSheet() == f"color:{ERROR_TEXT};"
        apply_theme(qapp, Qt.ColorScheme.Dark)
        qapp.processEvents()
        fill_history_table(table, [job])
        assert table.item(0, 4).foreground().color().name() == ERROR_TEXT_DARK
        assert panel._access_label.styleSheet() == f"color:{ERROR_TEXT_DARK};"
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)
        panel.deleteLater()


def test_text_color_glyph_follows_the_palette(qapp):
    """Das „A“ am Farbknopf nimmt die Textfarbe, nicht festes Schwarz."""
    from ql_editor.inspector import _text_color_icon

    original = QPalette(qapp.palette())

    def letter_lightness() -> float:
        image = _text_color_icon("black").pixmap(24, 24).toImage()
        total = 0
        count = 0
        for y in range(16):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.alpha() < 40:
                    continue
                total += color.lightness()
                count += 1
        assert count > 8
        return total / count

    try:
        apply_theme(qapp, Qt.ColorScheme.Light)
        assert letter_lightness() < 80
        apply_theme(qapp, Qt.ColorScheme.Dark)
        assert letter_lightness() > 160
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)
