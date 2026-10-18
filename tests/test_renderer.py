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
    img = render_for_label(scene, label, (label.width_dots, 472))
    assert img.size == (label.width_dots, 472)


# --- Drehung fuer die Ausrichtung "laengs des Bandes" ---
def test_render_rotate_swaps_axes_and_only_permutes_pixels():
    scene = _scene_with_black_box(200, 400)  # schwarze Box oben links
    normal = render_scene_to_image(scene, 200, 400).convert("L")
    rotated = render_scene_to_image(scene, 200, 400, rotate=True).convert("L")
    assert normal.size == (200, 400)
    assert rotated.size == (400, 200)
    # Reine Drehung: identische Pixel, nur anders angeordnet (Dither/Threshold
    # bleiben damit in beiden Ansichten gleich).
    assert rotated.tobytes() == normal.transpose(Image.Transpose.ROTATE_90).tobytes()


def test_render_rotate_moves_content_counter_clockwise():
    scene = _scene_with_black_box(200, 400)
    rotated = render_scene_to_image(scene, 200, 400, rotate=True).convert("L")
    # Box war x=10..50, y=10..40 -> nach CCW x=10..40, y=149..189.
    assert rotated.getpixel((25, 170)) < 128
    assert rotated.getpixel((25, 20)) > 200


def test_render_for_label_rotated_is_label_width():
    label = get_label("50")  # 554 px Bandbreite
    scene = _scene_with_black_box(300, label.width_dots)
    img = render_for_label(scene, label, (300, label.width_dots), rotate=True)
    assert img.size == (label.width_dots, 300)


# --- Renderfaktor fuer den 600-dpi-Modus ---
def test_render_for_label_scale_renders_finer_in_both_axes():
    """``scale=2`` rendert die Designflaeche doppelt so fein (600-dpi-Modus).

    Genau diese Groesse erwartet ``convert()`` dann (``dots_expected``); die
    Laenge bleibt, weil der Drucker die Zeilen mit halbem Abstand setzt.
    """
    label = get_label("50")  # 554 px Bandbreite
    scene = _scene_with_black_box(label.width_dots, 472)

    fine = render_for_label(scene, label, (label.width_dots, 472), scale=2)
    assert fine.size == (label.width_dots * 2, 472 * 2)
    assert_exact_label_width(fine, label, scale=2)

    # Ungerader/zu kleiner Faktor faellt auf: die Breite muss zum Faktor passen.
    with pytest.raises(RenderError):
        assert_exact_label_width(fine, label)


def test_render_for_label_scale_rotated_stays_label_width_times_scale():
    label = get_label("50")
    scene = _scene_with_black_box(300, label.width_dots)
    img = render_for_label(scene, label, (300, label.width_dots), rotate=True, scale=2)
    # Nach der Drehung: Bandbreite x Laenge, jeweils mit dem Faktor.
    assert img.size == (label.width_dots * 2, 300 * 2)


def test_render_scale_keeps_the_geometry_proportional():
    """Faktor 2 verdoppelt die Pixel, nicht die Form.

    Ein Rechteck an derselben relativen Stelle bleibt dort - im 600-dpi-Bild
    liegt es bei doppelten Koordinaten. Genau das braucht der 600-dpi-Druck:
    dieselbe Anordnung, nur feiner abgetastet.
    """
    scene = _scene_with_black_box(200, 400)  # schwarze Box bei (10,10)..(50,40)

    normal = render_scene_to_image(scene, 200, 400).convert("L")
    fine = render_scene_to_image(scene, 400, 800).convert("L")

    assert fine.size == (400, 800)
    assert normal.getpixel((30, 25)) < 128 and fine.getpixel((60, 50)) < 128
    assert normal.getpixel((150, 300)) > 200 and fine.getpixel((300, 600)) > 200
