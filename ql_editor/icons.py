"""Programmatisch gezeichnete Vektor-Icons.

Die Icons werden zur Laufzeit mit ``QPainter`` auf einem 24x24-Raster
gezeichnet. Vorteile:

* **keine externen Dateien** - es kann nichts "fehlen" und das ``.deb``
  braucht keine Icon-Assets,
* **scharf** - fuer jede benoetigte Groesse wird ein eigenes Pixmap gerendert
  (16/20/22/24/32/48 px),
* **theme-abhaengig** - die Farbe kommt aus der Palette (hell/dunkel),
* Qt erzeugt den deaktivierten Zustand automatisch durch Abblenden.

Gestaltung: einheitliche Strichstaerke (``_STROKE``), runde Enden/Ecken und
ein gemeinsamer optischer Bereich (ca. 4..20) - das wirkt ruhiger und
moderner als gemischte Strichbreiten.

Aufruf::

    from ql_editor.icons import icon
    action.setIcon(icon("print"))
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication

GRID = 24.0
_SIZES = (16, 20, 22, 24, 32, 48)
#: Einheitliche Strichstaerke (im 24er-Raster).
_STROKE = 1.8
#: Einheitlicher Eckenradius fuer abgerundete Rechtecke.
_RADIUS = 2.5
#: Groesse eines gezeichneten Mauszeigers (Bildschirmpixel).
CURSOR_SIZE = 24
_CACHE: dict[tuple[str, str], QIcon] = {}
_CURSOR_CACHE: dict[tuple[str, int, int], QCursor] = {}


# --------------------------------------------------------------------------- #
# Oeffentliche API
# --------------------------------------------------------------------------- #
def icon(name: str, color: QColor | None = None) -> QIcon:
    """Liefere ein (gecachtes) Icon fuer ``name`` in der gewuenschten Farbe."""
    if name not in _DRAW:
        raise KeyError(f"Unbekanntes Icon: {name}")
    color = color or text_color()
    key = (name, color.name())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = QIcon()
    for size in _SIZES:
        result.addPixmap(_render(name, size, color))
    _CACHE[key] = result
    return result


def text_color() -> QColor:
    """Standard-Iconfarbe (Palette der Anwendung, fallback dunkelgrau)."""
    app = QApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.ColorRole.WindowText)
    return QColor("#222222")


def cursor(name: str, size: int = CURSOR_SIZE) -> QCursor:
    """Ein ``QCursor`` aus einem gezeichneten Symbol (gecacht).

    Qt bringt keinen Rotations-Cursor mit - das Symbol wird deshalb wie die
    Icons gezeichnet und als Pixmap-Zeiger benutzt. Bewusst **ohne** Kontur:
    der Zeiger laeuft ueber dem hellen Canvas, und eine weisse Umrandung macht
    das feine Symbol bei 24 px nur dick und unkenntlich.

    Der "Klickpunkt" ist die Mitte des Symbols.
    """
    if name not in _DRAW:
        raise KeyError(f"Unbekanntes Icon: {name}")
    ratio = _device_pixel_ratio()
    key = (name, size, ratio)
    cached = _CURSOR_CACHE.get(key)
    if cached is None:
        cached = _build_cursor(name, size, ratio)
        _CURSOR_CACHE[key] = cached
    return cached


def _device_pixel_ratio() -> int:
    """Geraetepixel pro logischem Pixel (HiDPI) - mindestens 1."""
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1
    return max(1, round(screen.devicePixelRatio()))


def _build_cursor(name: str, size: int, ratio: int) -> QCursor:
    pixels = size * ratio
    pixmap = _render(name, pixels, QColor("#000000"))
    hotspot = QPoint(pixels // 2, pixels // 2)
    return QCursor(pixmap, hotspot.x(), hotspot.y())


def available() -> tuple[str, ...]:
    return tuple(sorted(_DRAW))


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _render(name: str, size: int, color: QColor) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / GRID, size / GRID)
    _DRAW[name](painter, color)
    painter.end()
    return pixmap


def _pen(color: QColor, width: float = _STROKE) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(p: QPainter, points: tuple[tuple[float, float], ...]) -> None:
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    p.drawPath(path)


def _stroke_only(p: QPainter, color: QColor, width: float = _STROKE) -> None:
    p.setPen(_pen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill_only(p: QPainter, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)


# --------------------------------------------------------------------------- #
# Zeichenfunktionen (24x24-Raster)
# --------------------------------------------------------------------------- #
def _draw_menu(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.9)
    for y in (7.0, 12.0, 17.0):
        _line(p, 4.5, y, 19.5, y)


def _draw_panel_left(p: QPainter, color: QColor) -> None:
    # Fenster mit hervorgehobenem linken Seitenpanel (ein-/ausblenden).
    _stroke_only(p, color)
    p.drawRoundedRect(QRectF(3.5, 5.0, 17.0, 14.0), _RADIUS, _RADIUS)
    _fill_only(p, color)
    p.drawRect(QRectF(5.3, 6.7, 5.0, 10.6))
    _stroke_only(p, color, 1.4)
    _line(p, 11.7, 6.7, 11.7, 17.3)


def _draw_panel_right(p: QPainter, color: QColor) -> None:
    # Fenster mit hervorgehobenem rechten Seitenpanel (ein-/ausblenden).
    _stroke_only(p, color)
    p.drawRoundedRect(QRectF(3.5, 5.0, 17.0, 14.0), _RADIUS, _RADIUS)
    _fill_only(p, color)
    p.drawRect(QRectF(13.7, 6.7, 5.0, 10.6))
    _stroke_only(p, color, 1.4)
    _line(p, 12.3, 6.7, 12.3, 17.3)


def _draw_text(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.9)
    _line(p, 5.5, 6.5, 18.5, 6.5)
    _line(p, 12.0, 6.5, 12.0, 18.5)


def _draw_image(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    p.drawRoundedRect(QRectF(3.5, 5.0, 17.0, 14.0), _RADIUS, _RADIUS)
    _fill_only(p, color)
    p.drawEllipse(QPointF(8.5, 9.5), 1.4, 1.4)
    _stroke_only(p, color)
    _poly(p, ((5.5, 17.0), (10.0, 12.0), (12.8, 14.8), (15.6, 11.6), (18.5, 17.0)))


def _draw_barcode(p: QPainter, color: QColor) -> None:
    _fill_only(p, color)
    for x, width in ((4.5, 1.6), (7.0, 1.0), (9.0, 2.2), (12.0, 1.0), (13.8, 1.6), (16.2, 1.0), (18.2, 1.6)):
        p.drawRect(QRectF(x, 5.5, width, 13.0))


def _draw_qr(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    for x, y in ((4.0, 4.0), (14.0, 4.0), (4.0, 14.0)):
        p.drawRoundedRect(QRectF(x, y, 6.0, 6.0), 1.4, 1.4)
    _fill_only(p, color)
    p.drawRect(QRectF(15.0, 15.0, 2.6, 2.6))
    p.drawRect(QRectF(18.6, 15.0, 1.4, 1.4))
    p.drawRect(QRectF(18.6, 18.6, 1.4, 1.4))


def _draw_line(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    _line(p, 5.0, 19.0, 19.0, 5.0)
    _fill_only(p, color)
    p.drawEllipse(QPointF(5.0, 19.0), 1.5, 1.5)
    p.drawEllipse(QPointF(19.0, 5.0), 1.5, 1.5)


def _draw_rect(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    p.drawRoundedRect(QRectF(4.0, 6.5, 16.0, 11.0), _RADIUS, _RADIUS)


def _draw_orient_across(p: QPainter, color: QColor) -> None:
    # Designflaeche so breit wie das Band: der Inhalt laeuft ueber die Bandbreite.
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(3.0, 8.0, 18.0, 8.0), 2.0, 2.0)
    _fill_only(p, color)
    p.drawRect(QRectF(6.0, 11.0, 12.0, 2.0))


def _draw_orient_along(p: QPainter, color: QColor) -> None:
    # Designflaeche so hoch wie das Band: der Inhalt laeuft in Bandrichtung.
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(8.0, 3.0, 8.0, 18.0), 2.0, 2.0)
    _fill_only(p, color)
    p.drawRect(QRectF(9.8, 11.0, 4.4, 2.0))


def _draw_front(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(3.5, 11.0, 9.5, 9.5), 2.0, 2.0)
    _line(p, 17.5, 19.5, 17.5, 5.5)
    _poly(p, ((14.0, 9.0), (17.5, 5.5), (21.0, 9.0)))


def _draw_back(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(3.5, 3.5, 9.5, 9.5), 2.0, 2.0)
    _line(p, 17.5, 4.5, 17.5, 18.5)
    _poly(p, ((14.0, 15.0), (17.5, 18.5), (21.0, 15.0)))


def _draw_delete(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    _line(p, 4.5, 6.8, 19.5, 6.8)
    _poly(p, ((9.2, 6.8), (9.2, 4.5), (14.8, 4.5), (14.8, 6.8)))
    _poly(p, ((6.8, 6.8), (7.6, 19.5), (16.4, 19.5), (17.2, 6.8)))
    _line(p, 10.4, 10.0, 10.8, 16.2)
    _line(p, 13.6, 10.0, 13.2, 16.2)


def _draw_zoom_in(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
    _line(p, 15.1, 15.1, 20.0, 20.0)
    _line(p, 7.5, 10.5, 13.5, 10.5)
    _line(p, 10.5, 7.5, 10.5, 13.5)


def _draw_zoom_out(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
    _line(p, 15.1, 15.1, 20.0, 20.0)
    _line(p, 7.5, 10.5, 13.5, 10.5)


def _draw_chevron_left(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 2.1)
    _poly(p, ((14.5, 5.5), (8.5, 12.0), (14.5, 18.5)))


def _draw_chevron_right(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 2.1)
    _poly(p, ((9.5, 5.5), (15.5, 12.0), (9.5, 18.5)))


def _draw_zoom_fit(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    for x1, y1, x2, y2, x3, y3 in (
        (4, 9, 4, 4, 9, 4),
        (15, 4, 20, 4, 20, 9),
        (20, 15, 20, 20, 15, 20),
        (9, 20, 4, 20, 4, 15),
    ):
        _line(p, x1, y1, x2, y2)
        _line(p, x2, y2, x3, y3)


def _draw_zoom_100(p: QPainter, color: QColor) -> None:
    # Lupe mit Punktraster: Ansicht in tatsaechlicher Groesse (1:1 = echte Dots).
    _stroke_only(p, color, 1.7)
    p.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
    _line(p, 15.1, 15.1, 20.0, 20.0)
    _fill_only(p, color)
    for x in (8.4, 12.6):
        for y in (8.4, 12.6):
            p.drawEllipse(QPointF(x, y), 1.15, 1.15)


def _draw_print(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(7.0, 3.5, 10.0, 5.0), 1.2, 1.2)
    p.drawRoundedRect(QRectF(3.5, 8.5, 17.0, 8.0), _RADIUS, _RADIUS)
    p.drawRoundedRect(QRectF(7.0, 16.5, 10.0, 4.0), 1.2, 1.2)
    _fill_only(p, color)
    p.drawEllipse(QPointF(17.0, 11.3), 1.0, 1.0)


def _draw_quit(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    # Kraft-Symbol: offener Kreis (Luecke oben) + senkrechter Strich.
    p.drawArc(QRectF(4.5, 5.0, 15.0, 15.0), 120 * 16, 300 * 16)
    _line(p, 12.0, 12.5, 12.0, 4.5)


def _draw_about(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    p.drawEllipse(QPointF(12.0, 12.0), 8.0, 8.0)
    _fill_only(p, color)
    p.drawEllipse(QPointF(12.0, 8.3), 1.15, 1.15)
    _stroke_only(p, color)
    _line(p, 12.0, 11.2, 12.0, 16.6)


def _draw_label(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawRoundedRect(QRectF(3.5, 6.5, 17.0, 11.0), _RADIUS, _RADIUS)
    _line(p, 7.0, 10.2, 17.0, 10.2)
    _line(p, 7.0, 13.8, 13.0, 13.8)


def _draw_detect(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color, 1.7)
    p.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
    _line(p, 15.1, 15.1, 20.0, 20.0)
    _line(p, 7.6, 9.4, 13.4, 9.4)
    _line(p, 7.6, 12.0, 11.4, 12.0)


def _draw_network(p: QPainter, color: QColor) -> None:
    """Globus - das uebliche Netzwerk-Symbol."""
    _stroke_only(p, color, 1.6)
    p.drawEllipse(QPointF(12.0, 12.0), 7.6, 7.6)
    p.drawEllipse(QPointF(12.0, 12.0), 3.4, 7.6)
    _line(p, 4.6, 9.4, 19.4, 9.4)
    _line(p, 4.6, 14.6, 19.4, 14.6)


def _draw_usb(p: QPainter, color: QColor) -> None:
    """USB-Dreizack: Stamm mit Pfeil, zwei Zweige, Kreis/Quadrat als Enden."""
    _stroke_only(p, color, 1.6)
    _line(p, 12.0, 4.6, 12.0, 18.4)
    _poly(p, ((9.7, 7.0), (12.0, 4.2), (14.3, 7.0)))
    _poly(p, ((12.0, 12.4), (8.0, 9.8), (8.0, 8.4)))
    _poly(p, ((12.0, 14.4), (16.0, 11.8), (16.0, 10.4)))
    _fill_only(p, color)
    p.drawEllipse(QPointF(8.0, 7.0), 1.5, 1.5)
    p.drawRect(QRectF(14.5, 7.0, 3.0, 3.0))
    p.drawEllipse(QPointF(12.0, 19.6), 1.7, 1.7)


def _draw_preview(p: QPainter, color: QColor) -> None:
    _stroke_only(p, color)
    path = QPainterPath()
    path.moveTo(2.8, 12.0)
    path.quadTo(12.0, 4.5, 21.2, 12.0)
    path.quadTo(12.0, 19.5, 2.8, 12.0)
    p.drawPath(path)
    p.drawEllipse(QPointF(12.0, 12.0), 2.8, 2.8)


def _draw_rotate(p: QPainter, color: QColor) -> None:
    """Kreisbogen mit Pfeilspitze - das uebliche "drehen"-Symbol.

    Wird auch als Mauszeiger am Drehgriff benutzt (Qt kennt keinen
    Rotations-Cursor).
    """
    center = QPointF(12.0, 12.0)
    radius = 7.6
    start, end = 55.0, 315.0  # Luecke rechts oben
    _stroke_only(p, color, 1.4)
    p.drawArc(
        QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
        int(start * 16),
        int((end - start) * 16),
    )
    # Pfeilspitze genau am Bogenende, in Bewegungsrichtung gedreht.
    theta = math.radians(end)
    tip = QPointF(
        center.x() + radius * math.cos(theta), center.y() - radius * math.sin(theta)
    )
    forward = QPointF(-math.sin(theta), -math.cos(theta))  # Bewegungsrichtung
    sideways = QPointF(-forward.y(), forward.x())
    _fill_only(p, color)
    p.drawPolygon(
        QPolygonF(
            [
                tip + forward * 5.8,
                tip - forward * 0.6 + sideways * 2.9,
                tip - forward * 0.6 - sideways * 2.9,
            ]
        )
    )


_DRAW = {
    "menu": _draw_menu,
    "text": _draw_text,
    "image": _draw_image,
    "barcode": _draw_barcode,
    "qr": _draw_qr,
    "line": _draw_line,
    "rect": _draw_rect,
    "panel_left": _draw_panel_left,
    "panel_right": _draw_panel_right,
    "orient_across": _draw_orient_across,
    "orient_along": _draw_orient_along,
    "front": _draw_front,
    "back": _draw_back,
    "delete": _draw_delete,
    "zoom_in": _draw_zoom_in,
    "zoom_out": _draw_zoom_out,
    "zoom_fit": _draw_zoom_fit,
    "zoom_100": _draw_zoom_100,
    "chevron_left": _draw_chevron_left,
    "chevron_right": _draw_chevron_right,
    "print": _draw_print,
    "quit": _draw_quit,
    "about": _draw_about,
    "label": _draw_label,
    "detect": _draw_detect,
    "network": _draw_network,
    "usb": _draw_usb,
    "preview": _draw_preview,
    "rotate": _draw_rotate,
}

__all__ = ["icon", "cursor", "text_color", "available", "GRID"]
