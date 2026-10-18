"""Druckauftrag-Verlauf der aktuellen Sitzung.

Netzwerkdruck (TCP 9100) liefert keine Rueckmeldung - ``outcome == "sent"``
heisst nur "an den Drucker geschickt". Nur USB (pyusb/linux_kernel) bestaetigt
den Druck (``printed``) oder meldet einen Fehler (``error``).
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


@dataclass(frozen=True)
class PrintJob:
    started: datetime
    label: str
    copies: int
    model: str
    address: str
    outcome: str  # "printed", "sent", "error" oder "failed" (lokaler Fehler)

    @property
    def is_error(self) -> bool:
        return self.outcome in ("error", "failed")

    def status_text(self) -> str:
        if self.outcome == "printed":
            return tr("Gedruckt")
        if self.outcome == "sent":
            return tr("An Drucker gesendet")
        if self.outcome == "error":
            return tr("Drucker meldet einen Fehler")
        return tr("Nicht gesendet")


class PrintHistoryDialog(QDialog):
    """Liste aller Druckaufträge seit Programmstart, neueste zuerst."""

    def __init__(self, jobs: list[PrintJob], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Druckverlauf"))
        self.resize(640, 320)

        headers = [tr("Zeit"), tr("Etikett"), tr("Kopien"), tr("Drucker"), tr("Status")]
        table = QTableWidget(len(jobs), len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for row, job in enumerate(reversed(jobs)):
            cells = (
                job.started.strftime("%H:%M:%S"),
                job.label,
                str(job.copies),
                f"{job.model} · {job.address}",
                job.status_text(),
            )
            for column, text in enumerate(cells):
                table.setItem(row, column, QTableWidgetItem(text))

        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(table)
        layout.addLayout(buttons)
