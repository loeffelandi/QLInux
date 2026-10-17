"""Vorlagen: fertige Etiketten und eigene zum Wiederverwenden.

Eine Vorlage **ist** ein Dokument (:mod:`ql_editor.document`) - dieselbe Datei,
die „Speichern" schreibt. Damit gibt es nur *ein* Format, und eine selbst
gebaute Vorlage ist automatisch ein speicherbares Etikett (und umgekehrt).

Die eingebauten Vorlagen entstehen im Code: sie stehen damit auch in einem
frischen AppImage zur Verfuegung und sind uebersetzbar (die Beispieltexte
kommen in der Oberflaechensprache). Eigene Vorlagen liegen als ``.qlx`` unter
``~/.config/QLInux/templates/``.

Alle eingebauten Vorlagen nehmen **62 mm Endlosband** und automatische Laenge -
so passen sie auf jedes Endlosband und der Benutzer wechselt hoechstens das
Band. Das Modell wird bewusst nicht gesetzt: es steht am Drucker, nicht in der
Vorlage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import APP_NAME, media
from .document import DOCUMENT_SUFFIX, DocumentError, build
from .i18n import tr

#: Umgebungsvariable, die das Vorlagenverzeichnis uebersteuert (Tests).
TEMPLATE_DIR_ENV = "QLINUX_TEMPLATE_DIR"

#: Band der eingebauten Vorlagen: 62 mm Endlosband (breiteste QL-Breite).
TEMPLATE_LABEL = "62"

#: Rastermass der Beispieltexte (Druckpunkte bei 300 dpi).
SMALL = 40          # ca. 3,4 mm
BODY = 56           # ca. 4,7 mm
HEADLINE = 96       # ca. 8,1 mm
HUGE = 190          # ca. 16 mm


def user_dir() -> Path:
    """Verzeichnis der eigenen Vorlagen.

    Orientiert sich an ``XDG_CONFIG_HOME`` - dieselbe Ecke, in der auch die
    Einstellungen liegen (``~/.config/QLInux``).
    """
    override = os.environ.get(TEMPLATE_DIR_ENV)
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME / "templates"


def list_user() -> list[Path]:
    """Eigene Vorlagen, nach Namen sortiert (auch die von Hand hineingelegten)."""
    directory = user_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{DOCUMENT_SUFFIX}"), key=lambda p: p.name.lower())


def save_user(name: str, data: dict[str, Any]) -> Path:
    """Eigene Vorlage schreiben; der Name wird zu einem Dateinamen.

    Pfadtrenner und Endung werden entfernt bzw. ergaenzt - ein Name aus dem
    Eingabefeld darf nie ausserhalb des Vorlagenordners landen.
    """
    clean = " ".join(name.split()).replace("/", "-").replace("\\", "-").strip(".")
    clean = clean.removesuffix(DOCUMENT_SUFFIX)
    if not clean:
        raise DocumentError(tr("Vorlage braucht einen Namen."))
    directory = user_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{clean}{DOCUMENT_SUFFIX}"
    from . import document  # lokal: haelt den Importzyklus flach

    document.save(path, data)
    return path


def builtins() -> list[tuple[str, dict[str, Any]]]:
    """Eingebaute Vorlagen als ``(Name, Dokumentdaten)``.

    Eine Funktion, keine Konstante: die Beispieltexte sollen in der gerade
    eingestellten Oberflaechensprache entstehen.
    """
    return [
        (tr("Adressetikett"), _address_label()),
        (tr("Paketmarke"), _parcel_label()),
        (tr("Kabel"), _cable_label()),
        (tr("Ordnerrücken"), _folder_spine()),
        (tr("Preisschild"), _price_tag()),
        (tr("WLAN-QR"), _wifi_qr()),
        (tr("Inventar"), _inventory_label()),
    ]


def find_builtin(name: str) -> dict[str, Any] | None:
    """Eingebaute Vorlage nach Namen - ``None``, wenn es sie nicht (mehr) gibt."""
    for template_name, data in builtins():
        if template_name == name:
            return data
    return None


# --------------------------------------------------------------- Bausteine --
def _base_media(**overrides: Any) -> dict[str, Any]:
    """Band-/Designwerte einer Vorlage (62 mm Endlosband, automatische Laenge)."""
    values: dict[str, Any] = {
        "label": TEMPLATE_LABEL,
        "color": "black",
        "auto_length": True,
        "length_mm": 40.0,
        "length_mode": media.LengthMode.FINISHED.value,
        "margins": {"left": 3.0, "right": 3.0, "top": 3.0, "bottom": 3.0},
        "orientation": media.Orientation.ACROSS.value,
    }
    values.update(overrides)
    return values


def _text(
    text: str,
    x: float,
    y: float,
    *,
    size: int = BODY,
    bold: bool = False,
    width: float = -1.0,
    z: float = 0.0,
) -> dict[str, Any]:
    """Ein Textobjekt (Druckpunkte; ``width=-1`` = kein Umbruch)."""
    return {
        "type": "text",
        "x": float(x),
        "y": float(y),
        "rotation": 0.0,
        "z": float(z),
        "text": text,
        "font_family": "Sans",
        "font_pixel_size": int(size),
        "bold": bool(bold),
        "italic": False,
        "color": "black",
        "text_width": float(width),
    }


def _rect(
    x: float, y: float, w: float, h: float, *, width: int = 3, z: float = -1.0
) -> dict[str, Any]:
    return {
        "type": "rect",
        "x": float(x),
        "y": float(y),
        "rotation": 0.0,
        "z": float(z),
        "w": float(w),
        "h": float(h),
        "width_px": int(width),
        "filled": False,
    }


def _line(x1: float, y1: float, x2: float, y2: float, *, width: int = 4) -> dict[str, Any]:
    return {
        "type": "line",
        "x": 0.0,
        "y": 0.0,
        "rotation": 0.0,
        "z": 0.0,
        "x1": float(x1),
        "y1": float(y1),
        "x2": float(x2),
        "y2": float(y2),
        "width_px": int(width),
    }


def _qr(data: str, x: float, y: float, *, size: int = 200) -> dict[str, Any]:
    return {
        "type": "qr",
        "x": float(x),
        "y": float(y),
        "rotation": 0.0,
        "z": 0.0,
        "data": data,
        "size_dots": int(size),
    }


def _barcode(
    value: str, x: float, y: float, *, height: int = 100, show_text: bool = True
) -> dict[str, Any]:
    return {
        "type": "barcode",
        "x": float(x),
        "y": float(y),
        "rotation": 0.0,
        "z": 0.0,
        "value": value,
        "symbology": "code128",
        "show_text": bool(show_text),
        "height_dots": int(height),
    }


# ----------------------------------------------------------------- Vorlagen --
def _address_label() -> dict[str, Any]:
    """Absender klein, Empfaenger gross - das klassische Adressetikett."""
    return build(
        _base_media(margins={"left": 6.0, "right": 3.0, "top": 4.0, "bottom": 4.0}),
        [
            _text(tr("Absender: Firma Muster, Musterweg 1"), 30, 30, size=SMALL),
            _line(30, 80, 640, 80, width=3),
            _text(tr("Empfänger"), 30, 110, size=BODY, bold=True),
            _text(tr("Vorname Nachname"), 30, 190, size=HEADLINE),
            _text(tr("Straße 12"), 30, 300, size=BODY),
            _text(tr("12345 Stadt"), 30, 370, size=BODY),
        ],
    )


def _parcel_label() -> dict[str, Any]:
    """Paketmarke: Rahmen, grosses Ziel, Barcode."""
    return build(
        _base_media(margins={"left": 4.0, "right": 4.0, "top": 4.0, "bottom": 4.0}),
        [
            _rect(20, 20, 650, 300),
            _text(tr("An"), 40, 40, size=SMALL),
            _text(tr("Vorname Nachname"), 40, 80, size=BODY, bold=True),
            _text(tr("12345 Stadt, Straße 12"), 40, 170, size=SMALL),
            _barcode("1234567890", 40, 330, height=110),
        ],
    )


def _cable_label() -> dict[str, Any]:
    """Kabelkennzeichnung: einmal ums Kabel wickeln, gross lesbar."""
    return build(
        _base_media(margins={"left": 5.0, "right": 5.0, "top": 4.0, "bottom": 4.0}),
        [
            _rect(20, 20, 650, 220),
            _text(tr("Kabel 12"), 40, 60, size=HUGE, bold=True),
            _text(tr("Patchfeld A → Switch 3"), 40, 270, size=SMALL),
        ],
    )


def _folder_spine() -> dict[str, Any]:
    """Ordnerruecken: laengs des Bandes, damit der Text stehend passt."""
    return build(
        _base_media(
            orientation=media.Orientation.ALONG.value,
            margins={"left": 4.0, "right": 4.0, "top": 4.0, "bottom": 4.0},
        ),
        [
            _text(tr("Aktenzeichen 2026-01"), 30, 40, size=BODY, bold=True),
            _text(tr("Rechnungen"), 30, 130, size=BODY),
            _text(tr("bis 31.12.2026"), 30, 220, size=SMALL),
        ],
    )


def _price_tag() -> dict[str, Any]:
    """Preisschild: der Preis dominiert, alles andere ist Beiwerk."""
    return build(
        _base_media(margins={"left": 6.0, "right": 6.0, "top": 4.0, "bottom": 4.0}),
        [
            _text(tr("9,90 €"), 40, 40, size=HUGE, bold=True),
            _text(tr("inkl. MwSt."), 40, 280, size=SMALL),
            _line(40, 250, 400, 250, width=3),
        ],
    )


def _wifi_qr() -> dict[str, Any]:
    """WLAN-Zugang als QR-Code (die uebliche WIFI:-Syntax)."""
    return build(
        _base_media(),
        [
            _qr("WIFI:T:WPA;S:MeinWLAN;P:geheim;;", 40, 40, size=220),
            _text(tr("WLAN"), 300, 60, size=BODY, bold=True),
            _text(tr("MeinWLAN"), 300, 140, size=BODY),
            _text(tr("Passwort: geheim"), 300, 220, size=SMALL),
        ],
    )


def _inventory_label() -> dict[str, Any]:
    """Inventar: Nummer gross, Barcode zum Scannen."""
    return build(
        _base_media(margins={"left": 5.0, "right": 5.0, "top": 4.0, "bottom": 4.0}),
        [
            _text(tr("Inventar"), 30, 30, size=SMALL),
            _text("QL-0001", 30, 80, size=HEADLINE, bold=True),
            _barcode("QL-0001", 30, 220, height=120),
        ],
    )


#: Alles, was eine Vorlage liefern darf - fuer Tests und Doku.
TEMPLATE_KINDS: tuple[str, ...] = ("text", "rect", "line", "qr", "barcode")

__all__ = [
    "TEMPLATE_DIR_ENV",
    "TEMPLATE_KINDS",
    "TEMPLATE_LABEL",
    "builtins",
    "find_builtin",
    "list_user",
    "save_user",
    "user_dir",
]
