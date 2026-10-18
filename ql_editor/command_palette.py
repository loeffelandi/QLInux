"""Suchbare Befehlsliste.

Strg+K (auf dem Mac die Befehlstaste, wie die anderen ``Ctrl+``-Kuerzel)
oeffnet dieselbe Liste, die das Hamburger-Menue und die Objektbefehle
hergeben. Ein Filter haengt nur am Suchfeld, nicht an der Anwendung.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .i18n import tr
from .sheet import Sheet


class CommandPalette(QWidget):
    """Suchfeld plus Liste. Enter fuehrt den gewaehlten Befehl aus."""

    def __init__(self, actions: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("command_palette")
        self._actions = list(actions)
        self._edit = QLineEdit()
        self._edit.setObjectName("command_palette_search")
        self._edit.setPlaceholderText(tr("Befehl suchen"))
        self._edit.textChanged.connect(self._refill)
        self._edit.installEventFilter(self)
        self._list = QListWidget()
        self._list.setObjectName("command_palette_list")
        self._list.itemActivated.connect(lambda _item: self._run())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._edit)
        layout.addWidget(self._list, 1)
        self.setMinimumWidth(360)
        self._list.setMinimumHeight(260)
        self._refill()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Das Sheet setzt danach selbst den Fokus. Danach gehoert er ins Feld.
        QTimer.singleShot(0, self._edit.setFocus)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run()
                return True
            if key == Qt.Key.Key_Escape:
                self._close()
                return True
        return super().eventFilter(obj, event)

    def _refill(self) -> None:
        words = self._edit.text().casefold().split()
        self._list.clear()
        for index, action in enumerate(self._actions):
            haystack = action.text().casefold().replace("…", "")
            if words and not all(word in haystack for word in words):
                continue
            label = action.text()
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if shortcut:
                label = f"{label}    {shortcut}"
            item = QListWidgetItem(action.icon(), label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            if not action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _move(self, step: int) -> None:
        count = self._list.count()
        if not count:
            return
        row = self._list.currentRow()
        if row < 0:
            row = 0
        self._list.setCurrentRow(max(0, min(count - 1, row + step)))

    def _run(self) -> None:
        item = self._list.currentItem()
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        action = self._actions[int(item.data(Qt.ItemDataRole.UserRole))]
        self._close()
        QTimer.singleShot(0, action.trigger)

    def _close(self) -> None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, Sheet):
                parent.close_sheet()
                return
            parent = parent.parentWidget()
