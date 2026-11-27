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

Auf dem Mac gilt das nicht: dort gibt es echte Sheets des Systems. Datei-,
Meldungs- und Eingabedialoge laufen dort als Systemdialog (``NSOpenPanel``,
``NSSavePanel``, ``NSAlert``), fensterweit modal am Hauptfenster. Eigene
Inhalte (Hilfe, Druck, Auswahl) bleiben auch dort ein Overlay.

Alle Helfer sind **asynchron** (Callback statt Rueckgabewert), weil das Sheet
- anders als ``exec()`` - den Event-Loop nicht blockiert.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import shiboken6
from PySide6.QtCore import QDir, QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import icon
from .platform_support import is_mac

#: Kleinstes Format eines Dateidialogs im Sheet (Bildschirmpixel).
DIALOG_MIN_WIDTH = 320
DIALOG_MIN_HEIGHT = 240
#: Randabstand um einen Dateidialog - so viel Hoehe wie moeglich bleibt.
DIALOG_MARGIN = 14

#: Abdunklung hinter dem Sheet (Alpha 0..255).
_SCRIM_ALPHA = 120

#: Kennzeichnet Dialoge, die ``_open_native`` geoeffnet hat.
_NATIVE_PROPERTY = "qlNativeSheet"

_MESSAGE_ICONS = {
    "info": QMessageBox.Icon.Information,
    "warning": QMessageBox.Icon.Warning,
    "critical": QMessageBox.Icon.Critical,
    "question": QMessageBox.Icon.Question,
}


class _NativeSheet(QObject):
    """Systemdialog (macOS) mit der Schnittstelle eines :class:`Sheet`.

    ``closed`` kommt erst aus :meth:`close_sheet`, nicht schon beim Ende des
    Dialogs: die Aufrufer entscheiden zuerst ueber ``finished``, was gewaehlt
    wurde, und melden danach. Ohne Eltern: die Verweise der Aufrufer halten das
    Objekt am Leben.
    """

    closed = Signal()

    def __init__(self, dialog: QDialog) -> None:
        super().__init__()
        self._dialog = dialog
        self._closing = False
        self._finished = False
        # Zuerst verbunden, also vor den Aufrufern: ``isVisible()`` bleibt beim
        # Systemdialog waehrend ``finished`` noch wahr, ein zweites ``reject()``
        # liesse die Aufrufer ein zweites Mal antworten.
        dialog.finished.connect(self._on_finished)

    def _on_finished(self, _result: int) -> None:
        self._finished = True

    def _is_open(self) -> bool:
        if self._finished:
            return False
        try:
            return self._dialog.isVisible()
        except RuntimeError:  # Fenster samt Dialog schon abgebaut
            return False

    def isVisible(self) -> bool:  # noqa: N802
        return not self._closing and self._is_open()

    def close_sheet(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._is_open():
            self._dialog.reject()
        self.closed.emit()
        try:
            self._dialog.deleteLater()
        except RuntimeError:
            pass


def _as_widget(dialog: QDialog) -> QDialog:
    """Im Overlay ist der Dialog ein Widget; auf dem Mac bleibt er ein Fenster."""
    if not is_mac():
        dialog.setWindowFlags(Qt.WindowType.Widget)
    return dialog


def _open_native(parent: QWidget, dialog: QDialog, title: str) -> _NativeSheet:
    """Dialog als Sheet des Hauptfensters zeigen (macOS).

    Wie beim Overlay ist nur eines offen: ein noch offener Systemdialog dieses
    Fensters wird abgebrochen. Sonst stellt macOS die Sheets hintereinander.
    """
    for existing in parent.findChildren(QDialog):
        if existing.property(_NATIVE_PROPERTY) and existing.isVisible():
            existing.reject()
    dialog.setProperty(_NATIVE_PROPERTY, True)
    dialog.setParent(parent, Qt.WindowType.Dialog)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    if isinstance(dialog, QMessageBox):
        # NSAlert hat keine Titelleiste: die Ueberschrift wird zur ersten Zeile.
        if title:
            dialog.setInformativeText(dialog.text())
            dialog.setText(title)
        # Markierbarer Text (Befehle zum Abschreiben) geht nur im Qt-Dialog.
        if dialog.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse:
            dialog.setOption(QMessageBox.Option.DontUseNativeDialog, True)
    elif title:
        dialog.setWindowTitle(title)
    handle = _NativeSheet(dialog)
    dialog.open()
    return handle


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
        on_enter: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("qlSheet")
        self._on_enter = on_enter
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
            # QShortcut und QAction sind keine Widgets: es zaehlen die Widgets,
            # an denen sie haengen (z. B. Strg+Hoch im Datei-Dialog).
            if isinstance(obj, QShortcut):
                owners = [obj.parent()]
            elif isinstance(obj, QAction):
                owners = list(obj.associatedObjects())
            else:
                owners = [obj]
            inside = any(
                isinstance(owner, QWidget)
                and (_same_object(owner, self) or self.isAncestorOf(owner))
                for owner in owners
            )
            if not inside:
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
            return
        # Eine Meldung bekommt den Fokus nicht von selbst: er bliebe auf der
        # Zeichenflaeche, und Enter erreichte sie statt des Standardknopfs.
        box = self._panel.findChild(QMessageBox)
        button = box.defaultButton() if box is not None else None
        if button is not None:
            button.setFocus()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._unwatch_parent()
        _shortcuts().discard(self)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_sheet()
            event.accept()
            return
        # Enter, das kein Feld im Sheet verbraucht hat: nicht ueber einen
        # QShortcut, dessen Zustellung am aktiven Fenster haengt.
        if (
            self._on_enter is not None
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ):
            event.accept()
            self._on_enter()
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


#: Ergebnis der Dialog-Helfer: ein Overlay oder auf dem Mac ein Systemdialog.
SheetLike = Sheet | _NativeSheet


# ------------------------------------------------------------------ Helfer --
def _open_overlay(parent: QWidget, content: QWidget, **kwargs) -> Sheet:
    """Oeffnet ein Overlay-Sheet; ein evtl. offenes wird vorher geschlossen.

    Ein schon geschlossenes Sheet wartet evtl. noch auf ``deleteLater`` und
    zaehlt nicht - sonst bliebe das offene neben dem neuen stehen.
    """
    for existing in parent.findChildren(Sheet):
        if not existing._closing:
            existing.close_sheet()
    sheet = Sheet(parent, content, **kwargs)
    sheet.show()
    return sheet


def _open_sheet(parent: QWidget, content: QDialog, **kwargs) -> SheetLike:
    """Dialog zeigen: auf dem Mac als Systemdialog, sonst als Overlay."""
    if is_mac():
        return _open_native(parent, content, kwargs.get("title", ""))
    return _open_overlay(parent, content, **kwargs)


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
    on_enter: Callable[[], None] | None = None,
) -> Sheet:
    """Eigenen Inhalt als Sheet zeigen (z. B. "Über QLInux").

    Fuer alles, was mehr ist als eine Meldung: der Inhalt ist ein eigenes
    Widget, das Sheet bleibt aber im Hauptfenster (siehe Modulbeschreibung).
    ``close_on_outside`` schliesst bei Klick auf die Abdunklung (Picker).
    ``on_enter`` laeuft bei Enter, das kein Feld im Sheet verbraucht.
    """
    return _open_overlay(
        parent,
        content,
        title=title,
        sizing=sizing,
        max_size=max_size,
        margins=margins,
        close_on_outside=close_on_outside,
        corner=corner,
        on_enter=on_enter,
    )


