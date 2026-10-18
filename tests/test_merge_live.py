"""Live-Canvas: Record-Wechsel aktualisiert gebundene Objekte (M2 / D15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from ql_editor import csv_source, document
from ql_editor.app import MainWindow
from ql_editor.items import BarcodeItem, QRItem, TextItem

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    QSettings("QLInux", "QLInux").clear()
    yield
    QSettings("QLInux", "QLInux").clear()


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    csv_path = tmp_path / "Fixture Data.csv"
    csv_path.write_text(
        "Fixture;Circuit;Channel\n"
        "Spot A;PB 1;11\n"
        "Spot B;PB 2;22\n"
        "Spot C;PB 3;33\n",
        encoding="utf-8-sig",
    )
    items = [
        {
            "type": "text",
            "text": "?",
            "x": 10,
            "y": 10,
            "binding": {"source": "database", "field": "Fixture"},
        },
        {
            "type": "text",
            "text": "CH:",
            "x": 10,
            "y": 60,
        },
        {
            "type": "text",
            "text": "?",
            "x": 80,
            "y": 60,
            "binding": {"source": "database", "field": "Channel"},
        },
        {
            "type": "qr",
            "data": "?",
            "x": 10,
            "y": 100,
            "size_dots": 80,
            "binding": {"source": "database", "field": "Circuit"},
        },
        {
            "type": "barcode",
            "value": "0000",
            "symbology": "code128",
            "x": 120,
            "y": 100,
            "binding": {"source": "serial"},
        },
    ]
    data_source = {
        "type": "csv",
        "path": "Fixture Data.csv",
        "encoding": "utf-8-sig",
        "delimiter": ";",
        "current_record": 0,
        "content_sha256": csv_source.load(csv_path).content_sha256,
    }
    qlx = tmp_path / "label.qlx"
    document.save(
        qlx,
        document.build(
            {"model": "QL-820NWB", "label": "62"},
            items,
            data_source=data_source,
            serial={
                "enabled": False,
                "start": 100,
                "count": 1,
                "step": 1,
                "prefix": "",
                "suffix": "",
                "pad_width": 4,
            },
        ),
    )
    return qlx, csv_path


def _bound_texts(win: MainWindow) -> list[TextItem]:
    return [
        item
        for item in win._canvas.ordered_items()
        if isinstance(item, TextItem) and item.binding
    ]


def test_opening_document_merges_current_record(qapp, tmp_path):
    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()

    assert win._active.csv_table is not None
    assert win._active.current_record == 0
    assert win._database_panel._grid.rowCount() == 3
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot A"
    assert texts["Channel"] == "11"
    qr = next(i for i in win._canvas.ordered_items() if isinstance(i, QRItem))
    assert qr.to_dict()["data"] == "PB 1"
    barcode = next(
        i for i in win._canvas.ordered_items() if isinstance(i, BarcodeItem)
    )
    assert barcode.value == "0100"
    # Statischer Prefix bleibt.
    static = [
        i
        for i in win._canvas.ordered_items()
        if isinstance(i, TextItem) and not i.binding
    ][0]
    assert static.text_value == "CH:"


def test_row_selection_updates_canvas_without_undo(qapp, tmp_path):
    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()
    assert win._undo_stack.isClean()

    win.set_current_record(2, mark_dirty=True)
    qapp.processEvents()

    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot C"
    assert texts["Channel"] == "33"
    assert win._active.current_record == 2
    assert win._database_panel.current_record() == 2
    # Record-Navigation erzeugt keinen Undo-Schritt (Plan-Risiko).
    assert win._undo_stack.count() == 0
    assert win._document_dirty is True


def test_panel_click_drives_live_merge(qapp, tmp_path):
    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()

    win._database_panel._grid.selectRow(1)
    qapp.processEvents()

    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot B"
    assert texts["Channel"] == "22"


def test_save_round_trip_keeps_data_source_and_merged_snapshots(qapp, tmp_path):
    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()
    win.set_current_record(1, mark_dirty=True)
    out = tmp_path / "saved.qlx"
    assert win._save_document_to(str(out))

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["format"] == 2
    assert data["data_source"]["current_record"] == 1
    assert data["data_source"]["path"] == "Fixture Data.csv"
    # CSV-Inhalt ist nicht eingebettet (D1); Snapshots liegen an den Items.
    assert "Spot A" not in json.dumps(data["data_source"])
    # Snapshots im Item spiegeln den aktuellen Record.
    fixture_item = next(
        item
        for item in data["items"]
        if item.get("binding", {}).get("field") == "Fixture"
    )
    assert fixture_item["text"] == "Spot B"


def test_bind_csv_api_applies_merge(qapp, tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("Name\nAlpha\nBeta\n", encoding="utf-8")
    table = csv_source.load(csv_path)
    win = MainWindow()
    item = TextItem("x")
    item.set_binding({"source": "database", "field": "Name"})
    win._canvas.add_item(item)
    win.bind_csv_table(table, current_record=1)
    qapp.processEvents()
    assert item.text_value == "Beta"
    assert win._database_panel._grid.rowCount() == 2


def test_missing_csv_keeps_stored_snapshots_and_status(qapp, tmp_path):
    """Fehlende CSV: Snapshots bleiben, Status warnt (Major / D11/D12)."""
    qlx, csv_path = _write_fixture(tmp_path)
    # Gespeicherte Snapshots vor dem Open auf bekannte Werte setzen.
    raw = json.loads(qlx.read_text(encoding="utf-8"))
    for item in raw["items"]:
        binding = item.get("binding") or {}
        if binding.get("field") == "Fixture":
            item["text"] = "Stored Fixture"
        elif binding.get("field") == "Channel":
            item["text"] = "Stored Channel"
        elif item.get("type") == "qr":
            item["data"] = "Stored Circuit"
    qlx.write_text(json.dumps(raw), encoding="utf-8")
    csv_path.rename(tmp_path / "Fixture Data.csv.missing")

    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()

    assert win._active.csv_table is None
    assert win._active.data_source is not None
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Stored Fixture"
    assert texts["Channel"] == "Stored Channel"
    qr = next(i for i in win._canvas.ordered_items() if isinstance(i, QRItem))
    assert qr.to_dict()["data"] == "Stored Circuit"
    # Serial-Vorschau (Index 0) darf ohne CSV weiterlaufen.
    barcode = next(
        i for i in win._canvas.ordered_items() if isinstance(i, BarcodeItem)
    )
    assert barcode.value == "0100"
    status = win.statusBar().currentMessage()
    assert "CSV nicht geladen" in status


def test_sha_drift_shows_status_after_open(qapp, tmp_path):
    qlx, csv_path = _write_fixture(tmp_path)
    raw = json.loads(qlx.read_text(encoding="utf-8"))
    raw["data_source"]["content_sha256"] = "0" * 64
    qlx.write_text(json.dumps(raw), encoding="utf-8")
    # CSV bleibt lesbar, Hash weicht ab.
    assert csv_path.is_file()

    win = MainWindow()
    win.open_path(str(qlx))
    qapp.processEvents()

    assert win._active.csv_table is not None
    status = win.statusBar().currentMessage()
    assert "Hash" in status or "geändert" in status
    # Meta wird auf aktuellen Hash aktualisiert.
    assert win._active.data_source["content_sha256"] == csv_source.load(
        csv_path
    ).content_sha256


def _fake_print_worker(captured: dict):
    from PySide6.QtCore import QObject, Signal

    class FakeWorker(QObject):
        succeeded = Signal(dict)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, image, label, config, options):
            super().__init__()
            captured["images"] = image
            captured["options"] = dict(options)

        def start(self) -> None:
            self.finished.emit()

    return FakeWorker


def test_print_ranges_render_selected_all_and_record_range(
    qapp, tmp_path, monkeypatch
):
    """Selected / All / Record Range gehen als Bildliste in einen Auftrag."""
    from ql_editor import app as app_module
    from ql_editor.printer import CUT_AT_END

    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.show()
    win.open_path(str(qlx))
    qapp.processEvents()
    win._media_panel.set_network_host("192.168.178.62")

    assert win._scope_selected.isEnabled()
    assert win._scope_selected.isChecked()
    assert not win._scope_all.isChecked()
    cut_index = win._cut_combo.findData(CUT_AT_END)
    assert win._cut_combo.model().item(cut_index).isEnabled() is False

    captured: dict = {}
    monkeypatch.setattr(app_module, "PrintWorker", _fake_print_worker(captured))

    win.set_current_record(1)
    qapp.processEvents()
    undo_before = win._undo_stack.count()
    win._on_print()
    qapp.processEvents()
    assert len(captured["images"]) == 1
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot B"
    assert win._undo_stack.count() == undo_before

    win._scope_all.setChecked(True)
    qapp.processEvents()
    assert win._cut_combo.model().item(cut_index).isEnabled() is True
    win._on_print()
    qapp.processEvents()
    assert len(captured["images"]) == 3
    assert captured["options"]["copies"] == 1
    assert len({image.tobytes() for image in captured["images"]}) == 3
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot B"
    assert "3 Etiketten" in win.statusBar().currentMessage()

    win._scope_range.setChecked(True)
    assert win._range_from.isEnabled()
    win._range_from.setValue(2)
    win._range_to.setValue(3)
    win._copies_spin.setValue(2)
    qapp.processEvents()
    win._on_print()
    qapp.processEvents()
    assert len(captured["images"]) == 2
    assert captured["options"]["copies"] == 2
    assert "4 Etiketten" in win.statusBar().currentMessage()
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot B"
    win.close()
    qapp.processEvents()


def test_print_range_over_page_limit_does_not_start(qapp, tmp_path, monkeypatch):
    from ql_editor import app as app_module
    from ql_editor.sheet import Sheet

    qlx, _csv = _write_fixture(tmp_path)
    win = MainWindow()
    win.show()
    win.open_path(str(qlx))
    qapp.processEvents()
    win._media_panel.set_network_host("192.168.178.62")
    win._scope_all.setChecked(True)
    win._copies_spin.setValue(40)
    created: list = []

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            created.append(args)

        def start(self) -> None:
            return None

    monkeypatch.setattr(app_module, "PrintWorker", FakeWorker)
    win._on_print()
    qapp.processEvents()
    assert created == []
    from PySide6.QtWidgets import QLabel

    sheet = next(item for item in win.findChildren(Sheet) if item.isVisible())
    message = " ".join(label.text() for label in sheet.findChildren(QLabel))
    assert "99" in message
    sheet.close_sheet()
    texts = {item.binding["field"]: item.text_value for item in _bound_texts(win)}
    assert texts["Fixture"] == "Spot A"
    win.close()
    qapp.processEvents()


def test_print_scope_is_persisted(qapp):
    win = MainWindow()
    win._scope_range.setChecked(True)
    win._range_from.setMaximum(10)
    win._range_to.setMaximum(10)
    win._range_from.setValue(2)
    win._range_to.setValue(4)
    win.close()
    qapp.processEvents()

    again = MainWindow()
    assert again._scope_range.isChecked()
    assert again._range_from.value() == 2
    assert again._range_to.value() == 4
    assert again._scope_selected.isEnabled() is False
    again.close()
    qapp.processEvents()
