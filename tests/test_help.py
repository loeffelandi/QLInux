"""Hilfe-Sheet: Menüpunkt, beide Sprachen, Tasten die der Code bindet."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
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

    assert "printer and the tape" in english
    assert "Ctrl+N" in english
    assert "Ctrl+Y" in english
    assert "Strg" not in english
    assert "Umschalt" not in english
    assert tr("Hilfe") == "Hilfe"


def test_help_lists_exactly_the_bound_action_shortcuts(qapp):
    """Jede Taste an einer Aktion steht in der Übersicht, und keine darüber."""
    from ql_editor.app import MainWindow

    win = MainWindow(discover=False)
    bound = {
        _chord_from_action(action)
        for action in win.findChildren(QAction)
        if not action.shortcut().isEmpty()
    }
    listed = {chord for chord, _what in action_shortcuts()}
    assert listed == bound

    chords = listed | {chord for chord, _what in canvas_shortcuts()}
    assert "Strg+B" in chords
    assert "Strg+Umschalt+B" in chords
    assert "Strg+I" not in chords
    assert "Strg+U" not in chords
    assert "F9" not in chords
    assert "Umschalt+F9" not in chords


def test_help_opens_from_the_menu_beside_about(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.sheet import Sheet

    win = MainWindow(discover=False)
    menu = win._menu_button.menu()
    actions = menu.actions()
    index = actions.index(win._act_help)
    assert actions[index - 1].text() == "Sprache"
    assert actions[index + 1] is win._act_about
    assert actions[index + 2] is win._act_quit
    assert not win._act_help.icon().isNull()

    win._act_help.trigger()
    qapp.processEvents()
    sheet = win.findChild(Sheet)
    assert sheet is not None
    texts = _labels(sheet)
    assert "Hilfe" in texts
    assert "Strg+P" in texts
    sheet.close_sheet()
    qapp.processEvents()
