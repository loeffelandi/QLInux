"""Unit-Tests fuer die Merge-Engine (headless, ohne Qt-Widgets)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ql_editor import merge
from ql_editor.document import DEFAULT_SERIAL


class _FakeText:
    kind = "text"

    def __init__(self, text: str = "", binding=None):
        self._text = text
        self._binding = binding

    @property
    def binding(self):
        return dict(self._binding) if self._binding else None

    def set_text_value(self, value: str) -> None:
        self._text = value

    @property
    def text_value(self) -> str:
        return self._text


class _FakeQR:
    kind = "qr"

    def __init__(self, data: str = "", binding=None):
        self._data = data
        self._binding = binding

    @property
    def binding(self):
        return dict(self._binding) if self._binding else None

    def set_data(self, data: str) -> None:
        self._data = data


class _FakeBarcode:
    kind = "barcode"

    def __init__(self, value: str = "OK", binding=None, *, fail: bool = False):
        self._value = value
        self._binding = binding
        self._fail = fail

    @property
    def binding(self):
        return dict(self._binding) if self._binding else None

    def set_value(self, value: str) -> None:
        if self._fail:
            raise ValueError("bad")
        self._value = value

    @property
    def value(self) -> str:
        return self._value


def test_format_serial_defaults_and_pad():
    assert merge.format_serial() == "1"
    assert merge.format_serial({"start": 7, "prefix": "N-", "suffix": "x"}) == "N-7x"
    assert (
        merge.format_serial(
            {"start": 1, "pad_width": 4, "step": 1}, index=2
        )
        == "0003"
    )


def test_format_serial_rejects_negative_index():
    with pytest.raises(merge.MergeError):
        merge.format_serial(index=-1)


def test_resolve_binding_database_and_serial():
    record = {"Fixture": "A1", "Channel": "91"}
    assert (
        merge.resolve_binding(
            {"source": "database", "field": "Channel"}, record=record
        )
        == "91"
    )
    assert (
        merge.resolve_binding(
            {"source": "database", "field": "Missing"}, record=record
        )
        == ""
    )
    assert merge.resolve_binding({"source": "serial"}, serial_value="0007") == "0007"
    assert merge.resolve_binding(None, record=record) is None
    assert merge.resolve_binding({"source": "none"}) is None


def test_resolve_binding_without_record_is_empty():
    assert (
        merge.resolve_binding({"source": "database", "field": "A"}, record=None)
        == ""
    )


def test_apply_record_updates_bound_items_only():
    text = _FakeText("old", {"source": "database", "field": "Fixture"})
    static = _FakeText("CH:", None)
    qr = _FakeQR("x", {"source": "database", "field": "Patch"})
    barcode = _FakeBarcode("1", {"source": "serial"})
    unbound_barcode = _FakeBarcode("keep")

    count = merge.apply_record(
        [text, static, qr, barcode, unbound_barcode],
        record={"Fixture": "PAR", "Patch": "1/2"},
        serial={"start": 12, "pad_width": 4},
        serial_index=0,
    )
    assert count == 3
    assert text.text_value == "PAR"
    assert static.text_value == "CH:"
    assert qr._data == "1/2"
    assert barcode.value == "0012"
    assert unbound_barcode.value == "keep"


def test_apply_record_keeps_barcode_on_invalid_value():
    barcode = _FakeBarcode("SAFE", {"source": "database", "field": "X"}, fail=True)
    merge.apply_record([barcode], record={"X": "bad"})
    assert barcode.value == "SAFE"


def test_clamp_record_index():
    assert merge.clamp_record_index(-3, 5) == 0
    assert merge.clamp_record_index(99, 5) == 4
    assert merge.clamp_record_index(2, 5) == 2
    assert merge.clamp_record_index(7, 0) == 0


def test_resolve_csv_path_relative_to_document(tmp_path: Path):
    csv = tmp_path / "Fixture Data.csv"
    csv.write_text("A;B\n1;2\n", encoding="utf-8")
    qlx = tmp_path / "design.qlx"
    qlx.write_text("{}", encoding="utf-8")
    resolved = merge.resolve_csv_path("Fixture Data.csv", document_path=qlx)
    assert resolved == csv
    assert merge.resolve_csv_path(str(csv)).is_file()


def test_serial_preview_uses_index_zero_like_d10():
    assert merge.format_serial(DEFAULT_SERIAL, index=0) == "1"
    item = _FakeText("", {"source": "serial"})
    assert (
        merge.resolve_item_display(
            item, serial={"start": 5, "count": 3, "step": 2}, serial_index=0
        )
        == "5"
    )
