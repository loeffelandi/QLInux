"""Tests fuer die Sheet-Dialoge (Overlay statt eigenem Fenster).

Hintergrund: Unter Wayland (COSMIC) bleibt ein eigener Dialog als Fenster im
Vordergrund und laesst sich nicht wegklicken. Diese Tests sichern ab, dass
alle Dialoge als Kind-Overlay *im* Hauptfenster laufen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget
from ql_editor.app import MainWindow
from ql_editor.items import BarcodeItem, ImageItem, QRItem, TextItem
from ql_editor.settings import user_settings
from ql_editor.sheet import (
    Sheet,
    ask_choice,
    ask_loaded_tape,
    ask_print_anyway,
    ask_save,
    ask_text,
    choose_file,
    show_message,
)

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    user_settings().clear()
    yield
    user_settings().clear()


def _window(qapp) -> MainWindow:
    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    return win


def _sheet(win) -> Sheet | None:
    """Das aktuell sichtbare Sheet (alte warten evtl. noch auf deleteLater)."""
    sheets = win.findChildren(Sheet)
    for sheet in sheets:
        if sheet.isVisible():
            return sheet
    return sheets[0] if sheets else None


def _pick_file(qapp, sheet: QWidget, path: str) -> None:
    """Simuliert die Auswahl einer Datei im eingebetteten Dialog.

    ``selectFile()`` greift headless nicht (asynchrones QFileSystemModel),
    deshalb wird - wie beim Tippen eines Pfads - das Namensfeld gefuellt.
    """
    dialog = sheet if isinstance(sheet, QFileDialog) else sheet.findChild(QFileDialog)
    assert dialog is not None
    dialog.setDirectory(str(Path(path).parent))
    for _ in range(20):
        qapp.processEvents()
    name = dialog.findChild(QLineEdit, "fileNameEdit")
    assert name is not None
    name.setText(path)
    dialog.accept()
    qapp.processEvents()


# --------------------------------------------------------------------------- #
# Sheet-Grundverhalten
# --------------------------------------------------------------------------- #
def test_message_sheet_is_child_overlay(qapp):
    win = _window(qapp)
    sheet = show_message(win, "warning", "Titel", "Etwas ist schiefgelaufen.")
    qapp.processEvents()

    # Kein eigenes Fenster: gleiche Top-Level-Flaeche wie das Hauptfenster.
    assert sheet.isWindow() is False
    assert sheet.window() is win
    assert sheet.parentWidget() is win
    assert sheet.isVisible()
    assert sheet.geometry() == win.rect()
    assert sheet.findChild(QMessageBox) is not None
    win.close()


def test_sheet_escape_closes(qapp):
    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()

    event = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    sheet.keyPressEvent(event)
    qapp.processEvents()
    assert not sheet.isVisible()
    win.close()


def test_sheet_scrim_click_closes_when_enabled(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QLabel
    from ql_editor.sheet import show_widget

    win = _window(qapp)
    sheet = show_widget(
        win,
        title="Picker",
        content=QLabel("Inhalt"),
        close_on_outside=True,
    )
    qapp.processEvents()
    outside = QPoint(4, 4)
    assert not sheet._panel.geometry().contains(outside)
    sheet.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            outside.toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    qapp.processEvents()
    assert not sheet.isVisible()

    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()
    sheet.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(4, 4).toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    qapp.processEvents()
    assert sheet.isVisible()
    win.close()


def test_message_ok_button_closes_sheet(qapp):
    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()

    box = sheet.findChild(QMessageBox)
    box.button(QMessageBox.StandardButton.Ok).click()
    qapp.processEvents()
    assert not sheet.isVisible()
    win.close()


def test_sheet_follows_window_resize(qapp):
    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()

    win.resize(900, 600)
    qapp.processEvents()
    assert sheet.geometry() == win.rect()
    win.close()


def test_only_one_sheet_at_a_time(qapp):
    win = _window(qapp)
    show_message(win, "info", "Erster", "Text")
    qapp.processEvents()
    show_message(win, "info", "Zweiter", "Text")
    qapp.processEvents()

    visible = [s for s in win.findChildren(Sheet) if s.isVisible()]
    assert len(visible) == 1
    win.close()


def test_sheet_blocks_app_shortcuts(qapp):
    """Solange das Sheet offen ist, keine App-Shortcuts (z. B. Ctrl+P)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeySequence, QShortcutEvent
    from ql_editor import sheet as sheet_module

    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()

    event = QShortcutEvent(QKeySequence("Ctrl+P"), 1)
    assert event.type() == QEvent.Type.Shortcut
    # Receiver ausserhalb des Sheets (das Hauptfenster) -> geschluckt.
    assert sheet.eventFilter(win, event) is True
    # Receiver innerhalb des Sheets -> durchgelassen.
    assert sheet.eventFilter(sheet, event) is False
    # Ein gemeinsamer Filter, nicht einer je Sheet.
    guard = sheet_module._shortcut_filter
    assert guard is not None and guard._installed is True
    assert sheet in guard._sheets

    sheet.close_sheet()
    qapp.processEvents()
    assert sheet not in guard._sheets
    win.close()


