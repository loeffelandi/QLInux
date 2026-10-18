"""Tests fuer :class:`ql_editor.items.ShapeItem` (Pfeile, Ellipse, Dreieck, Stern)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsScene

from ql_editor.items import ITEM_TYPES, SHAPES, ShapeItem, item_from_dict
from ql_editor.renderer import render_scene_to_image

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.mark.parametrize("shape", SHAPES)
def test_every_shape_has_a_path_and_roundtrips(shape):
    item = ShapeItem(QRectF(0, 0, 120, 80), shape, 3, True)
    assert not item.path().isEmpty()
    restored = item_from_dict(item.to_dict())
    assert isinstance(restored, ShapeItem)
    assert restored.shape_name == shape
    assert restored.filled
    assert restored.width_px == pytest.approx(3)


def test_shape_is_registered_as_item_type():
    assert ITEM_TYPES["shape"] is ShapeItem


def test_unknown_shape_falls_back_to_ellipse():
    assert ShapeItem(QRectF(0, 0, 10, 10), "gibt-es-nicht").shape_name == "ellipse"


@pytest.mark.parametrize("shape", SHAPES)
def test_resize_changes_bounds(shape):
    """Pfad-BoundingRect muss dem Ziel-_rect entsprechen (kein Handle-Drift)."""
    item = ShapeItem(QRectF(0, 0, 50, 50), shape)
    item.apply_resize(200, 100)
    bounds = item.path().boundingRect()
    assert bounds.width() == pytest.approx(200)
    assert bounds.height() == pytest.approx(100)
    assert bounds.x() == pytest.approx(0)
    assert bounds.y() == pytest.approx(0)


def test_filled_arrow_renders_dark():
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, 200, 100))
    scene.addItem(ShapeItem(QRectF(10, 20, 160, 60), "arrow_double", 2, True))
    image = render_scene_to_image(scene, 200, 100).convert("L")
    dark = sum(1 for p in image.getdata() if p < 128)
    assert dark > 1000
