"""Maus-Seitentasten in den Datei-Dialogen (Zurueck/Vor)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QToolButton, QWidget

from ql_editor import sheet

pytestmark = pytest.mark.usefixtures("qapp")


def _press(widget: QWidget, button: Qt.MouseButton) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(2, 2),
        QPointF(2, 2),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def test_side_buttons_navigate_file_dialog(qapp, tmp_path):
    parent = QWidget()
    parent.resize(1100, 760)
    parent.show()
    sheet.choose_file(
        parent,
        caption="Test",
        name_filter="Alle (*)",
        on_selected=lambda _path: None,
        start_dir=str(tmp_path),
    )
    dialog = parent.findChild(QFileDialog)
    assert dialog is not None
    back = dialog.findChild(QToolButton, "backButton")
    forward = dialog.findChild(QToolButton, "forwardButton")
    assert back is not None and forward is not None

    sub = tmp_path / "sub"
    sub.mkdir()
    dialog.setDirectory(str(sub))
    qapp.processEvents()
    assert back.isEnabled()
    _press(dialog.findChild(QWidget, "listView") or dialog, Qt.MouseButton.BackButton)
    qapp.processEvents()
    assert dialog.directory().absolutePath() == str(tmp_path)
    assert forward.isEnabled()
    _press(dialog, Qt.MouseButton.ForwardButton)
    qapp.processEvents()
    assert dialog.directory().absolutePath() == str(sub)
    parent.close()

