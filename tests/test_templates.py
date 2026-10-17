"""Tests fuer die Vorlagen (:mod:`ql_editor.templates`).

Die wichtigste Pruefung: **jede** eingebaute Vorlage muss sich laden lassen -
also gueltige Objekte enthalten und ein Dokument sein, wie „Speichern" es
schreibt. Ein Tippfehler in einem Objektfeld faellt hier auf, nicht erst beim
Benutzer.
"""

from __future__ import annotations

import pytest

from ql_editor import document, media, templates
from ql_editor.items import item_from_dict

# Objekte sind QGraphicsItems - dafuer braucht es eine QApplication.
pytestmark = pytest.mark.usefixtures("qapp")


def test_builtins_are_documents_that_load(tmp_path):
    """Jede Vorlage laesst sich schreiben, lesen und in Objekte umsetzen."""
    builtins = templates.builtins()
    assert builtins, "keine eingebauten Vorlagen"

    for name, data in builtins:
        path = tmp_path / f"{name}{document.DOCUMENT_SUFFIX}"
        document.save(path, data)
        loaded = document.load(path)

        assert loaded["items"], name
        assert loaded["media"]["label"] == templates.TEMPLATE_LABEL
        for raw in loaded["items"]:
            # Wirft KeyError/TypeError, wenn ein Feld fehlt oder falsch heisst.
            item = item_from_dict(raw)
            assert item is not None


def test_builtins_only_use_known_object_kinds():
    kinds = set(templates.TEMPLATE_KINDS)
    for name, data in templates.builtins():
        for raw in data["items"]:
            assert raw["type"] in kinds, (name, raw["type"])


def test_builtins_do_not_pin_a_printer_model():
    """Das Modell steht am Drucker - eine Vorlage darf es nicht setzen."""
    for _name, data in templates.builtins():
        assert "model" not in data["media"]


def test_builtins_use_endless_tape_and_automatic_length():
    """62 mm Endlosband + Auto-Laenge: passen auf jedes Endlosband."""
    for _name, data in templates.builtins():
        media_state = data["media"]
        assert media_state["auto_length"] is True
        assert media_state["orientation"] in {
            media.Orientation.ACROSS.value,
            media.Orientation.ALONG.value,
        }


def test_find_builtin_by_name():
    name, _data = templates.builtins()[0]

    assert templates.find_builtin(name) is not None
    assert templates.find_builtin("gibtsnicht") is None


def test_builtin_texts_follow_the_language():
    """Die Beispieltexte kommen in der Oberflaechensprache."""
    from ql_editor import i18n

    i18n.set_language("de")
    german = templates.builtins()
    i18n.set_language("en")
    english = templates.builtins()
    i18n.set_language(i18n.DEFAULT_LANGUAGE)

    assert [name for name, _ in german] != [name for name, _ in english]
    assert german[0][0] == "Adressetikett"
    assert english[0][0] == "Address label"


def test_user_templates_are_stored_in_the_config_dir(monkeypatch, tmp_path):
    """Eigene Vorlagen liegen unter Linux bei den Einstellungen (XDG_CONFIG_HOME)."""
    monkeypatch.setattr(templates, "IS_MAC", False)
    monkeypatch.setattr(templates, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(templates.TEMPLATE_DIR_ENV, raising=False)

    assert templates.user_dir() == tmp_path / "QLInux" / "templates"
    assert templates.list_user() == []


def test_user_dir_follows_the_platform(monkeypatch, tmp_path):
    """macOS und Windows legen Vorlagen neben die dortigen Einstellungen."""
    monkeypatch.delenv(templates.TEMPLATE_DIR_ENV, raising=False)

    monkeypatch.setattr(templates, "IS_WINDOWS", False)
    monkeypatch.setattr(templates, "IS_MAC", True)
    expected_mac = (
        tmp_path / "Library" / "Application Support" / "QLInux" / "templates"
    )
    monkeypatch.setattr(templates.Path, "home", staticmethod(lambda: tmp_path))
    assert templates.user_dir() == expected_mac

    monkeypatch.setattr(templates, "IS_MAC", False)
    monkeypatch.setattr(templates, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert templates.user_dir() == tmp_path / "Roaming" / "QLInux" / "templates"


def test_saving_and_listing_own_templates(monkeypatch, tmp_path):
    monkeypatch.setenv(templates.TEMPLATE_DIR_ENV, str(tmp_path))
    data = templates.builtins()[0][1]

    path = templates.save_user("Mein Etikett", data)

    assert path == tmp_path / f"Mein Etikett{document.DOCUMENT_SUFFIX}"
    assert path.exists()
    assert templates.list_user() == [path]
    # Auch von Hand hineingelegte Vorlagen werden gefunden - und sortiert.
    (tmp_path / f"aaa{document.DOCUMENT_SUFFIX}").write_text("{}", encoding="utf-8")
    assert [p.name for p in templates.list_user()] == [
        f"aaa{document.DOCUMENT_SUFFIX}",
        path.name,
    ]


def test_template_names_cannot_escape_the_directory(monkeypatch, tmp_path):
    """Ein Name aus dem Eingabefeld bleibt ein Dateiname, kein Pfad."""
    monkeypatch.setenv(templates.TEMPLATE_DIR_ENV, str(tmp_path))

    path = templates.save_user("../../boese", templates.builtins()[0][1])

    assert path.parent == tmp_path
    assert "/" not in path.name


def test_template_suffix_is_not_doubled(monkeypatch, tmp_path):
    monkeypatch.setenv(templates.TEMPLATE_DIR_ENV, str(tmp_path))

    path = templates.save_user(
        f"Kabel{document.DOCUMENT_SUFFIX}", templates.builtins()[0][1]
    )

    assert path.name == f"Kabel{document.DOCUMENT_SUFFIX}"


def test_empty_template_name_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv(templates.TEMPLATE_DIR_ENV, str(tmp_path))

    with pytest.raises(document.DocumentError):
        templates.save_user("   ", templates.builtins()[0][1])
