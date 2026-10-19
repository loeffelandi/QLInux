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


def test_clipart_sheet_fits_a_short_window_and_closes_on_scrim(qapp):
    """Kleine Fenster: Karte schrumpft, Scroll bleibt sichtbar; Klick aussen zu."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QScrollArea

    from ql_editor.app import MainWindow
    from ql_editor.sheet import Sheet

    win = MainWindow()
    win.resize(720, 420)
    win.show()
    qapp.processEvents()
    win._act_add_clipart.trigger()
    qapp.processEvents()
    sheet = next(s for s in win.findChildren(Sheet) if s.isVisible())
    panel = sheet._panel
    assert panel.height() <= win.height() - 2 * 20
    scroll = sheet.findChild(QScrollArea, "clipart_scroll")
    assert scroll is not None
    assert scroll.height() >= 72
    assert panel.geometry().bottom() <= sheet.height()

    outside = QPoint(8, 8)
    assert not panel.geometry().contains(outside)
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        outside.toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    sheet.mousePressEvent(press)
    qapp.processEvents()
    assert not sheet.isVisible()
    win.close()
    qapp.processEvents()


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


def test_clipart_inverted_round_trips(qapp):
    from ql_editor.items import ClipArtItem

    item = ClipArtItem("warning", 80)
    assert not item.inverted
    item.set_inverted(True)
    restored = ClipArtItem.from_dict(item.to_dict())
    assert restored.inverted
    assert restored.to_dict()["inverted"] is True


def _paint_item(item: ClipArtItem) -> QImage:
    rect = item.boundingRect()
    image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    return image


def test_inverted_clipart_paints_a_box_with_a_white_symbol(qapp):
    normal = ClipArtItem("warning", 80)
    inverted = ClipArtItem("warning", 80, inverted=True)
    plain = _paint_item(normal)
    flipped = _paint_item(inverted)
    assert flipped.pixelColor(1, 1).red() < 40
    ink = [
        (x, y)
        for y in range(80)
        for x in range(80)
        if plain.pixelColor(x, y).red() < 40
    ]
    assert len(ink) > 80
    assert all(flipped.pixelColor(x, y).red() > 215 for x, y in ink)


def test_inverted_red_clipart_prints_red_without_black(qapp):
    canvas = LabelCanvas()
    canvas.resize(400, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 400)
    item = ClipArtItem("warning", 180, color="red", inverted=True)
    canvas.add_item(item)
    item.setPos(8, 8)
    image = canvas.render_printable()
    dark = red = 0
    for pixel in image.getdata():
        r, g, b = pixel[:3]
        if r < 40 and g < 40 and b < 40:
            dark += 1
        if r > 180 and g < 40 and b < 40:
            red += 1
    assert red > 180 * 180 // 2
    assert dark == 0


def test_inspector_inverts_clipart_with_undo(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 760)
    win.show()
    qapp.processEvents()
    win._act_add_clipart.trigger()
    qapp.processEvents()
    win.findChild(QToolButton, "symbol_home").click()
    qapp.processEvents()
    mark = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "clipart")
    invert = next(
        box
        for box in win._inspector.findChildren(QCheckBox)
        if box.text() == "Invertiert" and box.isVisible()
    )
    assert not invert.isChecked()
    invert.click()
    qapp.processEvents()
    assert mark.inverted
    win._act_undo.trigger()
    qapp.processEvents()
    mark = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "clipart")
    assert not mark.inverted
    win.close()
