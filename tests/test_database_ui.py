"""M4: Datenbank-Panel, Drag-Binding, Inspector Database Field (D4/D13/D14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QToolBar

from ql_editor.app import MainWindow
from ql_editor.database_panel import field_from_mime, field_mime
from ql_editor.inspector import InspectorPanel
from ql_editor.items import BarcodeItem, TextItem

pytestmark = pytest.mark.usefixtures("qapp")


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "Fixture Data.csv"
    path.write_text(
        "Fixture;Circuit;Channel\n"
        "Spot A;PB 1;11\n"
        "Spot B;PB 2;22\n",
        encoding="utf-8",
    )
    return path


def _window_with_csv(qapp, tmp_path: Path) -> MainWindow:
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    assert win.connect_csv_path(str(_csv(tmp_path)))
    qapp.processEvents()
    return win


def _drop(canvas, mime: QMimeData, view_pos: QPointF) -> None:
    event = QDropEvent(
        view_pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(event)


def test_field_mime_round_trip():
    assert field_from_mime(field_mime("Circuit")) == "Circuit"
    plain = QMimeData()
    plain.setText("Circuit")
    assert field_from_mime(plain) is None


def _open_database(win: MainWindow) -> None:
    assert win._act_database.isVisible()
    win._act_database.setChecked(True)


def test_database_ui_hidden_without_csv(qapp):
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    assert not win._act_database.isVisible()
    assert not win._database_panel.isVisible()
    assert win._act_connect_csv.isVisible()
    bar = win.findChild(QToolBar, "main_toolbar")
    assert win._act_connect_csv in bar.actions()
    assert win._act_database in bar.actions()
    text = TextItem("A")
    win._canvas.add_item(text)
    text.setSelected(True)
    win._on_selection_changed()
    assert win._inspector.findChild(QCheckBox, "inspector_serial_enabled") is None
    assert win._inspector.findChild(QComboBox, "inspector_database_field") is None


def test_connect_shows_grid_counter_and_headers(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    panel = win._database_panel
    assert win._act_database.isVisible()
    assert not panel.isVisible()
    _open_database(win)
    qapp.processEvents()
    assert panel.isVisible()
    assert panel.expanded
    assert panel._grid.rowCount() == 2
    assert panel._grid.columnCount() == 3
    assert panel._grid.horizontalHeaderItem(0).text().startswith("○")
    assert panel._counter.text() == "Datensatz 1 / 2"
    assert panel._disconnect.isEnabled()
    assert panel._other.isEnabled()
    win.close()


def test_disconnect_keeps_snapshots_and_serial(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = TextItem("CH:")
    item.set_binding({"source": "database", "field": "Fixture"})
    win._canvas.add_item(item)
    win.set_current_record(0)
    qapp.processEvents()
    assert item.text_value == "Spot A"
    serial_before = dict(win._active.serial)

    _open_database(win)
    assert win._database_panel.isVisible()
    win.disconnect_csv()
    qapp.processEvents()

    assert win._active.csv_table is None
    assert win._active.data_source is None
    assert item.text_value == "Spot A"
    assert item.binding == {"source": "database", "field": "Fixture"}
    assert win._active.serial == serial_before
    assert not win._act_database.isVisible()
    assert not win._database_panel.isVisible()
    assert win._act_connect_csv.isEnabled()
    assert win._document_dirty is True
    win.close()


def test_row_click_still_merges_without_undo(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = TextItem("?")
    item.set_binding({"source": "database", "field": "Fixture"})
    win._canvas.add_item(item)
    win._undo_stack.clear()
    win._undo_stack.setClean()
    win._document_dirty = False

    _open_database(win)
    win._database_panel._grid.selectRow(1)
    qapp.processEvents()

    assert item.text_value == "Spot B"
    assert win._undo_stack.count() == 0
    assert win._database_panel._counter.text() == "Datensatz 2 / 2"
    win.close()


def test_drop_on_text_binds_and_undoes(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = TextItem("offen", font_pixel_size=48)
    win._canvas.add_item(item)
    item.setPos(40, 40)
    qapp.processEvents()
    before = win._undo_stack.count()

    view = win._canvas.mapFromScene(item.sceneBoundingRect().center())
    _drop(win._canvas, field_mime("Fixture"), QPointF(view))
    qapp.processEvents()

    assert item.binding == {"source": "database", "field": "Fixture"}
    assert item.text_value == "Spot A"
    assert win._undo_stack.count() == before + 1
    win._undo_stack.undo()
    qapp.processEvents()
    restored = win._canvas.ordered_items()[0]
    assert restored.binding is None
    assert restored.text_value == "offen"
    win.close()


def test_drop_on_empty_canvas_creates_bound_text(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    _drop(win._canvas, field_mime("Circuit"), QPointF(80, 90))
    qapp.processEvents()
    texts = [
        item
        for item in win._canvas.ordered_items()
        if isinstance(item, TextItem)
    ]
    assert len(texts) == 1
    assert texts[0].binding == {"source": "database", "field": "Circuit"}
    assert texts[0].text_value == "PB 1"
    win.close()


def test_drop_on_serial_barcode_replaces_serial(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    barcode = BarcodeItem("ABC", "code128")
    barcode.set_binding({"source": "serial"})
    win._canvas.add_item(barcode)
    barcode.setPos(30, 30)
    qapp.processEvents()

    view = win._canvas.mapFromScene(barcode.sceneBoundingRect().center())
    _drop(win._canvas, field_mime("Channel"), QPointF(view))
    qapp.processEvents()

    assert barcode.binding == {"source": "database", "field": "Channel"}
    assert barcode.value == "11"
    win.close()


def test_empty_text_accepts_database_field_after_click_away(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = win._new_text(QPointF(40, 40))
    win._canvas.cancel_editing()
    qapp.processEvents()
    assert item.scene() is not None
    assert item.isSelected()
    assert item.toPlainText() == ""

    combo = win._inspector.findChild(QComboBox, "inspector_database_field")
    assert combo is not None
    combo.setFocus()
    qapp.processEvents()
    combo.setCurrentIndex(combo.findData("Fixture"))
    qapp.processEvents()

    assert item.scene() is not None
    assert item.binding == {"source": "database", "field": "Fixture"}
    assert item.text_value == "Spot A"
    win.close()


def test_inspector_database_field_merges_and_unbinds(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = TextItem("alt")
    win._canvas.add_item(item)
    item.setSelected(True)
    win._on_selection_changed()
    qapp.processEvents()

    combo = win._inspector.findChild(QComboBox, "inspector_database_field")
    assert combo is not None
    assert combo.itemText(0) == "(keine)"
    combo.setCurrentIndex(combo.findData("Circuit"))
    qapp.processEvents()

    assert item.binding == {"source": "database", "field": "Circuit"}
    assert item.text_value == "PB 1"
    hint = win._inspector.findChild(QLabel, "inspector_snapshot_hint")
    assert hint is not None
    button = win._inspector.findChild(QPushButton, "inspector_unbind")
    assert button is not None
    button.click()
    qapp.processEvents()

    assert item.binding is None
    assert item.text_value == "PB 1"
    win.close()


def _visible(widget, type_, name: str):
    return [
        child
        for child in widget.findChildren(type_, name)
        if child.isVisible()
    ]


def test_inspector_database_field_replaces_serial(qapp):
    inspector = InspectorPanel()
    inspector.show()
    inspector.set_database_fields(["Fixture", "Channel"])
    inspector.set_serial_context(None, csv_connected=True)
    item = TextItem("0100")
    item.set_binding({"source": "serial"})
    inspector.set_item(item)
    qapp.processEvents()

    assert _visible(inspector, QLabel, "inspector_serial_exclusive")
    combo = inspector.findChild(QComboBox, "inspector_database_field")
    assert combo.currentData() is None
    combo.setCurrentIndex(combo.findData("Fixture"))
    assert item.binding == {"source": "database", "field": "Fixture"}
    inspector.set_item(item)
    qapp.processEvents()
    assert _visible(inspector, QLabel, "inspector_serial_exclusive") == []
    assert _visible(inspector, QLabel, "inspector_snapshot_hint")
    inspector.close()


def test_missing_csv_banner_and_hash_banner(qapp, tmp_path):
    from ql_editor import csv_source, document

    csv_path = _csv(tmp_path)
    qlx = tmp_path / "label.qlx"
    data_source = csv_source.data_source_dict(
        csv_source.load(csv_path),
        path=csv_path,
        current_record=0,
        relative_to=qlx,
    )
    data_source["content_sha256"] = "0" * 64
    document.save(
        qlx,
        document.build(
            {"model": "QL-820NWB", "label": "62"},
            [
                {
                    "type": "text",
                    "text": "Snapshot",
                    "binding": {"source": "database", "field": "Fixture"},
                }
            ],
            data_source=data_source,
        ),
    )
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()
    assert win._act_database.isVisible()
    assert not win._database_panel.isVisible()
    _open_database(win)
    qapp.processEvents()
    assert "Hash" in win._database_panel._banner.text()
    assert not win._database_panel._banner.isHidden()
    win.close()

    csv_path.rename(tmp_path / "gone.csv")
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()
    assert win._active.csv_table is None
    texts = [
        item.text_value
        for item in win._canvas.ordered_items()
        if isinstance(item, TextItem)
    ]
    assert texts == ["Snapshot"]
    assert win._act_database.isVisible()
    _open_database(win)
    qapp.processEvents()
    assert "CSV nicht geladen" in win._database_panel._banner.text()
    assert not win._database_panel._banner.isHidden()
    assert win._database_panel._disconnect.isEnabled()
    win.close()


def test_failed_connect_does_not_drop_loaded_table(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    assert win.connect_csv_path(str(tmp_path / "fehlt.csv")) is False
    assert win._active.csv_table is not None
    assert win._database_panel._grid.rowCount() == 2
    _open_database(win)
    qapp.processEvents()
    assert win._database_panel._banner.isVisible()
    win.close()


def test_collapse_keeps_row_selection(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    _open_database(win)
    win._database_panel.set_expanded(False)
    assert not win._database_panel._body.isVisible()
    assert win._database_panel._other.isVisible()
    win._database_panel.set_expanded(True)
    assert win._database_panel._grid.rowCount() == 2
    win.close()


def test_serial_step_zero_returns_to_the_previous_value():
    """Schritt 0 ist kein Fortschritt. Der Spin geht auf den letzten Wert."""
    from PySide6.QtWidgets import QSpinBox

    inspector = InspectorPanel()
    inspector.set_serial_context(
        {
            "enabled": True,
            "start": 1,
            "count": 1,
            "step": 4,
            "prefix": "",
            "suffix": "",
            "pad_width": 0,
        },
        csv_connected=True,
    )
    item = TextItem("1")
    item.set_binding({"source": "serial"})
    inspector.set_item(item)
    step = inspector.findChild(QSpinBox, "inspector_serial_step")
    assert step is not None
    step.setValue(0)
    assert step.value() == 4


def test_connect_save_stores_relative_path(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    out = tmp_path / "label.qlx"
    assert win._save_document_to(str(out))
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["data_source"]["path"] == "Fixture Data.csv"
    assert "Spot A" not in json.dumps(saved["data_source"])
    win.close()



def _select_rows(win: MainWindow, rows: list[int]) -> None:
    grid = win._database_panel._grid
    model = grid.selectionModel()
    for position, row in enumerate(rows):
        flag = (
            model.SelectionFlag.ClearAndSelect
            if position == 0
            else model.SelectionFlag.Select
        )
        model.select(grid.model().index(row, 0), flag | model.SelectionFlag.Rows)


def test_multi_select_previews_first_selected_record(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    item = TextItem("CH:")
    item.set_binding({"source": "database", "field": "Fixture"})
    win._canvas.add_item(item)
    _open_database(win)
    _select_rows(win, [1, 0])
    qapp.processEvents()
    assert win._database_panel.selected_records() == [0, 1]
    assert win._active.current_record == 0
    assert item.text_value == "Spot A"
    win.set_current_record(1)
    qapp.processEvents()
    assert win._database_panel.selected_records() == [0, 1]
    win.close()


def test_print_selected_uses_all_selected_rows(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    _open_database(win)
    _select_rows(win, [0, 1])
    qapp.processEvents()
    labels = win._planned_labels()
    assert [label.variant.index for label in labels] == [0, 1]
    win.close()


def test_last_selected_row_stays_selected_on_ctrl_click(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    _open_database(win)
    _select_rows(win, [1])
    qapp.processEvents()
    grid = win._database_panel._grid
    model = grid.selectionModel()
    model.select(
        grid.model().index(1, 0),
        model.SelectionFlag.Deselect | model.SelectionFlag.Rows,
    )
    qapp.processEvents()
    assert win._database_panel.selected_records() == [1]
    assert win._active.current_record == 1
    win.close()


def test_multi_selection_survives_panel_resync(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    _open_database(win)
    _select_rows(win, [0, 1])
    qapp.processEvents()
    win._sync_database_panel()
    qapp.processEvents()
    assert win._database_panel.selected_records() == [0, 1]
    win.close()


def test_opening_label_with_database_shows_grid(qapp, tmp_path):
    _csv(tmp_path)
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    data = {
        "items": [],
        "data_source": {"type": "csv", "path": "Fixture Data.csv", "current_record": 1},
    }
    win._apply_document(data, document_path=str(tmp_path / "label.qlx"))
    qapp.processEvents()
    assert win._act_database.isChecked()
    assert win._database_panel.isVisible()
    assert win._database_panel.current_record() == 1
    win.close()


def test_opening_label_without_database_keeps_grid_hidden(qapp, tmp_path):
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    win._apply_document({"items": []}, document_path=str(tmp_path / "label.qlx"))
    qapp.processEvents()
    assert not win._act_database.isChecked()
    assert not win._database_panel.isVisible()
    win.close()


def test_enter_in_print_sheet_starts_print(qapp, monkeypatch):
    from PySide6.QtTest import QTest

    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    win._show_print_sheet()
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(win, "_on_print", lambda: calls.append(True))
    win._print_button.setEnabled(True)
    win._copies_spin.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._copies_spin, Qt.Key.Key_Return)
    qapp.processEvents()
    assert calls == [True]
    win._print_button.setEnabled(False)
    QTest.keyClick(win._copies_spin, Qt.Key.Key_Return)
    qapp.processEvents()
    assert calls == [True]
    win.close()


def test_enter_prints_right_after_opening_the_sheet(qapp, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    calls = []
    monkeypatch.setattr(win, "_on_print", lambda: calls.append(True))
    win._show_print_sheet()
    qapp.processEvents()
    win._print_button.setEnabled(True)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    qapp.processEvents()
    assert calls == [True]
    win._print_button.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._print_button, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    qapp.processEvents()
    assert calls == [True, True]
    win.close()


def test_enter_on_canvas_does_not_print_after_sheet_closed(qapp, monkeypatch):
    from PySide6.QtTest import QTest

    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    calls = []
    monkeypatch.setattr(win, "_on_print", lambda: calls.append(True))
    win._show_print_sheet()
    qapp.processEvents()
    win._close_print_sheet()
    qapp.processEvents()
    win._canvas.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._canvas, Qt.Key.Key_Return)
    qapp.processEvents()
    assert calls == []
    win.close()


def test_shift_click_selects_range_of_rows(qapp, tmp_path):
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    win = _window_with_csv(qapp, tmp_path)
    _open_database(win)
    grid = win._database_panel._grid
    model = grid.selectionModel()
    first = grid.model().index(0, 0)
    last = grid.model().index(1, 0)
    model.select(first, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
    model.select(QItemSelection(first, last), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    qapp.processEvents()
    assert win._database_panel.selected_records() == [0, 1]
    win.close()


def _rows_csv(tmp_path: Path, name: str, prefix: str, rows: int = 6) -> Path:
    path = tmp_path / name
    lines = ["Fixture;Channel"] + [f"{prefix} {i};{i}" for i in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_replacing_the_csv_drops_the_old_selection(qapp, tmp_path):
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    assert win.connect_csv_path(str(_rows_csv(tmp_path, "a.csv", "A")))
    _open_database(win)
    _select_rows(win, [3, 4, 5])
    qapp.processEvents()
    assert win.connect_csv_path(str(_rows_csv(tmp_path, "b.csv", "B")))
    qapp.processEvents()
    assert win._active.current_record == 0
    assert win._database_panel.selected_records() == [0]
    assert [label.variant.index for label in win._planned_labels()] == [0]
    win.close()


def test_reconnecting_after_disconnect_starts_with_one_row(qapp, tmp_path):
    win = MainWindow(discover=False)
    win.resize(1100, 760)
    win.show()
    path = _rows_csv(tmp_path, "a.csv", "A")
    assert win.connect_csv_path(str(path))
    _open_database(win)
    _select_rows(win, [2, 3])
    qapp.processEvents()
    win.disconnect_csv()
    assert win._active.selected_records == []
    assert win.connect_csv_path(str(path))
    qapp.processEvents()
    assert win._database_panel.selected_records() == [0]
    win.close()