def test_sheet_judges_shortcuts_and_actions_by_their_widget(qapp):
    """QShortcut/QAction im Sheet laufen, App-Aktionen bleiben gesperrt."""
    from PySide6.QtGui import QAction, QKeySequence, QShortcut, QShortcutEvent

    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()
    box = sheet.findChild(QMessageBox)
    event = QShortcutEvent(QKeySequence("Ctrl+Up"), 1)

    inner_shortcut = QShortcut(QKeySequence("Return"), box)
    assert sheet.eventFilter(inner_shortcut, event) is False
    outer_shortcut = QShortcut(QKeySequence("Return"), win)
    assert sheet.eventFilter(outer_shortcut, event) is True

    inner_action = QAction("Hoch", box)
    box.addAction(inner_action)
    assert sheet.eventFilter(inner_action, event) is False
    assert sheet.eventFilter(win._act_print, event) is True
    sheet.close_sheet()
    win.close()


def test_message_sheet_takes_enter_instead_of_the_canvas(qapp):
    """Der Fokus liegt auf dem Standardknopf, Enter erreicht die Zeichenflaeche nie."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    win = _window(qapp)
    win._canvas.setFocus()
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()
    focus = QApplication.focusWidget()
    assert isinstance(focus, QPushButton)
    assert sheet.isAncestorOf(focus)
    QTest.keyClick(focus, Qt.Key.Key_Return)
    qapp.processEvents()
    assert not sheet.isVisible()
    win.close()


@pytest.mark.parametrize("ask", [ask_loaded_tape, ask_print_anyway])
def test_enter_in_a_printer_question_cancels(qapp, ask):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    win = _window(qapp)
    choices = []
    ask(win, title="t", text="x", on_choice=choices.append)
    qapp.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    qapp.processEvents()
    assert choices == ["cancel"]
    win.close()


def test_enter_does_not_start_text_editing_behind_a_sheet(qapp):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    win = _window(qapp)
    item = TextItem("Hallo")
    win._canvas.add_item(item)
    item.setSelected(True)
    win._canvas.setFocus()
    qapp.processEvents()
    show_message(win, "warning", "Titel", "Text")
    qapp.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    qapp.processEvents()
    assert not item.is_editing
    win.close()


def test_file_dialog_keeps_its_own_shortcuts_in_the_sheet(qapp, tmp_path):
    """Strg+Hoch (uebergeordneter Ordner) ist eine QAction des Dialogs."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    sub = tmp_path / "sub"
    sub.mkdir()
    win = _window(qapp)
    sheet = choose_file(
        win,
        caption="Test",
        name_filter="Alle (*)",
        on_selected=lambda _path: None,
        start_dir=str(sub),
    )
    qapp.processEvents()
    dialog = win.findChild(QFileDialog)
    QTest.keyClick(
        QApplication.focusWidget(), Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier
    )
    qapp.processEvents()
    assert dialog.directory().absolutePath() == str(tmp_path)
    sheet.close_sheet()
    win.close()


