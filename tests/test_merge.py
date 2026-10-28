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
        merge.format_serial({"start": 1, "pad_width": 4, "step": 1}, index=2) == "0003"
    )


def test_format_serial_rejects_negative_index():
    with pytest.raises(merge.MergeError):
        merge.format_serial(index=-1)


def test_resolve_binding_database_and_serial():
    record = {"Fixture": "A1", "Channel": "91"}
    assert (
        merge.resolve_binding({"source": "database", "field": "Channel"}, record=record)
        == "91"
    )
    assert (
        merge.resolve_binding({"source": "database", "field": "Missing"}, record=record)
        == ""
    )
    assert merge.resolve_binding({"source": "serial"}, serial_value="0007") == "0007"
    assert merge.resolve_binding(None, record=record) is None
    assert merge.resolve_binding({"source": "none"}) is None


def test_resolve_binding_without_record_skips_database():
    """Ohne Record Database-Bindings nicht anwenden (Snapshot behalten)."""
    assert (
        merge.resolve_binding({"source": "database", "field": "A"}, record=None) is None
    )
    assert (
        merge.resolve_binding({"source": "serial"}, record=None, serial_value="9")
        == "9"
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


def test_apply_record_without_record_preserves_database_snapshots():
    text = _FakeText("Spot A", {"source": "database", "field": "Fixture"})
    qr = _FakeQR("PB 1", {"source": "database", "field": "Circuit"})
    barcode = _FakeBarcode("0000", {"source": "serial"})

    count = merge.apply_record(
        [text, qr, barcode],
        record=None,
        serial={"start": 100, "pad_width": 4},
        serial_index=0,
    )
    assert count == 1
    assert text.text_value == "Spot A"
    assert qr._data == "PB 1"
    assert barcode.value == "0100"


def test_apply_record_keeps_barcode_on_invalid_value():
    barcode = _FakeBarcode("SAFE", {"source": "database", "field": "X"}, fail=True)
    count = merge.apply_record([barcode], record={"X": "bad"})
    assert barcode.value == "SAFE"
    assert count == 0


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


def test_resolve_csv_path_prefers_document_neighbor_over_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Relativer Name neben der .qlx gewinnt vor einer gleichnamigen CWD-Datei."""
    doc_dir = tmp_path / "doc"
    cwd_dir = tmp_path / "cwd"
    doc_dir.mkdir()
    cwd_dir.mkdir()
    neighbor = doc_dir / "shared.csv"
    neighbor.write_text("A\nfrom-doc\n", encoding="utf-8")
    cwd_hit = cwd_dir / "shared.csv"
    cwd_hit.write_text("A\nfrom-cwd\n", encoding="utf-8")
    qlx = doc_dir / "label.qlx"
    qlx.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(cwd_dir)
    resolved = merge.resolve_csv_path("shared.csv", document_path=qlx)
    assert resolved.resolve() == neighbor.resolve()


def test_apply_record_empty_records_preserves_database():
    text = _FakeText("keep", {"source": "database", "field": "A"})
    count = merge.apply_record([text], record=None)
    assert count == 0
    assert text.text_value == "keep"


def test_serial_preview_uses_index_zero_like_d10():
    assert merge.format_serial(DEFAULT_SERIAL, index=0) == "1"
    item = _FakeText("", {"source": "serial"})
    assert (
        merge.resolve_item_display(
            item, serial={"start": 5, "count": 3, "step": 2}, serial_index=0
        )
        == "5"
    )


def _rows():
    return (
        {"Fixture": "Spot A"},
        {"Fixture": "Spot B"},
        {"Fixture": "Spot C"},
    )


def test_plan_print_variants_selected_all_and_range():
    rows = _rows()
    selected = merge.plan_print_variants(rows, scope="selected", selected=1)
    assert [item.index for item in selected] == [1]
    assert selected[0].record["Fixture"] == "Spot B"

    everything = merge.plan_print_variants(rows, scope="all")
    assert [item.index for item in everything] == [0, 1, 2]

    span = merge.plan_print_variants(rows, scope="range", range_from=3, range_to=2)
    assert [item.record["Fixture"] for item in span] == ["Spot B", "Spot C"]


def test_plan_print_variants_without_records_is_one_virtual_label():
    planned = merge.plan_print_variants(None, scope="all")
    assert planned == [merge.PrintVariant(None, None)]
    assert merge.plan_print_variants((), scope="range") == planned


def test_plan_print_variants_keeps_selection_order_and_drops_gaps():
    rows = _rows()
    planned = merge.plan_print_variants(rows, scope="selected", selected=[2, 0, 2, 9])
    assert [item.index for item in planned] == [2, 0]
    with pytest.raises(merge.MergeError):
        merge.plan_print_variants(rows, scope="selected", selected=[])
    with pytest.raises(merge.MergeError):
        merge.plan_print_variants(rows, scope="nope")
    with pytest.raises(merge.MergeError):
        merge.plan_print_variants(rows, scope="range", range_from=8, range_to=9)


def test_plan_serial_labels_walks_each_record_then_the_series():
    """D5: Record aussen, Serie innen. Kopien vervielfachen hier nicht."""
    rows = _rows()
    variants = merge.plan_print_variants(rows, scope="all")
    serial = {"enabled": True, "start": 1, "count": 2, "step": 10}
    labels = merge.plan_serial_labels(variants, serial)
    assert [(label.variant.index, label.serial_index) for label in labels] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (2, 0),
        (2, 1),
    ]
    assert [
        merge.format_serial(serial, index=label.serial_index) for label in labels
    ] == [
        "1",
        "11",
        "1",
        "11",
        "1",
        "11",
    ]


def test_plan_serial_labels_without_database_is_one_virtual_record():
    variants = merge.plan_print_variants(None)
    serial = {"enabled": True, "start": 4, "count": 3, "step": 1}
    labels = merge.plan_serial_labels(variants, serial)
    assert len(labels) == 3
    assert all(label.variant.record is None for label in labels)
    assert [label.serial_index for label in labels] == [0, 1, 2]


def test_serial_length_ignores_count_until_enabled():
    assert merge.serial_length({"enabled": False, "count": 8}) == 1
    assert merge.serial_length(None) == 1
    with pytest.raises(merge.MergeError):
        merge.serial_length({"enabled": True, "count": 0})


def test_job_page_count_is_variants_times_copies():
    from ql_editor.printer import COPIES_MAX

    assert not hasattr(merge, "PRINT_PAGE_LIMIT")
    assert merge.job_page_count(3, 2) == 6
    assert merge.job_page_count(1, COPIES_MAX) == COPIES_MAX
    with pytest.raises(merge.MergeError):
        merge.job_page_count(3, 40)
    with pytest.raises(merge.MergeError):
        merge.job_page_count(0, 1)


def test_apply_record_strict_rejects_bad_barcode():
    code = _FakeBarcode("OK", {"source": "database", "field": "A"}, fail=True)
    with pytest.raises(merge.MergeError):
        merge.apply_record([code], record={"A": "bad"}, strict=True)
    assert code.value == "OK"
    assert merge.apply_record([code], record={"A": "bad"}) == 0
    assert code.value == "OK"
