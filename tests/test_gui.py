"""GUI-Tests (PySide6, headless via Offscreen-Plattform).

Prueft die Verschaltung von Media-Panel, Canvas und Vorschau sowie die
Randbegrenzung. Es wird kein Drucker benoetigt.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from ql_editor import media
from ql_editor.canvas import LabelCanvas
from ql_editor.items import BarcodeItem, QRItem, TextItem, item_from_dict
from ql_editor.media import get_label

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
def test_canvas_scene_rect_is_exact_width(qapp):
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    assert canvas.sceneRect().width() == 554
    assert canvas.sceneRect().height() == 472


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

    item.setPos(10_000, 10_000)
    br = item.sceneBoundingRect()
    assert br.right() <= canvas.sceneRect().right() + 1
    assert br.bottom() <= canvas.sceneRect().bottom() + 1

    item.setPos(-10_000, -10_000)
    br = item.sceneBoundingRect()
    assert br.left() >= canvas.sceneRect().left() - 1
    assert br.top() >= canvas.sceneRect().top() - 1


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
    item.finish_editing()
    assert item.is_editing is False


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


def test_default_dock_widths_are_roomy(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    assert win._left_dock.minimumWidth() >= 200
    assert win._right_dock.minimumWidth() >= 240


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

    center_y = canvas.sceneRect().center().y()
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
    win._new_text()
    win._canvas.cancel_editing()
    label = win._media_panel.label
    length = win._canvas.length_dots
    assert win._canvas.sceneRect().size().toSize() == QSize(label.width_dots, length)

    win._media_panel.set_orientation(media.Orientation.ALONG)
    assert win._canvas.sceneRect().size().toSize() == QSize(length, label.width_dots)
    assert win._canvas.length_dots == length
    # Das Druckbild ist in beiden Ausrichtungen bandbreit.
    assert win._for_print().size == (label.width_dots, length)


def test_orientation_moves_side_border_to_tape_edges(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    label = win._media_panel.label
    win._media_panel.set_orientation(media.Orientation.ALONG)
    tape = win._canvas.tape_rect()
    printable = win._canvas.sceneRect()
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
    rect = win._canvas.sceneRect()
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
# Seitenpanels ein-/ausblenden
# --------------------------------------------------------------------------- #
def test_panel_toggle_actions_present_and_checked(qapp):
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
    assert win._act_panel_left in bar_actions
    assert win._act_panel_right in bar_actions
    assert win._act_panel_left in win._menu_button.menu().actions()


def test_hiding_panel_gives_canvas_more_room(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    before = win._canvas.width()
    assert win._right_dock.isVisible()

    win._act_panel_right.setChecked(False)
    qapp.processEvents()
    assert not win._right_dock.isVisible()
    assert win._canvas.width() > before

    win._act_panel_right.setChecked(True)
    qapp.processEvents()
    assert win._right_dock.isVisible()


def test_both_panels_can_be_hidden(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()

    win._act_panel_left.setChecked(False)
    win._act_panel_right.setChecked(False)
    qapp.processEvents()
    assert not win._left_dock.isVisible()
    assert not win._right_dock.isVisible()
    # Der Canvas bekommt die volle Breite und der Fokus bleibt dort.
    assert win._canvas.width() == pytest.approx(win.width(), abs=4)
    assert qapp.focusWidget() is win._canvas


def test_hiding_panel_by_dock_keeps_action_in_sync(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    # Simuliert das Verstecken von aussen (z. B. Titelleiste/Programmcode).
    win._left_dock.hide()
    qapp.processEvents()
    assert win._act_panel_left.isChecked() is False


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
    assert again._right_dock.isVisible() is False
    assert again._act_panel_right.isChecked() is False
    assert again._left_dock.isVisible() is True


def test_panel_icons_available(qapp):
    from ql_editor import icons

    names = icons.available()
    assert "panel_left" in names and "panel_right" in names
