"""Druckauftrag-Verlauf der aktuellen Sitzung.

Netzwerkdruck (TCP 9100) liefert keine Rueckmeldung - ``outcome == "sent"``
heisst nur "an den Drucker geschickt". Nur USB (pyusb/linux_kernel) bestaetigt
den Druck (``printed``) oder meldet einen Fehler (``error``). Beim Netzwerk
meldet SNMP eine Stoerung (``error``); schweigt der Drucker danach, bleibt es
bei ``unconfirmed`` - gesendet, aber ohne Statusantwort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .i18n import tr
from .theme import error_text_color


@dataclass(frozen=True)
class PrintJob:
    started: datetime
    label: str
    copies: int
    model: str
    address: str
    outcome: str  # "printed", "sent", "unconfirmed", "error" oder "failed" (lokal)

    @property
    def is_error(self) -> bool:
        return self.outcome in ("error", "failed")

    def status_text(self) -> str:
        if self.outcome == "printed":
            return tr("Gedruckt")
        if self.outcome == "sent":
            return tr("An Drucker gesendet")
        if self.outcome == "saved":
            return tr("PDF gespeichert")
        if self.outcome == "unconfirmed":
            return tr("Gesendet, keine Statusantwort")
        if self.outcome == "error":
            return tr("Drucker meldet einen Fehler")
        return tr("Nicht gesendet")


def history_headers() -> list[str]:
    return [tr("Zeit"), tr("Etikett"), tr("Kopien"), tr("Drucker"), tr("Status")]


def configure_history_table(table: QTableWidget) -> None:
    """Tabelle fuer den Sitzungsverlauf: nur lesen, neueste Zeile oben."""
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(96)


def fill_history_table(table: QTableWidget, jobs: list[PrintJob]) -> None:
    """Verlauf neu schreiben, neueste Aufträge zuerst."""
    headers = history_headers()
    table.clearContents()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(jobs))
    for row, job in enumerate(reversed(jobs)):
        cells = (
            job.started.strftime("%H:%M:%S"),
            job.label,
            str(job.copies),
            f"{job.model} · {job.address}",
            job.status_text(),
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if column == 4 and job.is_error:
                item.setForeground(error_text_color())
            table.setItem(row, column, item)


def make_history_table(parent=None) -> QTableWidget:
    table = QTableWidget(parent)
    configure_history_table(table)
    fill_history_table(table, [])
    return table


class PrintHistoryDialog(QDialog):
    """Liste aller Druckaufträge seit Programmstart, neueste zuerst."""

    def __init__(self, jobs: list[PrintJob], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Druckverlauf"))
        self.resize(640, 320)

        table = make_history_table(self)
        fill_history_table(table, jobs)

        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(table)
        layout.addLayout(buttons)