# --------------------------------------------------------------------------- #
# Datei-Dialog
# --------------------------------------------------------------------------- #
def test_choose_file_returns_selection(qapp, tmp_path):
    win = _window(qapp)
    chosen: list[str | None] = []
    sheet = choose_file(
        win,
        caption="Bild wählen",
        name_filter="Bilder (*.png);;Alle Dateien (*)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
    )
    qapp.processEvents()

    dialog = sheet.findChild(QFileDialog)
    assert dialog is not None
    assert dialog.isWindow() is False
    assert dialog.window() is win

    target = tmp_path / "probe.png"
    Image.new("RGB", (8, 8), "white").save(target)
    _pick_file(qapp, sheet, str(target))

    assert chosen == [str(target)]
    assert not sheet.isVisible()
    win.close()


def test_choose_file_cancel_reports_none(qapp, tmp_path):
    win = _window(qapp)
    chosen: list[str | None] = []
    sheet = choose_file(
        win,
        caption="Bild wählen",
        name_filter="Alle Dateien (*)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
    )
    qapp.processEvents()

    sheet.findChild(QFileDialog).reject()
    qapp.processEvents()
    assert chosen == [None]
    assert not sheet.isVisible()
    win.close()


def test_add_image_via_sheet(qapp, tmp_path):
    win = _window(qapp)
    target = tmp_path / "foto.png"
    Image.new("RGB", (20, 10), "black").save(target)

    win._add_image()
    qapp.processEvents()
    sheet = _sheet(win)
    assert sheet is not None

    _pick_file(qapp, sheet, str(target))

    images = [i for i in win._canvas.items() if isinstance(i, ImageItem)]
    assert len(images) == 1
    win.close()


# --------------------------------------------------------------------------- #
# Eingabe-Dialoge
# --------------------------------------------------------------------------- #
def test_ask_text_callback(qapp):
    win = _window(qapp)
    values: list[str] = []
    sheet = ask_text(
        win, title="QR-Code", label="Inhalt", on_ok=values.append, default="https://"
    )
    qapp.processEvents()

    dialog = sheet.findChild(QInputDialog)
    assert dialog is not None
    dialog.setTextValue("https://example.org")
    dialog.accept()
    qapp.processEvents()

    assert values == ["https://example.org"]
    win.close()


def test_ask_choice_callback(qapp):
    win = _window(qapp)
    values: list[str] = []
    sheet = ask_choice(
        win,
        title="Barcode",
        label="Symbologie",
        items=["code128", "ean13"],
        on_ok=values.append,
    )
    qapp.processEvents()

    dialog = sheet.findChild(QInputDialog)
    dialog.setTextValue("ean13")
    dialog.accept()
    qapp.processEvents()

    assert values == ["ean13"]
    win.close()


def test_add_qr_via_sheet(qapp):
    win = _window(qapp)
    win._add_qr()
    qapp.processEvents()

    dialog = _sheet(win).findChild(QInputDialog)
    dialog.setTextValue("https://example.org")
    dialog.accept()
    qapp.processEvents()

    qrs = [i for i in win._canvas.items() if isinstance(i, QRItem)]
    assert len(qrs) == 1
    win.close()


def test_add_barcode_via_sheets(qapp):
    win = _window(qapp)
    win._add_barcode()
    qapp.processEvents()

    symbology = _sheet(win).findChild(QInputDialog)
    assert symbology is not None
    symbology.setTextValue("code128")
    symbology.accept()
    qapp.processEvents()

    content = _sheet(win).findChild(QInputDialog)
    assert content is not None
    content.setTextValue("ABC-123")
    content.accept()
    qapp.processEvents()

    barcodes = [i for i in win._canvas.items() if isinstance(i, BarcodeItem)]
    assert len(barcodes) == 1
    assert barcodes[0].value == "ABC-123"
    win.close()


