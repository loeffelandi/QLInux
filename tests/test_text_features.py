"""Tests fuer die Textfunktionen von :class:`ql_editor.items.TextItem`.

Invertieren, Unter-/Durchstreichen, Abstaende, vertikale Schrift, Aufzaehlung,
Ausrichtung und Umbruch - jeweils mit Serialisierung und Renderpfad.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent
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


def test_vertical_toggle_off_preserves_logical_text():
    """B1: Vertikal ein→aus darf den Klartext nicht mit Newlines zerlegen."""
    item = TextItem("Hello World")
    item.set_vertical(True)
    assert item.toPlainText() == "\n".join("Hello World")
    assert item.text_value == "Hello World"
    item.set_vertical(False)
    assert item.text_value == "Hello World"
    assert item.toPlainText() == "Hello World"
    assert item.to_dict()["text"] == "Hello World"


def test_prepare_geometry_change_keeps_scene_index():
    """M1: Nach Box-Hoehenaenderung muss der Szenen-Index Hit-Tests treffen."""
    scene = QGraphicsScene()
    item = TextItem("Hi", font_pixel_size=20)
    scene.addItem(item)
    item.setPos(0, 0)
    # Vor-Indexierung: Hit oben, damit der BSP-Index die alte Geometrie kennt.
    top = item.mapToScene(QPointF(5, 5))
    assert scene.itemAt(top, item.transform()) is item
    item.set_box_height(300)
    bottom = item.mapToScene(QPointF(5, 280))
    hits = sum(1 for _ in range(20) if scene.itemAt(bottom, item.transform()) is item)
    assert hits == 20, f"BSP-Index veraltet: nur {hits}/20 Hits unten"


def test_shape_and_contains_cover_fixed_box():
    """M2: Leerer Box-Bereich muss shape/contains abdecken."""
    item = TextItem("Hi", font_pixel_size=20)
    item.set_box_height(300)
    item.set_text_width(200)
    assert item.boundingRect().height() == pytest.approx(300)
    low = QPointF(10, 250)
    assert item.contains(low)
    assert item.shape().contains(low)


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
    # Auto-Hoehe folgt dem Text, nicht der zuvor fixierten Box.
    assert item.boundingRect().height() < 150


def _ink_vertical_span(item: TextItem) -> tuple[int, int]:
    """Erste und letzte dunkle Zeile nach dem Rendern (Item bei 0,0)."""
    scene = QGraphicsScene()
    scene.addItem(item)
    item.setPos(0, 0)
    box = item.boundingRect()
    width = max(8, int(box.width()) + 4)
    height = max(8, int(box.height()) + 40)
    image = render_scene_to_image(scene, width, height)
    gray = image.convert("L")
    first = last = None
    for y in range(gray.height):
        if any(
            isinstance(pixel := gray.getpixel((x, y)), int) and pixel < 200
            for x in range(min(gray.width, width))
        ):
            if first is None:
                first = y
            last = y
    assert first is not None and last is not None
    return first, last


def test_auto_height_box_tracks_wrapped_text():
    """Umbruch + Hoehe automatisch: Rahmen dicht am Text, nicht mit Leerraum darunter."""
    item = TextItem("Höhe automatisch dia", font_pixel_size=48)
    item.set_text_width(250)
    item.set_wrap(True)
    item.set_auto_height(True)
    assert item.auto_height
    assert item.wrap
    doc_h = item.document().size().height()
    box_h = item.boundingRect().height()
    # Unterlaengen duerfen die Dokumenthoehe um wenige Pixel ueberragen.
    # Eine zusaetzliche Leerzeile (der eigentliche Bug) ist ein Vielfaches davon.
    assert box_h <= doc_h + 2.0
    _first, last = _ink_vertical_span(item)
    # Letzte Zeile innerhalb der Box, nur kleiner Rand (Dokument-Margin), kein grosser Leerraum.
    assert last < box_h
    assert box_h - (last + 1) < 24


def test_auto_height_with_line_and_letter_spacing():
    item = TextItem("Höhe\nautomatisch\ndia", font_pixel_size=40)
    item.set_text_width(180)
    item.set_wrap(True)
    item.set_line_spacing(1.5)
    item.set_letter_spacing(2.0)
    item.set_auto_height(True)
    box_h = item.boundingRect().height()
    _first, last = _ink_vertical_span(item)
    assert last < box_h
    assert box_h - (last + 1) < 28
    # Feste Hoehe bleibt, wenn Auto aus ist (neues Item: der Render-Pfad
    # oben hat das vorige Objekt der Szene uebergeben).
    fixed = TextItem("Höhe\nautomatisch\ndia", font_pixel_size=40)
    fixed.set_text_width(180)
    fixed.set_wrap(True)
    fixed.set_line_spacing(1.5)
    fixed.set_auto_height(False)
    fixed.set_box_height(box_h + 80)
    assert not fixed.auto_height
    assert fixed.boundingRect().height() == pytest.approx(box_h + 80)


def test_auto_height_vertical_text():
    item = TextItem("ABC", font_pixel_size=36)
    item.set_vertical(True)
    item.set_auto_height(True)
    box_h = item.boundingRect().height()
    doc_h = item.document().size().height()
    # Nicht das aufgeblaehte Dokumentrechteck (leere Folgezeile), aber
    # mindestens die gemalte letzte Zeile.
    assert box_h <= doc_h + 1.0
    _first, last = _ink_vertical_span(item)
    assert last <= box_h + 2
    assert box_h - last < 28


def test_auto_width_toggle():
    item = TextItem("Text")
    assert item.auto_width
    item.set_auto_width(False)
    assert not item.auto_width
    item.set_auto_width(True)
    assert item.auto_width


def test_editing_yields_style_shortcuts_to_the_item_action():
    item = TextItem("Hallo", font_pixel_size=32)
    item.start_editing()
    for key in (Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U):
        event = QKeyEvent(
            QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.ControlModifier
        )
        assert item.sceneEvent(event) is False
        assert not event.isAccepted()
    letter = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier, "x"
    )
    item.sceneEvent(letter)
    assert "x" in item.toPlainText()


def test_legacy_text_width_means_wrap():
    data = TextItem("Text").to_dict()
    data.pop("wrap", None)
    data["text_width"] = 300.0
    restored = item_from_dict(data)
    assert restored.wrap
    assert not restored.auto_width
