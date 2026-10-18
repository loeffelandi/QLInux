"""Suchbare Befehlsliste.

Strg+K oeffnet alle Befehle, nach Bereichen gruppiert. Ein Filter haengt
nur am Suchfeld, nicht an der Anwendung. Leere Bereiche verschwinden.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .i18n import tr
from .sheet import Sheet


class CommandPalette(QWidget):
    """Suchfeld plus Liste. Enter fuehrt den gewaehlten Befehl aus."""

    def __init__(self, groups: list[tuple[str, list]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("command_palette")
        self._groups = [(title, list(actions)) for title, actions in groups]
        self._actions = [action for _title, actions in self._groups for action in actions]
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
        cursor = 0
        for title, actions in self._groups:
            matched: list[tuple[int, object]] = []
            for action in actions:
                index = cursor
                cursor += 1
                haystack = action.text().casefold().replace("…", "")
                if words and not all(word in haystack for word in words):
                    continue
                matched.append((index, action))
            if not matched:
                continue
            if title:
                header = QListWidgetItem(title)
                header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                header.setData(Qt.ItemDataRole.UserRole, -1)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self._list.addItem(header)
            for index, action in matched:
                label = action.text()
                shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                if shortcut:
                    label = f"{label}    {shortcut}"
                item = QListWidgetItem(action.icon(), label)
                item.setData(Qt.ItemDataRole.UserRole, index)
                if not action.isEnabled():
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self._list.addItem(item)
        rows = self._command_rows()
        if rows:
            self._list.setCurrentRow(rows[0])

    def _command_rows(self) -> list[int]:
        rows = []
        for row in range(self._list.count()):
            data = self._list.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, int) and data >= 0:
                rows.append(row)
        return rows

    def _move(self, step: int) -> None:
        rows = self._command_rows()
        if not rows:
            return
        current = self._list.currentRow()
        if current in rows:
            index = rows.index(current) + step
        elif step > 0:
            later = [i for i, row in enumerate(rows) if row > current]
            index = later[0] if later else len(rows) - 1
        else:
            earlier = [i for i, row in enumerate(rows) if row < current]
            index = earlier[-1] if earlier else 0
        self._list.setCurrentRow(rows[max(0, min(len(rows) - 1, index))])

    def _run(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or index < 0:
            return
        action = self._actions[index]
        if not action.isEnabled():
            return
        self._close()
        QTimer.singleShot(0, action.trigger)

    def _close(self) -> None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, Sheet):
                parent.close_sheet()
                return
            parent = parent.parentWidget()
