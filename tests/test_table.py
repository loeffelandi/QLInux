"""Tabellen: Zellen, Verbindungen, Trennlinien, Speichern, Einfuegen."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from ql_editor.canvas import LabelCanvas, _TABLE_MOVE_THRESHOLD_PX
from ql_editor.items import TableCell, TableItem, item_from_dict
from ql_editor.media import get_label

pytestmark = pytest.mark.usefixtures("qapp")


def test_roundtrip_keeps_cells_and_spans():
    item = TableItem(3, 2, 300, 180, font_pixel_size=20)
    item.set_selected("text", "oben")
    item.set_selected("bold", True)
    item.select_cell_at(QPointF(1, 1))
    item.select_cell_at(QPointF(item.table_width - 1, 1), extend=True)
    assert item.can_merge()
    item.merge_selected()

    restored = item_from_dict(item.to_dict())
    assert isinstance(restored, TableItem)
    assert restored.rows == 3 and restored.cols == 2
    assert restored._cells[0][0].text == "oben"
    assert restored._cells[0][0].bold is True
    assert restored._cells[0][0].col_span == 2
    assert restored._cells[0][1].skip is True
    assert restored.line_style == "solid"
    assert restored.fixed_size is True


def test_table_cell_color_clamps_to_black_or_red():
    assert TableCell.from_dict({"color": "lime"}).color == "black"
    assert TableCell.from_dict({"color": "red"}).color == "red"
    item = TableItem(1, 1, 80, 40)
    item.set_selected("color", "purple")
    assert item._cells[0][0].color == "black"
    item.set_selected("color", "red")
    assert item._cells[0][0].color == "red"


def test_merge_unmerge_and_reject_a_gap():
    item = TableItem(2, 2, 200, 100)
    item._cells[0][0].text = "a"
    item._cells[0][1].text = "b"
    item.select_cell_at(QPointF(10, 10))
    item.select_cell_at(QPointF(150, 10), extend=True)
    item.merge_selected()
    assert item._cells[0][0].text == "a\nb"
    assert item._cells[0][0].col_span == 2
    assert not item.can_merge()
    assert item.can_unmerge()

    item.unmerge_selected()
    assert item._cells[0][0].col_span == 1
    assert item._cells[0][1].skip is False
    assert item._cells[0][0].text == "a\nb"
    assert item._cells[0][1].text == ""

    # Umschalt-Klick markiert das Rechteck dazwischen. Eine Luecke
    # (nur die zwei Diagonalzellen) bleibt unverbindbar.
    item._selection = {(0, 0), (1, 1)}
    assert not item.can_merge()


def test_insert_row_into_a_merged_block_extends_the_span():
    item = TableItem(2, 2, 200, 100)
    item._fixed_size = False
    before = item.table_height
    item.select_cell_at(QPointF(10, 10))
    item.select_cell_at(QPointF(190, 90), extend=True)
    item.merge_selected()
    assert item._cells[0][0].row_span == 2
    item.insert_row_above()  # ueber Zeile 0, die Verbindung rutscht nach unten
    assert item.rows == 3
    assert item._cells[1][0].row_span == 2
    assert item._cells[1][0].col_span == 2
    assert item._cells[0][0].skip is False
    assert item.table_height > before


def test_insert_inside_a_merge_grows_the_span_and_fixed_size_holds():
    item = TableItem(2, 1, 100, 80)
    item.select_cell_at(QPointF(10, 10))
    item.select_cell_at(QPointF(10, 70), extend=True)
    item.merge_selected()
    total = item.table_height
    item._selection = {(1, 0)}  # die verbundene Zelle, Einfuegen darueber waere Zeile 0
    # Zeile unter dem Ursprung: die Auswahl liegt auf der verbundenen Zelle,
    # deren erste Zeile 0 ist. Deshalb direkt die innere Zeile aufmachen.
    item._insert_row(1)
    assert item.rows == 3
    assert item._cells[0][0].row_span == 3
    assert item._cells[1][0].skip is True
    assert item.table_height == pytest.approx(total)


def test_delete_keeps_one_row_and_moves_a_merge_origin_down():
    item = TableItem(3, 2, 200, 150)
    item._cells[0][0].text = "bleibt"
    item._cells[0][0].row_span = 2
    item._cells[1][0].skip = True
    item.select_cell_at(QPointF(10, 10))
    item.delete_selected_rows()
    assert item.rows == 2
    assert item._cells[0][0].text == "bleibt"
    assert item._cells[0][0].row_span == 1
    item.delete_selected_rows()
    item.delete_selected_rows()
    assert item.rows == 1


def test_fixed_divider_keeps_the_outer_size():
    item = TableItem(2, 2, 200, 100)
    widths = item.col_widths
    total = item.table_width
    item.drag_divider("col", 0, 30, widths, item.row_heights)
    assert item.col_widths[0] == pytest.approx(widths[0] + 30)
    assert item.col_widths[1] == pytest.approx(widths[1] - 30)
    assert item.table_width == pytest.approx(total)

    item.set_fixed_size(False)
    grown = item.col_widths
    item.drag_divider("col", 0, 20, grown, item.row_heights)
    assert item.col_widths[0] == pytest.approx(grown[0] + 20)
    assert item.col_widths[1] == pytest.approx(grown[1])
    assert item.table_width == pytest.approx(total + 20)


def test_row_height_with_fixed_size_redistributes():
    item = TableItem(2, 1, 100, 100)
    total = item.table_height
    item.set_selected_row_height(70)
    assert item.row_heights[0] == pytest.approx(70)
    assert item.table_height == pytest.approx(total)
    assert item.row_heights[1] == pytest.approx(total - 70)


def test_apply_resize_scales_every_track():
    item = TableItem(2, 2, 200, 100)
    item.apply_resize(100, 50)
    assert item.table_width == pytest.approx(100)
    assert item.table_height == pytest.approx(50)
    assert item.col_widths == pytest.approx([50, 50])


def test_divider_hit_ignores_a_merged_line():
    item = TableItem(1, 2, 200, 80)
    item.select_cell_at(QPointF(10, 10))
    item.select_cell_at(QPointF(150, 10), extend=True)
    item.merge_selected()
    assert item.divider_at(QPointF(100, 40), tol=6) is None


def _mouse(kind, canvas, scene_pos, button, buttons, mods=None):
    vp = canvas.mapFromScene(scene_pos)
    mods = Qt.KeyboardModifier.NoModifier if mods is None else mods
    return QMouseEvent(kind, QPointF(vp), QPointF(vp), button, buttons, mods)


def test_canvas_drag_resizes_a_column_and_double_click_edits(qapp):
    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 600)
    item = TableItem(2, 2, 240, 120, font_pixel_size=18)
    canvas.add_item(item)
    item.setPos(30, 20)
    qapp.processEvents()

    boundary = QPointF(item.pos().x() + item.col_widths[0], item.pos().y() + 30)
    target = QPointF(boundary.x() + 24, boundary.y())
    canvas.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, canvas, boundary, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    )
    assert canvas._op == "table-divider"
    canvas.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, canvas, target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    canvas.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, canvas, target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    )
    assert item.col_widths[0] == pytest.approx(120 + 24, abs=1.5)
    assert item.table_width == pytest.approx(240, abs=1.5)

    cell = QPointF(item.pos().x() + 20, item.pos().y() + 20)
    canvas.mouseDoubleClickEvent(
        _mouse(QEvent.Type.MouseButtonDblClick, canvas, cell, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    )
    assert item.is_editing
    item.editor.setPlainText("Kabel")
    assert item._cells[0][0].text == "Kabel"
    item.finish_editing()
    qapp.processEvents()
    assert not item.is_editing
    assert item._cells[0][0].text == "Kabel"


def test_render_draws_the_grid_without_the_selection_chrome(qapp):
    canvas = LabelCanvas()
    canvas.resize(400, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 400)
    item = TableItem(2, 2, 180, 80)
    item.set_selected("text", "X")
    canvas.add_item(item)
    item.setPos(8, 8)
    image = canvas.render_printable()
    dark = 0
    blue = 0
    for pixel in image.getdata():
        r, g, b = pixel[:3]
        if r < 40 and g < 40 and b < 40:
            dark += 1
        if b > 150 and r < 80 and g < 160:
            blue += 1
    assert dark > 20
    assert blue == 0


def _tab_texts(inspector) -> list[str]:
    from PySide6.QtWidgets import QTabBar

    tabs = inspector.findChild(QTabBar, "table_inspector_tabs")
    assert tabs is not None
    return [tabs.tabText(i) for i in range(tabs.count())]


def _page_labels(inspector, index: int) -> set[str]:
    from PySide6.QtWidgets import QLabel, QStackedWidget

    stack = inspector.findChild(QStackedWidget)
    assert stack is not None
    return {label.text() for label in stack.widget(index).findChildren(QLabel)}


def _inspector_body(inspector):
    # deleteLater-Reste haengen noch am Panel; das aktuelle Formular steckt im Layout.
    body = inspector._root.itemAt(1).widget()
    assert body is not None
    return body


def _tabs(inspector):
    from PySide6.QtWidgets import QTabBar

    bars = _inspector_body(inspector).findChildren(QTabBar, "table_inspector_tabs")
    assert len(bars) == 1
    return bars[0]


def _tool(inspector, tip: str):
    from PySide6.QtWidgets import QStackedWidget, QToolButton

    stacks = _inspector_body(inspector).findChildren(QStackedWidget)
    assert len(stacks) == 1
    page = stacks[0].currentWidget()
    matches = [
        button
        for button in page.findChildren(QToolButton)
        if button.toolTip().split("\n", 1)[0] == tip
    ]
    assert len(matches) == 1, tip
    assert matches[0].isEnabled()
    return matches[0]


def test_main_window_inserts_a_compact_one_by_two_table(qapp):
    from PySide6.QtWidgets import QTabBar, QToolButton

    from ql_editor.app import MainWindow
    from ql_editor.media import dots_to_mm

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    win._act_add_table.trigger()
    qapp.processEvents()
    tables = [it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.rows == 1 and table.cols == 2
    assert dots_to_mm(table.table_width) == pytest.approx(44, abs=0.2)
    assert dots_to_mm(table.table_height) == pytest.approx(8, abs=0.2)
    assert table._cells[0][0].font_pixel_size == max(16, int(table.table_height * 0.45))
    assert table._cells[0][0].font_pixel_size < int(table.table_height * 0.55)
    assert win._inspector._title.text() == "Tabelle"
    tabs = win._inspector.findChild(QTabBar, "table_inspector_tabs")
    assert tabs is not None
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Text", "Zelle", "Tabelle"]
    assert not any(
        button.text()
        for button in win._inspector.findChildren(QToolButton)
        if button.icon() is not None and not button.icon().isNull() and button.text() not in ("", "A")
    )
    # Fuellung gehoert auf die Zellen-Seite, nicht zu Text oder Tabelle.
    assert "Füllung" in _page_labels(win._inspector, 1)
    assert "Füllung" not in _page_labels(win._inspector, 0)
    assert "Füllung" not in _page_labels(win._inspector, 2)
    tabs.setCurrentIndex(2)
    qapp.processEvents()
    assert win._inspector._table_page == 2
    win.close()
    qapp.processEvents()


def test_table_inspector_icon_buttons_merge_and_insert_a_row(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    # Ein frueherer Test kann das rechte Panel ausblenden und das speichern.
    win._act_panel_right.setChecked(True)
    qapp.processEvents()
    win._act_add_table.trigger()
    qapp.processEvents()
    table = _live_table(win)
    table.select_cell_at(QPointF(10, 10))
    table.select_cell_at(QPointF(table.table_width - 10, 10), extend=True)
    qapp.processEvents()
    tabs = _tabs(win._inspector)
    tabs.setCurrentIndex(1)
    assert tabs.currentIndex() == 1
    _tool(win._inspector, "Zellen verbinden").click()
    qapp.processEvents()
    table = _live_table(win)
    assert table._cells[0][0].col_span == 2

    tabs = _tabs(win._inspector)
    tabs.setCurrentIndex(2)
    assert tabs.currentIndex() == 2
    _tool(win._inspector, "Zeile darüber").click()
    qapp.processEvents()
    table = _live_table(win)
    assert table.rows == 2
    win.close()
    qapp.processEvents()


def test_table_inspector_tabs_follow_the_ui_language(qapp):
    from ql_editor import app as app_module
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    win._act_add_table.trigger()
    qapp.processEvents()
    win.switch_language("en")
    qapp.processEvents()
    new = app_module._current_window
    table = _live_table(new)
    _select_table(new, table)
    assert _tab_texts(new._inspector) == ["Text", "Cell", "Table"]
    new.close()
    qapp.processEvents()


def test_negative_table_page_stays_on_the_first_tab(qapp):
    from PySide6.QtWidgets import QStackedWidget, QTabBar

    from ql_editor.inspector import InspectorPanel

    panel = InspectorPanel()
    panel._table_page = -1
    panel.set_item(TableItem(1, 2, 200, 80))
    qapp.processEvents()
    tabs = panel.findChild(QTabBar, "table_inspector_tabs")
    stack = panel.findChild(QStackedWidget)
    assert tabs.currentIndex() == 0
    assert stack.currentIndex() == 0
    assert panel._table_page == 0
    tabs.currentChanged.emit(-1)
    assert panel._table_page == 0
    assert stack.currentIndex() == 0


def test_shift_click_selects_cells_without_starting_move(qapp):
    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 600)
    item = TableItem(2, 2, 240, 120, font_pixel_size=18)
    canvas.add_item(item)
    item.setPos(30, 20)
    qapp.processEvents()

    first = QPointF(item.pos().x() + 20, item.pos().y() + 20)
    second = QPointF(item.pos().x() + item.col_widths[0] + 20, item.pos().y() + 20)
    canvas.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            canvas,
            first,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    assert canvas._op is None
    assert canvas._pending_move_start is not None
    canvas.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            canvas,
            first,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert canvas._pending_move_start is None

    canvas.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            canvas,
            second,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
        )
    )
    assert canvas._op is None
    assert canvas._pending_move_start is not None
    assert (0, 0) in item._selection and (0, 1) in item._selection
    # Kleiner Ruck unter der Schwelle: Tabelle bleibt stehen.
    nudge = QPointF(second.x() + 1, second.y())
    before = QPointF(item.pos())
    canvas.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            canvas,
            nudge,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
        )
    )
    assert canvas._op is None
    assert item.pos() == before
    canvas.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            canvas,
            nudge,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    # Ohne Umschalt und mit genug Drag startet die Verschiebung.
    canvas.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            canvas,
            first,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    drag = QPointF(first.x() + _TABLE_MOVE_THRESHOLD_PX + 8, first.y())
    canvas.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            canvas,
            drag,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    assert canvas._op == "move"
    canvas.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            canvas,
            drag,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def _live_table(win):
    return next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "table")


def _select_table(win, table) -> None:
    win._canvas.scene().clearSelection()
    table.setSelected(True)
    win._on_selection_changed()
    qapp = QApplication.instance()
    if qapp is not None:
        qapp.processEvents()


def test_main_window_undoes_table_merge_row_and_inspector_text(qapp):
    """Struktur und Inspector-Text schliessen Undo (M1 / m4)."""
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    win._act_add_table.trigger()
    qapp.processEvents()
    table = _live_table(win)
    assert table.rows == 1 and table.cols == 2

    table.select_cell_at(QPointF(10, 10))
    table.select_cell_at(QPointF(table.table_width - 10, 10), extend=True)
    assert table.can_merge()
    # Inspector-_apply_now ist der gleiche Pfad wie die Struktur-Knoepfe.
    win._inspector._apply_now(table.merge_selected)
    qapp.processEvents()
    assert table._cells[0][0].col_span == 2
    win._act_undo.trigger()
    qapp.processEvents()
    table = _live_table(win)
    assert table._cells[0][0].col_span == 1

    _select_table(win, table)
    rows_before = table.rows
    win._inspector._apply_now(table.insert_row_above)
    qapp.processEvents()
    table = _live_table(win)
    assert table.rows == rows_before + 1
    win._act_undo.trigger()
    qapp.processEvents()
    table = _live_table(win)
    assert table.rows == rows_before

    _select_table(win, table)
    original = table._cells[0][0].text
    # deleteLater-Reste zuerst: das aktuelle Textfeld ist das letzte mit Parent.
    edits = [
        field
        for field in win._inspector.findChildren(QPlainTextEdit)
        if field.parent() is not None
    ]
    assert edits
    edit = edits[-1]
    edit.setFocus()
    qapp.processEvents()
    edit.setPlainText("Kabel")
    qapp.processEvents()
    assert win._inspector.edit_open is True
    assert table._cells[0][0].text == "Kabel"
    # FocusOut schliesst den Undo-Schritt (eventFilter / M1).
    QApplication.sendEvent(edit, QEvent(QEvent.Type.FocusOut))
    qapp.processEvents()
    assert win._inspector.edit_open is False
    win._act_undo.trigger()
    qapp.processEvents()
    table = _live_table(win)
    assert table._cells[0][0].text == original
    win.close()
    qapp.processEvents()
