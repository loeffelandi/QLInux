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
