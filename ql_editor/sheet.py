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

import shiboken6
from PySide6.QtCore import QDir, QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr

#: Kleinstes Format eines Dateidialogs im Sheet (Bildschirmpixel).
DIALOG_MIN_WIDTH = 320
DIALOG_MIN_HEIGHT = 240
#: Randabstand um einen Dateidialog - so viel Hoehe wie moeglich bleibt.
DIALOG_MARGIN = 14

#: Abdunklung hinter dem Sheet (Alpha 0..255).
_SCRIM_ALPHA = 120

_MESSAGE_ICONS = {
    "info": QMessageBox.Icon.Information,
    "warning": QMessageBox.Icon.Warning,
    "critical": QMessageBox.Icon.Critical,
    "question": QMessageBox.Icon.Question,
}


class _SheetShortcutFilter(QObject):
    """Ein Filter fuer alle offenen Sheets.

    Jedes Sheet als eigenen Filter auf die ``QApplication`` zu setzen wuerde
    jedes Qt-Ereignis durch Python schicken. Bleibt ein Sheet offen, stapelt
    der naechste Filter sich obendrauf. Ein gemeinsamer Filter reicht: er
    haengt nur, solange ein Sheet sichtbar ist, und fragt die Sheets nur bei
    echten Tastenkuerzeln.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sheets: list[Sheet] = []
        self._installed = False

    def add(self, sheet: Sheet) -> None:
        if sheet not in self._sheets:
            self._sheets.append(sheet)
            sheet.destroyed.connect(lambda *args, watched=sheet: self.discard(watched))
        self._install()

    def discard(self, sheet: Sheet) -> None:
        if not shiboken6.isValid(self):
            return
        try:
            self._sheets.remove(sheet)
        except ValueError:
            return
        if not self._sheets:
            self._remove()

    def _install(self) -> None:
        if self._installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._installed = True

    def _remove(self) -> None:
        if not self._installed:
            return
        self._installed = False
        app = QApplication.instance()
        if app is not None and shiboken6.isValid(app) and shiboken6.isValid(self):
            app.removeEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Shortcut:
            return False
        for sheet in list(self._sheets):
            if sheet.eventFilter(obj, event):
                return True
        return False


_shortcut_filter: _SheetShortcutFilter | None = None


def _same_object(left, right) -> bool:
    """Qt-Objekte vergleichen, auch wenn Python zwei Wrapper haelt."""
    if left is right:
        return True
    try:
        return shiboken6.getCppPointer(left) == shiboken6.getCppPointer(right)
    except Exception:
        return False


def _shortcuts() -> _SheetShortcutFilter:
    global _shortcut_filter
    if _shortcut_filter is None:
        _shortcut_filter = _SheetShortcutFilter()
    return _shortcut_filter


class _SheetCard(QFrame):
    """Karte ohne Stylesheet.

    Ein Stylesheet am Sheet zieht die Kinder aus der Anwendungspalette: nach
    einem Wechsel bleiben Felder und Grund auf der alten Helligkeit stehen.
    """

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid)))
        painter.setBrush(palette.color(QPalette.ColorRole.Window))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)


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
        close_on_outside: bool = False,
        corner: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("qlSheet")
        self._sizing = sizing
        self._margins = margins
        self._max_size = max_size or QSize(1000, 760)
        self._close_on_outside = bool(close_on_outside)
        self._closing = False
        self._filtering_parent = False

        self._panel = self._build_panel(content, title, corner)
        self._panel.setParent(self)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_MouseTracking, True)
        self.setGeometry(parent.rect())
        self._relayout()

    # --------------------------------------------------------------- Aufbau --
    @staticmethod
    def _build_panel(
        content: QWidget, title: str, corner: QWidget | None = None
    ) -> QFrame:
        card = _SheetCard()
        card.setObjectName("qlSheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        if title or corner is not None:
            header = QWidget()
            row = QHBoxLayout(header)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            if title:
                label = QLabel(title)
                label.setObjectName("qlSheetTitle")
                font = QFont(label.font())
                font.setBold(True)
                font.setPointSizeF(font.pointSizeF() + 2.0)
                label.setFont(font)
                row.addWidget(label, 1)
            else:
                row.addStretch(1)
            if corner is not None:
                row.addWidget(
                    corner,
                    0,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )
            layout.addWidget(header)
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
            # Bei knapper Hoehe nicht an der Mindestgroesse festhalten - sonst
            # wird Inhalt (z. B. Scrollbalken) abgeschnitten.
            w = min(w, avail.width(), self._max_size.width())
            h = min(h, avail.height(), self._max_size.height())
        else:
            w = min(self._max_size.width(), avail.width())
            h = min(self._max_size.height(), avail.height())
            w = max(w, min(panel.minimumWidth(), avail.width()))
            h = max(h, min(panel.minimumHeight(), avail.height()))
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
            if not _same_object(obj, self) and not self.isAncestorOf(obj):
                return True
        parent = self.parentWidget()
        if parent is not None and obj == parent and event.type() == QEvent.Type.Resize:
            self.setGeometry(parent.rect())
        return super().eventFilter(obj, event)

    def _watch_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None or self._filtering_parent:
            return
        parent.installEventFilter(self)
        self._filtering_parent = True

    def _unwatch_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None and self._filtering_parent:
            parent.removeEventFilter(self)
        self._filtering_parent = False

    # ---------------------------------------------------------- Darstellung --
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, _SCRIM_ALPHA))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._watch_parent()
        self.raise_()
        self._relayout()
        _shortcuts().add(self)
        # QFileDialog/QInputDialog setzen den Fokus selbst auf ihr Eingabefeld.
        if self._panel.findChild(QDialog) is None:
            self.setFocus()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._unwatch_parent()
        _shortcuts().discard(self)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_sheet()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Klick auf die Abdunklung schliesst optional (Picker, Clip Art)."""
        if (
            self._close_on_outside
            and event.button() == Qt.MouseButton.LeftButton
            and not self._panel.geometry().contains(event.position().toPoint())
        ):
            self.close_sheet()
            event.accept()
            return
        super().mousePressEvent(event)

    # --------------------------------------------------------- Schliessen ---
    def close_sheet(self) -> None:
        """Schliesst das Sheet (idempotent)."""
        if self._closing:
            return
        self._closing = True
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