def test_error_message_uses_sheet(qapp, tmp_path):
    win = _window(qapp)
    bad = tmp_path / "kaputt.png"
    bad.write_bytes(b"das ist kein bild")

    win._on_image_dropped(str(bad), QPointF(0, 0))
    qapp.processEvents()

    sheet = _sheet(win)
    assert sheet is not None
    assert sheet.findChild(QMessageBox) is not None
    win.close()


def test_unsaved_question_buttons_have_icons(qapp):
    parent = QWidget()
    parent.resize(1100, 760)
    parent.show()
    choices: list[str] = []
    ask_save(parent, title="Test", text="Ungespeichert", on_choice=choices.append)
    box = parent.findChild(QMessageBox)
    assert box is not None
    buttons = {button.text(): button for button in box.buttons()}
    for label in ("Speichern", "Verwerfen", "Abbrechen"):
        assert not buttons[label].icon().isNull()
    parent.close()


# -- macOS: Systemdialoge statt Overlay ---------------------------------------
def _native_dialog(win, kind):
    """Der Dialog, den ein Mac-Helfer als Kind des Hauptfensters geoeffnet hat."""
    dialogs = [d for d in win.findChildren(kind) if d.isVisible()]
    assert len(dialogs) == 1
    return dialogs[0]


def test_mac_file_dialog_is_a_native_window_sheet(qapp, tmp_path, platform):
    platform("darwin")
    win = _window(qapp)
    chosen: list[str | None] = []
    handle = choose_file(
        win,
        caption="Bild wählen",
        name_filter="Bilder (*.png);;Alle Dateien (*)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
    )
    qapp.processEvents()

    dialog = _native_dialog(win, QFileDialog)
    assert not dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.parentWidget() is win
    assert dialog.isWindow()
    assert win.findChildren(Sheet) == []

    target = tmp_path / "probe.png"
    Image.new("RGB", (8, 8), "white").save(target)
    _pick_file(qapp, dialog, str(target))

    assert chosen == [str(target)]
    assert not handle.isVisible()
    win.close()


def test_mac_file_dialog_cancel_reports_none(qapp, tmp_path, platform):
    platform("darwin")
    win = _window(qapp)
    chosen: list[str | None] = []
    closed: list[bool] = []
    handle = choose_file(
        win,
        caption="Öffnen",
        name_filter="Alle Dateien (*)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
    )
    handle.closed.connect(lambda: closed.append(True))
    qapp.processEvents()

    _native_dialog(win, QFileDialog).reject()
    qapp.processEvents()

    assert chosen == [None]
    assert closed == [True]
    win.close()


def test_mac_save_dialog_proposes_the_name(qapp, tmp_path, platform):
    from ql_editor.sheet import save_file

    platform("darwin")
    win = _window(qapp)
    chosen: list[str | None] = []
    save_file(
        win,
        caption="Etikett speichern",
        name_filter="QLInux-Etiketten (*.qlx)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
        default_name="Unbenannt.qlx",
    )
    qapp.processEvents()

    dialog = _native_dialog(win, QFileDialog)
    assert dialog.acceptMode() == QFileDialog.AcceptMode.AcceptSave
    dialog.accept()
    qapp.processEvents()

    assert chosen == [str(tmp_path / "Unbenannt.qlx")]
    win.close()


