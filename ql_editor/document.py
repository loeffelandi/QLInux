"""Etikett-Designs speichern und oeffnen.

Ein Dokument ist JSON - lesbar, diffbar und ohne Ueberraschungen. Es enthaelt
**nur** die Objekte des Canvas und die Band-/Designwerte
(:meth:`ql_editor.media_panel.MediaPanel.media_state`) plus eine Formatnummer.
Ab Format 2 zusaetzlich optional ``data_source`` (CSV-Pfad, kein Einbetten)
und ``serial`` (Serienparameter, Default ausgeschaltet). Bewusst **nicht**
drin: Druckeradresse, Druckoptionen, Fenstergroesse - das sind Einstellungen
des Rechners, nicht des Etiketts. Ein geoeffnetes Design stellt also niemandem
den Drucker um.

Suffix ist ``.qlx`` ("QLinux eXchange"). Die Formatnummer erlaubt es, spaeter
etwas hinzuzufuegen, ohne alte Dateien zu zerstoeren: gelesen wird nur, was
die Nummer kennt. Format 1 bleibt lesbar (D9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import APP_NAME, __version__
from .i18n import tr

#: Endung der Designdateien.
DOCUMENT_SUFFIX = ".qlx"

#: Formatnummer dieses Schreibers. Erhoehen, wenn sich das Format aendert.
DOCUMENT_FORMAT = 2

#: Beim Lesen akzeptierte Formatnummern (D9: Format 1 bleibt lesbar).
SUPPORTED_FORMATS = frozenset({1, 2})

#: Default-Serie in Format-2-Dokumenten (Engine/UI folgen in spaeteren M).
DEFAULT_SERIAL: dict[str, Any] = {
    "enabled": False,
    "start": 1,
    "count": 1,
    "step": 1,
    "prefix": "",
    "suffix": "",
    "pad_width": 0,
}


class DocumentError(Exception):
    """Datei fehlt, ist kein QLInux-Dokument oder nicht lesbar."""


def build(
    media: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    data_source: Mapping[str, Any] | None = None,
    serial: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Dokumentdaten aus Band-/Designwerten und Canvas-Objekten bauen.

    Schreibt stets :data:`DOCUMENT_FORMAT` (aktuell 2). ``serial`` wird mit
    Defaults gefuellt; ``data_source`` nur gesetzt, wenn eine CSV verbunden ist.
    """
    data: dict[str, Any] = {
        "format": DOCUMENT_FORMAT,
        "app": APP_NAME,
        "version": __version__,
        "media": dict(media),
        "items": [dict(item) for item in items],
        "serial": dict(DEFAULT_SERIAL if serial is None else serial),
    }
    if data_source is not None:
        data["data_source"] = dict(data_source)
    return data


def save(path: str | Path, data: Mapping[str, Any]) -> None:
    """Design schreiben; Fehler kommen als :class:`DocumentError` zurueck."""
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        Path(path).write_text(text + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        raise DocumentError(
            tr("Konnte {path} nicht speichern: {error}").format(
                path=path, error=exc
            )
        ) from exc


def load(path: str | Path) -> dict[str, Any]:
    """Design lesen und pruefen.

    Geprueft wird nur, was zum Weiterarbeiten noetig ist (Formatnummer,
    Objektliste). Unbekannte Schluessel bleiben erhalten - so geht beim
    Bearbeiten nichts verloren, was eine spaetere Fassung geschrieben hat.
    Format 1 und 2 sind lesbar; neuere Nummern werden abgelehnt.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentError(
            tr("Konnte {path} nicht lesen: {error}").format(path=path, error=exc)
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DocumentError(
            tr("{path} ist kein QLInux-Dokument: {error}").format(
                path=path, error=exc
            )
        ) from exc
    if not isinstance(data, dict):
        raise DocumentError(
            tr("{path} ist kein QLInux-Dokument.").format(path=path)
        )
    format_number = data.get("format")
    if format_number not in SUPPORTED_FORMATS:
        raise DocumentError(
            tr(
                "Unbekanntes Format ({number}) - bitte mit einer neueren "
                "QLInux-Fassung öffnen."
            ).format(number=format_number)
        )
    if not isinstance(data.get("items"), list):
        raise DocumentError(
            tr("{path} ist kein QLInux-Dokument: Objektliste fehlt.").format(
                path=path
            )
        )
    if not isinstance(data.get("media"), dict):
        data["media"] = {}
    return data