def show_widget(
    parent: QWidget,
    *,
    title: str,
    content: QWidget,
    sizing: str = "hint",
    max_size: QSize | None = None,
    margins: int = 40,
    close_on_outside: bool = False,
    corner: QWidget | None = None,
) -> Sheet:
    """Eigenen Inhalt als Sheet zeigen (z. B. "Über QLInux").

    Fuer alles, was mehr ist als eine Meldung: der Inhalt ist ein eigenes
    Widget, das Sheet bleibt aber im Hauptfenster (siehe Modulbeschreibung).
    ``close_on_outside`` schliesst bei Klick auf die Abdunklung (Picker).
    """
    return _open_sheet(
        parent,
        content,
        title=title,
        sizing=sizing,
        max_size=max_size,
        margins=margins,
        close_on_outside=close_on_outside,
        corner=corner,
    )


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


def ask_save(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> Sheet:
    """Speichern, Verwerfen oder Abbrechen.

    ``on_choice`` bekommt ``"save"``, ``"discard"`` oder ``"cancel"``.
    Escape und das Schließen des Sheets zählen als Abbrechen.
    """
    box = QMessageBox()
    box.setWindowFlags(Qt.WindowType.Widget)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    save = box.addButton(tr("Speichern"), QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton(tr("Verwerfen"), QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(save)
    sheet = _open_sheet(parent, box, title=title, sizing="hint")
    chosen: dict[str, str | None] = {"value": None}

    def _finish(choice: str) -> None:
        if chosen["value"] is not None:
            return
        chosen["value"] = choice
        sheet.close_sheet()
        on_choice(choice)

    def _clicked(_result: int) -> None:
        button = box.clickedButton()
        if button is save:
            _finish("save")
        elif button is discard:
            _finish("discard")
        else:
            _finish("cancel")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("cancel"))
    return sheet


def ask_label_printer(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> Sheet:
    """Etikett behalten oder an den gefundenen Drucker anpassen.

    ``on_choice`` bekommt ``"keep"`` oder ``"adapt"``. Escape und das
    Schließen des Sheets zählen als Behalten: das Etikett bleibt, wie es ist.
    """
    box = QMessageBox()
    box.setWindowFlags(Qt.WindowType.Widget)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    keep = box.addButton(tr("Etikett behalten"), QMessageBox.ButtonRole.AcceptRole)
    adapt = box.addButton(
        tr("An den Drucker anpassen"), QMessageBox.ButtonRole.ActionRole
    )
    box.setDefaultButton(keep)
    sheet = _open_sheet(parent, box, title=title, sizing="hint")
    chosen: dict[str, str | None] = {"value": None}

    def _finish(choice: str) -> None:
        if chosen["value"] is not None:
            return
        chosen["value"] = choice
        sheet.close_sheet()
        on_choice(choice)

    def _clicked(_result: int) -> None:
        button = box.clickedButton()
        if button is adapt:
            _finish("adapt")
        else:
            _finish("keep")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("keep"))
    return sheet


def ask_loaded_tape(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> Sheet:
    """Gewaehltes Band passt nicht zum eingelegten: drucken, merken oder abbrechen.

    ``on_choice`` bekommt ``"print"``, ``"remember"`` (das gewaehlte Band wird
    als eingelegt gemerkt und gedruckt) oder ``"cancel"``. Escape und das
    Schliessen des Sheets zaehlen als Abbrechen.
    """
    box = QMessageBox()
    box.setWindowFlags(Qt.WindowType.Widget)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    cancel = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
    cancel.setIcon(icon("close"))
    remember = box.addButton(
        tr("Als eingelegt merken und drucken"), QMessageBox.ButtonRole.ActionRole
    )
    send = box.addButton(tr("Trotzdem drucken"), QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(cancel)
    sheet = _open_sheet(parent, box, title=title, sizing="hint")
    chosen: dict[str, str | None] = {"value": None}

    def _finish(choice: str) -> None:
        if chosen["value"] is not None:
            return
        chosen["value"] = choice
        sheet.close_sheet()
        on_choice(choice)

    def _clicked(_result: int) -> None:
        button = box.clickedButton()
        if button is send:
            _finish("print")
        elif button is remember:
            _finish("remember")
        else:
            _finish("cancel")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("cancel"))
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
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, tr("Öffnen"))
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, tr("Abbrechen"))
    # Keine harte Mindestgroesse: die erzwingt das Sheet und schneidet sonst die
    # Schaltflaechen unten ab, wenn das Fenster niedrig ist.
    dialog.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
    sheet = _open_sheet(
        parent,
        dialog,
        title=caption,
        sizing="fill",
        margins=DIALOG_MARGIN,
        max_size=QSize(980, 700),
    )

    def _finished(result: int) -> None:
        files = dialog.selectedFiles()
        sheet.close_sheet()
        selected = files[0] if result == QDialog.DialogCode.Accepted and files else None
        on_selected(selected)

    dialog.finished.connect(_finished)
    return sheet


def save_file(
    parent: QWidget,
    *,
    caption: str,
    name_filter: str,
    on_selected: Callable[[str | None], None],
    start_dir: str = "",
    default_name: str = "",
) -> Sheet:
    """Speicherort waehlen - wie :func:`choose_file`, nur zum Schreiben."""
    dialog = QFileDialog()
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setSizeGripEnabled(False)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setNameFilter(name_filter)
    dialog.setDirectory(start_dir or QDir.homePath())
    if default_name:
        dialog.selectFile(default_name)
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, tr("Speichern"))
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, tr("Abbrechen"))
    # Keine harte Mindestgroesse: die erzwingt das Sheet und schneidet sonst die
    # Schaltflaechen unten ab, wenn das Fenster niedrig ist.
    dialog.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
    sheet = _open_sheet(
        parent,
        dialog,
        title=caption,
        sizing="fill",
        margins=DIALOG_MARGIN,
        max_size=QSize(980, 700),
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
    dialog.setCancelButtonText(tr("Abbrechen"))
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
    dialog.setCancelButtonText(tr("Abbrechen"))
    dialog.setMinimumWidth(340)
    sheet = _open_sheet(parent, dialog, title=title, sizing="hint")

    def _finished(result: int) -> None:
        value = dialog.textValue()
        sheet.close_sheet()
        if result == QDialog.DialogCode.Accepted:
            on_ok(value)

    dialog.finished.connect(_finished)
    return sheet


__all__ = [
    "Sheet",
    "show_message",
    "choose_file",
    "ask_text",
    "ask_choice",
    "ask_save",
    "ask_label_printer",
]
