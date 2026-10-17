"""Tests fuer das Dokumentformat (``.qlx``, :mod:`ql_editor.document`).

Ein Dokument ist JSON und enthaelt nur, was zum Etikett gehoert: Band- und
Designwerte plus die Canvas-Objekte. Adresse, Druckoptionen und Fenstergroesse
sind Sache des Rechners - das prueft auch der GUI-Test.
"""

from __future__ import annotations

import json

import pytest

from ql_editor import document

MEDIA = {"model": "QL-820NWB", "label": "29", "orientation": "across"}
ITEMS = [{"kind": "text", "text": "Hallo"}, {"kind": "qr", "data": "https://x"}]


def test_round_trip(tmp_path):
    """Schreiben und Lesen geben dasselbe zurueck."""
    path = tmp_path / "design.qlx"
    document.save(path, document.build(MEDIA, ITEMS))

    data = document.load(path)

    assert data["format"] == document.DOCUMENT_FORMAT
    assert data["media"] == MEDIA
    assert data["items"] == ITEMS


def test_unknown_keys_survive(tmp_path):
    """Was eine spaetere Fassung schreibt, geht beim Bearbeiten nicht verloren."""
    path = tmp_path / "design.qlx"
    data = document.build(MEDIA, ITEMS)
    data["future"] = {"something": True}
    document.save(path, data)

    assert document.load(path)["future"] == {"something": True}


def test_missing_media_is_empty_not_fatal(tmp_path):
    """Ein Dokument ohne Bandwerte ist lesbar - es hat eben keine."""
    path = tmp_path / "design.qlx"
    document.save(path, {"format": document.DOCUMENT_FORMAT, "items": []})

    assert document.load(path)["media"] == {}


def test_the_file_is_human_readable(tmp_path):
    """JSON mit Einrueckung - diffbar, kein Binaerformat."""
    path = tmp_path / "design.qlx"
    document.save(path, document.build(MEDIA, ITEMS))

    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert '"QL-820NWB"' in text
    assert json.loads(text)["items"] == ITEMS


def test_missing_file(tmp_path):
    with pytest.raises(document.DocumentError):
        document.load(tmp_path / "gibtsnicht.qlx")


def test_broken_json(tmp_path):
    path = tmp_path / "kaputt.qlx"
    path.write_text("{ das ist kein json", encoding="utf-8")

    with pytest.raises(document.DocumentError):
        document.load(path)


def test_wrong_format_number(tmp_path):
    """Eine neuere Fassung soll man nicht halb oeffnen."""
    path = tmp_path / "neu.qlx"
    document.save(path, {"format": document.DOCUMENT_FORMAT + 1, "items": []})

    with pytest.raises(document.DocumentError):
        document.load(path)


def test_items_must_be_a_list(tmp_path):
    path = tmp_path / "halb.qlx"
    document.save(path, {"format": document.DOCUMENT_FORMAT, "items": {}})

    with pytest.raises(document.DocumentError):
        document.load(path)


def test_not_a_dict(tmp_path):
    path = tmp_path / "liste.qlx"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(document.DocumentError):
        document.load(path)


def test_save_error_is_reported(tmp_path):
    """Unschreibbarer Ort: klarer Fehler statt Absturz."""
    with pytest.raises(document.DocumentError):
        document.save(tmp_path / "nicht" / "da" / "design.qlx", document.build({}, []))
