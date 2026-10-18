"""Tabellen: Zellen, Verbindungen, Trennlinien, Speichern, Einfuegen."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from ql_editor.canvas import LabelCanvas
from ql_editor.items import TableItem, item_from_dict
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


def _mouse(kind, canvas, scene_pos, button, buttons):
    vp = canvas.mapFromScene(scene_pos)
    return QMouseEvent(
        kind, QPointF(vp), QPointF(vp), button, buttons, Qt.KeyboardModifier.NoModifier
    )


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


def test_main_window_inserts_a_table_like_ptouch(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    before = win._canvas.length_dots
    win._act_add_table.trigger()
    qapp.processEvents()
    tables = [it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.rows == 3 and table.cols == 2
    # Laengs der Bandrichtung (ACROSS: Hoehe) groesser als das bisherige Minimum.
    assert win._canvas.length_dots > before
    assert win._inspector._title.text() == "Tabelle"
    assert table.table_height > table.table_width
