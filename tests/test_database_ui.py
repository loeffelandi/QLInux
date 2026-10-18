"""M4: Datenbank-Panel, Drag-Binding, Inspector Database Field (D4/D13/D14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QToolBar

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
    win = MainWindow()
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
    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    assert not win._act_database.isVisible()
    assert not win._database_panel.isVisible()
    assert win._act_connect_csv.isVisible()
    bar = win.findChild(QToolBar, "main_toolbar")
    assert win._act_database in bar.actions()
    win.close()


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
    assert not panel._connect.isEnabled()
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
    assert win._database_panel._connect.isVisible()
    win._database_panel.set_expanded(True)
    assert win._database_panel._grid.rowCount() == 2
    win.close()


def test_connect_save_stores_relative_path(qapp, tmp_path):
    win = _window_with_csv(qapp, tmp_path)
    out = tmp_path / "label.qlx"
    assert win._save_document_to(str(out))
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["data_source"]["path"] == "Fixture Data.csv"
    assert "Spot A" not in json.dumps(saved["data_source"])
    win.close()
