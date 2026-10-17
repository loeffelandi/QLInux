"""GUI-Tests (PySide6, headless via Offscreen-Plattform).

Prueft die Verschaltung von Media-Panel, Canvas und Vorschau sowie die
Randbegrenzung. Es wird kein Drucker benoetigt.
"""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QSettings, Qt

from ql_editor import media
from ql_editor.canvas import ROTATE_OFFSET_PX, LabelCanvas
from ql_editor.items import BarcodeItem, QRItem, TextItem, item_from_dict
from ql_editor.media import get_label
from ql_editor.printer import RESOLUTION_HIGH, RESOLUTION_STANDARD

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    QSettings("QLInux", "QLInux").clear()
    yield
    QSettings("QLInux", "QLInux").clear()


# --------------------------------------------------------------------------- #
# MediaPanel
# --------------------------------------------------------------------------- #
def test_media_panel_defaults(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert panel.model_id() == media.DEFAULT_MODEL
    assert panel.label_id() == media.DEFAULT_LABEL
    assert panel.auto_length() is True
    # Auto-Laenge: minimaler Canvas = Modell-Minimum.
    width, height = panel.canvas_size()
    assert width == 554
    assert height == panel.model.min_max_length_dots[0]


def test_media_panel_shows_band_erkennen_only_where_it_works(qapp):
    """Der Knopf „Band erkennen" braucht einen Rueckkanal - den gibt es nur ueber USB.

    Deshalb steht er im Netzwerk gar nicht erst da (statt ausgegraut).
    """
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert panel.printer_config().backend == "network"
    assert not panel._printer_form.isRowVisible(panel._row_detect)

    panel.set_address("usb://0x04f9:0x209b")
    assert panel.printer_config().backend == "pyusb"
    assert panel._printer_form.isRowVisible(panel._row_detect)

    panel.set_address("/dev/usb/lp1")
    assert panel.printer_config().backend == "linux_kernel"
    assert panel._printer_form.isRowVisible(panel._row_detect)

    panel.set_address("tcp://192.168.178.62:9100")
    assert not panel._printer_form.isRowVisible(panel._row_detect)


def test_media_panel_emits_a_usb_search(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[bool] = []
    panel.usb_search_requested.connect(lambda: seen.append(True))
    panel._usb_button.click()
    assert seen == [True]


def test_usb_search_applies_the_only_printer_found(qapp, tmp_path, monkeypatch):
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(
        media_panel_module, "usb_devices", lambda: ["usb://0x04f9:0x209b"]
    )

    win._on_usb_search()

    assert win._media_panel.address() == "usb://0x04f9:0x209b"
    assert win._media_panel.printer_config().backend == "pyusb"


def test_usb_search_switches_the_model_from_the_usb_id(qapp, tmp_path, monkeypatch):
    """Am USB haengt ein anderes Modell - die Kennung zieht das Modell nach."""
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_model("QL-820NWB")
    monkeypatch.setattr(
        media_panel_module, "usb_devices", lambda: ["usb://0x04f9:0x2042"]
    )

    win._on_usb_search()

    assert win._media_panel.address() == "usb://0x04f9:0x2042"
    assert win._media_panel.model_id() == "QL-700"
    assert win._media_panel.printer_config().model == "QL-700"


def test_usb_search_keeps_the_model_when_it_is_unknown(qapp, tmp_path, monkeypatch):
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_model("QL-820NWB")
    monkeypatch.setattr(
        media_panel_module, "usb_devices", lambda: ["usb://0x04f9:0x9999"]
    )

    win._on_usb_search()

    assert win._media_panel.model_id() == "QL-820NWB"


# --------------------------------------------------------------------------- #
# Druckerauswahl: Anschluss waehlen statt Adresse auswendig lernen
# --------------------------------------------------------------------------- #
def test_media_panel_asks_only_for_the_ip(qapp):
    """Netzwerk: nur die IP eintippen - Praefix und Port ergaenzt die App."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel._host_edit.setText("192.168.178.77")

    assert panel.address() == "tcp://192.168.178.77:9100"
    assert panel.printer_config().backend == "network"


def test_media_panel_switches_between_network_and_usb_rows(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_NETWORK, CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_devices", lambda: [])
    panel = MediaPanel()
    assert panel.connection() == CONNECTION_NETWORK
    assert panel._printer_form.isRowVisible(panel._row_host)
    assert not panel._printer_form.isRowVisible(panel._row_usb)

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.connection() == CONNECTION_USB
    assert not panel._printer_form.isRowVisible(panel._row_host)
    assert panel._printer_form.isRowVisible(panel._row_usb)
    # Ohne Geraet gibt es keine Adresse - und der Druckdialog sagt das dann.
    assert panel.address() == ""


def test_media_panel_restores_a_network_address_from_settings(qapp):
    from ql_editor.media_panel import CONNECTION_NETWORK, MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.99:9100")

    assert panel.connection() == CONNECTION_NETWORK
    assert panel._host_edit.text() == "192.168.178.99"
    assert panel.address() == "tcp://192.168.178.99:9100"


def test_media_panel_usb_switch_finds_and_applies_the_device(qapp, monkeypatch):
    """Anschluss auf USB stellen genuegt: das Geraet wird gefunden und uebernommen."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(
        media_panel_module, "usb_devices", lambda: ["usb://0x04f9:0x2042"]
    )
    panel = MediaPanel()
    panel.set_model("QL-820NWB")

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.connection() == CONNECTION_USB
    assert panel.address() == "usb://0x04f9:0x2042"
    assert panel.model_id() == "QL-700"


def test_media_panel_usb_placeholder_is_not_an_address(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel, USB_PLACEHOLDER

    monkeypatch.setattr(
        media_panel_module,
        "usb_devices",
        lambda: ["usb://0x04f9:0x2042", "/dev/usb/lp1"],
    )
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel._usb_combo.currentText() == USB_PLACEHOLDER
    assert panel.address() == ""


def test_media_panel_keeps_a_stored_usb_address_when_unplugged(qapp, monkeypatch):
    """Beim Laden der Einstellungen darf eine Adresse nicht verloren gehen."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_devices", lambda: [])
    panel = MediaPanel()
    panel.set_address("usb://0x04f9:0x2042")

    assert panel.connection() == CONNECTION_USB
    assert panel.address() == "usb://0x04f9:0x2042"

    panel.refresh_usb_devices()  # Geraet ist inzwischen abgezogen

    assert panel.address() == "usb://0x04f9:0x2042"
    assert "nicht angeschlossen" in panel._usb_combo.currentText()


def test_media_panel_offers_access_help_when_rights_are_missing(qapp, monkeypatch):
    """Ohne Rechte am Geraet steht im Panel, was zu tun ist."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_devices", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "usb_access", lambda address: False)
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.access_allowed is False
    assert panel._printer_form.isRowVisible(panel._row_access)
    assert "Kein Zugriff" in panel._access_label.text()

    requested = []
    panel.usb_permission_requested.connect(lambda: requested.append(True))
    panel._access_button.click()
    assert requested == [True]


def test_media_panel_hides_access_help_when_the_device_works(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_devices", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "usb_access", lambda address: True)
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.access_allowed is True
    assert not panel._printer_form.isRowVisible(panel._row_access)


def test_media_panel_refresh_access_follows_the_new_state(qapp, monkeypatch):
    """Nach dem Einrichten der Regel verschwindet der Hinweis."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    allowed = {"value": False}
    monkeypatch.setattr(media_panel_module, "usb_devices", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(
        media_panel_module, "usb_access", lambda address: allowed["value"]
    )
    panel = MediaPanel()
    panel._conn_buttons[CONNECTION_USB].setChecked(True)
    assert panel._printer_form.isRowVisible(panel._row_access)

    allowed["value"] = True
    assert panel.refresh_access() is True
    assert not panel._printer_form.isRowVisible(panel._row_access)


def test_media_panel_has_no_access_row_for_network(qapp):
    """Im Netzwerk gibt es keine Geraeterechte - also auch keinen Hinweis."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.62:9100")

    assert panel.access_allowed is None
    assert not panel._printer_form.isRowVisible(panel._row_access)


def test_detect_button_only_works_where_readback_is_possible(qapp):
    """Band-Erkennung braucht einen Rueckkanal - nur USB hat einen."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert not panel._printer_form.isRowVisible(panel._row_detect)  # Netzwerk

    panel.set_address("usb://0x04f9:0x2042")
    assert panel._printer_form.isRowVisible(panel._row_detect)  # USB

    panel.set_address("tcp://192.168.178.62:9100")
    assert not panel._printer_form.isRowVisible(panel._row_detect)


def test_media_panel_finished_vs_content(qapp):
    from ql_editor.media_panel import MediaPanel
    from ql_editor.media import LengthMode

    panel = MediaPanel()
    panel._auto_check.setChecked(False)
    panel._length_spin.setValue(40)

    panel._mode_combo.setCurrentIndex(panel._mode_combo.findData(LengthMode.FINISHED.value))
    assert panel.canvas_size() == (554, 389)

    panel._mode_combo.setCurrentIndex(panel._mode_combo.findData(LengthMode.CONTENT.value))
    assert panel.canvas_size() == (554, 472)


def test_media_panel_model_switch_repopulates_bands(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    # 102 mm ist nur auf QL-1050/1060N erlaubt -> nicht bei QL-820NWB.
    assert panel._band_combo.findData("102") == -1
    idx = panel._model_combo.findData("QL-1050")
    panel._model_combo.setCurrentIndex(idx)
    assert panel._band_combo.findData("102") != -1


def test_media_panel_margins_from_feed_margin(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    margins = panel.margins()
    assert margins.left == 0.0 and margins.right == 0.0
    # Der Spinbox rundet auf 1 Nachkommastelle.
    assert margins.top == pytest.approx(get_label("50").feed_margin_mm, abs=0.1)


# --------------------------------------------------------------------------- #
# Canvas
# --------------------------------------------------------------------------- #
def test_canvas_printable_rect_is_exact_width(qapp):
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    printable = canvas.printable_rect()
    assert printable.width() == 554
    assert printable.height() == 472
    # Die Szene selbst (Renderquelle) bleibt exakt die Designflaeche ...
    assert canvas.scene().sceneRect() == printable
    # ... der View zeigt ringsum eine Arbeitsflaeche (Scrollbereich).
    assert canvas.sceneRect().width() > printable.width()
    assert canvas.sceneRect().height() > printable.height()


def test_canvas_tape_rect_includes_side_border(qapp):
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    tape = canvas.tape_rect()
    assert tape.width() == pytest.approx(554 + 2 * label.side_border_dots)


def test_items_are_clamped_to_printable_area(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("x")
    canvas.add_item(item)

    printable = canvas.printable_rect()
    item.setPos(10_000, 10_000)
    br = item.sceneBoundingRect()
    assert br.right() <= printable.right() + 1
    assert br.bottom() <= printable.bottom() + 1

    item.setPos(-10_000, -10_000)
    br = item.sceneBoundingRect()
    assert br.left() >= printable.left() - 1
    assert br.top() >= printable.top() - 1


def test_canvas_item_serialization_roundtrip(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    canvas.add_item(TextItem("Hallo"))
    canvas.add_item(QRItem("https://example.org", 120))
    data = canvas.items_serialized()
    assert {d["type"] for d in data} == {"text", "qr"}

    canvas.clear_items()
    assert canvas.items_serialized() == []
    canvas.load_items(data)
    assert len(canvas.items_serialized()) == 2


def test_item_from_dict_unknown_type():
    with pytest.raises(ValueError):
        item_from_dict({"type": "nope"})


def test_barcode_item_invalid_value_raises(qapp):
    with pytest.raises(ValueError):
        BarcodeItem("not-a-number", "ean13")


# --------------------------------------------------------------------------- #
# MainWindow
# --------------------------------------------------------------------------- #
def test_mainwindow_render_matches_canvas(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._media_panel._auto_check.setChecked(False)
    win._media_panel._length_spin.setValue(40)
    win._media_panel._mode_combo.setCurrentIndex(
        win._media_panel._mode_combo.findData("finished")
    )
    win._on_media_changed()
    win._add_text()
    win._recompute_canvas()
    image = win._current_render()
    assert image.width == 554
    assert image.height == win._canvas.height_dots


def test_canvas_print_preview_mode(qapp):
    from PIL import Image
    from PySide6.QtCore import QPointF

    from ql_editor.preview import binarize, to_qimage

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(40, 60)

    assert canvas.print_preview is False
    assert canvas.isInteractive() is True

    canvas.set_print_preview(True)
    assert canvas.print_preview is True
    assert canvas.isInteractive() is False
    assert canvas.selected_items() == []

    # Im Vorschau-Modus darf die Maus keine Items bewegen.
    before = QPointF(item.pos())
    center = item.sceneBoundingRect().center()
    _press(canvas, center)
    _drag_to(canvas, QPointF(center.x() + 50, center.y() + 40))
    _release(canvas, QPointF(center.x() + 50, center.y() + 40))
    assert item.pos() == before

    canvas.set_print_image(to_qimage(binarize(Image.new("L", (10, 10), 128))))
    assert canvas._print_image is not None

    canvas.set_print_preview(False)
    assert canvas.print_preview is False
    assert canvas.isInteractive() is True


def test_canvas_print_preview_paints(qapp):
    """Regression: das Zeichnen der Vorschau darf nicht abstuerzen."""
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(900, 650)
    win.show()
    qapp.processEvents()
    win._add_text()
    win._act_print_preview.setChecked(True)
    qapp.processEvents()

    pixmap = win._canvas.grab()
    assert not pixmap.isNull()


def test_canvas_print_preview_esc_requests_exit(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = _prepared_canvas(qapp)
    seen: list[int] = []
    canvas.print_preview_exit_requested.connect(lambda: seen.append(1))
    canvas.set_print_preview(True)

    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert seen == [1]

    # Ausserhalb des Vorschau-Modus darf Esc das Signal nicht ausloesen.
    canvas.set_print_preview(False)
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert seen == [1]


# --------------------------------------------------------------------------- #
# Inline-Bearbeitung / Interaktion
# --------------------------------------------------------------------------- #
def test_text_item_inline_editing(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("Hallo")
    canvas.add_item(item)
    assert item.is_editing is False
    item.start_editing()
    assert item.is_editing is True
    assert item.textCursor().hasSelection() is True  # Doppelklick markiert alles
    item.finish_editing()
    assert item.is_editing is False


def test_escape_ends_inline_editing(qapp):
    """Esc beendet die Bearbeitung (Qt laesst das Textfeld sonst offen)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo")
    canvas.add_item(item)
    item.start_editing()
    assert item.is_editing is True

    canvas.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert item.is_editing is False
    assert item.isSelected() is False


def test_new_text_is_empty_and_not_selected(qapp):
    """Doppelklick legt ein leeres Feld an - nichts ist markiert."""
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    item = win._new_text(QPointF(50, 50))
    qapp.processEvents()

    assert item.is_editing is True
    assert item.toPlainText() == ""
    assert item.textCursor().hasSelection() is False  # leeres Feld: nichts zu markieren
    # Sofort tippen schreibt den eigenen Text.
    item.textCursor().insertText("Hallo")
    assert item.toPlainText() == "Hallo"


def test_double_click_selects_existing_text(qapp):
    """Im offenen Text markiert der Doppelklick weiterhin alles."""
    from PySide6.QtCore import QEvent, QPointF, Qt

    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo Band", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    canvas.cancel_editing()

    click = item.mapToScene(QPointF(120, 20))
    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            click,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    cursor = item.textCursor()
    assert item.is_editing is True
    assert cursor.hasSelection() is True
    assert cursor.selectedText() == "Hallo Band"

    # Tippen ersetzt den markierten Text (Umbenennen-Verhalten).
    cursor.insertText("Neu")
    assert item.toPlainText() == "Neu"

    # Zweiter Doppelklick im offenen Feld markiert wieder alles.
    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            item.mapToScene(QPointF(20, 20)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert item.textCursor().hasSelection() is True
    assert item.textCursor().selectedText() == "Neu"


def test_empty_text_field_is_discarded_when_editing_ends(qapp):
    """Leer gebliebene Felder verschwinden (kein unsichtbares Objekt)."""
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win._new_text(QPointF(50, 50))
    qapp.processEvents()
    win._canvas.cancel_editing()
    qapp.processEvents()
    assert [i for i in win._canvas.scene().items() if isinstance(i, TextItem)] == []


def test_text_field_with_content_survives_editing(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    item = win._new_text(QPointF(50, 50))
    item.textCursor().insertText("Bleibt")
    win._canvas.cancel_editing()
    qapp.processEvents()
    texts = [i for i in win._canvas.scene().items() if isinstance(i, TextItem)]
    assert [i.toPlainText() for i in texts] == ["Bleibt"]


def _force_focus(window):
    """Fenster und Canvas wirklich fokussieren (offscreen sonst nicht).

    Genau dieser Fokus ist der Unterschied: ``setTextInteractionFlags`` nimmt
    einem **fokussierten** Feld den Fokus - ohne Fokus passiert nichts.
    """
    import warnings

    from PySide6.QtWidgets import QApplication

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        QApplication.setActiveWindow(window)
    window.setFocus()
    QApplication.processEvents()


def test_rendering_does_not_discard_a_new_text_field(qapp, tmp_path):
    """Regression: der Refresh nach dem Anlegen verwarf das leere Textfeld.

    ``LabelCanvas.suspend_text_caret`` blendet die Textmarke fuers Rendern aus.
    Frueher geschah das ueber die Interaktionsflags (``NoTextInteraction``) -
    das nimmt dem Feld den Fokus, beendet die Bearbeitung, und die App warf das
    gerade angelegte (noch leere) Feld sofort wieder weg. Jetzt blendet das
    Item die Marke selbst aus; Fokus und Bearbeitung bleiben unberuehrt.
    """
    from PySide6.QtCore import QPointF

    win = _temp_window(qapp, tmp_path)
    _force_focus(win)
    item = win._new_text(QPointF(60, 60))
    finished: list[bool] = []
    item.editing_finished.connect(lambda: finished.append(True))

    # Genau das, was der Refresh-Timer nach dem Anlegen tut.
    for _ in range(3):
        win._refresh_now()
        qapp.processEvents()

    assert finished == []
    assert item.is_editing is True
    assert item.scene() is not None
    assert win._canvas.scene().focusItem() is item


def test_suspend_text_caret_leaves_focus_and_editing_alone(qapp):
    """Textmarke ausblenden ohne die Interaktionsflags anzufassen."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(30, 30)
    item.start_editing()

    with canvas.suspend_text_caret():
        assert item.caret_hidden is True
        assert item.is_editing is True
        assert canvas.scene().focusItem() is item

    assert item.caret_hidden is False
    assert item.is_editing is True
    assert canvas.scene().focusItem() is item


def test_render_has_no_caret_and_no_selection(qapp):
    """Das Druckbild enthaelt weder Textmarke noch Auswahl."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(30, 30)
    canvas.cancel_editing()
    idle = canvas.render_printable()

    item.start_editing()  # markiert alles und setzt die Textmarke
    assert item.textCursor().hasSelection() is True
    editing = canvas.render_printable()

    assert editing.tobytes() == idle.tobytes()


def test_double_click_on_empty_canvas_requests_new_text(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt

    canvas = _prepared_canvas(qapp)
    seen: list[QPointF] = []
    canvas.text_requested.connect(seen.append)

    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            QPointF(200, 150),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert len(seen) == 1
    assert seen[0].x() == pytest.approx(200, abs=1)
    assert seen[0].y() == pytest.approx(150, abs=1)


def test_apply_resize_for_all_types(qapp):
    from PySide6.QtGui import QPixmap

    from ql_editor.items import BarcodeItem, ImageItem, LineItem, QRItem, RectItem

    qr = QRItem("x", 100)
    qr.apply_resize(200, 180)
    assert qr.boundingRect().width() == pytest.approx(180, abs=2)

    rect = RectItem()
    rect.apply_resize(150, 60)
    assert rect.rect().width() == pytest.approx(150)
    assert rect.rect().height() == pytest.approx(60)

    line = LineItem()
    line.apply_resize(120, 40)
    assert line.line().x2() == pytest.approx(120)

    image = ImageItem(QPixmap(40, 20))
    image.apply_resize(80, 40)
    assert image.sceneBoundingRect().width() == pytest.approx(80, abs=1)

    barcode = BarcodeItem("ABC123", "code128", height_dots=100)
    barcode.apply_resize(300, 200)
    assert barcode.boundingRect().height() == pytest.approx(200, abs=3)

    text = TextItem("Hi", font_pixel_size=40)
    text.apply_resize(300, 80)
    assert text.boundingRect().height() == pytest.approx(80, abs=8)


def test_canvas_handle_only_for_single_resizable_item(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    assert canvas._handle_scene_rect() is None

    first = TextItem("a")
    canvas.add_item(first)
    assert canvas._handle_scene_rect() is not None

    second = TextItem("b")
    canvas.add_item(second)  # Auswahl wechselt auf second
    first.setSelected(True)  # jetzt zwei ausgewaehlt
    assert canvas._handle_scene_rect() is None


def test_canvas_keyboard_delete_and_nudge(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("x")
    canvas.add_item(item)
    item.setPos(50, 50)

    nudge = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(nudge)
    assert item.pos().x() == pytest.approx(51)

    delete = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(delete)
    assert canvas.items_serialized() == []


def test_inspector_shows_only_selected_kind(qapp):
    from ql_editor.inspector import InspectorPanel
    from ql_editor.items import QRItem

    inspector = InspectorPanel()
    inspector.set_item(TextItem("x"))
    assert inspector._title.text() == "Text"
    inspector.set_item(QRItem("y", 100))
    assert inspector._title.text() == "QR-Code"
    inspector.set_item(None)
    assert inspector._title.text() == "Nichts ausgewählt"


def test_mainwindow_double_click_creates_text(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win._on_text_requested(QPointF(30, 30))
    texts = [i for i in win._canvas.scene().items() if isinstance(i, TextItem)]
    assert len(texts) == 1
    assert texts[0].is_editing is True


def test_mainwindow_print_preview_action(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    win._add_text()

    act = win._act_print_preview
    assert act.isCheckable()
    assert win._canvas.print_preview is False

    act.setChecked(True)
    assert win._canvas.print_preview is True
    assert win._canvas._print_image is not None
    assert not win._canvas._print_image.isNull()

    act.setChecked(False)
    assert win._canvas.print_preview is False
    assert win._canvas._print_image is None


def test_print_preview_exit_signal_unchecks_action(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._act_print_preview.setChecked(True)
    assert win._canvas.print_preview is True

    win._canvas.print_preview_exit_requested.emit()
    assert win._act_print_preview.isChecked() is False
    assert win._canvas.print_preview is False


# --------------------------------------------------------------------------- #
# Scrollen / Zoomen / Wheel-Guard
# --------------------------------------------------------------------------- #
def _wheel_event(modifiers, dy, dx=0, x=100, y=100):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    pos = QPointF(x, y)
    return QWheelEvent(
        pos, pos, QPoint(dx, dy), QPoint(dx, dy),
        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_wheel_guard_prevents_unfocused_change(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSpinBox, QVBoxLayout, QWidget

    from ql_editor.widgets import install_wheel_guard_recursive

    host = QWidget()
    layout = QVBoxLayout(host)
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    layout.addWidget(spin)
    install_wheel_guard_recursive(host)

    qapp.sendEvent(spin, _wheel_event(Qt.KeyboardModifier.NoModifier, 120))
    assert spin.value() == 10


def test_canvas_wheel_zooms_when_nothing_to_scroll(qapp):
    from PySide6.QtCore import Qt

    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    before = canvas.transform().m11()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, 120))
    assert canvas.transform().m11() > before


def test_canvas_wheel_scrolls_when_zoomed(qapp):
    import time

    from PySide6.QtCore import Qt

    canvas = LabelCanvas()
    canvas.resize(300, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 1400, refit=False)
    canvas.zoom_by(2.0)
    qapp.processEvents()

    vbar = canvas.verticalScrollBar()
    assert vbar.maximum() > 0
    before = vbar.value()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, -120))

    # Weiches Scrollen laeuft animiert -> kurz den Event-Loop bedienen.
    deadline = time.monotonic() + 2.0
    while vbar.value() == before and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert vbar.value() != before


def test_smooth_scroll_area_wheel_scrolls_and_guard_keeps_value(qapp):
    """Rad ueber einem Feld scrollt das Panel, ohne den Feldwert zu aendern."""
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSpinBox, QVBoxLayout, QWidget

    from ql_editor.widgets import SmoothScrollArea, install_wheel_guard_recursive

    content = QWidget()
    layout = QVBoxLayout(content)
    first = QSpinBox()
    first.setRange(0, 100)
    first.setValue(10)
    layout.addWidget(first)
    others = []
    for _ in range(40):
        spin = QSpinBox()
        others.append(spin)
        layout.addWidget(spin)

    area = SmoothScrollArea()
    area.setWidgetResizable(True)
    area.resize(200, 120)
    area.setWidget(content)
    area.show()
    qapp.processEvents()
    install_wheel_guard_recursive(content)

    target = others[5]  # nicht das Fokus-Widget
    target.clearFocus()
    assert not target.hasFocus()

    vbar = area.verticalScrollBar()
    assert vbar.maximum() > 0
    before = vbar.value()
    qapp.sendEvent(target, _wheel_event(Qt.KeyboardModifier.NoModifier, -120))

    deadline = time.monotonic() + 2.0
    while vbar.value() == before and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert vbar.value() != before  # Panel scrollt
    assert target.value() == 0     # Feldwert bleibt


def test_side_panels_use_smooth_scroll_area(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.widgets import SmoothScrollArea

    win = MainWindow()
    assert len(win.findChildren(SmoothScrollArea)) >= 3


def test_open_panels_are_roomy(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import PANEL_WIDTH

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    assert win._left_panel.docked and win._right_panel.docked
    assert win._left_panel.visible_width == PANEL_WIDTH
    assert win._right_panel.visible_width == PANEL_WIDTH
    assert win._media_panel.minimumWidth() >= 200
    assert win._inspector.minimumWidth() >= 240


def test_set_label_height_change_keeps_zoom(qapp):
    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    canvas.zoom_by(2.0)
    zoom = canvas.transform().m11()
    canvas.set_label(get_label("50"), 900)  # nur Hoehe -> kein Refit
    assert canvas.transform().m11() == pytest.approx(zoom)


def test_canvas_zoom_actions_emit_zoom_changed(qapp):
    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    seen: list[float] = []
    canvas.zoom_changed.connect(seen.append)
    canvas.zoom_in()
    assert seen and seen[-1] > 0


# --------------------------------------------------------------------------- #
# Responsivitaet
# --------------------------------------------------------------------------- #
def test_canvas_refits_on_window_resize(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    zoom_big = win._canvas.transform().m11()

    win.resize(760, 560)
    qapp.processEvents()
    assert win._canvas._auto_fit is True
    assert win._canvas.transform().m11() < zoom_big


def test_manual_zoom_persists_across_resize(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    win._canvas.zoom_in()
    win._canvas.zoom_in()
    zoom = win._canvas.transform().m11()

    win.resize(900, 700)
    qapp.processEvents()
    assert win._canvas._auto_fit is False
    assert win._canvas.transform().m11() == pytest.approx(zoom)


def test_side_panels_are_scrollable(qapp):
    from PySide6.QtWidgets import QScrollArea

    from ql_editor.app import MainWindow

    win = MainWindow()
    # linkes Panel + Inspector + Vorschau/Druck = mindestens 3 Scrollbereiche
    assert len(win.findChildren(QScrollArea)) >= 3
    assert win.minimumWidth() <= 760


# --------------------------------------------------------------------------- #
# Moderne Maus-Bearbeitung: Verschieben, Groesse, Drehen, Snapping, Drag&Drop
# --------------------------------------------------------------------------- #
def _mouse_event(kind, canvas, scene_pos, button, buttons, mods):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    vp = canvas.mapFromScene(scene_pos)
    return QMouseEvent(kind, QPointF(vp), QPointF(vp), button, buttons, mods)


def _press(canvas, scene_pos, mods=None):
    from PySide6.QtCore import QEvent, Qt

    mods = Qt.KeyboardModifier.NoModifier if mods is None else mods
    canvas.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, canvas, scene_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)
    )


def _drag_to(canvas, scene_pos, mods=None):
    from PySide6.QtCore import QEvent, Qt

    mods = Qt.KeyboardModifier.NoModifier if mods is None else mods
    canvas.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, canvas, scene_pos, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, mods)
    )


def _release(canvas, scene_pos):
    from PySide6.QtCore import QEvent, Qt

    canvas.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, canvas, scene_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    )


def _prepared_canvas(qapp):
    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 472)
    return canvas


def test_canvas_has_eight_handles_and_rotate(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)

    points = canvas._handle_points(item)
    assert set(points) == {"nw", "n", "ne", "e", "se", "s", "sw", "w"}
    assert canvas._handle_at(points["se"]) == ("se", item)
    rotate = canvas._handle_at(canvas._rotate_handle_point(item))
    assert rotate is not None and rotate[0] == "rotate"


def test_canvas_drag_moves_item(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(40, 60)

    changed: list[int] = []
    canvas.items_changed.connect(lambda: changed.append(1))

    before = QPointF(item.pos())
    start = item.sceneBoundingRect().center()
    target = QPointF(start.x() + 60, start.y() + 40)
    _press(canvas, start)
    _drag_to(canvas, target)
    _release(canvas, target)

    assert item.pos().x() - before.x() == pytest.approx(60, abs=7)
    assert item.pos().y() - before.y() == pytest.approx(40, abs=7)
    assert changed == [1]


def test_canvas_resize_nw_keeps_opposite_corner(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(60, 80)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    b0 = item.sceneBoundingRect()
    nw = canvas._handle_points(item)["nw"]
    target = QPointF(nw.x() - 25, nw.y() - 18)
    _press(canvas, nw)
    _drag_to(canvas, target)
    _release(canvas, target)

    b1 = item.sceneBoundingRect()
    assert b1.right() == pytest.approx(b0.right(), abs=1.5)
    assert b1.bottom() == pytest.approx(b0.bottom(), abs=1.5)
    assert b1.width() > b0.width()


def test_canvas_resize_se_keeps_top_left(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(60, 80)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    b0 = item.sceneBoundingRect()
    se = canvas._handle_points(item)["se"]
    target = QPointF(se.x() + 20, se.y() + 15)
    _press(canvas, se)
    _drag_to(canvas, target)
    _release(canvas, target)

    b1 = item.sceneBoundingRect()
    assert b1.left() == pytest.approx(b0.left(), abs=0.5)
    assert b1.top() == pytest.approx(b0.top(), abs=0.5)
    assert b1.width() > b0.width()


def test_rotate_handle_shows_a_rotation_cursor(qapp):
    """Am Drehgriff zeigt der Zeiger ein Rotations-Symbol, kein Fadenkreuz.

    Qt hat keinen Rotations-Cursor - er wird wie die Icons gezeichnet und als
    Pixmap-Zeiger gesetzt (siehe :func:`ql_editor.icons.cursor`).
    """
    from PySide6.QtCore import QEvent, Qt

    from ql_editor import icons

    canvas = _prepared_canvas(qapp)
    item = TextItem("drehen", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(100, 120)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    canvas.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            canvas,
            canvas._rotate_handle_point(item),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    cursor = canvas.viewport().cursor()
    assert cursor.shape() == Qt.CursorShape.BitmapCursor
    assert cursor.pixmap().width() == icons.CURSOR_SIZE

    # Ueber einem Groessen-Griff bleibt es beim System-Cursor.
    east = canvas._handle_points(item)["e"]
    canvas.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            canvas,
            east,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.SizeHorCursor


def test_rotation_cursor_is_cached_and_unknown_names_raise(qapp):
    from ql_editor import icons

    assert icons.cursor("rotate") is icons.cursor("rotate")
    with pytest.raises(KeyError):
        icons.cursor("gibt-es-nicht")


def test_canvas_rotate_handle(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(100, 120)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    assert item.rotation() == pytest.approx(0)
    center = item.mapToScene(item.boundingRect().center())
    handle = canvas._rotate_handle_point(item)
    _press(canvas, handle)
    _drag_to(canvas, QPointF(center.x() + 120, center.y()))
    _release(canvas, QPointF(center.x() + 120, center.y()))

    assert item.rotation() == pytest.approx(90, abs=12)


def test_canvas_move_snaps_to_center_with_guide(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    other = TextItem("a", font_pixel_size=20)
    canvas.add_item(other)
    other.setPos(30, 30)

    item = TextItem("b", font_pixel_size=20)
    canvas.add_item(item)
    item.setPos(30, 200)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    center_y = canvas.printable_rect().center().y()
    start = item.sceneBoundingRect().center()
    target = QPointF(start.x(), center_y - 2)
    _press(canvas, start)
    _drag_to(canvas, target)
    axes = {axis for axis, _ in canvas._guides}
    _release(canvas, target)

    assert "h" in axes
    assert item.sceneBoundingRect().center().y() == pytest.approx(center_y, abs=0.6)


def test_canvas_small_drag_does_not_stick_to_own_edges(qapp):
    """Regression: ein bewegtess Item darf nicht an seiner eigenen alten Kante einrasten."""
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(120, 130)

    start = item.sceneBoundingRect().center()
    target = QPointF(start.x() + 3, start.y() + 3)
    _press(canvas, start)
    _drag_to(canvas, target)
    _release(canvas, target)

    assert item.pos().x() == pytest.approx(123, abs=1.5)
    assert item.pos().y() == pytest.approx(133, abs=1.5)


def test_mainwindow_drop_image_and_text(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDropEvent
    from PIL import Image as PILImage

    from ql_editor.app import MainWindow
    from ql_editor.items import ImageItem

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    canvas = win._canvas

    path = tmp_path / "bild.png"
    PILImage.new("RGB", (40, 30), "black").save(path)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(
        QPointF(300, 200), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(ev)
    images = [i for i in canvas.scene().items() if isinstance(i, ImageItem)]
    assert len(images) == 1
    # am Mauszeiger zentriert
    center = images[0].sceneBoundingRect().center()
    assert center.x() == pytest.approx(canvas.mapToScene(300, 200).x(), abs=2)

    mime2 = QMimeData()
    mime2.setText("Hallo Welt")
    ev2 = QDropEvent(
        QPointF(120, 200), Qt.DropAction.CopyAction, mime2,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(ev2)
    texts = [i.to_dict().get("text") for i in canvas.scene().items() if getattr(i, "kind", None) == "text"]
    assert "Hallo Welt" in texts


def test_image_item_serialization_roundtrip(qapp):
    """Regression: Pixmap-Serialisierung muss ohne BytesIO funktionieren."""
    from PySide6.QtGui import QPixmap

    from ql_editor.items import ImageItem

    item = ImageItem(QPixmap(40, 20))
    data = item.to_dict()
    assert data["data_b64"]

    restored = item_from_dict(data)
    assert isinstance(restored, ImageItem)
    assert not restored.pixmap().isNull()
    assert restored.pixmap().width() == 40


# --------------------------------------------------------------------------- #
# Icons / icon-basiertes Menue
# --------------------------------------------------------------------------- #
def test_icons_render_for_all_names(qapp):
    from ql_editor import icons

    assert len(icons.available()) >= 15
    for name in icons.available():
        ic = icons.icon(name)
        assert not ic.isNull()
        assert not ic.pixmap(24, 24).isNull()


def test_icon_unknown_name_raises(qapp):
    from ql_editor import icons

    with pytest.raises(KeyError):
        icons.icon("gibt-es-nicht")


def test_icon_color_is_configurable(qapp):
    from PySide6.QtGui import QColor

    from ql_editor import icons

    red = icons.icon("print", QColor("#ff0000"))
    assert not red.isNull()


def test_toolbar_is_icon_only(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolBar, QWidgetAction

    from ql_editor.app import MainWindow

    win = MainWindow()
    bar = win.findChild(QToolBar)
    assert bar is not None
    assert bar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    actions = [
        a
        for a in bar.actions()
        if not a.isSeparator() and not isinstance(a, QWidgetAction)
    ]
    assert actions
    assert all(not a.icon().isNull() for a in actions)
    assert all(a.toolTip() for a in actions)


def test_no_menu_bar_but_hamburger_menu(qapp):
    """Es gibt keine Menueleiste mehr - alle Befehle liegen im Hamburger-Menue."""
    from PySide6.QtWidgets import QMenuBar, QToolBar, QToolButton, QWidgetAction

    from ql_editor.app import MainWindow

    win = MainWindow()
    assert win.findChild(QMenuBar) is None

    button = win.findChild(QToolButton, "main_menu_button")
    assert button is not None
    assert not button.icon().isNull()
    assert button.toolTip()
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup

    menu = button.menu()
    assert menu is not None
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert items
    assert all(not a.icon().isNull() for a in items)
    # Die Befehle werden mit der Toolbar geteilt (dieselben QActions).
    bar_actions = {
        a
        for a in win.findChild(QToolBar).actions()
        if not a.isSeparator() and not isinstance(a, QWidgetAction)
    }
    assert bar_actions <= set(items)


def test_menu_actions_have_icons(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    menu = win._menu_button.menu()
    assert menu is not None
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert len(items) >= 10
    assert all(not a.icon().isNull() for a in items)


def test_context_menu_has_icons(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    menu = win._build_context_menu(QPointF(10, 10))
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert items
    assert all(not a.icon().isNull() for a in items)


# --------------------------------------------------------------------------- #
# Ausrichtung (quer / laengs des Bandes)
# --------------------------------------------------------------------------- #
def test_panel_orientation_buttons_and_actions(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    across, along = panel.orientation_actions()
    assert (across.text(), along.text()) == ("Quer zum Band", "Längs des Bandes")
    assert across.isCheckable() and along.isCheckable()
    assert across.isChecked() and not along.isChecked()
    assert panel.orientation() is media.Orientation.ACROSS
    assert [b.isChecked() for b in panel._orientation_buttons] == [True, False]

    panel._orientation_buttons[1].click()
    assert panel.orientation() is media.Orientation.ALONG
    assert along.isChecked() and not across.isChecked()
    assert [b.isChecked() for b in panel._orientation_buttons] == [False, True]


def test_orientation_actions_are_exclusive_and_emit(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[str] = []
    panel.changed.connect(lambda: seen.append(panel.orientation().value))
    across, along = panel.orientation_actions()

    along.trigger()
    across.trigger()
    assert seen == ["along", "across"]
    assert across.isChecked() and not along.isChecked()


def test_orientation_ignored_when_unchanged(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[str] = []
    panel.changed.connect(lambda: seen.append("changed"))
    panel.set_orientation(media.Orientation.ACROSS)
    assert seen == []
    # Auch bei bereits gewaehlter Ausrichtung bleiben die Aktionen synchron.
    panel.orientation_actions()[1].setChecked(True)
    panel.set_orientation(media.Orientation.ACROSS)
    assert panel.orientation_actions()[0].isChecked() is True


def test_toolbar_has_no_orientation_buttons(qapp):
    from PySide6.QtWidgets import QToolBar

    from ql_editor.app import MainWindow

    win = MainWindow()
    bar = win.findChild(QToolBar)
    texts = {a.text() for a in bar.actions()}
    assert "Quer zum Band" not in texts
    assert "Längs des Bandes" not in texts


def test_orientation_is_in_hamburger_menu(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    items = win._menu_button.menu().actions()
    for act in win._media_panel.orientation_actions():
        assert act in items


def test_orientation_changes_canvas_and_print_image(qapp):
    from PySide6.QtCore import QSize

    from ql_editor.app import MainWindow

    win = MainWindow()
    # Auflösung festnageln: hier geht es um die Ausrichtung, nicht um 600 dpi.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_STANDARD.key)
    )
    win._new_text()
    win._canvas.cancel_editing()
    label = win._media_panel.label
    length = win._canvas.length_dots
    assert win._canvas.printable_rect().size().toSize() == QSize(label.width_dots, length)

    win._media_panel.set_orientation(media.Orientation.ALONG)
    assert win._canvas.printable_rect().size().toSize() == QSize(length, label.width_dots)
    assert win._canvas.length_dots == length
    # Das Druckbild ist in beiden Ausrichtungen bandbreit.
    assert win._for_print().size == (label.width_dots, length)

    # Im 600-dpi-Modus rendert die Designflaeche doppelt so fein - in beiden
    # Ausrichtungen, denn die feine Achse ist immer die Bandlaufrichtung.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    assert win._for_print().size == (label.width_dots * 2, length * 2)
    win._media_panel.set_orientation(media.Orientation.ACROSS)
    assert win._for_print().size == (label.width_dots * 2, length * 2)


def test_orientation_moves_side_border_to_tape_edges(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    label = win._media_panel.label
    win._media_panel.set_orientation(media.Orientation.ALONG)
    tape = win._canvas.tape_rect()
    printable = win._canvas.printable_rect()
    assert tape.top() == pytest.approx(-label.side_border_dots)
    assert tape.bottom() == pytest.approx(printable.bottom() + label.side_border_dots)
    assert tape.left() == pytest.approx(printable.left())
    assert tape.width() == pytest.approx(printable.width())


def test_print_preview_image_stays_canvas_aligned(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._new_text()
    win._canvas.cancel_editing()
    win._media_panel.set_orientation(media.Orientation.ALONG)
    win._act_print_preview.setChecked(True)
    win._refresh_now()
    image = win._canvas._print_image
    assert image is not None
    rect = win._canvas.printable_rect()
    assert image.width() == int(rect.width())
    assert image.height() == int(rect.height())


def test_panel_result_shows_real_content_length(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.items import TextItem

    win = MainWindow()
    win._add_item(TextItem("Hallo Welt", font_pixel_size=90))
    win._canvas.cancel_editing()
    assert "Inhalt" in win._media_panel._size_label.text()
    across = win._media_panel._size_label.text()

    win._media_panel.set_orientation(media.Orientation.ALONG)
    along = win._media_panel._size_label.text()
    assert across != along
    assert "längs des Bandes" == win._media_panel._orientation_label.text()


# --------------------------------------------------------------------------- #
# Seitenpanels: einklappen, Pfeil im Panel, Hover-Overlay
# --------------------------------------------------------------------------- #
def test_panel_actions_are_in_the_menu_not_the_toolbar(qapp):
    from PySide6.QtWidgets import QToolBar

    from ql_editor.app import MainWindow

    win = MainWindow()
    for act in (win._act_panel_left, win._act_panel_right):
        assert act.isCheckable() and act.isChecked()
        assert not act.icon().isNull()
        assert act.toolTip()
    assert win._act_panel_left.shortcut().toString() == "Ctrl+B"
    assert win._act_panel_right.shortcut().toString() == "Ctrl+Shift+B"

    bar = win.findChild(QToolBar)
    bar_actions = [a for a in bar.actions() if not a.isSeparator()]
    assert win._act_panel_left not in bar_actions
    assert win._act_panel_right not in bar_actions
    # Erreichbar bleiben sie im Hamburger-Menue (Shortcut-Wege).
    assert win._act_panel_left in win._menu_button.menu().actions()
    assert win._act_panel_right in win._menu_button.menu().actions()


def test_panel_arrow_sits_in_the_panel(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    qapp.processEvents()

    for panel in (win._left_panel, win._right_panel):
        assert panel._button.parent() is panel
        assert not panel._button.icon().isNull()
        # Der Pfeil liegt im schmalen Streifen, nicht im Inhalt.
        assert panel._strip_rect().contains(QPointF(panel._button.geometry().center()))
        assert panel._button.toolTip()
        assert panel.content.isVisible()


def test_collapsing_panel_gives_canvas_more_room(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    before = win._canvas.width()

    win._act_panel_right.setChecked(False)
    win._right_panel.finish_animation()
    qapp.processEvents()
    assert win._right_panel.docked is False
    assert win._right_panel.visible_width == STRIP_WIDTH
    assert win._canvas.width() > before
    # Der Streifen mit Pfeil bleibt erreichbar, der Inhalt ist weg.
    assert win._right_panel.width() == STRIP_WIDTH
    assert win._right_panel._button.isVisible()
    assert not win._right_panel.content.isVisible()

    win._act_panel_right.setChecked(True)
    win._right_panel.finish_animation()
    qapp.processEvents()
    assert win._right_panel.docked is True
    assert win._right_panel.content.isVisible()


def test_both_panels_can_be_collapsed(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()

    win._act_panel_left.setChecked(False)
    win._act_panel_right.setChecked(False)
    win._left_panel.finish_animation()
    win._right_panel.finish_animation()
    qapp.processEvents()
    # Der Canvas bekommt alles bis auf die beiden Streifen.
    assert win._canvas.width() == pytest.approx(win.width() - 2 * STRIP_WIDTH, abs=4)


def test_panel_arrow_keeps_action_in_sync(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()

    win._left_panel._button.click()
    qapp.processEvents()
    assert win._left_panel.docked is False
    assert win._act_panel_left.isChecked() is False

    win._left_panel._button.click()
    qapp.processEvents()
    assert win._left_panel.docked is True
    assert win._act_panel_left.isChecked() is True


def test_collapsed_panel_peeks_over_canvas_on_hover(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    win._act_panel_left.setChecked(False)
    win._left_panel.finish_animation()
    qapp.processEvents()
    canvas_width = win._canvas.width()
    expanded = win._left_panel.reserved_width

    # Hover auf dem Streifen -> Panel klappt als Overlay auf.
    win._left_panel.set_hovered(True)
    win._left_panel.finish_animation()
    qapp.processEvents()
    assert win._left_panel.peeking is True
    assert win._left_panel.visible_width == expanded
    assert win._left_panel.content.isVisible()
    # Der Canvas behaelt seine Breite: Overlay statt Verschieben.
    assert win._canvas.width() == canvas_width
    assert win._left_panel.canvas_reserved == STRIP_WIDTH

    # Mauszeiger weg -> wieder einklappen.
    win._left_panel.set_hovered(False)
    win._left_panel.finish_animation()
    qapp.processEvents()
    assert win._left_panel.peeking is False
    assert win._left_panel.visible_width == STRIP_WIDTH
    assert not win._left_panel.content.isVisible()


def test_docked_panel_does_not_peek(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win._left_panel.set_hovered(True)
    assert win._left_panel.peeking is False
    assert win._left_panel.docked is True


def test_panel_visibility_is_persisted(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win._act_panel_right.setChecked(False)
    win.close()
    qapp.processEvents()

    again = MainWindow()
    again.show()
    qapp.processEvents()
    assert again._right_panel.docked is False
    assert again._act_panel_right.isChecked() is False
    assert again._left_panel.docked is True


def test_panel_icons_available(qapp):
    from ql_editor import icons

    names = icons.available()
    assert "panel_left" in names and "panel_right" in names


# --------------------------------------------------------------------------- #
# Arbeitsflaeche (Pasteboard) / Scrollen
# --------------------------------------------------------------------------- #
def _wide_image(width: int = 2400, height: int = 1600):
    from PySide6.QtGui import QPixmap

    from ql_editor.items import ImageItem

    pixmap = QPixmap(width, height)
    pixmap.fill()
    return ImageItem(pixmap)


def test_pasteboard_gives_scrollbars_for_oversized_items(qapp):
    canvas = _prepared_canvas(qapp)
    assert canvas.printable_rect().width() == 554
    # Arbeitsflaeche ist groesser als die Designflaeche -> es gibt etwas zu scrollen.
    assert canvas.sceneRect().width() > canvas.printable_rect().width()

    item = _wide_image()
    canvas.add_item(item)
    item.apply_resize(900, 600)
    canvas._update_pasteboard()
    qapp.processEvents()

    assert canvas.horizontalScrollBar().maximum() > 0
    assert canvas.sceneRect().contains(item.sceneBoundingRect())


def test_pasteboard_keeps_visible_area_when_items_grow(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    canvas.zoom_by(2.0)
    qapp.processEvents()
    before = canvas.mapToScene(canvas.viewport().rect().center())

    item = _wide_image()
    canvas.add_item(item)
    item.apply_resize(1200, 800)
    canvas._update_pasteboard()
    qapp.processEvents()

    after = canvas.mapToScene(canvas.viewport().rect().center())
    assert after.x() == pytest.approx(before.x(), abs=1.5)
    assert after.y() == pytest.approx(before.y(), abs=1.5)


def test_wheel_zooms_while_whole_label_is_visible(qapp):
    from PySide6.QtCore import Qt

    canvas = _prepared_canvas(qapp)
    canvas.fit_tape()
    qapp.processEvents()
    assert canvas._label_fits_in_view() is True

    before = canvas.transform().m11()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, 120))
    assert canvas.transform().m11() > before


def test_wheel_scrolls_horizontally_when_zoomed_in(qapp):
    from PySide6.QtCore import Qt

    canvas = _prepared_canvas(qapp)
    canvas.zoom_by(4.0)
    qapp.processEvents()
    assert canvas._label_fits_in_view() is False

    bar = canvas.horizontalScrollBar()
    before_zoom = canvas.transform().m11()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.ShiftModifier, -120))
    assert canvas.transform().m11() == pytest.approx(before_zoom)
    assert bar.maximum() > 0


def test_mainwindow_shrinks_oversized_image_to_tape_width(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    item = _wide_image(2400, 1600)
    win._add_item(item)

    width, height = win._canvas.item_scene_size(item)
    assert width == pytest.approx(win._canvas.printable_rect().width(), abs=1.0)
    assert height < width
    # Seitenverhaeltnis bleibt erhalten (1600/2400 = 2/3).
    assert height == pytest.approx(width * 1600 / 2400, rel=0.01)


def test_small_image_is_not_enlarged(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    item = _wide_image(120, 80)
    win._add_item(item)
    width, height = win._canvas.item_scene_size(item)
    # Pixmap-Items haben in Qt einen halben Dot "Rand" pro Seite.
    assert width == pytest.approx(120.0, abs=1.5)
    assert height == pytest.approx(80.0, abs=1.5)


# --------------------------------------------------------------------------- #
# Groesse / Drehung (auch bei gedrehten und skalierten Objekten)
# --------------------------------------------------------------------------- #
def test_resize_keeps_anchor_for_rotated_item(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("gedreht", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(150, 120)
    item.setRotation(30)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    anchor_before = canvas._handle_points(item)["nw"]
    se = canvas._handle_points(item)["se"]
    target = QPointF(se.x() + 40, se.y() + 30)
    _press(canvas, se)
    _drag_to(canvas, target)
    _release(canvas, target)

    anchor_after = canvas._handle_points(item)["nw"]
    assert anchor_after.x() == pytest.approx(anchor_before.x(), abs=0.5)
    assert anchor_after.y() == pytest.approx(anchor_before.y(), abs=0.5)


def test_resize_of_scaled_image_uses_scene_units(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = _wide_image(1000, 800)
    canvas.add_item(item)
    item.setPos(40, 40)
    item.setTransform(item.transform().scale(0.2, 0.2))  # angezeigte Breite 200
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    width_before = canvas.item_scene_size(item)[0]
    assert width_before == pytest.approx(200, abs=1)

    e = canvas._handle_points(item)["e"]
    target = QPointF(e.x() + 50, e.y())
    _press(canvas, e)
    _drag_to(canvas, target)
    _release(canvas, target)

    # Der Zeiger wanderte 50 Szenen-Dots -> das Bild waechst um 50 Dots,
    # nicht um 50 * 1/0.2.
    assert canvas.item_scene_size(item)[0] == pytest.approx(width_before + 50, abs=1.5)


def test_rotation_keeps_item_center(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("mitte", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(200, 150)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    center_before = item.mapToScene(item.boundingRect().center())
    handle = canvas._rotate_handle_point(item)
    _press(canvas, handle)
    _drag_to(canvas, QPointF(center_before.x() + 120, center_before.y() + 60))
    _release(canvas, QPointF(center_before.x() + 120, center_before.y() + 60))

    center_after = item.mapToScene(item.boundingRect().center())
    assert item.rotation() != pytest.approx(0)
    assert center_after.x() == pytest.approx(center_before.x(), abs=0.5)
    assert center_after.y() == pytest.approx(center_before.y(), abs=0.5)


def test_rotation_snaps_to_15_degrees(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("rastet", font_pixel_size=40)
    canvas.add_item(item)
    canvas._scene.clearSelection()
    item.setSelected(True)
    center = item.mapToScene(item.boundingRect().center())
    canvas._op_item = item
    canvas._op_rotate_center = center
    canvas._op_rotate_start = -math.pi / 2
    canvas._op_start_rotation = 0.0
    canvas._do_rotate(QPointF(center.x() + 100, center.y() + 17), snap=True)
    # atan2(17, 100) = 9.65 Grad, plus 90 Grad Startversatz -> auf 105 Grad gerastet.
    assert item.rotation() % 15 == pytest.approx(0, abs=0.01)
    assert item.rotation() == pytest.approx(105, abs=0.01)


def test_rotate_handle_distance_is_constant_for_scaled_items(qapp):
    canvas = _prepared_canvas(qapp)
    item = _wide_image(1000, 800)
    canvas.add_item(item)
    item.setTransform(item.transform().scale(0.1, 0.1))
    qapp.processEvents()

    top = canvas._handle_points(item)["n"]
    handle = canvas._rotate_handle_point(item)
    distance = math.hypot(handle.x() - top.x(), handle.y() - top.y())
    assert distance == pytest.approx(ROTATE_OFFSET_PX / canvas.transform().m11(), rel=0.01)


def test_handle_cursor_follows_rotation(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("cursor", font_pixel_size=40)
    canvas.add_item(item)

    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeHorCursor
    item.setRotation(90)
    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeVerCursor
    item.setRotation(45)
    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeFDiagCursor


def test_rotated_item_is_clamped_by_rotated_hull(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("Rand", font_pixel_size=40)
    canvas.add_item(item)
    item.setRotation(90)
    item.setPos(10_000, 10_000)

    printable = canvas.printable_rect()
    hull = item.sceneBoundingRect()
    assert hull.right() <= printable.right() + 1
    assert hull.bottom() <= printable.bottom() + 1


def test_inspector_image_size_in_millimetres(qapp):
    from PySide6.QtWidgets import QDoubleSpinBox

    from ql_editor.inspector import InspectorPanel
    from ql_editor.media import DOTS_PER_MM

    inspector = InspectorPanel()
    item = _wide_image(600, 300)
    inspector.set_item(item)

    fields = inspector.findChildren(QDoubleSpinBox)
    assert len(fields) == 2
    width, height = fields
    assert width.value() == pytest.approx(600 / DOTS_PER_MM, abs=0.2)
    assert height.value() == pytest.approx(300 / DOTS_PER_MM, abs=0.2)

    # Breite aendern: Hoehe folgt im Seitenverhaeltnis (2:1).
    width.setValue(30.0)
    assert inspector._image_size(item)[0] == pytest.approx(30 * DOTS_PER_MM, abs=1.5)
    assert inspector._image_size(item)[1] == pytest.approx(15 * DOTS_PER_MM, abs=1.5)
    assert height.value() == pytest.approx(15.0, abs=0.2)

    # Hoehe aendern: Breite folgt.
    height.setValue(10.0)
    assert inspector._image_size(item)[1] == pytest.approx(10 * DOTS_PER_MM, abs=1.5)
    assert width.value() == pytest.approx(20.0, abs=0.2)


# --------------------------------------------------------------------------- #
# Druckbild: Auswahl, Textmarke und Qualitaetsoptionen
# --------------------------------------------------------------------------- #
def _render_1bit(canvas):
    """Druckbild der Szene als 1-bit-Vergleichsbytes (ohne Drucker)."""
    from ql_editor.preview import binarize

    return binarize(canvas.render_printable()).tobytes()


def _sample_items():
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPixmap

    from ql_editor.items import ImageItem, LineItem, RectItem

    pixmap = QPixmap(120, 80)
    pixmap.fill(QColor("black"))
    return {
        "Text": TextItem("Test 123", font_pixel_size=40),
        "Image": ImageItem(pixmap),
        "Barcode": BarcodeItem("123456789"),
        "QR": QRItem("test", 120),
        "Line": LineItem(0, 0, 200, 0, width_px=3),
        "Rect": RectItem(QRectF(0, 0, 200, 80)),
    }


def test_selection_is_not_printed(qapp):
    """Qt malt bei Auswahl einen gestrichelten Rahmen - der darf nicht drucken."""
    canvas = _prepared_canvas(qapp)
    for kind, item in _sample_items().items():
        canvas.clear_items()
        canvas.add_item(item)
        item.setPos(40, 40)
        canvas.scene().clearSelection()
        without = _render_1bit(canvas)
        item.setSelected(True)
        with_selection = _render_1bit(canvas)
        assert with_selection == without, f"{kind}: Auswahl landet im Druckbild"


def test_text_caret_is_not_printed(qapp):
    """Weder Einfuegemarke noch Textmarkierung duerfen im Etikett landen."""
    from PySide6.QtGui import QTextCursor

    canvas = _prepared_canvas(qapp)
    item = TextItem("Bearbeitung 123", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    qapp.processEvents()

    item.start_editing()
    qapp.processEvents()
    cursor = item.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    item.setTextCursor(cursor)
    editing = _render_1bit(canvas)
    item.finish_editing()
    qapp.processEvents()
    assert editing == _render_1bit(canvas)


def test_text_editing_survives_rendering(qapp):
    """Das Rendern blendet die Textmarke nur kurz aus - Bearbeitung bleibt."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    item.start_editing()
    qapp.processEvents()
    cursor = item.textCursor()
    cursor.clearSelection()
    cursor.movePosition(cursor.MoveOperation.End)
    item.setTextCursor(cursor)

    canvas.render_printable()

    assert item.is_editing is True
    assert item.hasFocus() is True
    assert item.textCursor().position() == 5


def test_print_preview_zooms_to_1_1_and_restores(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qapp.processEvents()
    before = win._canvas.transform().m11()
    assert before < 1.0  # eingepasst

    win._act_print_preview.setChecked(True)
    qapp.processEvents()
    assert win._canvas.transform().m11() == pytest.approx(1.0)
    assert win._canvas.print_preview is True

    win._act_print_preview.setChecked(False)
    qapp.processEvents()
    assert win._canvas.transform().m11() == pytest.approx(before)
    assert win._canvas.print_preview is False


def test_zoom_label_hints_when_preview_is_not_1_1(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qapp.processEvents()
    win._act_print_preview.setChecked(True)
    qapp.processEvents()
    win._canvas.zoom_out()
    qapp.processEvents()
    assert "1:1" in win._zoom_label.text()
    win._act_print_preview.setChecked(False)
    qapp.processEvents()
    assert "1:1" not in win._zoom_label.text()


def test_zoom_100_action_exists(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qapp.processEvents()
    assert not win._act_zoom_100.icon().isNull()
    assert win._act_zoom_100.shortcut().toString() == "Ctrl+1"
    win._canvas.zoom_by(0.5)
    win._act_zoom_100.trigger()
    assert win._canvas.transform().m11() == pytest.approx(1.0)


def test_ink_readout_tracks_threshold(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win._add_item(TextItem("Tinte", font_pixel_size=40), None)
    win._canvas.cancel_editing()
    win._refresh_now()

    win._threshold_spin.setValue(20)
    win._refresh_now()
    low = win._ink_label.text()
    win._threshold_spin.setValue(95)
    win._refresh_now()
    high = win._ink_label.text()
    assert low.startswith("Tinte:") and high.startswith("Tinte:")
    assert float(low.split()[1].replace(",", ".")) < float(high.split()[1].replace(",", "."))


def _temp_window(qapp, tmp_path):
    """MainWindow mit Einstellungen in einer temporaeren INI-Datei.

    Damit bleiben Tests unabhaengig von den echten Nutzer-Einstellungen (und
    schreiben auch nicht hinein).
    """
    from PySide6.QtCore import QSettings

    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    win = MainWindow(settings=settings)
    win.show()
    qapp.processEvents()
    return win


def test_resolution_and_hq_are_forwarded_to_the_printer(qapp, tmp_path):
    """Auflösung und HQ sind zwei Schalter - beide landen im Druckauftrag."""
    from ql_editor.printer import build_raster

    win = _temp_window(qapp, tmp_path)
    label = win._media_panel.label
    config = win._media_panel.printer_config()

    # Vorgabe: die Standardauflösung des Druckkopfs, HQ an.
    assert win._resolution().key == RESOLUTION_STANDARD.key
    assert win._hq() is True
    assert win._print_scale() == 1
    assert win._for_print().width == label.width_dots

    # 600 dpi nur in Bandlaufrichtung: doppelt so fein gerendert.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    qapp.processEvents()
    assert win._resolution().scale == 2
    assert win._print_scale() == 2
    assert win._for_print().width == label.width_dots * 2

    fine = win._for_print()
    with_hq = build_raster(fine, label, config, hq=True, dpi_600=True)
    without_hq = build_raster(fine, label, config, hq=False, dpi_600=True)
    assert with_hq != without_hq


def test_print_options_are_persisted(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    win._threshold_spin.setValue(88)
    win._dither_check.setChecked(True)
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    win._hq_check.setChecked(False)
    win._cut_check.setChecked(False)
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    assert again._threshold_spin.value() == 88
    assert again._dither_check.isChecked() is True
    assert again._resolution_combo.currentData() == RESOLUTION_HIGH.key
    assert again._hq_check.isChecked() is False
    assert again._cut_check.isChecked() is False


def test_connection_and_address_are_persisted(qapp, tmp_path):
    """Der gewaehlte Anschluss samt Adresse ueberlebt einen Neustart."""
    from ql_editor.media_panel import CONNECTION_NETWORK

    win = _temp_window(qapp, tmp_path)
    win._media_panel._host_edit.setText("192.168.178.99")
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    assert again._media_panel.connection() == CONNECTION_NETWORK
    assert again._media_panel._host_edit.text() == "192.168.178.99"
    assert again._media_panel.address() == "tcp://192.168.178.99:9100"


def _sheet(win):
    """Das aktuell sichtbare Sheet im Hauptfenster (wie in test_sheet)."""
    from ql_editor.sheet import Sheet

    sheets = win.findChildren(Sheet)
    for sheet in sheets:
        if sheet.isVisible():
            return sheet
    return sheets[0] if sheets else None


class _FakePermissionProcess:
    """Steht fuer den laufenden pkexec-Prozess, damit der Abschluss pruefbar ist."""

    def __init__(self, stderr: bytes = b"") -> None:
        self._stderr = stderr
        self.killed = False

    def readAllStandardError(self) -> bytes:
        return self._stderr

    def kill(self) -> None:
        self.killed = True


def test_permission_button_without_a_prompt_shows_the_one_liner(
    qapp, tmp_path, monkeypatch
):
    """Ohne Passwort-Dialog bleibt der Befehl zum Abschreiben."""
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(access, "install_command", lambda: None)
    monkeypatch.setattr(access, "reason_no_prompt", lambda: "Es läuft kein Dialog.")

    win._on_usb_permission()
    qapp.processEvents()

    sheet = _sheet(win)
    assert sheet is not None
    box = sheet.findChild(QMessageBox)
    assert "Es läuft kein Dialog." in box.text()
    assert "install-udev-rule.sh" in box.text()
    # Der Befehl muss sich markieren (und damit kopieren) lassen.
    assert box.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_permission_failure_explains_the_abort(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(access, "rule_installed", lambda: False)
    win._permission_process = _FakePermissionProcess()

    win._on_permission_finished(access.PKEXEC_DISMISSED)
    qapp.processEvents()

    sheet = _sheet(win)
    assert sheet is not None
    assert "Abgebrochen" in sheet.findChild(QMessageBox).text()


def test_permission_success_refreshes_the_panel(qapp, tmp_path, monkeypatch):
    win = _temp_window(qapp, tmp_path)
    win._permission_process = _FakePermissionProcess()
    refreshed = []
    monkeypatch.setattr(
        win._media_panel, "refresh_access", lambda: refreshed.append(True)
    )

    win._on_permission_finished(0)

    assert refreshed == [True]
    assert "eingerichtet" in win.statusBar().currentMessage()


def test_permission_timeout_kills_and_shows_the_one_liner(
    qapp, tmp_path, monkeypatch
):
    """Ein Agent, der nicht fragt, darf die Anzeige nicht blockieren."""
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    process = _FakePermissionProcess()
    win._permission_process = process
    monkeypatch.setattr(access, "reason_no_prompt", lambda: "Kein Dialog gefunden.")

    win._on_permission_timeout()
    qapp.processEvents()

    assert process.killed is True
    sheet = _sheet(win)
    assert sheet is not None
    assert "Kein Dialog gefunden." in sheet.findChild(QMessageBox).text()


def test_resolution_options_follow_the_printer_model(qapp):
    """Nur die Auflösungen, die der Druckkopf wirklich kann."""
    from ql_editor.printer import (
        maximum_resolution,
        resolution_by_key,
        resolution_options,
    )

    keys = [option.key for option in resolution_options("QL-820NWB")]
    assert keys == [RESOLUTION_STANDARD.key, RESOLUTION_HIGH.key]
    assert maximum_resolution("QL-820NWB").label == "300 × 600 dpi"
    assert maximum_resolution("QL-820NWB").scale == 2

    # Alle uebrigen Modelle der Bibliothek haben nur den 300-dpi-Druckkopf -
    # laut Datenblatt ohne High-Resolution-Modus.
    for model_id in ("QL-500", "QL-570", "QL-700", "QL-720NW", "QL-1050", "QL-1060N"):
        assert [option.key for option in resolution_options(model_id)] == [
            RESOLUTION_STANDARD.key
        ], model_id
        assert maximum_resolution(model_id).label == "300 × 300 dpi"

    # Eine nicht unterstuetzte Aufloesung faellt auf das Maximum des Modells zurueck.
    assert (
        resolution_by_key("QL-500", RESOLUTION_HIGH.key).key == RESOLUTION_STANDARD.key
    )
    assert resolution_by_key("QL-820NWB", RESOLUTION_HIGH.key).scale == 2


def test_resolution_combo_follows_a_model_change(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    assert win._resolution().key == RESOLUTION_STANDARD.key

    combo = win._media_panel._model_combo
    combo.setCurrentIndex(combo.findData("QL-500"))
    qapp.processEvents()
    assert [
        win._resolution_combo.itemData(i) for i in range(win._resolution_combo.count())
    ] == [RESOLUTION_STANDARD.key]
    assert "300 × 300 dpi" in win._resolution_hint.text()

    # Zurueck zum QL-820NWB: 600 dpi ist wieder waehlbar.
    combo.setCurrentIndex(combo.findData("QL-820NWB"))
    qapp.processEvents()
    assert RESOLUTION_HIGH.key in [
        win._resolution_combo.itemData(i) for i in range(win._resolution_combo.count())
    ]

    # Eine Aufloesung, die das neue Modell nicht kann, faellt auf 300 dpi zurueck.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    qapp.processEvents()
    assert win._resolution().scale == 2
    combo.setCurrentIndex(combo.findData("QL-500"))
    qapp.processEvents()
    assert win._resolution().scale == 1
    assert "QL-500" in win._resolution_hint.text()


def test_print_options_are_never_cut_off(qapp, tmp_path):
    """Der Drucken-Knopf darf nicht hinter dem Scrollbalken verschwinden."""
    win = _temp_window(qapp, tmp_path)
    area = win._right_panel.content.widget(1)
    assert area.minimumHeight() >= area.widget().sizeHint().height()
    assert area.verticalScrollBar().maximum() == 0
    assert win._print_button.isVisible()


def test_print_preview_in_600dpi_is_reduced_to_canvas_size(qapp, tmp_path):
    """Im 600-dpi-Modus zeigt die Vorschau die echten Druckdaten.

    Das 1-bit-Bild hat dann doppelt so viele Zeilen; fuer das Overlay wird es
    auf die Canvas-Groesse gemittelt (sonst waere die Vorschau gestaucht).
    """
    win = _temp_window(qapp, tmp_path)
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    win._add_text()
    win._canvas.cancel_editing()
    win._canvas.set_print_preview(True)
    win._refresh_now()

    printable = win._canvas.printable_rect()
    preview = win._canvas._print_image
    assert preview is not None
    assert (preview.width(), preview.height()) == (
        int(printable.width()),
        int(printable.height()),
    )
    assert win._ink_label.text().startswith("Tinte:")


def test_threshold_is_disabled_while_dithering(qapp, tmp_path):
    """Dithering ignoriert die Tintenmenge - das Feld sagt das auch."""
    win = _temp_window(qapp, tmp_path)
    assert win._threshold_spin.isEnabled() is True

    win._dither_check.setChecked(True)
    qapp.processEvents()
    assert win._threshold_spin.isEnabled() is False
    assert "ohne Wirkung" in win._threshold_label.text()

    win._dither_check.setChecked(False)
    qapp.processEvents()
    assert win._threshold_spin.isEnabled() is True
    assert win._threshold_label.text() == "Tintenmenge"


def test_threshold_range_excludes_the_extremes(qapp, tmp_path):
    """Alles-schwarz und nur-reines-Schwarz sind nicht waehlbar."""
    from ql_editor.preview import THRESHOLD_MAX, THRESHOLD_MIN

    win = _temp_window(qapp, tmp_path)
    assert win._threshold_spin.minimum() == THRESHOLD_MIN
    assert win._threshold_spin.maximum() == THRESHOLD_MAX
    assert THRESHOLD_MIN < 70 < THRESHOLD_MAX

    win._threshold_spin.setValue(100)
    assert win._threshold_spin.value() == THRESHOLD_MAX
    win._threshold_spin.setValue(0)
    assert win._threshold_spin.value() == THRESHOLD_MIN

    # Alte Einstellungen ausserhalb der Spanne werden beim Laden begrenzt.
    win._settings.threshold = 5
    win._apply_saved_settings()
    assert win._threshold_spin.value() == THRESHOLD_MIN


def test_threshold_has_an_explanatory_tooltip(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    tooltip = win._threshold_spin.toolTip()
    assert tooltip == win._threshold_label.toolTip()
    assert "Schwärze" in tooltip          # was der Wert bedeutet
    assert "kräftiger" in tooltip         # hoeher = mehr Tinte
    assert "Dithering" in tooltip         # wann er nicht wirkt
    assert "40 %" in tooltip and "90 %" in tooltip  # waehlbare Spanne


def test_old_settings_are_migrated(qapp, tmp_path):
    """Bestehende Einstellungen (print/quality, print/hq) werden uebersetzt."""
    from PySide6.QtCore import QSettings

    from ql_editor.settings import AppSettings

    raw = QSettings(str(tmp_path / "migration.ini"), QSettings.Format.IniFormat)
    raw.setValue("print/hq", False)
    assert AppSettings(raw).hq is False
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key

    raw.setValue("print/hq", True)
    assert AppSettings(raw).hq is True

    # Die kombinierte "Qualitaet" einer aelteren Version: "maximum" war 600 dpi.
    raw.remove("print/hq")
    raw.setValue("print/quality", "maximum")
    assert AppSettings(raw).print_resolution == RESOLUTION_HIGH.key
    assert AppSettings(raw).hq is True

    raw.setValue("print/quality", "standard")
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key
    assert AppSettings(raw).hq is False

    # Die neuen Schluessel gewinnen, sobald sie gesetzt sind.
    settings = AppSettings(raw)
    settings.print_resolution = RESOLUTION_STANDARD.key
    settings.hq = True
    assert raw.value("print/resolution") == RESOLUTION_STANDARD.key
    assert raw.value("print/hq") is True
    assert settings.print_resolution == RESOLUTION_STANDARD.key
    assert settings.hq is True


def test_fresh_settings_use_the_standard_resolution(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from ql_editor.settings import AppSettings

    raw = QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat)
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key
    assert AppSettings(raw).hq is True
