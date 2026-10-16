"""Persistente Einstellungen via ``QSettings``.

Gespeichert werden nur Nutzerpraeferenzen (Druckeradresse, Modell, zuletzt
gewaehltes Band, Fenstergeometrie). Der Drucker wird **nie** hartcodiert -
der Default steht als Konstante in :mod:`ql_editor.printer`.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from .media import DEFAULT_MODEL
from .printer import DEFAULT_ADDRESS

_ORG = "QLInux"
_APP = "QLInux"


class AppSettings:
    """Duenne, typisierte Huelle um ``QSettings``."""

    def __init__(self) -> None:
        self._settings = QSettings(_ORG, _APP)

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

    # -- Fenster ------------------------------------------------------------
    def save_geometry(self, geometry: QByteArray) -> None:
        self.set_value("window/geometry", geometry)

    def restore_geometry(self) -> QByteArray | None:
        value = self.value("window/geometry", None)
        return value if isinstance(value, QByteArray) else None


__all__ = ["AppSettings"]
