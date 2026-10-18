"""Clip Art: eigene Symbole, Seitenverhältnis, Einfügen über das Sheet."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QCheckBox, QPushButton, QToolButton

from ql_editor import i18n
from ql_editor.canvas import LabelCanvas
from ql_editor.items import ClipArtItem, item_from_dict
from ql_editor.media import get_label
from ql_editor.symbols import (
    SYMBOLS,
    category_label,
    known_symbol,
    paint_symbol,
    symbol_label,
)


def test_labels_follow_the_ui_language():
    assert symbol_label("warning") == "Achtung"
    assert symbol_label("cross") == "Kreuz"
    assert category_label("arrows") == "Pfeile"
    assert known_symbol("missing") == "warning"

    i18n.set_language("en")
    try:
        assert symbol_label("warning") == "Caution"
        assert category_label("signs") == "Signs"
        assert symbol_label("home") == "Home"
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_every_symbol_paints_ink(qapp):
    assert len({spec.id for spec in SYMBOLS}) == len(SYMBOLS)
    for spec in SYMBOLS:
        image = QImage(80, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        paint_symbol(painter, spec.id, QRectF(0, 0, 80, 80), "black")
        painter.end()
        dark = sum(
            1
            for y in range(80)
            for x in range(80)
            if image.pixelColor(x, y).red() < 40
        )
        assert dark > 80, spec.id


def test_roundtrip_aspect_and_unknown_symbol(qapp):
    item = ClipArtItem("star", 100)
    item.apply_resize(180, 100)
    assert item.boundingRect().width() == 180
    assert item.boundingRect().height() == 180

    item.set_keep_aspect(False)
    item.apply_resize(180, 90)
    assert item.boundingRect().height() == 90
    item.set_color("red")
    item.set_symbol("nope")
    assert item.symbol == "warning"
    item.set_symbol("bolt")

    restored = item_from_dict(item.to_dict())
    assert isinstance(restored, ClipArtItem)
    assert restored.symbol == "bolt"
    assert restored.color == "red"
    assert restored.keep_aspect is False
    assert restored.boundingRect().width() == 180
    assert restored.boundingRect().height() == 90

    broken = item_from_dict({"type": "clipart", "symbol": "nope", "color": "blue"})
    assert broken.symbol == "warning"
    assert broken.color == "black"
    assert broken.keep_aspect is True


def test_render_has_ink_and_no_selection_chrome(qapp):
    canvas = LabelCanvas()
    canvas.resize(400, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 400)
    item = ClipArtItem("warning", 180)
    item.set_color("red")
    canvas.add_item(item)
    item.setPos(8, 8)
    item.setSelected(True)
    image = canvas.render_printable()
    dark = red = blue = 0
    for pixel in image.getdata():
        r, g, b = pixel[:3]
        if r < 40 and g < 40 and b < 40:
            dark += 1
        if r > 180 and g < 40 and b < 40:
            red += 1
        if b > 150 and r < 80 and g < 160:
            blue += 1
    assert red > 40
    assert dark == 0
    assert blue == 0


def test_main_window_inserts_from_the_sheet_and_undoes_a_swap(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    win._act_add_clipart.trigger()
    qapp.processEvents()
    home = win.findChild(QToolButton, "symbol_home")
    assert home is not None and home.isVisible()
    home.click()
    qapp.processEvents()

    marks = [it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "clipart"]
    assert len(marks) == 1
    assert marks[0].symbol == "home"
    assert marks[0].keep_aspect
    assert win._inspector._title.text() == "Clip Art"
    aspect = [
        box
        for box in win._inspector.findChildren(QCheckBox)
        if box.text() == "Seitenverhältnis festhalten" and box.isVisible()
    ]
    assert len(aspect) == 1 and aspect[0].isChecked()

    swap = next(
        button
        for button in win._inspector.findChildren(QPushButton)
        if button.text() == "Austauschen…" and button.isVisible()
    )
    swap.click()
    qapp.processEvents()
    stars = [
        button
        for button in win.findChildren(QToolButton, "symbol_star")
        if button.isVisible()
    ]
    assert len(stars) == 1
    stars[0].click()
    qapp.processEvents()
    mark = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "clipart")
    assert mark.symbol == "star"

    win._act_undo.trigger()
    qapp.processEvents()
    mark = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "clipart")
    assert mark.symbol == "home"
