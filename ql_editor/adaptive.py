"""Seiten untereinander, wenn Platz ist - sonst als Reiter.

Ein Seitenpaar (z. B. "Objekt" und "Drucken" im rechten Panel) steht untereinander,
solange die Hoehe fuer beide Seiten reicht. Wird es knapp, wechselt dieselbe
Seite in einen Reiter. Die Seiten selbst bleiben unveraendert - sie wandern nur
in einen anderen Behaelter.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QSplitter, QTabWidget, QVBoxLayout, QWidget

STACKED = "stacked"
TABS = "tabs"
#: Reserve (Pixel) zwischen den Seiten im Stapel.
SPACING_PX = 24


class AdaptivePages(QWidget):
    """Mehrere Seiten: untereinander oder als Reiter, je nach Hoehe.

    ``pages`` sind ``(Titel, Widget, Hoehe)``-Tripel. Die Hoehe ist eine Funktion,
    die die gewuenschte Hoehe der Seite liefert - so bleibt sie aktuell, wenn sich
    der Inhalt aendert.
    """

    def __init__(
        self,
        pages: list[tuple[str, QWidget, Callable[[], int]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pages = pages
        self._mode = ""
        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.setChildrenCollapsible(False)
        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._apply_mode(STACKED)

    # ------------------------------------------------------------ Abfragen --
    @property
    def mode(self) -> str:
        """Aktuelle Darstellung: :data:`STACKED` oder :data:`TABS`."""
        return self._mode

    def page(self, index: int) -> QWidget:
        """Das Widget der Seite ``index`` (unabhaengig von der Darstellung)."""
        return self._pages[index][1]

    def show_page(self, index: int) -> None:
        """Seite nach vorn holen: im Reiter-Modus den Reiter wechseln.

        Im Stapel-Modus sind alle Seiten ohnehin sichtbar - dann passiert nichts.
        """
        if self._mode == TABS:
            self._tabs.setCurrentIndex(index)

    def needed_height(self) -> int:
        """Hoehe, die alle Seiten untereinander brauchen."""
        # Etwas Reserve fuer Trennleisten und Rahmen der Bereiche.
        return sum(height() for _title, _widget, height in self._pages) + SPACING_PX

    # ----------------------------------------------------------- Umschalten --
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_mode(STACKED if self.height() >= self.needed_height() else TABS)

    def set_mode(self, mode: str) -> None:
        """Darstellung erzwingen (Tests, Einstellungen)."""
        self._apply_mode(mode)

    def _apply_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        # Seiten aus dem alten Behaelter loesen, dann in den neuen einhaengen.
        for _title, widget, _height in self._pages:
            widget.setParent(None)
        for child in (self._splitter, self._tabs):
            self._layout.removeWidget(child)
            child.hide()
        if mode == STACKED:
            self._splitter.show()
            self._layout.addWidget(self._splitter)
            for _title, widget, height in self._pages:
                # Jede Seite behaelt ihre Hoehe - gequetscht wird nur der Rest.
                widget.setMinimumHeight(height())
                self._splitter.addWidget(widget)
                # setParent(None) hat die Seite versteckt; der Splitter zeigt sie nicht von selbst wieder.
                widget.show()
            self._splitter.setStretchFactor(0, 1)
            self._splitter.setStretchFactor(1, 0)
        else:
            self._tabs.show()
            self._layout.addWidget(self._tabs)
            for title, widget, _height in self._pages:
                widget.setMinimumHeight(0)
                self._tabs.addTab(widget, title)
