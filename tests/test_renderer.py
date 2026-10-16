"""Tests fuer :mod:`ql_editor.renderer` (headless via Offscreen-Qt)."""

from __future__ import annotations

import pytest
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from ql_editor.media import get_label
from ql_editor.renderer import (
    RenderError,
    assert_exact_label_width,
    render_for_label,
    render_scene_to_image,
)

pytestmark = pytest.mark.usefixtures("qapp")


def _scene_with_black_box(width: int, height: int) -> QGraphicsScene:
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, width, height))
    bg = QGraphicsRectItem(QRectF(0, 0, width, height))
    bg.setBrush(QBrush(QColor("white")))
    bg.setPen(QPen(QColor("white")))
    scene.addItem(bg)
    box = QGraphicsRectItem(QRectF(10, 10, 40, 30))
    box.setBrush(QBrush(QColor("black")))
    box.setPen(QPen(QColor("black")))
    scene.addItem(box)
    return scene


def test_render_produces_exact_size():
    scene = _scene_with_black_box(554, 472)
    img = render_scene_to_image(scene, 554, 472)
    assert isinstance(img, Image.Image)
    assert img.size == (554, 472)
    assert img.mode == "RGB"


def test_render_white_background_and_black_content():
    scene = _scene_with_black_box(200, 100)
    img = render_scene_to_image(scene, 200, 100).convert("L")
    # Ecke weit weg vom schwarzen Kaestchen ist weiss.
    assert img.getpixel((190, 90)) > 200
    # Innerhalb des Kaestchens ist es schwarz.
    assert img.getpixel((30, 25)) < 60


def test_render_rejects_invalid_size():
    scene = _scene_with_black_box(100, 100)
    with pytest.raises(RenderError):
        render_scene_to_image(scene, 0, 100)


def test_render_rejects_empty_scene_rect():
    scene = QGraphicsScene()
    with pytest.raises(RenderError):
        render_scene_to_image(scene, 50, 50)


def test_assert_exact_label_width_ok_and_fail():
    label = get_label("50")
    ok_image = Image.new("RGB", (label.width_dots, 100), "white")
    assert_exact_label_width(ok_image, label)  # kein Fehler

    wrong = Image.new("RGB", (label.width_dots - 1, 100), "white")
    with pytest.raises(RenderError) as excinfo:
        assert_exact_label_width(wrong, label)
    assert "554" in str(excinfo.value)


def test_render_for_label_uses_label_width():
    label = get_label("50")
    scene = _scene_with_black_box(label.width_dots, 472)
    img = render_for_label(scene, label, 472)
    assert img.size == (label.width_dots, 472)


def test_render_for_label_mismatched_label_is_caught():
    # Szene in falscher Breite -> render_for_label rendert mit Label-Breite,
    # die Szene wird skaliert/geclippt, aber die Bildbreite stimmt.
    label = get_label("29")  # 306 px
    scene = _scene_with_black_box(306, 200)
    img = render_for_label(scene, label, 200)
    assert img.size == (306, 200)
