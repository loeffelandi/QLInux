"""Qt-E2E-Tests: Hauptfenster mit echten Mausklicks und Tastatureingaben.

Die Tests bedienen das Fenster wie ein Mensch: Aktion aus der Toolbar,
Ziehen mit der Maus auf dem Canvas, Tippen im Textfeld. Nur der Dateidialog
wird ersetzt, damit kein Fenster aufgeht. Kein Drucker wird benoetigt.
"""

from __future__ import annotations

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ql_editor import app as app_module
from ql_editor.items import ImageItem, TextItem

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    from PySide6.QtCore import QSettings

    QSettings("QLInux", "QLInux").clear()
    yield
    QSettings("QLInux", "QLInux").clear()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    QApplication.processEvents()


@pytest.fixture
def image_path(tmp_path) -> str:
    path = tmp_path / "logo.png"
    img = Image.new("RGB", (240, 120), (200, 30, 30))
    for x in range(60, 180):
        for y in range(30, 90):
            img.putpixel((x, y), (255, 255, 255))
    img.save(path)
    return str(path)


def _choose_file_returns(monkeypatch, path: str) -> None:
    """Ersetzt den Dateidialog durch eine sofortige Auswahl von ``path``."""

    def fake_choose_file(parent, *, on_selected, **_kwargs):
        on_selected(path)

    monkeypatch.setattr(app_module, "choose_file", fake_choose_file)


def _drag(canvas, start: QPointF, end: QPointF, steps: int = 8) -> None:
    """Linke Maustaste von ``start`` nach ``end`` ziehen (Szenenkoordinaten)."""
    vp = canvas.viewport()
    p0 = canvas.mapFromScene(start)
    p1 = canvas.mapFromScene(end)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for i in range(1, steps + 1):
        t = i / steps
        mid = p0 + (p1 - p0) * t
        QTest.mouseMove(vp, mid)
    QTest.mouseRelease(
        vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1
    )
    QApplication.processEvents()


def _last_item(canvas, kind):
    items = [i for i in canvas.ordered_items() if isinstance(i, kind)]
    assert items, f"kein {kind.__name__} auf dem Canvas"
    return items[-1]


def _center(item) -> QPointF:
    return item.sceneBoundingRect().center()


def test_bild_einfuegen_legt_bild_auf_den_canvas(window, monkeypatch, image_path):
    _choose_file_returns(monkeypatch, image_path)

    window._act_add_image.trigger()
    QApplication.processEvents()

    image = _last_item(window._canvas, ImageItem)
    assert image.sceneBoundingRect().width() > 0


def test_bild_verschieben_mit_der_maus(window, monkeypatch, image_path):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    before = image.pos()

    start = _center(image)
    _drag(canvas, start, start + QPointF(20, 0))

    assert image.pos().x() != pytest.approx(before.x(), abs=1)


def test_bild_groesse_aendern_ueber_griff(window, monkeypatch, image_path):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    canvas.scene().clearSelection()
    image.setSelected(True)
    QApplication.processEvents()
    width_before = image.sceneBoundingRect().width()

    corner = canvas._handle_points(image)["se"]
    _drag(canvas, corner, corner + QPointF(-30, 0))

    assert image.sceneBoundingRect().width() < width_before


def test_bild_drehen_ueber_drehgriff(window, monkeypatch, image_path):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    canvas.scene().clearSelection()
    image.setSelected(True)
    QApplication.processEvents()
    assert image.rotation() == pytest.approx(0)

    corner = canvas._handle_points(image)["se"]
    _drag(canvas, corner, corner + QPointF(-150, -50))
    canvas.scene().clearSelection()
    image.setSelected(True)
    QApplication.processEvents()

    handle = canvas._rotate_handle_point(image)
    center = _center(image)
    target = center + QPointF(
        center.y() - handle.y(), 0
    )  # eine Vierteldrehung nach rechts
    _drag(canvas, handle, target)

    assert image.rotation() == pytest.approx(90, abs=5)


def test_drehen_wird_verhindert_wenn_das_bild_den_rand_verlaesst(
    window, monkeypatch, image_path
):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    canvas.scene().clearSelection()
    image.setSelected(True)
    QApplication.processEvents()

    handle = canvas._rotate_handle_point(image)
    center = _center(image)
    target = center + QPointF(center.y() - handle.y(), 0)
    _drag(canvas, handle, target)

    assert image.rotation() == pytest.approx(0)


def test_text_eingeben(window):
    canvas = window._canvas
    window._act_add_text.trigger()
    QApplication.processEvents()
    text = _last_item(canvas, TextItem)

    text.start_editing()
    canvas.setFocus()
    QTest.keyClicks(canvas.viewport(), "Hallo QLInux")
    text.finish_editing()
    QApplication.processEvents()

    assert "Hallo QLInux" in text.text_value


def test_bild_wird_am_druckbereich_geklemmt(window, monkeypatch, image_path):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    printable = canvas.printable_rect()

    start = _center(image)
    _drag(canvas, start, start + QPointF(printable.width() * 3, 0))

    rect = image.sceneBoundingRect()
    assert rect.right() <= printable.right() + 1
    assert rect.left() >= printable.left() - 1


def test_bild_wird_am_druckbereich_oben_und_unten_geklemmt(
    window, monkeypatch, image_path
):
    _choose_file_returns(monkeypatch, image_path)
    window._act_add_image.trigger()
    canvas = window._canvas
    image = _last_item(canvas, ImageItem)
    printable = canvas.printable_rect()

    start = _center(image)
    _drag(canvas, start, start + QPointF(0, printable.height() * 3))
    rect = image.sceneBoundingRect()
    assert rect.bottom() <= printable.bottom() + 1

    _drag(canvas, _center(image), _center(image) + QPointF(0, -printable.height() * 6))
    rect = image.sceneBoundingRect()
    assert rect.top() >= printable.top() - 1


def test_rand_verkleinert_den_innenbereich(window):
    canvas = window._canvas
    printable = canvas.printable_rect()
    canvas.set_margins(8, 0, 0, 0)
    QApplication.processEvents()

    inner = canvas.margin_rect()
    assert inner.left() > printable.left() + 1
    assert inner.top() == pytest.approx(printable.top(), abs=0.5)
    assert inner.right() == pytest.approx(printable.right(), abs=0.5)


def test_rand_null_laesst_den_innenbereich_unveraendert(window):
    canvas = window._canvas
    canvas.set_margins(0, 0, 0, 0)
    QApplication.processEvents()

    inner = canvas.margin_rect()
    printable = canvas.printable_rect()
    assert inner.left() == pytest.approx(printable.left(), abs=0.5)
    assert inner.top() == pytest.approx(printable.top(), abs=0.5)
