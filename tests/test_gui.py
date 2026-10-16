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


def test_preview_widget_renders(qapp):
    from ql_editor.preview import PreviewWidget
    from PIL import Image

    widget = PreviewWidget()
    widget.set_image(Image.new("RGB", (100, 50), "white"))
    assert widget._rendered is not None
    assert widget._rendered.size == (100, 50)
