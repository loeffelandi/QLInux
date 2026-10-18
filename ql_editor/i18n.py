"""Zweisprachige Oberflaeche (Deutsch/Englisch).

Deutsch ist die Quellsprache: der deutsche Text ist der Schluessel. Fehlt eine
Uebersetzung, bleibt der deutsche Text stehen - es bricht also nichts, wenn
mal eine Zeile fehlt. Die englischen Texte stehen in
:mod:`ql_editor.translations`.

Bewusst ohne Qt: dieses Modul kennt nur Texte, kein Fenster. Die Oberflaeche
ruft :func:`tr` beim Aufbau; beim Sprachwechsel wird sie neu aufgebaut
(:meth:`ql_editor.app.MainWindow.switch_language`), damit auch jede
Formularbeschriftung mitkommt.

Platzhalter werden wie in :meth:`str.format` geschrieben (``{address}``) und
muessen in der Uebersetzung erhalten bleiben - ein Test prueft das.
"""

from __future__ import annotations

from .translations import EN

#: Verfuegbare Sprachen, in der Reihenfolge der Anzeige.
LANGUAGES = ("de", "en")

#: Quellsprache (und Rueckfall, wenn nichts anderes gesetzt ist).
DEFAULT_LANGUAGE = "de"

_TRANSLATIONS: dict[str, dict[str, str]] = {"en": EN}

_language = DEFAULT_LANGUAGE


def language() -> str:
    """Aktuell eingestellte Sprache (``"de"`` oder ``"en"``)."""
    return _language


def set_language(code: str) -> str:
    """Sprache setzen. Unbekannte Werte fallen auf die Quellsprache zurueck."""
    global _language
    _language = code if code in LANGUAGES else DEFAULT_LANGUAGE
    return _language


def language_name(code: str) -> str:
    """Sprache in ihrer eigenen Schreibweise - fuer die Auswahl im Menue."""
    return {"de": "Deutsch", "en": "English"}.get(code, code)


def tr(text: str) -> str:
    """Text in der aktuellen Sprache.

    ``text`` ist der deutsche Originaltext; gibt es keine Uebersetzung, kommt
    genau dieser zurueck.
    """
    if _language == DEFAULT_LANGUAGE:
        return text
    return _TRANSLATIONS.get(_language, {}).get(text, text)


def paste_label() -> str:
    """Einfügen aus der Zwischenablage.

    Der gleiche deutsche Wortlaut ist die Gruppe „Einfügen" und heißt dort
    auf Englisch Insert. Deshalb nicht über :func:`tr`.
    """
    return "Paste" if _language == "en" else "Einfügen"


def paste_hint() -> str:
    """Kurzbefehle neben dem Einfügen-Befehl."""
    if _language == "en":
        return "Paste (Ctrl+V)"
    return "Einfügen (Strg+V)"


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "language",
    "language_name",
    "paste_hint",
    "paste_label",
    "set_language",
    "tr",
]