def show_message(
    parent: QWidget,
    kind: str,
    title: str,
    text: str,
    *,
    selectable: bool = False,
) -> SheetLike:
    """Meldung (info/warning/critical) als Sheet.

    ``selectable=True`` macht den Text markierbar - fuer Befehle, die man
    abschreiben soll.
    """
    box = QMessageBox()
    _as_widget(box)
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
) -> SheetLike:
    """Speichern, Verwerfen oder Abbrechen.

    ``on_choice`` bekommt ``"save"``, ``"discard"`` oder ``"cancel"``.
    Escape und das Schließen des Sheets zählen als Abbrechen.
    """
    box = QMessageBox()
    _as_widget(box)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    save = box.addButton(tr("Speichern"), QMessageBox.ButtonRole.AcceptRole)
    save.setIcon(icon("save"))
    discard = box.addButton(tr("Verwerfen"), QMessageBox.ButtonRole.DestructiveRole)
    discard.setIcon(icon("delete"))
    cancel = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
    cancel.setIcon(icon("cancel"))
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


def ask_update(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> SheetLike:
    """Neue Version gefunden: jetzt installieren, spaeter oder ueberspringen.

    ``on_choice`` bekommt ``"update"``, ``"later"`` oder ``"skip"``. Escape und
    das Schliessen des Sheets zaehlen als Spaeter.
    """
    box = QMessageBox()
    _as_widget(box)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(text)
    box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
    skip = box.addButton(
        tr("Diese Version überspringen"), QMessageBox.ButtonRole.DestructiveRole
    )
    update = box.addButton(tr("Jetzt aktualisieren"), QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(update)
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
        if button is update:
            _finish("update")
        elif button is skip:
            _finish("skip")
        else:
            _finish("later")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("later"))
    return sheet


def ask_restart(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> SheetLike:
    """Update installiert: jetzt neu starten oder spaeter.

    ``on_choice`` bekommt ``"restart"`` oder ``"later"``. Escape und das
    Schliessen des Sheets zaehlen als Spaeter.
    """
    box = QMessageBox()
    _as_widget(box)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
    restart = box.addButton(tr("Jetzt neu starten"), QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(restart)
    sheet = _open_sheet(parent, box, title=title, sizing="hint")
    chosen: dict[str, str | None] = {"value": None}

    def _finish(choice: str) -> None:
        if chosen["value"] is not None:
            return
        chosen["value"] = choice
        sheet.close_sheet()
        on_choice(choice)

    def _clicked(_result: int) -> None:
        _finish("restart" if box.clickedButton() is restart else "later")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("later"))
    return sheet


def ask_label_printer(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> SheetLike:
    """Etikett behalten oder an den gefundenen Drucker anpassen.

    ``on_choice`` bekommt ``"keep"`` oder ``"adapt"``. Escape und das
    Schließen des Sheets zählen als Behalten: das Etikett bleibt, wie es ist.
    """
    box = QMessageBox()
    _as_widget(box)
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
) -> SheetLike:
    """Gewaehltes Band passt nicht zum eingelegten: drucken, merken oder abbrechen.

    ``on_choice`` bekommt ``"print"``, ``"remember"`` (das gewaehlte Band wird
    als eingelegt gemerkt und gedruckt) oder ``"cancel"``. Escape und das
    Schliessen des Sheets zaehlen als Abbrechen.
    """
    box = QMessageBox()
    _as_widget(box)
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


def ask_print_anyway(
    parent: QWidget,
    *,
    title: str,
    text: str,
    on_choice: Callable[[str], None],
) -> SheetLike:
    """Drucker meldet eine Stoerung: trotzdem drucken oder abbrechen.

    ``on_choice`` bekommt ``"print"`` oder ``"cancel"``. Escape und das
    Schliessen des Sheets zaehlen als Abbrechen.
    """
    box = QMessageBox()
    _as_widget(box)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    cancel = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
    cancel.setIcon(icon("close"))
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
        _finish("print" if box.clickedButton() is send else "cancel")

    box.finished.connect(_clicked)
    sheet.closed.connect(lambda: _finish("cancel"))
    return sheet


class _HistoryNavFilter(QObject):
    """Maus-Seitentasten: Zurueck/Vor wie die Pfeile des Datei-Dialogs.

    Liegt an der Anwendung, damit auch Widgets gelten, die der Dialog erst
    spaeter erzeugt. Nur Klicks innerhalb des Dialogs zaehlen.
    """

    _BUTTONS: ClassVar[dict[Qt.MouseButton, str]] = {
        Qt.MouseButton.BackButton: "backButton",
        Qt.MouseButton.ForwardButton: "forwardButton",
    }

    def __init__(self, dialog: QFileDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # Der zweite schnelle Druck kommt bei Widgets nur als Doppelklick an.
        if event.type() not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        ):
            return False
        name = self._BUTTONS.get(event.button())
        if name is None:
            return False
        if not isinstance(obj, QWidget):
            return False
        if not (_same_object(obj, self._dialog) or self._dialog.isAncestorOf(obj)):
            return False
        button = self._dialog.findChild(QToolButton, name)
        if button is not None and button.isEnabled():
            button.click()
        return True


def _bind_history_buttons(dialog: QFileDialog) -> Callable[..., None]:
    """Seitentasten an den Dialog binden. Der Rückgabewert entfernt den Filter wieder."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return lambda *_args: None
    filter_ = _HistoryNavFilter(dialog)
    app.installEventFilter(filter_)

    def _remove(*_args: object) -> None:
        app.removeEventFilter(filter_)

    dialog.destroyed.connect(_remove)
    return _remove


def choose_file(
    parent: QWidget,
    *,
    caption: str,
    name_filter: str,
    on_selected: Callable[[str | None], None],
    start_dir: str = "",
) -> SheetLike:
    """Datei waehlen - eingebettet im Hauptfenster (kein eigenes Fenster)."""
    dialog = QFileDialog()
    _as_widget(dialog)
    if not is_mac():
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
    remove_history_nav = (
        (lambda *_args: None) if is_mac() else _bind_history_buttons(dialog)
    )
    sheet = _open_sheet(
        parent,
        dialog,
        title=caption,
        sizing="fill",
        margins=DIALOG_MARGIN,
        max_size=QSize(980, 700),
    )
    sheet.closed.connect(remove_history_nav)

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
) -> SheetLike:
    """Speicherort waehlen - wie :func:`choose_file`, nur zum Schreiben."""
    dialog = QFileDialog()
    _as_widget(dialog)
    if not is_mac():
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
    remove_history_nav = (
        (lambda *_args: None) if is_mac() else _bind_history_buttons(dialog)
    )
    sheet = _open_sheet(
        parent,
        dialog,
        title=caption,
        sizing="fill",
        margins=DIALOG_MARGIN,
        max_size=QSize(980, 700),
    )
    sheet.closed.connect(remove_history_nav)

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
) -> SheetLike:
    """Freitext abfragen (Ersatz fuer ``QInputDialog.getText``)."""
    dialog = QInputDialog()
    _as_widget(dialog)
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
) -> SheetLike:
    """Aus einer Liste waehlen (Ersatz fuer ``QInputDialog.getItem``)."""
    dialog = QInputDialog()
    _as_widget(dialog)
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
    "SheetLike",
    "ask_choice",
    "ask_label_printer",
    "ask_loaded_tape",
    "ask_print_anyway",
    "ask_restart",
    "ask_save",
    "ask_text",
    "ask_update",
    "choose_file",
    "show_message",
]