def test_mac_message_uses_the_title_as_headline(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    closed: list[bool] = []
    handle = show_message(win, "warning", "USB-Zugriff", "Kein Zugriff.")
    handle.closed.connect(lambda: closed.append(True))
    qapp.processEvents()

    box = _native_dialog(win, QMessageBox)
    assert box.text() == "USB-Zugriff"
    assert box.informativeText() == "Kein Zugriff."
    assert box.windowModality() == Qt.WindowModality.WindowModal
    assert win.findChildren(Sheet) == []

    box.button(QMessageBox.StandardButton.Ok).click()
    qapp.processEvents()
    assert closed == [True]
    assert not handle.isVisible()
    win.close()


def test_mac_question_reports_the_clicked_choice(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    choices: list[str] = []
    ask_save(win, title="Speichern?", text="Ungespeichert", on_choice=choices.append)
    qapp.processEvents()

    box = _native_dialog(win, QMessageBox)
    buttons = {button.text(): button for button in box.buttons()}
    buttons["Verwerfen"].click()
    qapp.processEvents()

    assert choices == ["discard"]
    win.close()


def test_mac_question_escape_counts_as_cancel(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    choices: list[str] = []
    ask_save(win, title="Speichern?", text="Ungespeichert", on_choice=choices.append)
    qapp.processEvents()

    _native_dialog(win, QMessageBox).reject()
    qapp.processEvents()

    assert choices == ["cancel"]
    win.close()


def test_mac_text_input_returns_the_value(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    values: list[str] = []
    ask_text(win, title="Barcode", label="Inhalt", on_ok=values.append)
    qapp.processEvents()

    dialog = _native_dialog(win, QInputDialog)
    dialog.setTextValue("12345")
    dialog.accept()
    qapp.processEvents()

    assert values == ["12345"]
    win.close()


def test_linux_keeps_the_overlay_sheets(qapp, tmp_path, platform):
    platform("linux")
    win = _window(qapp)
    sheet = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()

    assert isinstance(sheet, Sheet)
    assert sheet.findChild(QMessageBox).isWindow() is False
    win.close()


def test_mac_dialog_answers_only_once_even_if_it_still_looks_visible(
    qapp, tmp_path, platform
):
    """Der Systemdialog meldet sich waehrend ``finished`` noch als sichtbar.

    Ein zweites ``reject()`` aus ``close_sheet`` liess die Aufrufer sonst
    zweimal antworten (beobachtet mit dem echten ``NSOpenPanel``).
    """
    platform("darwin")
    win = _window(qapp)
    chosen: list[str | None] = []
    choose_file(
        win,
        caption="Öffnen",
        name_filter="Alle Dateien (*)",
        on_selected=chosen.append,
        start_dir=str(tmp_path),
    )
    qapp.processEvents()
    dialog = _native_dialog(win, QFileDialog)
    dialog.isVisible = lambda: True

    dialog.reject()
    qapp.processEvents()

    assert chosen == [None]
    win.close()


def test_mac_opens_only_one_system_dialog_per_window(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    choices: list[str] = []
    ask_save(win, title="Erste", text="Text", on_choice=choices.append)
    qapp.processEvents()
    show_message(win, "info", "Zweite", "Text")
    qapp.processEvents()

    boxes = [b for b in win.findChildren(QMessageBox) if b.isVisible()]
    assert [b.text() for b in boxes] == ["Zweite"]
    assert choices == ["cancel"]
    win.close()


def test_mac_selectable_message_stays_a_qt_dialog(qapp, platform):
    platform("darwin")
    win = _window(qapp)
    show_message(win, "warning", "Befehl", "sudo tee /etc/x", selectable=True)
    qapp.processEvents()

    box = _native_dialog(win, QMessageBox)
    assert box.testOption(QMessageBox.Option.DontUseNativeDialog)
    win.close()


def test_mac_dialog_handle_survives_a_deleted_window(qapp, platform):
    """Sprachwechsel baut das Fenster ab: das Handle darf dann nicht abstuerzen."""
    import shiboken6

    platform("darwin")
    win = _window(qapp)
    handle = show_message(win, "info", "Titel", "Text")
    qapp.processEvents()
    box = _native_dialog(win, QMessageBox)
    win.close()
    shiboken6.delete(box)

    assert handle.isVisible() is False
    handle.close_sheet()
