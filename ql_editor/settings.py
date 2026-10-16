"""Persistente Einstellungen via ``QSettings``.

Gespeichert werden nur Nutzerpraeferenzen (Druckeradresse, Modell, zuletzt
gewaehltes Band, Fenstergeometrie). Der Drucker wird **nie** hartcodiert -
der Default steht als Konstante in :mod:`ql_editor.printer`.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from .media import DEFAULT_MODEL
from .preview import DEFAULT_THRESHOLD
from .printer import DEFAULT_ADDRESS, QUALITY_MAXIMUM

_ORG = "QLInux"
_APP = "QLInux"


class AppSettings:
    """Duenne, typisierte Huelle um ``QSettings``.

    ``settings`` laesst sich injizieren (Tests nutzen eine temporaere INI-Datei
    und beruehren so die echten Nutzer-Einstellungen nicht).
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(_ORG, _APP)

    # -- Rohzugriff ---------------------------------------------------------
    def value(self, key: str, default=None):
        return self._settings.value(key, default)

    def set_value(self, key: str, value) -> None:
        self._settings.setValue(key, value)

    def sync(self) -> None:
        self._settings.sync()

    # -- Drucker ------------------------------------------------------------
    @property
    def address(self) -> str:
        return str(self.value("printer/address", DEFAULT_ADDRESS))

    @address.setter
    def address(self, value: str) -> None:
        self.set_value("printer/address", value)

    @property
    def model(self) -> str:
        return str(self.value("printer/model", DEFAULT_MODEL))

    @model.setter
    def model(self, value: str) -> None:
        self.set_value("printer/model", value)

    @property
    def last_label(self) -> str | None:
        value = self.value("media/last_label", None)
        return str(value) if value else None

    @last_label.setter
    def last_label(self, value: str) -> None:
        self.set_value("media/last_label", value)

    @property
    def image_dir(self) -> str:
        return str(self.value("files/image_dir", ""))

    @image_dir.setter
    def image_dir(self, value: str) -> None:
        self.set_value("files/image_dir", value)

    # -- Druckoptionen ------------------------------------------------------
    @staticmethod
    def _as_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @property
    def threshold(self) -> int:
        """Schwelle in Prozent (brother_ql ``-t``), Default siehe Preview."""
        return self._as_int(self.value("print/threshold", None), DEFAULT_THRESHOLD)

    @threshold.setter
    def threshold(self, value: int) -> None:
        self.set_value("print/threshold", int(value))

    @property
    def dither(self) -> bool:
        return self._as_bool(self.value("print/dither", None), False)

    @dither.setter
    def dither(self, value: bool) -> None:
        self.set_value("print/dither", bool(value))

    @property
    def print_quality(self) -> str:
        """Gewaehlte Druckqualitaet (Schluessel aus :mod:`ql_editor.printer`).

        Ohne gespeicherte Wahl ist die **maximale** Stufe voreingestellt - die
        Oberflaeche begrenzt sie auf das, was das gewaehlte Modell kann. Aeltere
        Versionen kannten nur ein HQ-Haekchen; das wird einmalig uebersetzt,
        damit bestehende Einstellungen nicht verloren gehen.
        """
        value = self.value("print/quality", None)
        if value is not None:
            return str(value)
        legacy = self.value("print/hq", None)
        if legacy is None:
            return QUALITY_MAXIMUM.key
        return "high" if self._as_bool(legacy, True) else "standard"

    @print_quality.setter
    def print_quality(self, value: str) -> None:
        self.set_value("print/quality", str(value))

    @property
    def cut(self) -> bool:
        return self._as_bool(self.value("print/cut", None), True)

    @cut.setter
    def cut(self, value: bool) -> None:
        self.set_value("print/cut", bool(value))

    # -- Fenster ------------------------------------------------------------
    def save_geometry(self, geometry: QByteArray) -> None:
        self.set_value("window/geometry", geometry)

    def restore_geometry(self) -> QByteArray | None:
        value = self.value("window/geometry", None)
        return value if isinstance(value, QByteArray) else None

    # -- Seitenpanels -------------------------------------------------------
    @staticmethod
    def _as_bool(value, default: bool = True) -> bool:
        """QSettings liefert Booleans je nach Plattform/Backend auch als Text."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def panel_left_visible(self) -> bool:
        return self._as_bool(self.value("view/panel_left", None), True)

    @panel_left_visible.setter
    def panel_left_visible(self, value: bool) -> None:
        self.set_value("view/panel_left", bool(value))

    @property
    def panel_right_visible(self) -> bool:
        return self._as_bool(self.value("view/panel_right", None), True)

    @panel_right_visible.setter
    def panel_right_visible(self, value: bool) -> None:
        self.set_value("view/panel_right", bool(value))


__all__ = ["AppSettings"]
