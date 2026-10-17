"""Tests fuer die Zweisprachigkeit (:mod:`ql_editor.i18n`).

Wichtigster Test ist die Vollstaendigkeit: zu jedem ``tr(...)`` im Quelltext
muss es einen englischen Text geben - und die Platzhalter muessen gleich
bleiben. So kann keine Zeile "vergessen" werden.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ql_editor import i18n
from ql_editor.i18n import tr
from ql_editor.translations import EN

PACKAGE = Path(i18n.__file__).resolve().parent
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)[!:}]", re.IGNORECASE)


def source_keys() -> set[str]:
    """Alle Texte, die im Quelltext durch ``tr`` laufen."""
    keys: set[str] = set()
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "tr":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    keys.add(argument.value)
    return keys


def placeholders(text: str) -> set[str]:
    return {match.group(1) for match in PLACEHOLDER.finditer(text)}


def test_every_used_text_is_translated():
    missing = sorted(source_keys() - set(EN))
    assert not missing, f"Ohne englischen Text: {missing}"


def test_no_orphan_translations():
    unused = sorted(set(EN) - source_keys())
    assert not unused, f"Uebersetzung ohne Text im Quelltext: {unused}"


def test_placeholders_match():
    broken = []
    for german_text, english_text in EN.items():
        if placeholders(german_text) != placeholders(english_text):
            broken.append((german_text, english_text))
    assert not broken, f"Platzhalter weichen ab: {broken}"


def test_german_is_the_source_language():
    assert i18n.language() == "de"
    assert tr("Drucker") == "Drucker"


def test_english_translates_and_falls_back():
    i18n.set_language("en")
    assert tr("Drucker") == "Printer"
    # Unbekannter Text bleibt deutsch - es bricht nichts.
    assert tr("Gibt es nicht") == "Gibt es nicht"


def test_unknown_language_falls_back_to_source():
    assert i18n.set_language("fr") == "de"
    assert i18n.language() == "de"


def test_language_name_is_not_translated():
    assert i18n.language_name("de") == "Deutsch"
    assert i18n.language_name("en") == "English"
    assert i18n.LANGUAGES == ("de", "en")


def test_counted_message_is_translated():
    """Die Zaehlmeldung nennt den Plural - auch im Englischen."""
    assert EN["{count} USB-Drucker gefunden"] == "{count} USB printers found"
    i18n.set_language("en")
    assert tr("{count} USB-Drucker gefunden").format(count=3) == "3 USB printers found"
