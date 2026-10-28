"""Tests fuer :mod:`ql_editor.csv_source` (M1: CSV laden, D2/D1/D3)."""

from __future__ import annotations

import pytest
from ql_editor import csv_source


def test_load_comma_utf8(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Fixture,Circuit\nSpot,A1\nWash,B2\n", encoding="utf-8")

    table = csv_source.load(path)

    assert table.encoding == "utf-8"
    assert table.delimiter == ","
    assert table.fields == ("Fixture", "Circuit")
    assert len(table.records) == 2
    assert table.record(0) == {"Fixture": "Spot", "Circuit": "A1"}
    assert table.content_sha256 == csv_source.content_sha256(path.read_bytes())


def test_load_semicolon_and_bom(tmp_path):
    path = tmp_path / "data.csv"
    raw = "Fixture;Circuit\nSpot;A1\n".encode("utf-8-sig")
    path.write_bytes(raw)

    table = csv_source.load(path)

    assert table.encoding == "utf-8-sig"
    assert table.delimiter == ";"
    assert table.record(0)["Circuit"] == "A1"


def test_sniff_prefers_semicolon_when_more_common():
    assert csv_source.sniff_delimiter("a;b;c\n1;2;3\n") == ";"
    assert csv_source.sniff_delimiter("a,b,c\n1,2,3\n") == ","


def test_sniff_quoted_comma_with_semicolon_delimiter():
    """Kommas in Anfuehrungszeichen zaehlen nicht als Trenner."""
    sample = '"a,b";c\n1;2\n'
    assert csv_source.sniff_delimiter(sample) == ";"
    fields, records, delim = csv_source.parse_csv_text(sample)
    assert delim == ";"
    assert fields == ("a,b", "c")
    assert records[0] == {"a,b": "1", "c": "2"}


def test_empty_column_names_raise(tmp_path):
    path = tmp_path / "empty_col.csv"
    path.write_text("A,,B\n1,2,3\n", encoding="utf-8")

    with pytest.raises(csv_source.CsvSourceError, match="leere Spaltennamen"):
        csv_source.load(path)


def test_empty_csv_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(csv_source.CsvSourceError):
        csv_source.load(path)


def test_duplicate_headers_raise(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text("A,A\n1,2\n", encoding="utf-8")

    with pytest.raises(csv_source.CsvSourceError):
        csv_source.load(path)


def test_missing_file(tmp_path):
    with pytest.raises(csv_source.CsvSourceError):
        csv_source.load(tmp_path / "fehlt.csv")


def test_short_rows_are_padded(tmp_path):
    path = tmp_path / "short.csv"
    path.write_text("A,B,C\n1\n", encoding="utf-8")

    table = csv_source.load(path)

    assert table.record(0) == {"A": "1", "B": "", "C": ""}


def test_relativize_path_when_under_base(tmp_path):
    qlx = tmp_path / "design.qlx"
    csv = tmp_path / "Fixture Data.csv"
    csv.write_text("A\n1\n", encoding="utf-8")

    assert csv_source.relativize_path(csv, qlx) == "Fixture Data.csv"


def test_data_source_dict_round_trip_fields(tmp_path):
    path = tmp_path / "Fixture Data.csv"
    path.write_text("Fixture;Channel\nAlpha;1\n", encoding="utf-8")
    table = csv_source.load(path)

    block = csv_source.data_source_dict(
        table, current_record=0, relative_to=tmp_path / "design.qlx"
    )

    assert block == {
        "type": "csv",
        "path": "Fixture Data.csv",
        "encoding": "utf-8",
        "delimiter": ";",
        "current_record": 0,
        "content_sha256": table.content_sha256,
    }
