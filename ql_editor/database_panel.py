"""Unteres Datenbank-Panel (D13/D14/D15).

Grid, Dateiname, Verbinden/Andere/Trennen, Record-Zaehler und Banner.
Spaltenkoepfe (○) lassen sich auf den Canvas ziehen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .csv_source import CsvTable
from .i18n import tr
from .merge import clamp_record_index

#: MIME fuer den Spaltenkopf-Drag (D14). Kein Klartext, damit der Canvas
#: das nicht als frei fallenden Text anlegt.
DB_FIELD_MIME = "application/x-qlinux-db-field"

def field_mime(field: str) -> QMimeData:
    """``QMimeData`` mit dem Spaltennamen (UTF-8)."""
    mime = QMimeData()
    mime.setData(DB_FIELD_MIME, str(field).encode("utf-8"))
    return mime


def field_from_mime(mime) -> str | None:
    """Spaltenname aus einem Drag, oder ``None``."""
    if mime is None or not mime.hasFormat(DB_FIELD_MIME):
        return None
    raw = bytes(mime.data(DB_FIELD_MIME)).decode("utf-8").strip()
    return raw or None


class _FieldHeader(QHeaderView):
    """Horizontaler Kopf: Zug am Spaltennamen startet den Feld-Drag."""

    field_dragged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._origin: QPoint | None = None
        self.setSectionsClickable(True)
        self.setHighlightSections(True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        origin = self._origin
        if (
            origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - origin).manhattanLength()
            >= QApplication.startDragDistance()
            and not self._on_resize_grip(origin)
        ):
            column = self.logicalIndexAt(origin)
            self._origin = None
            if column >= 0:
                self.field_dragged.emit(column)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._origin = None
        super().mouseReleaseEvent(event)

    def _on_resize_grip(self, pos: QPoint) -> bool:
        index = self.logicalIndexAt(pos)
        if index < 0:
            return True
        left = self.sectionViewportPosition(index)
        width = self.sectionSize(index)
        edge = 6
        return pos.x() <= left + edge or pos.x() >= left + width - edge


class DatabasePanel(QWidget):
    """CSV-Tabelle unter dem Canvas; Zeilenklick setzt ``current_record``."""

    #: Nutzer waehlte eine Tabellenzeile (0-basiert).
    record_selected = Signal(int)
    #: CSV-Datei waehlen (noch keine Verbindung).
    connect_requested = Signal()
    #: Andere CSV waehlen (Verbindung ersetzen).
    replace_requested = Signal()
    #: Verbindung loesen; Snapshots bleiben.
    disconnect_requested = Signal()
    #: Serienparameter (Start, Anzahl, …) geaendert. ``enabled`` bleibt,
    #: wie es die App zuletzt gesetzt hat.
    serial_spec_changed = Signal(object)
    #: Checkbox an der aktuellen Auswahl: Serie anbinden oder loesen.
    serial_toggle_requested = Signal(bool)
    #: Undo-Klammer um eine Serien-Aenderung.
    serial_edit_begun = Signal()
    serial_edit_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table_data: CsvTable | None = None
        self._updating = False
        self._linked = False
        self._spec: dict = {
            "enabled": False,
            "start": 1,
            "count": 1,
            "step": 1,
            "prefix": "",
            "suffix": "",
            "pad_width": 0,
        }
        self._target_kind: str | None = None
        self._target_source: str | None = None

        self._toggle = QToolButton()
        self._toggle.setObjectName("database_panel_toggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setAutoRaise(True)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle.toggled.connect(self._on_expanded_toggled)

        self._title = QLabel(tr("Datenbank"))
        self._title.setObjectName("database_panel_title")
        self._file_label = QLabel(tr("Keine CSV verbunden"))
        self._file_label.setObjectName("database_panel_file")
        self._file_label.setWordWrap(False)
        self._counter = QLabel("")
        self._counter.setObjectName("database_panel_counter")

        self._connect = QPushButton(tr("Verbinden"))
        self._connect.setObjectName("database_panel_connect")
        self._other = QPushButton(tr("Andere…"))
        self._other.setObjectName("database_panel_other")
        self._disconnect = QPushButton(tr("Trennen"))
        self._disconnect.setObjectName("database_panel_disconnect")
        self._connect.clicked.connect(
            lambda _checked=False: self.connect_requested.emit()
        )
        self._other.clicked.connect(
            lambda _checked=False: self.replace_requested.emit()
        )
        self._disconnect.clicked.connect(
            lambda _checked=False: self.disconnect_requested.emit()
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._toggle)
        header.addWidget(self._title)
        header.addWidget(self._file_label, 1)
        header.addWidget(self._counter)
        header.addWidget(self._connect)
        header.addWidget(self._other)
        header.addWidget(self._disconnect)

        self._banner = QLabel("")
        self._banner.setObjectName("database_panel_banner")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            "background:#fff4d6; color:#6a4b00; padding:4px 6px;"
        )
        self._banner.hide()

        self._hint = QLabel(
            tr(
                "Text, Barcode oder QR auf das Etikett legen und den "
                "Spaltenkopf (○) darauf ziehen. Zeile wählen = Live-Vorschau."
            )
        )
        self._hint.setObjectName("database_panel_hint")
        self._hint.setWordWrap(True)

        self._grid = QTableWidget(0, 0, self)
        self._grid.setObjectName("database_panel_grid")
        self._header = _FieldHeader(self._grid)
        self._grid.setHorizontalHeader(self._header)
        self._header.field_dragged.connect(self._drag_field)
        self._grid.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._grid.setAlternatingRowColors(True)
        self._grid.verticalHeader().setVisible(False)
        self._grid.horizontalHeader().setStretchLastSection(True)
        self._grid.itemSelectionChanged.connect(self._on_selection_changed)

        self._body = QWidget()
        self._body.setObjectName("database_panel_body")
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        body.addWidget(self._banner)
        body.addWidget(self._hint)
        body.addWidget(self._build_serial())
        body.addWidget(self._grid, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self._body, 1)

        self._apply_expanded(False)
        self._serial.hide()
        self.clear()

    def _build_serial(self) -> QWidget:
        """Serie im Datenbank-Panel. Sichtbar nur bei geladener CSV."""
        box = QWidget()
        box.setObjectName("database_serial")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._serial_check = QCheckBox(tr("Serie"))
        self._serial_check.setObjectName("database_serial_enabled")
        self._serial_check.toggled.connect(self._on_serial_toggled)
        row.addWidget(self._serial_check)

        self._serial_start = self._serial_spin("database_serial_start", -1000000, 1000000)
        self._serial_count = self._serial_spin("database_serial_count", 1, 99)
        self._serial_step = self._serial_spin("database_serial_step", -1000000, 1000000)
        self._serial_pad = self._serial_spin("database_serial_pad", 0, 12)
        self._serial_pad.setToolTip(
            tr("Führende Nullen; 0 lässt die Zahl, wie sie ist.")
        )
        self._serial_prefix = self._serial_line("database_serial_prefix")
        self._serial_suffix = self._serial_line("database_serial_suffix")
        for label, widget in (
            (tr("Start"), self._serial_start),
            (tr("Anzahl"), self._serial_count),
            (tr("Schritt"), self._serial_step),
            (tr("Präfix"), self._serial_prefix),
            (tr("Suffix"), self._serial_suffix),
            (tr("Stellen"), self._serial_pad),
        ):
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)

        self._serial_note = QLabel(
            tr("Datenbankfeld und Serie schließen sich an diesem Objekt aus.")
        )
        self._serial_note.setObjectName("database_serial_exclusive")
        self._serial_note.setWordWrap(True)
        self._serial_note.hide()
        layout.addWidget(self._serial_note)
        self._serial = box
        return box

    def _serial_spin(self, name: str, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName(name)
        spin.setRange(low, high)
        spin.valueChanged.connect(self._on_serial_value)
        spin.editingFinished.connect(self._on_serial_edit_finished)
        return spin

    def _serial_line(self, name: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName(name)
        edit.setMaxLength(32)
        edit.textEdited.connect(lambda _text: self._on_serial_value())
        edit.editingFinished.connect(self._on_serial_edit_finished)
        return edit

    def set_serial_state(
        self,
        serial: dict | None,
        *,
        target_kind: str | None = None,
        target_source: str | None = None,
    ) -> None:
        """Serienfelder an das Dokument und die Auswahl binden.

        Ohne geladene CSV bleibt der Block versteckt. Ein Datenbank-Binding
        an der Auswahl sperrt die Felder (D4).
        """
        if serial:
            self._spec = dict(serial)
        self._target_kind = target_kind
        self._target_source = target_source
        visible = self._table_data is not None
        self._serial.setVisible(visible)
        if not visible:
            self._serial_note.hide()
            return
        locked = target_source == "database"
        serial_on = target_source == "serial"
        can_bind = target_kind in ("text", "qr", "barcode") and not locked
        self._updating = True
        try:
            self._serial_check.setChecked(serial_on)
            self._serial_start.setValue(self._clamp_int(self._spec.get("start"), 1, self._serial_start))
            self._serial_count.setValue(self._clamp_int(self._spec.get("count"), 1, self._serial_count))
            self._serial_step.setValue(self._clamp_int(self._spec.get("step"), 1, self._serial_step))
            self._serial_pad.setValue(
                self._clamp_int(self._spec.get("pad_width"), 0, self._serial_pad)
            )
            self._serial_prefix.setText(str(self._spec.get("prefix") or ""))
            self._serial_suffix.setText(str(self._spec.get("suffix") or ""))
        finally:
            self._updating = False
        self._serial_check.setEnabled(can_bind)
        fields_on = serial_on and not locked
        for widget in (
            self._serial_start,
            self._serial_count,
            self._serial_step,
            self._serial_pad,
            self._serial_prefix,
            self._serial_suffix,
        ):
            widget.setEnabled(fields_on)
        self._serial_note.setVisible(locked)

    @staticmethod
    def _clamp_int(value, default: int, spin: QSpinBox) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            number = default
        else:
            number = value
        return max(spin.minimum(), min(spin.maximum(), number))

    def _on_serial_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        self.serial_edit_begun.emit()
        self.serial_toggle_requested.emit(bool(checked))
        self.serial_edit_finished.emit()

    def _on_serial_value(self, *_args) -> None:
        if self._updating or not hasattr(self, "_serial_suffix"):
            return
        self.serial_edit_begun.emit()
        spec = dict(self._spec)
        spec["start"] = self._serial_start.value()
        spec["count"] = self._serial_count.value()
        spec["step"] = self._serial_step.value()
        spec["pad_width"] = self._serial_pad.value()
        spec["prefix"] = self._serial_prefix.text()
        spec["suffix"] = self._serial_suffix.text()
        self._spec = spec
        self.serial_spec_changed.emit(dict(spec))

    def _on_serial_edit_finished(self) -> None:
        if self._updating:
            return
        self.serial_edit_finished.emit()

    @property
    def csv_table(self) -> CsvTable | None:
        return self._table_data

    @property
    def expanded(self) -> bool:
        return self._toggle.isChecked()

    def clear(self, *, notice: str | None = None) -> None:
        """Keine Verbindung: Grid leeren. Banner bleibt, wenn ``notice`` gesetzt ist."""
        self._table_data = None
        self._linked = False
        self._updating = True
        try:
            self._grid.clear()
            self._grid.setRowCount(0)
            self._grid.setColumnCount(0)
        finally:
            self._updating = False
        self._file_label.setText(tr("Keine CSV verbunden"))
        self._counter.setText("")
        self._set_notice(notice)
        self._set_actions(connected=False, linked=False)
        self._serial.hide()
        self.setVisible(True)
        if notice:
            self.set_expanded(True)

    def show_unloaded(self, display_name: str, notice: str | None = None) -> None:
        """Pfad bekannt, Datei aber nicht geladen (D12): Banner, kein Grid."""
        self._table_data = None
        self._linked = True
        self._updating = True
        try:
            self._grid.clear()
            self._grid.setRowCount(0)
            self._grid.setColumnCount(0)
        finally:
            self._updating = False
        self._file_label.setText(display_name or tr("CSV"))
        self._counter.setText("")
        self._set_notice(notice)
        self._set_actions(connected=False, linked=True)
        self._serial.hide()
        self.setVisible(True)
        self.set_expanded(True)

    def set_table(
        self,
        table: CsvTable | None,
        *,
        current_record: int = 0,
        display_name: str | None = None,
        notice: str | None = None,
    ) -> None:
        """Tabelle laden und Zeile ``current_record`` selektieren."""
        if table is None or not table.fields:
            self.clear(notice=notice)
            return
        self._table_data = table
        self._linked = True
        name = display_name
        if not name and table.path is not None:
            name = Path(table.path).name
        self._file_label.setText(name or tr("CSV"))
        self._set_notice(notice)
        self._set_actions(connected=True, linked=True)
        self._updating = True
        try:
            self._grid.clear()
            fields = list(table.fields)
            self._grid.setColumnCount(len(fields))
            self._grid.setHorizontalHeaderLabels(
                [f"○ {field}" for field in fields]
            )
            tip = tr("Auf Text, Barcode oder QR ziehen")
            for column, field in enumerate(fields):
                header_item = self._grid.horizontalHeaderItem(column)
                if header_item is not None:
                    header_item.setToolTip(tip)
                    header_item.setData(Qt.ItemDataRole.UserRole, field)
            self._grid.setRowCount(len(table.records))
            for row_index, record in enumerate(table.records):
                for col_index, field in enumerate(fields):
                    cell = QTableWidgetItem(str(record.get(field, "")))
                    cell.setFlags(
                        Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                    )
                    self._grid.setItem(row_index, col_index, cell)
            index = clamp_record_index(current_record, len(table.records))
            self._show_counter(index)
            if table.records:
                self._grid.selectRow(index)
                item = self._grid.item(index, 0)
                if item is not None:
                    self._grid.scrollToItem(item)
        finally:
            self._updating = False
        self.setVisible(True)
        self.set_expanded(True)
        self.set_serial_state(
            self._spec,
            target_kind=self._target_kind,
            target_source=self._target_source,
        )

    def set_current_record(self, index: int) -> None:
        """Selektion setzen, ohne ``record_selected`` auszuloesen."""
        if self._table_data is None or not self._table_data.records:
            return
        index = clamp_record_index(index, len(self._table_data.records))
        self._show_counter(index)
        self._updating = True
        try:
            self._grid.selectRow(index)
            item = self._grid.item(index, 0)
            if item is not None:
                self._grid.scrollToItem(item)
        finally:
            self._updating = False

    def set_expanded(self, expanded: bool) -> None:
        """Grid ein- oder ausklappen, ohne das Signal doppelt zu verarbeiten."""
        if self._toggle.isChecked() == expanded:
            self._apply_expanded(expanded)
            return
        self._toggle.setChecked(expanded)

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
        index = int(rows[0].row())
        self._show_counter(index)
        self.record_selected.emit(index)

    def _drag_field(self, column: int) -> None:
        if self._table_data is None:
            return
        fields = list(self._table_data.fields)
        if column < 0 or column >= len(fields):
            return
        drag = QDrag(self._header)
        drag.setMimeData(field_mime(fields[column]))
        drag.exec(Qt.DropAction.CopyAction)

    def _show_counter(self, index: int) -> None:
        total = len(self._table_data.records) if self._table_data is not None else 0
        if total <= 0:
            self._counter.setText("")
            return
        self._counter.setText(
            tr("Datensatz {current} / {total}").format(
                current=index + 1, total=total
            )
        )

    def _set_notice(self, notice: str | None) -> None:
        text = (notice or "").strip()
        self._banner.setText(text)
        self._banner.setVisible(bool(text))

    def _set_actions(self, *, connected: bool, linked: bool) -> None:
        self._connect.setEnabled(not connected)
        self._other.setEnabled(linked)
        self._disconnect.setEnabled(linked)

    def _on_expanded_toggled(self, expanded: bool) -> None:
        self._apply_expanded(expanded)

    def _apply_expanded(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        if expanded:
            self.setMinimumHeight(140)
            self.setMaximumHeight(280)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(52)


__all__ = [
    "DB_FIELD_MIME",
    "DatabasePanel",
    "field_from_mime",
    "field_mime",
]
