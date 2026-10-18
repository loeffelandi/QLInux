"""LBX-Import von Datenbank-Merge (M3, Plan Abschnitt 2 und 10)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ql_editor import csv_source, lbx
from tests.lbx_samples import text_object, write_lbx

_DB_NS = "http://schemas.brother.info/ptouch/2007/lbx/database"
_MAC_PATH = (
    "/Users/Andreas/OpenCloud/Personal/SustainVT/VT Vorlagen/"
    "1_Fixture Labels/Fixture Data.csv"
)


def _styles() -> str:
    return f"""
    <database:dbMergeFieldStyle xmlns:database="{_DB_NS}"
      name="Circuit" fieldName="Circuit" joinedField="false"/>
    <database:dbField xmlns:database="{_DB_NS}"
      fieldName="Circuit" joinedField="false" removeEmptyLine="false"/>
    <database:dbMergeFieldStyle xmlns:database="{_DB_NS}"
      name="Filters" fieldName="Filters" joinedField="true" removeEmptyLine="true"/>
    <database:dbMergeFieldStyle xmlns:database="{_DB_NS}"
      name="DMX" fieldName="DMX Mode" joinedField="false"/>
    """


def _database(
    *,
    database_path: str,
    merge_table: str = "Fixture Data.csv",
    current_record: str = "4",
    contains: str = "true",
) -> str:
    return f"""
    <database:database xmlns:database="{_DB_NS}"
      type="FILE"
      databasePath="{database_path}"
      mergeTable="{merge_table}"
      mergeTableType="NONE"
      currentRecord="{current_record}"
      containsFieldName="{contains}"
      readonly="true"
      cellWidths="0">
      {_styles()}
    </database:database>
    """


def _objects(*, database_path: str, merge_table: str = "Fixture Data.csv", current: str = "4") -> str:
    return (
        _database(database_path=database_path, merge_table=merge_table, current_record=current)
        + text_object(body="CH:", x=2)
        + text_object(body="PB 6B-6", x=12, expanded="Circuit")
        + text_object(body="", x=22, expanded="Filters")
        + text_object(body="snap", x=32, expanded="DMX")
        + text_object(body="", x=42)
        + '<barcode:barcode xmlns:barcode="urn:barcode"/>'
    )


def _write_csv(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _rows() -> str:
    lines = ["Circuit;Filters;DMX Mode"]
    for index in range(6):
        lines.append(f"c{index};f{index};m{index}")
    return "\n".join(lines) + "\n"


def test_import_binds_known_attributes_and_keeps_empty_merge_text(tmp_path):
    csv_path = tmp_path / "Fixture Data.csv"
    _write_csv(csv_path, _rows())
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=_MAC_PATH),
    )

    data = lbx.load(path)

    by_field = {
        item.get("binding", {}).get("field"): item
        for item in data["items"]
        if item["type"] == "text"
    }
    assert by_field[None]["text"] == "CH:"
    assert "binding" not in by_field[None]
    assert by_field["Circuit"]["text"] == "PB 6B-6"
    assert by_field["Circuit"]["binding"] == {"source": "database", "field": "Circuit"}
    assert by_field["Filters"]["text"] == ""
    assert by_field["Filters"]["binding"]["field"] == "Filters"
    assert by_field["DMX Mode"]["binding"] == {
        "source": "database",
        "field": "DMX Mode",
    }
    assert all(item["type"] != "barcode" for item in data["items"])
    source = data["data_source"]
    assert source["type"] == "csv"
    assert source["path"] == str(csv_path.resolve())
    assert source["current_record"] == 4
    assert source["containsFieldName"] is True
    assert source["delimiter"] == ";"
    assert source["content_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert "f0" not in source["path"]
    assert set(source) >= {
        "type",
        "path",
        "encoding",
        "delimiter",
        "current_record",
        "content_sha256",
        "containsFieldName",
    }
    assert not any("Datenbankfeld" in warning for warning in data["warnings"])
    assert any("Barcode" in warning for warning in data["warnings"])


def test_database_path_wins_over_sibling_merge_table(tmp_path):
    sibling = tmp_path / "Fixture Data.csv"
    _write_csv(sibling, "Circuit\nFROM-TABLE\n")
    other = tmp_path / "other" 
    other.mkdir()
    chosen = other / "chosen.csv"
    _write_csv(chosen, "Circuit\nFROM-PATH\n")
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=str(chosen)),
    )

    data = lbx.load(path)

    assert data["data_source"]["content_sha256"] == hashlib.sha256(
        chosen.read_bytes()
    ).hexdigest()
    assert data["warnings"] == [] or not any(
        "nicht gefunden" in warning for warning in data["warnings"]
    )


def test_merge_table_beside_lbx_when_database_path_missing(tmp_path):
    csv_path = tmp_path / "Fixture Data.csv"
    _write_csv(csv_path, _rows())
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=_MAC_PATH, merge_table="Fixture Data.csv"),
    )

    data = lbx.load(path)

    assert data["data_source"]["path"] == str(csv_path.resolve())
    assert data["data_source"]["current_record"] == 4


def test_data_csv_in_folder_when_named_paths_miss(tmp_path):
    decoy = tmp_path / "notes.csv"
    _write_csv(decoy, "Circuit\nNO\n")
    show = tmp_path / "Show Data.csv"
    _write_csv(show, "Circuit\nSHOW\n")
    fixture = tmp_path / "Fixture Data.csv"
    _write_csv(fixture, "Circuit\nFIXTURE\n")
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=_MAC_PATH, merge_table="missing.csv"),
    )

    data = lbx.load(path)

    assert data["data_source"]["path"] == str(fixture.resolve())


def test_missing_csv_keeps_layout_bindings_and_snapshots(tmp_path):
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=_MAC_PATH, merge_table="missing.csv"),
    )

    data = lbx.load(path)

    circuit = next(item for item in data["items"] if item.get("text") == "PB 6B-6")
    filters = next(
        item
        for item in data["items"]
        if item.get("binding", {}).get("field") == "Filters"
    )
    assert circuit["binding"]["field"] == "Circuit"
    assert filters["text"] == ""
    assert data["data_source"]["path"] == _MAC_PATH
    assert data["data_source"]["current_record"] == 4
    assert "content_sha256" not in data["data_source"]
    assert any(_MAC_PATH in warning for warning in data["warnings"])
    assert not any("Datenbankfeld" in warning for warning in data["warnings"])


def test_unreadable_csv_warns_and_keeps_snapshots(tmp_path):
    csv_path = tmp_path / "Fixture Data.csv"
    csv_path.write_bytes(b"\xff\xfe\x00not-utf8")
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=str(csv_path)),
    )

    data = lbx.load(path)

    assert any(item["text"] == "PB 6B-6" for item in data["items"])
    assert any("nicht lesbar" in warning for warning in data["warnings"])
    assert "content_sha256" not in data["data_source"]


def test_current_record_is_clamped_when_csv_is_short(tmp_path):
    csv_path = tmp_path / "Fixture Data.csv"
    _write_csv(csv_path, "Circuit\na\nb\n")
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=_objects(database_path=str(csv_path), current="4"),
    )

    data = lbx.load(path)

    assert data["data_source"]["current_record"] == 1
    assert csv_source.load(csv_path).record(1)["Circuit"] == "b"


def test_optional_fixture_labels_when_present():
    """Echte Fixture Labels, wenn sie unter tests/data/ liegen — sonst skip."""
    folder = Path(__file__).resolve().parent / "data" / "fixture_labels"
    lbx_files = sorted(folder.glob("*.lbx")) if folder.is_dir() else []
    if not lbx_files:
        pytest.skip("optional fixture not under tests/data/fixture_labels")
    data = lbx.load(lbx_files[0])
    bound = [
        item
        for item in data["items"]
        if isinstance(item.get("binding"), dict)
        and item["binding"].get("source") == "database"
    ]
    fields = {item["binding"]["field"] for item in bound}
    assert "Circuit" in fields
    assert data.get("data_source", {}).get("type") == "csv"
    assert int(data["data_source"].get("current_record", 0)) >= 0
    assert not any("Datenbankfeld" in warning for warning in data["warnings"])
