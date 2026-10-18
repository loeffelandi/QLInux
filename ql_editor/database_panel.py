"""Unteres Datenbank-Panel: Tabellenzeile steuert Live-Merge (D13/D15).

M2: Grid + Dateiname + Record-Selektion. Verbinden/Trennen-Dialoge und
Drag-Binding folgen in spaeteren Meilensteinen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .csv_source import CsvTable
from .i18n import tr
from .merge import clamp_record_index


class DatabasePanel(QWidget):
    """CSV-Tabelle unter dem Canvas; Zeilenklick setzt ``current_record``."""

    #: Nutzer waehlte eine Tabellenzeile (0-basiert).
    record_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table_data: CsvTable | None = None
        self._updating = False

        self._title = QLabel(tr("Datenbank"))
        self._title.setObjectName("database_panel_title")
        self._file_label = QLabel(tr("Keine CSV verbunden"))
        self._file_label.setObjectName("database_panel_file")
        self._file_label.setWordWrap(True)
        self._hint = QLabel(
            tr(
                "Zeile wählen = Live-Vorschau. "
                "Spaltenköpfe später per Drag auf Text/Barcode/QR binden."
            )
        )
        self._hint.setObjectName("database_panel_hint")
        self._hint.setWordWrap(True)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._file_label, 1)

        self._grid = QTableWidget(0, 0, self)
        self._grid.setObjectName("database_panel_grid")
        self._grid.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._grid.setAlternatingRowColors(True)
        self._grid.verticalHeader().setVisible(False)
        self._grid.horizontalHeader().setStretchLastSection(True)
        self._grid.itemSelectionChanged.connect(self._on_selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self._hint)
        layout.addWidget(self._grid, 1)

        self.setMinimumHeight(120)
        self.setMaximumHeight(220)
        self.clear()

    @property
    def csv_table(self) -> CsvTable | None:
        return self._table_data

    def clear(self) -> None:
        """Keine CSV: Grid leeren und Hinweis zeigen."""
        self._table_data = None
        self._updating = True
        try:
            self._grid.clear()
            self._grid.setRowCount(0)
            self._grid.setColumnCount(0)
        finally:
            self._updating = False
        self._file_label.setText(tr("Keine CSV verbunden"))
        self.setVisible(False)

    def set_table(
        self,
        table: CsvTable | None,
        *,
        current_record: int = 0,
        display_name: str | None = None,
    ) -> None:
        """Tabelle laden und Zeile ``current_record`` selektieren."""
        if table is None or not table.fields:
            self.clear()
            return
        self._table_data = table
        name = display_name
        if not name and table.path is not None:
            name = Path(table.path).name
        self._file_label.setText(name or tr("CSV"))
        self._updating = True
        try:
            self._grid.clear()
            fields = list(table.fields)
            self._grid.setColumnCount(len(fields))
            self._grid.setHorizontalHeaderLabels(fields)
            self._grid.setRowCount(len(table.records))
            for row_index, record in enumerate(table.records):
                for col_index, field in enumerate(fields):
                    cell = QTableWidgetItem(str(record.get(field, "")))
                    cell.setFlags(
                        Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                    )
                    self._grid.setItem(row_index, col_index, cell)
            index = clamp_record_index(current_record, len(table.records))
            if table.records:
                self._grid.selectRow(index)
                self._grid.scrollToItem(self._grid.item(index, 0))
        finally:
            self._updating = False
        self.setVisible(True)

    def set_current_record(self, index: int) -> None:
        """Selektion setzen, ohne ``record_selected`` auszuloesen."""
        if self._table_data is None or not self._table_data.records:
            return
        index = clamp_record_index(index, len(self._table_data.records))
        self._updating = True
        try:
            self._grid.selectRow(index)
            item = self._grid.item(index, 0)
            if item is not None:
                self._grid.scrollToItem(item)
        finally:
            self._updating = False

    def current_record(self) -> int:
        """Aktuell selektierte Zeile (0-basiert), oder 0."""
        rows = self._grid.selectionModel().selectedRows()
        if not rows:
            return 0
        return int(rows[0].row())

    def _on_selection_changed(self) -> None:
        if self._updating or self._table_data is None:
            return
        rows = self._grid.selectionModel().selectedRows()
        if not rows:
            return
        self.record_selected.emit(int(rows[0].row()))


__all__ = ["DatabasePanel"]
