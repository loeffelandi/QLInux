"""Suchbare Befehlsliste.

Strg+K oeffnet die Gruppen. Pfeil rechts steigt in eine Gruppe, Pfeil links
kehrt zur gemerkten Zeile zurueck. Ein Filter haengt nur am Suchfeld.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .sheet import Sheet

#: Kennzeichnet eine Zeile, die sich nach rechts oeffnet.
_SUBMENU_MARK = "›"


class PaletteEntry:
    """Eine Zeile: Befehl oder Gruppe mit Kindern."""

    def __init__(
        self,
        title: str,
        *,
        action: QAction | None = None,
        children: list[PaletteEntry] | None = None,
        icon: QIcon | None = None,
    ) -> None:
        self.title = title
        self.action = action
        self.children = [child for child in (children or []) if child is not None]
        if icon is not None:
            self.icon = icon
        elif action is not None:
            self.icon = action.icon()
        else:
            self.icon = QIcon()

    def walk_actions(self) -> list[QAction]:
        found: list[QAction] = []
        if self.action is not None:
            found.append(self.action)
        for child in self.children:
            found.extend(child.walk_actions())
        return found


class CommandPalette(QWidget):
    """Suchfeld plus Liste. Enter fuehrt einen Befehl aus oder oeffnet die Gruppe."""

    def __init__(
        self, entries: list[PaletteEntry], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("command_palette")
        self._root = list(entries)
        self._entries = self._root
        self._visible: list[PaletteEntry] = []
        self._index = 0
        self._levels: list[list[PaletteEntry]] = []
        self._back_index: list[int] = []
        self._titles: list[str] = []
        self._edit = QLineEdit()
        self._edit.setObjectName("command_palette_search")
        self._edit.setPlaceholderText(tr("Befehl suchen"))
        self._edit.textChanged.connect(self._refill)
        self._edit.installEventFilter(self)
        self._level = QLabel()
        self._level.setObjectName("command_palette_level")
        font = self._level.font()
        font.setBold(True)
        self._level.setFont(font)
        self._level.setVisible(False)
        self._list = QListWidget()
        self._list.setObjectName("command_palette_list")
        self._list.itemActivated.connect(lambda _item: self._activate())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._edit)
        layout.addWidget(self._level)
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
                self._activate()
                return True
            if key == Qt.Key.Key_Right and self._caret_at_end():
                self._enter()
                return True
            if key == Qt.Key.Key_Left and self._caret_at_start():
                self._back()
                return True
            if key == Qt.Key.Key_Escape:
                self._close()
                return True
        return super().eventFilter(obj, event)

    def _caret_at_start(self) -> bool:
        return self._edit.cursorPosition() == 0 and not self._edit.hasSelectedText()

    def _caret_at_end(self) -> bool:
        return (
            self._edit.cursorPosition() == len(self._edit.text())
            and not self._edit.hasSelectedText()
        )

    def _refill(self) -> None:
        words = self._edit.text().casefold().split()
        # Die Suche gilt immer fuer alle Befehle, nicht nur fuer die offene Gruppe.
        shown = self._search(self._root, words) if words else list(self._entries)
        self._visible = shown
        self._list.clear()
        for entry in shown:
            item = QListWidgetItem(entry.icon, self._label(entry))
            if entry.action is not None and not entry.action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(item)
        if not shown:
            return
        if words:
            self._list.setCurrentRow(0)
            return
        row = min(self._index, len(shown) - 1)
        self._index = row
        self._list.setCurrentRow(row)

    def _label(self, entry: PaletteEntry) -> str:
        if entry.children:
            return f"{entry.title}    {_SUBMENU_MARK}"
        label = entry.title
        if entry.action is not None:
            shortcut = entry.action.shortcut().toString(
                QKeySequence.SequenceFormat.NativeText
            )
            if shortcut:
                label = f"{label}    {shortcut}"
        return label

    def _search(
        self, entries: list[PaletteEntry], words: list[str]
    ) -> list[PaletteEntry]:
        found: list[PaletteEntry] = []
        for entry in entries:
            haystack = entry.title.casefold().replace("…", "")
            if all(word in haystack for word in words):
                found.append(entry)
            if entry.children:
                found.extend(self._search(entry.children, words))
        return found

    def _current(self) -> PaletteEntry | None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._visible):
            return None
        return self._visible[row]

    def _move(self, step: int) -> None:
        count = self._list.count()
        if not count:
            return
        row = self._list.currentRow()
        if row < 0:
            row = 0 if step > 0 else count - 1
        else:
            row = max(0, min(count - 1, row + step))
        self._list.setCurrentRow(row)
        if not self._edit.text().strip():
            self._index = row

    def _enter(self) -> None:
        entry = self._current()
        if entry is None or not entry.children:
            return
        self._back_index.append(self._index)
        self._levels.append(self._entries)
        self._titles.append(entry.title)
        self._entries = entry.children
        self._index = 0
        self._set_query("")
        self._level.setText(entry.title)
        self._level.setVisible(True)
        self._refill()

    def _back(self) -> None:
        if not self._levels:
            if self._edit.text():
                self._set_query("")
                self._refill()
            return
        self._entries = self._levels.pop()
        self._index = self._back_index.pop()
        self._titles.pop()
        self._set_query("")
        if self._titles:
            self._level.setText(self._titles[-1])
        else:
            self._level.clear()
            self._level.setVisible(False)
        self._refill()

    def _set_query(self, text: str) -> None:
        self._edit.blockSignals(True)
        self._edit.setText(text)
        self._edit.blockSignals(False)

    def _activate(self) -> None:
        entry = self._current()
        if entry is None:
            return
        if entry.children:
            self._enter()
            return
        action = entry.action
        if action is None or not action.isEnabled():
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
