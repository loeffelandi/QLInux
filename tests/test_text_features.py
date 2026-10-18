"""Tests fuer die Textfunktionen von :class:`ql_editor.items.TextItem`.

Invertieren, Unter-/Durchstreichen, Abstaende, vertikale Schrift, Aufzaehlung,
Ausrichtung und Umbruch - jeweils mit Serialisierung und Renderpfad.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsScene

from ql_editor.items import TextItem, item_from_dict
from ql_editor.renderer import render_scene_to_image

pytestmark = pytest.mark.usefixtures("qapp")


def _render(item: TextItem, width: int = 400, height: int = 200):
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, width, height))
    scene.addItem(item)
    item.setPos(10, 10)
    return render_scene_to_image(scene, width, height)


def _dark_share(image) -> float:
    gray = image.convert("L")
    pixels = list(gray.getdata())
    return sum(1 for p in pixels if p < 128) / len(pixels)


def test_inverted_text_renders_dark_box():
    plain = TextItem("MMMM", font_pixel_size=40)
    inverted = TextItem("MMMM", font_pixel_size=40)
    inverted.set_inverted(True)
    inverted.set_box_height(120)
    inverted.set_text_width(200)
    inverted.set_wrap(True)
    assert _dark_share(_render(inverted)) > _dark_share(_render(plain)) + 0.2


def test_inverted_uses_text_colour_for_box_and_white_text():
    item = TextItem("A")
    item.set_text_color("red")
    item.set_inverted(True)
    assert item.inverted
    assert item.to_dict()["inverted"] is True
    assert item.to_dict()["color"] == "red"


def test_underline_and_strike_roundtrip():
    item = TextItem("Text")
    item.set_underline(True)
    item.set_strike(True)
    restored = item_from_dict(item.to_dict())
    assert restored.underline and restored.strike
    assert restored.font().underline() and restored.font().strikeOut()


def test_spacing_roundtrip():
    item = TextItem("Text")
    item.set_letter_spacing(3.5)
    item.set_line_spacing(1.5)
    restored = item_from_dict(item.to_dict())
    assert restored.letter_spacing == pytest.approx(3.5)
    assert restored.line_spacing == pytest.approx(1.5)


def test_vertical_text_stacks_characters_and_keeps_logical_text():
    item = TextItem("ABC")
    item.set_vertical(True)
    assert item.toPlainText() == "A\nB\nC"
    assert item.text_value == "ABC"
    restored = item_from_dict(item.to_dict())
    assert restored.toPlainText() == "A\nB\nC"
    assert restored.vertical


def test_list_is_paragraph_format_not_text():
    item = TextItem("eins\nzwei")
    item.set_list("number")
    assert item.text_value == "eins\nzwei"
    cursor = item.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    assert cursor.currentList() is not None
    assert item.to_dict()["text"] == "eins\nzwei"
    assert item_from_dict(item.to_dict()).list_style == "number"


def test_fixed_box_height_sets_bounding_rect():
    item = TextItem("Text")
    item.set_box_height(150)
    assert item.boundingRect().height() == pytest.approx(150)
    item.set_auto_height(True)
    assert item.auto_height


def test_auto_width_toggle():
    item = TextItem("Text")
    assert item.auto_width
    item.set_auto_width(False)
    assert not item.auto_width
    item.set_auto_width(True)
    assert item.auto_width


def test_legacy_text_width_means_wrap():
    data = TextItem("Text").to_dict()
    data.pop("wrap", None)
    data["text_width"] = 300.0
    restored = item_from_dict(data)
    assert restored.wrap
    assert not restored.auto_width
