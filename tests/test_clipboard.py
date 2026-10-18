"""Kopieren, Ausschneiden, Einfuegen, Duplizieren und Ctrl-Ziehen."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from ql_editor.app import MainWindow, _CLIPBOARD_MIME
from ql_editor.canvas import DUPLICATE_OFFSET_DOTS
from ql_editor.help import action_shortcuts, canvas_shortcuts
from ql_editor.items import TextItem


def _mouse(canvas, kind, scene_pos, button, buttons, mods):
    vp = canvas.mapFromScene(scene_pos)
    return QMouseEvent(kind, QPointF(vp), QPointF(vp), button, buttons, mods)


def _at(item) -> QPointF:
    return item.sceneBoundingRect().center()


def test_text_field_keeps_copy_and_paste_while_editing(qapp):
    item = TextItem("Hallo", font_pixel_size=32)
    item.start_editing()
    for key in (Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V):
        event = QKeyEvent(
            QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.ControlModifier
        )
        assert item.sceneEvent(event) is True
        assert event.isAccepted()
    duplicate = QKeyEvent(
        QEvent.Type.ShortcutOverride,
        Qt.Key.Key_D,
        Qt.KeyboardModifier.ControlModifier,
    )
    item.sceneEvent(duplicate)
    assert not duplicate.isAccepted()


def test_ctrl_drag_duplicates_and_plain_drag_moves(qapp):
    from ql_editor.canvas import LabelCanvas
    from ql_editor.media import get_label

    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.set_label(get_label("50"), 472)
    canvas.zoom_100()
    item = TextItem("Hallo", font_pixel_size=32)
    canvas.add_item(item)
    item.setPos(80, 60)
    origin = QPointF(item.pos())
    ctrl = Qt.KeyboardModifier.ControlModifier

    def press(pos, mods=Qt.KeyboardModifier.NoModifier):
        canvas.mousePressEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseButtonPress,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                mods,
            )
        )

    def drag(pos, mods=Qt.KeyboardModifier.NoModifier):
        canvas.mouseMoveEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseMove,
                pos,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                mods,
            )
        )

    def release(pos):
        canvas.mouseReleaseEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseButtonRelease,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    press(_at(item), ctrl)
    release(_at(item))
    assert not item.isSelected()
    assert len(canvas.ordered_items()) == 1

    press(_at(item), ctrl)
    assert item.isSelected()
    release(_at(item))
    assert item.isSelected()

    nudge = QPointF(50, 30)
    press(_at(item))
    drag(_at(item) + nudge)
    release(_at(item) + nudge)
    assert len(canvas.ordered_items()) == 1
    assert item.pos() != origin
    item.setPos(origin)

    press(_at(item), ctrl)
    drag(_at(item) + nudge, ctrl)
    release(_at(item) + nudge)
    assert len(canvas.ordered_items()) == 2
    stayed = [obj for obj in canvas.ordered_items() if obj.pos() == origin]
    shifted = [obj for obj in canvas.ordered_items() if obj.pos() != origin]
    assert len(stayed) == 1 and len(shifted) == 1
    assert stayed[0].toPlainText() == shifted[0].toPlainText() == "Hallo"


def test_ctrl_drag_follows_the_key_and_skips_the_source(qapp):
    """Losgelassenes Strg verschiebt. Eine kurze Kopie rastet nicht aufs Original."""
    from ql_editor.canvas import LabelCanvas
    from ql_editor.media import get_label

    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.set_label(get_label("50"), 472)
    canvas.zoom_100()
    item = TextItem("Hallo", font_pixel_size=32)
    canvas.add_item(item)
    item.setPos(120, 80)
    origin = QPointF(item.pos())
    ctrl = Qt.KeyboardModifier.ControlModifier

    def press(pos, mods):
        canvas.mousePressEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseButtonPress,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                mods,
            )
        )

    def drag(pos, mods):
        canvas.mouseMoveEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseMove,
                pos,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                mods,
            )
        )

    def release(pos):
        canvas.mouseReleaseEvent(
            _mouse(
                canvas,
                QEvent.Type.MouseButtonRelease,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    none = Qt.KeyboardModifier.NoModifier
    press(_at(item), none)
    drag(_at(item) + QPointF(40, 20), ctrl)
    release(_at(item) + QPointF(40, 20))
    assert len(canvas.ordered_items()) == 1
    assert item.pos() != origin
    item.setPos(origin)

    press(_at(item), ctrl)
    drag(_at(item) + QPointF(40, 20), none)
    release(_at(item) + QPointF(40, 20))
    assert len(canvas.ordered_items()) == 1
    assert item.pos() != origin
    item.setPos(origin)

    step = QPointF(8, 0)
    press(_at(item), ctrl)
    drag(_at(item) + step, ctrl)
    release(_at(item) + step)
    copies = [obj for obj in canvas.ordered_items() if obj is not item]
    assert item.pos() == origin
    assert len(copies) == 1
    assert abs(copies[0].pos().x() - (origin.x() + 8)) < 0.6
    assert abs(copies[0].pos().y() - origin.y()) < 0.6


def test_copy_paste_duplicate_and_ctrl_drag(qapp):
    clipboard = QApplication.clipboard()
    clipboard.clear()

    win = MainWindow(discover=False)
    canvas = win._canvas

    chords = {chord for _icon, chord, _what in action_shortcuts()}
    assert {"Strg+C", "Strg+X", "Strg+V", "Strg+D"} <= chords
    assert "Strg+Ziehen" in {chord for _icon, chord, _what in canvas_shortcuts()}

    menu_actions = []

    def _walk(menu):
        for action in menu.actions():
            menu_actions.append(action)
            if action.menu() is not None:
                _walk(action.menu())

    _walk(win._menu_button.menu())
    for action in (
        win._act_copy,
        win._act_cut,
        win._act_paste,
        win._act_duplicate,
    ):
        assert action not in menu_actions
        assert action in win.actions()

    bearbeiten = next(
        entry for entry in win._palette_entries() if entry.title == "Bearbeiten"
    )
    listed = bearbeiten.walk_actions()
    for action in (
        win._act_copy,
        win._act_cut,
        win._act_paste,
        win._act_duplicate,
    ):
        assert action in listed

    item = TextItem("Hallo", font_pixel_size=32)
    win._add_item(item, QPointF(80, 60))
    canvas.cancel_editing()
    assert item.isSelected()
    assert win._act_copy.isEnabled()
    assert not win._act_paste.isEnabled()
    origin = QPointF(item.pos())
    ctrl = Qt.KeyboardModifier.ControlModifier
    nudge = QPointF(50, 30)
    canvas.mousePressEvent(
        _mouse(
            canvas,
            QEvent.Type.MouseButtonPress,
            _at(item),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            ctrl,
        )
    )
    canvas.mouseMoveEvent(
        _mouse(
            canvas,
            QEvent.Type.MouseMove,
            _at(item) + nudge,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            ctrl,
        )
    )
    canvas.mouseReleaseEvent(
        _mouse(
            canvas,
            QEvent.Type.MouseButtonRelease,
            _at(item) + nudge,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert len(canvas.ordered_items()) == 2
    assert win._undo_stack.undoText() == "Duplizieren"
    win._act_undo.trigger()
    item = canvas.ordered_items()[-1]
    assert item.pos() == origin

    context = win._build_context_menu(QPointF(10, 10))
    context_actions = context.actions()
    for action in (
        win._act_copy,
        win._act_cut,
        win._act_paste,
        win._act_duplicate,
    ):
        assert action in context_actions

    win._act_copy.trigger()
    assert clipboard.mimeData().hasFormat(_CLIPBOARD_MIME)
    win._act_paste.trigger()
    assert len(canvas.ordered_items()) == 2
    assert win._act_paste.text() == "Einfügen"
    assert "\u2060" not in win._act_paste.text()
    assert win._undo_stack.undoText() == "Einfügen"
    pasted = [obj for obj in canvas.ordered_items() if obj is not item][0]
    assert pasted.toPlainText() == "Hallo"
    assert pasted.pos().x() == origin.x() + DUPLICATE_OFFSET_DOTS
    assert pasted.pos().y() == origin.y() + DUPLICATE_OFFSET_DOTS
    assert pasted.isSelected() and not item.isSelected()
    win._act_undo.trigger()
    assert len(canvas.ordered_items()) == 1

    item = canvas.ordered_items()[-1]
    item.setSelected(True)
    win._act_duplicate.trigger()
    clone = [obj for obj in canvas.ordered_items() if obj.pos() != origin][0]
    assert clone.pos().x() == origin.x() + DUPLICATE_OFFSET_DOTS
    assert win._undo_stack.undoText() == "Duplizieren"

    win._act_cut.trigger()
    assert len(canvas.ordered_items()) == 1
    assert win._undo_stack.undoText() == "Ausschneiden"
    win._act_undo.trigger()
    assert len(canvas.ordered_items()) == 2

    item = next(obj for obj in canvas.ordered_items() if obj.pos() == origin)
    item.setSelected(True)
    canvas.scene().clearSelection()
    item.setSelected(True)
    item.start_editing()
    assert item.is_editing
    assert not win._act_copy.isEnabled()
    assert not win._act_cut.isEnabled()
    assert not win._act_paste.isEnabled()
    assert not win._act_duplicate.isEnabled()
    clipboard.clear()
    before = len(canvas.ordered_items())
    canvas.keyPressEvent(
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier,
        )
    )
    assert clipboard.text() == "Hallo"
    assert not clipboard.mimeData().hasFormat(_CLIPBOARD_MIME)
    assert len(canvas.ordered_items()) == before
    win._act_copy.trigger()
    assert not clipboard.mimeData().hasFormat(_CLIPBOARD_MIME)

    canvas.cancel_editing()
    assert win._act_copy.isEnabled()
    # Der zweite Klick auf Strg+C darf das Objekt kopieren, nicht den Text.
    win._act_copy.trigger()
    assert clipboard.mimeData().hasFormat(_CLIPBOARD_MIME)

    clipboard.clear()
    win.close()
