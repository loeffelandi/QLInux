"""Palette folgt dem Farbschema, ohne ein Fenster aufzubauen."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from ql_editor.theme import ACCENT, apply_theme, palette_for, scheme_for


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
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#242424"
        assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == ACCENT
        apply_theme(qapp)
        # Offscreen meldet Unknown: ohne Ausnahme bleibt die helle Palette.
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#fafafa"
    finally:
        apply_theme(qapp)
        qapp.setPalette(original)
