"""Hilfe-Sheet: Menüpunkt, beide Sprachen, Tasten die der Code bindet."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeySequence, QMouseEvent
from PySide6.QtWidgets import QLabel

from ql_editor import i18n
from ql_editor.help import action_shortcuts, build_help_content, canvas_shortcuts
from ql_editor.i18n import tr


def _labels(widget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel)]


def _chord_from_action(action: QAction) -> str:
    text = action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
    text = text.replace("Backtab", "Tab")
    return (
        text.replace("Shift", "Umschalt")
        .replace("Ctrl", "Strg")
        .replace("Del", "Entf")
    )


def test_help_text_is_short_and_follows_the_language(qapp):
    content = build_help_content()
    german = "\n".join(_labels(content))
    assert "Drucker und Band" in german
    assert "Tasten" in german
    assert "Strg+N" in german
    assert "macOS" not in german

    i18n.set_language("en")
    try:
        english = "\n".join(_labels(build_help_content()))
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    assert "printer and tape" in english
    assert "Ctrl+N" in english
    assert "Paste" in english
    assert "Einfügen" not in english
    assert "Ctrl+Y" in english
    assert "Ctrl+B" in english
    assert "Ctrl+I" in english
    assert "Ctrl+U" in english
    assert "F9" in english
    assert "Shift+F9" in english
    assert "Bold" in english
    assert "Italic" in english
    assert "Ctrl+Shift+B" not in english
    assert "Strg" not in english
    assert "Umschalt" not in english
    assert tr("Hilfe") == "Hilfe"


def test_help_lists_the_decided_shortcuts(qapp):
    """Übersicht und gebundene Tasten sind dieselben.

    Strg+B, Strg+I und Strg+U sind fett, kursiv und unterstrichen. Die
    Panels sind F9 und Umschalt+F9. Strg+Umschalt+B ist keine Taste mehr.
    """
    from ql_editor.app import MainWindow

    win = MainWindow(discover=False)
    bound = {
        _chord_from_action(action)
        for action in win.findChildren(QAction)
        if not action.shortcut().isEmpty()
    }
    pairs = {chord: what for _icon, chord, what in action_shortcuts()}
    assert pairs["Strg+B"] == "Fett"
    assert pairs["Strg+I"] == "Kursiv"
    assert pairs["Strg+U"] == "Unterstrichen"
    assert pairs["F9"] == "Panel links"
    assert pairs["Umschalt+F9"] == "Panel rechts"
    assert "Strg+Umschalt+B" not in pairs
    assert "Strg+Umschalt+B" not in bound
    assert set(pairs) == bound


def test_help_opens_from_the_menu_beside_about(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.sheet import Sheet

    win = MainWindow(discover=False)
    win.resize(960, 720)
    menu = win._menu_button.menu()
    actions = menu.actions()
    index = actions.index(win._act_help)
    assert actions[index - 1].text() == "Erscheinungsbild"
    assert actions[index + 1] is win._act_about
    assert actions[index + 2] is win._act_quit
    titles = [entry.title for entry in win._palette_entries()]
    assert titles[titles.index("Sprache") + 1] == "Erscheinungsbild"
    assert titles[titles.index("Erscheinungsbild") + 1] == "Hilfe"
    assert titles[titles.index("Hilfe") + 1] == "Über QLInux"
    assert not win._act_help.icon().isNull()

    win._act_help.trigger()
    qapp.processEvents()
    sheet = win.findChild(Sheet)
    assert sheet is not None
    texts = _labels(sheet)
    assert "Hilfe" in texts
    assert "Strg+P" in texts
    assert "Fett" in texts
    assert "F9" in texts
    pictures = [
        label
        for label in sheet.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert len(pictures) >= 10
    outside = QPoint(4, 4)
    assert sheet._close_on_outside
    assert not sheet._panel.geometry().contains(outside)
    sheet.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            outside.toPointF(),
            outside.toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    qapp.processEvents()
    assert not sheet.isVisible()
