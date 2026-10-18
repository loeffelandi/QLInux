"""Hilfslinien von den Linealen: ziehen, loeschen, speichern, einrasten."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from ql_editor.canvas import SNAP_TOLERANCE_PX, LabelCanvas
from ql_editor.history import design_snapshot, push_if_changed
from ql_editor.items import TextItem
from ql_editor.media import get_label


def _canvas(qapp) -> LabelCanvas:
    canvas = LabelCanvas()
    canvas.resize(700, 500)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 472)
    canvas.fit_tape()
    qapp.processEvents()
    return canvas


def _ruler_event(kind, local: QPointF, global_pos: QPointF, button, buttons):
    return QMouseEvent(
        kind,
        local,
        global_pos,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _global(widget, local: QPoint) -> QPointF:
    return QPointF(widget.mapToGlobal(local))


def test_rulers_accept_mouse_and_corner_stays_clear(qapp):
    canvas = _canvas(qapp)
    assert not canvas._h_ruler.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not canvas._v_ruler.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert canvas._corner.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_drag_from_top_ruler_creates_horizontal_guide_and_back_removes_it(qapp):
    canvas = _canvas(qapp)
    ruler = canvas._h_ruler
    origin = QPoint(40, RULER_LOCAL_Y)
    press_global = _global(ruler, origin)
    ruler.mousePressEvent(
        _ruler_event(
            QEvent.Type.MouseButtonPress,
            QPointF(origin),
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseReleaseEvent(
        _ruler_event(
            QEvent.Type.MouseButtonRelease,
            QPointF(origin),
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert canvas.guides() == []

    target = QPointF(canvas.printable_rect().center().x(), 120.0)
    move_global = _global(canvas.viewport(), canvas.mapFromScene(target))
    ruler.mousePressEvent(
        _ruler_event(
            QEvent.Type.MouseButtonPress,
            QPointF(origin),
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseMoveEvent(
        _ruler_event(
            QEvent.Type.MouseMove,
            QPointF(0, 80),
            move_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseReleaseEvent(
        _ruler_event(
            QEvent.Type.MouseButtonRelease,
            QPointF(0, 80),
            move_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert len(canvas.guides()) == 1
    assert canvas.guides()[0]["axis"] == "h"
    assert canvas.guides()[0]["pos"] == pytest.approx(target.y(), abs=1.0 / canvas._scale())

    view_pos = canvas.mapFromScene(target)
    canvas.mousePressEvent(
        _view_event(
            QEvent.Type.MouseButtonPress,
            view_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    above = QPoint(view_pos.x(), -6)
    canvas.mouseMoveEvent(
        _view_event(
            QEvent.Type.MouseMove,
            above,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(
        _view_event(
            QEvent.Type.MouseButtonRelease,
            above,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert canvas.guides() == []


def test_drag_from_left_ruler_creates_vertical_guide(qapp):
    canvas = _canvas(qapp)
    ruler = canvas._v_ruler
    origin = QPoint(RULER_LOCAL_Y, 30)
    press_global = _global(ruler, origin)
    target = QPointF(90.0, canvas.printable_rect().center().y())
    move_global = _global(canvas.viewport(), canvas.mapFromScene(target))
    ruler.mousePressEvent(
        _ruler_event(
            QEvent.Type.MouseButtonPress,
            QPointF(origin),
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseMoveEvent(
        _ruler_event(
            QEvent.Type.MouseMove,
            QPointF(80, 0),
            move_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    ruler.mouseReleaseEvent(
        _ruler_event(
            QEvent.Type.MouseButtonRelease,
            QPointF(80, 0),
            move_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert len(canvas.guides()) == 1
    assert canvas.guides()[0]["axis"] == "v"
    assert canvas.guides()[0]["pos"] == pytest.approx(target.x(), abs=1.0 / canvas._scale())


def test_placed_guide_is_visible(qapp):
    canvas = _canvas(qapp)
    y = canvas.printable_rect().center().y()
    canvas.set_guides([{"axis": "h", "pos": y}])
    qapp.processEvents()
    image = canvas.viewport().grab().toImage()
    assert not image.isNull()
    sample = canvas.mapFromScene(QPointF(canvas.printable_rect().center().x(), y))
    color = image.pixelColor(sample)
    off = image.pixelColor(QPoint(sample.x(), sample.y() + 8))
    assert color.green() > color.red() + 40
    assert color.blue() > color.red() + 40
    assert off.red() > 240 and off.green() > 240 and off.blue() > 240


def test_snap_uses_guides_and_still_the_label(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("b", font_pixel_size=20)
    canvas.add_item(item)
    item.setPos(80, 80)
    tol = SNAP_TOLERANCE_PX / canvas._scale()
    guide_x = 160.0
    box = item.sceneBoundingRect()
    item.moveBy((guide_x + tol * 0.4) - box.left(), 0)
    canvas.set_guides([{"axis": "v", "pos": guide_x}, {"axis": "h", "pos": 4000.0}])
    box = item.sceneBoundingRect()
    dx, dy, shown = canvas._snap_move(box, 0.0, 0.0, exclude=[item])
    assert box.left() + dx == pytest.approx(guide_x)
    assert any(axis == "v" and coord == pytest.approx(guide_x) for axis, coord in shown)

    left = canvas.printable_rect().left()
    box = item.sceneBoundingRect()
    item.moveBy((left + tol * 0.4) - box.left(), 0)
    canvas.set_guides([{"axis": "v", "pos": left + 500.0}])
    box = item.sceneBoundingRect()
    dx, _dy, shown = canvas._snap_move(box, 0.0, 0.0, exclude=[item])
    assert box.left() + dx == pytest.approx(left)
    assert any(axis == "v" and coord == pytest.approx(left) for axis, coord in shown)


def test_guides_survive_item_reload_and_follow_margin_shift(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    canvas.set_guides(
        [
            {"axis": "h", "pos": 10.0},
            {"axis": "v", "pos": 20.0},
            {"axis": "nope", "pos": 1},
            {"axis": "h", "pos": "x"},
        ]
    )
    assert canvas.guides() == [{"axis": "h", "pos": 10.0}, {"axis": "v", "pos": 20.0}]
    canvas.load_items([])
    assert canvas.guides() == [{"axis": "h", "pos": 10.0}, {"axis": "v", "pos": 20.0}]
    canvas.translate_items(3, -4, clamp=False)
    assert canvas.guides() == [{"axis": "h", "pos": 6.0}, {"axis": "v", "pos": 23.0}]


def test_guide_change_is_undoable(qapp):
    restored: list = []

    def restore(snapshot):
        restored.append(list(snapshot.get("guides") or []))

    before = design_snapshot({}, [], guides=[])
    after = design_snapshot({}, [], guides=[{"axis": "v", "pos": 10.0}])
    from PySide6.QtGui import QUndoStack

    stack = QUndoStack()
    assert push_if_changed(stack, before, after, restore, "Hilfslinie")
    stack.undo()
    assert restored[-1] == []
    stack.redo()
    assert restored[-1] == [{"axis": "v", "pos": 10.0}]
    assert not push_if_changed(stack, after, design_snapshot({}, [], guides=[{"axis": "v", "pos": 10.0}]), restore, "gleich")


def test_label_document_keeps_guides(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    settings = AppSettings(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    win = MainWindow(settings=settings, discover=False)
    guides = [{"axis": "h", "pos": 30.0}, {"axis": "v", "pos": 80.0}]
    win._canvas.set_guides(guides)
    data = win._document_data()
    assert data["guides"] == guides
    win._canvas.set_guides([])
    win._apply_document(data)
    assert win._canvas.guides() == guides

    state = win._state()
    assert state["tabs"][0]["guides"] == guides
    win._canvas.set_guides([])
    win.apply_state(state)
    assert win._canvas.guides() == guides

    win._blank_tab(win._active)
    assert win._canvas.guides() == []
    win.close()
    qapp.processEvents()


def _view_event(kind, vp: QPoint, button, buttons):
    return QMouseEvent(
        kind,
        QPointF(vp),
        QPointF(vp),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


RULER_LOCAL_Y = 8
