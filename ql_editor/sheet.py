"""Dialoge als *Sheet* im App-Fenster.

Warum kein normaler Dialog?
---------------------------
Unter Wayland verwaltet der Compositor jedes eigene Fenster. Ein Dialog ist
damit ein zweites Top-Level-Fenster: es bleibt als eigenes Fenster im
Vordergrund und laesst sich nicht einfach "wegklicken". Qt 6.12 meldet
Dialoge ausserdem *nicht* ueber das Protokoll ``xdg-dialog-v1`` an, sodass
Tiling-Compositor (z. B. COSMIC) sie wie normale Fenster behandeln.

Deshalb laufen alle Dialoge dieser App als **Sheet**: ein Overlay *innerhalb*
des Hauptfensters. Es gibt kein zweites Fenster, das der Fenstermanager
verwalten koennte - der Dialog kann daher nicht im Vordergrund "haengen".
Das Verhalten entspricht einem macOS-Sheet: der Hintergrund wird abgedunkelt,
die Bedienung dahinter ist gesperrt, ``Esc`` schliesst.

Alle Helfer sind **asynchron** (Callback statt Rueckgabewert), weil das Sheet
- anders als ``exec()`` - den Event-Loop nicht blockiert.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QDir, QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

#: Abdunklung hinter dem Sheet (Alpha 0..255).
_SCRIM_ALPHA = 120

_MESSAGE_ICONS = {
    "info": QMessageBox.Icon.Information,
    "warning": QMessageBox.Icon.Warning,
    "critical": QMessageBox.Icon.Critical,
    "question": QMessageBox.Icon.Question,
}


class Sheet(QWidget):
    """Modal-Overlay im Hauptfenster: dimmt den Hintergrund, zeigt den Inhalt.

    Der Inhalt sitzt in einer "Karte" mit Titelzeile. Das Sheet folgt der
    Fenstergroesse (responsiv) und deckt das ganze Fenster ab.
    """

    closed = Signal()

    def __init__(
        self,
        parent: QWidget,
        content: QWidget,
        *,
        title: str = "",
        sizing: str = "hint",
        margins: int = 40,
        max_size: QSize | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("qlSheet")
        self._sizing = sizing
        self._margins = margins
        self._max_size = max_size or QSize(1000, 760)
        self._closing = False

        self._panel = self._build_panel(content, title)
        self._panel.setParent(self)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(
            "#qlSheetCard { background: palette(window); border: 1px solid palette(mid);"
            " border-radius: 12px; }"
            "#qlSheetTitle { color: palette(windowText); }"
        )
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self._relayout()

    # --------------------------------------------------------------- Aufbau --
    @staticmethod
    def _build_panel(content: QWidget, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("qlSheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        if title:
            label = QLabel(title)
            label.setObjectName("qlSheetTitle")
            font = QFont(label.font())
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() + 2.0)
            label.setFont(font)
            layout.addWidget(label)
        layout.addWidget(content, 1)
        return card

    # ------------------------------------------------------------ Geometrie --
    def _relayout(self) -> None:
        avail = self.rect().adjusted(
            self._margins, self._margins, -self._margins, -self._margins
        )
        if avail.width() <= 0 or avail.height() <= 0:
            return
        panel = self._panel
        if self._sizing == "hint":
            hint = panel.sizeHint()
            w = max(panel.minimumWidth(), hint.width())
            h = max(panel.minimumHeight(), hint.height())
        else:
            w = self._max_size.width()
            h = self._max_size.height()
            w = max(w, panel.minimumWidth())
            h = max(h, panel.minimumHeight())
        w = min(w, avail.width())
        h = min(h, avail.height())
        panel.setGeometry(
            avail.x() + (avail.width() - w) // 2,
            avail.y() + (avail.height() - h) // 2,
            w,
            h,
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # Solange das Sheet offen ist, keine App-Tastenkombinationen
        # (Ctrl+P, Entf, ...) ausloesen - das Sheet ist modal.
        if event.type() == QEvent.Type.Shortcut and self.isVisible():
            if obj is not self and not self.isAncestorOf(obj):
                return True
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------- Darstellung --
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, _SCRIM_ALPHA))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self._relayout()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        # QFileDialog/QInputDialog setzen den Fokus selbst auf ihr Eingabefeld.
        if self._panel.findChild(QDialog) is None:
            self.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_sheet()
            event.accept()
            return
        super().keyPressEvent(event)

    # --------------------------------------------------------- Schliessen ---
    def close_sheet(self) -> None:
        """Schliesst das Sheet (idempotent)."""
        if self._closing:
            return
        self._closing = True
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()


# ------------------------------------------------------------------ Helfer --
def _open_sheet(parent: QWidget, content: QWidget, **kwargs) -> Sheet:
    """Oeffnet ein Sheet; ein evtl. offenes wird vorher geschlossen."""
    existing = parent.findChild(Sheet)
    if existing is not None:
        existing.close_sheet()
    sheet = Sheet(parent, content, **kwargs)
    sheet.show()
    return sheet


def show_message(
    parent: QWidget,
    kind: str,
    title: str,
    text: str,
    *,
    selectable: bool = False,
) -> Sheet:
    """Meldung (info/warning/critical) als Sheet.

    ``selectable=True`` macht den Text markierbar - fuer Befehle, die man
    abschreiben soll.
    """
    box = QMessageBox()
    box.setWindowFlags(Qt.WindowType.Widget)
    box.setIcon(_MESSAGE_ICONS.get(kind, QMessageBox.Icon.Information))
    box.setText(text)
    if selectable:
        box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setDefaultButton(QMessageBox.StandardButton.Ok)
    sheet = _open_sheet(parent, box, title=title, sizing="hint")
    box.finished.connect(lambda _result: sheet.close_sheet())
    return sheet


def choose_file(
    parent: QWidget,
    *,
    caption: str,
    name_filter: str,
    on_selected: Callable[[str | None], None],
    start_dir: str = "",
) -> Sheet:
    """Datei waehlen - eingebettet im Hauptfenster (kein eigenes Fenster)."""
    dialog = QFileDialog()
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setSizeGripEnabled(False)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setNameFilter(name_filter)
    dialog.setDirectory(start_dir or QDir.homePath())
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Öffnen")
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, "Abbrechen")
    dialog.setMinimumSize(560, 380)
    sheet = _open_sheet(
        parent, dialog, title=caption, sizing="fill", max_size=QSize(980, 700)
    )

    def _finished(result: int) -> None:
        files = dialog.selectedFiles()
        sheet.close_sheet()
        selected = files[0] if result == QDialog.DialogCode.Accepted and files else None
        on_selected(selected)

    dialog.finished.connect(_finished)
    return sheet


def ask_text(
    parent: QWidget,
    *,
    title: str,
    label: str,
    on_ok: Callable[[str], None],
    default: str = "",
) -> Sheet:
    """Freitext abfragen (Ersatz fuer ``QInputDialog.getText``)."""
    dialog = QInputDialog()
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    dialog.setLabelText(label)
    dialog.setTextValue(default)
    dialog.setOkButtonText("OK")
    dialog.setCancelButtonText("Abbrechen")
    dialog.setMinimumWidth(340)
    sheet = _open_sheet(parent, dialog, title=title, sizing="hint")

    def _finished(result: int) -> None:
        value = dialog.textValue()
        sheet.close_sheet()
        if result == QDialog.DialogCode.Accepted:
            on_ok(value)

    dialog.finished.connect(_finished)
    return sheet


def ask_choice(
    parent: QWidget,
    *,
    title: str,
    label: str,
    items: list[str],
    on_ok: Callable[[str], None],
) -> Sheet:
    """Aus einer Liste waehlen (Ersatz fuer ``QInputDialog.getItem``)."""
    dialog = QInputDialog()
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setLabelText(label)
    dialog.setComboBoxItems(list(items))
    dialog.setComboBoxEditable(False)
    dialog.setOkButtonText("OK")
    dialog.setCancelButtonText("Abbrechen")
    dialog.setMinimumWidth(340)
    sheet = _open_sheet(parent, dialog, title=title, sizing="hint")

    def _finished(result: int) -> None:
        value = dialog.textValue()
        sheet.close_sheet()
        if result == QDialog.DialogCode.Accepted:
            on_ok(value)

    dialog.finished.connect(_finished)
    return sheet


__all__ = ["Sheet", "show_message", "choose_file", "ask_text", "ask_choice"]
