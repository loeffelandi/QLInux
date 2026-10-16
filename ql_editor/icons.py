"""Programmatisch gezeichnete Vektor-Icons.

Die Icons werden zur Laufzeit mit ``QPainter`` auf einem 24x24-Raster
gezeichnet. Vorteile:

* **keine externen Dateien** - es kann nichts "fehlen" und das ``.deb``
  braucht keine Icon-Assets,
* **scharf** - fuer jede benoetigte Groesse wird ein eigenes Pixmap gerendert
  (16/20/24/32/48 px),
* **theme-abhaengig** - die Farbe kommt aus der Palette (hell/dunkel),
* Qt erzeugt den deaktivierten Zustand automatisch durch Abblenden.

Aufruf::

    from ql_editor.icons import icon
    action.setIcon(icon("print"))
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

GRID = 24.0
_SIZES = (16, 20, 24, 32, 48)
_CACHE: dict[tuple[str, str], QIcon] = {}


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


def _pen(color: QColor, width: float = 1.9) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


# --------------------------------------------------------------------------- #
# Zeichenfunktionen (24x24-Raster)
# --------------------------------------------------------------------------- #
def _draw_text(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 2.0))
    _line(p, 5.5, 6.5, 18.5, 6.5)
    _line(p, 12, 6.5, 12, 18)


def _draw_image(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(8.5, 9.5), 1.5, 1.5)
    path = QPainterPath()
    path.moveTo(5.5, 17.5)
    path.lineTo(10, 12)
    path.lineTo(12.8, 15)
    path.lineTo(15.5, 11.8)
    path.lineTo(18.5, 17.5)
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_barcode(p: QPainter, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for x, width in ((4.5, 1.4), (7, 1.0), (9, 2.0), (12, 1.0), (13.6, 1.6), (16, 1.0), (18, 1.4)):
        p.drawRect(QRectF(x, 5, width, 14))


def _draw_qr(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for x, y in ((4, 4), (14.5, 4), (4, 14.5)):
        p.drawRect(QRectF(x, y, 5.5, 5.5))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for x, y in ((14.5, 14.5), (17.5, 14.5), (14.5, 17.5), (17.5, 17.5)):
        p.drawRect(QRectF(x, y, 2, 2))


def _draw_line(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color))
    _line(p, 4.5, 19.5, 19.5, 4.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(4.5, 19.5), 1.7, 1.7)
    p.drawEllipse(QPointF(19.5, 4.5), 1.7, 1.7)


def _draw_rect(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)


def _draw_front(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(4, 9.5, 10.5, 10.5))
    _line(p, 18, 18.5, 18, 6)
    _line(p, 14.5, 9.5, 18, 6)
    _line(p, 21.5, 9.5, 18, 6)


def _draw_back(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(4, 4, 10.5, 10.5))
    _line(p, 18, 5.5, 18, 18)
    _line(p, 14.5, 14.5, 18, 18)
    _line(p, 21.5, 14.5, 18, 18)


def _draw_delete(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _line(p, 5.5, 7, 18.5, 7)
    _line(p, 9.5, 4.5, 14.5, 4.5)
    path = QPainterPath()
    path.moveTo(7, 7)
    path.lineTo(7.9, 19)
    path.lineTo(16.1, 19)
    path.lineTo(17, 7)
    p.drawPath(path)
    _line(p, 10.5, 10, 10.8, 16)
    _line(p, 13.5, 10, 13.2, 16)


def _draw_zoom_in(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    _line(p, 15, 15, 20, 20)
    _line(p, 7.5, 10.5, 13.5, 10.5)
    _line(p, 10.5, 7.5, 10.5, 13.5)


def _draw_zoom_out(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    _line(p, 15, 15, 20, 20)
    _line(p, 7.5, 10.5, 13.5, 10.5)


def _draw_zoom_fit(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for x1, y1, x2, y2, x3, y3 in (
        (4, 9, 4, 4, 9, 4),
        (15, 4, 20, 4, 20, 9),
        (20, 15, 20, 20, 15, 20),
        (9, 20, 4, 20, 4, 15),
    ):
        _line(p, x1, y1, x2, y2)
        _line(p, x2, y2, x3, y3)


def _draw_print(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(7, 3.5, 10, 5))
    p.drawRect(QRectF(3.5, 8.5, 17, 8))
    p.drawRect(QRectF(7, 16.5, 10, 4))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(17, 11.2), 1.0, 1.0)


def _draw_quit(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(13, 5)
    path.lineTo(5, 5)
    path.lineTo(5, 19)
    path.lineTo(13, 19)
    p.drawPath(path)
    _line(p, 10, 12, 20, 12)
    _line(p, 16.5, 8.5, 20, 12)
    _line(p, 16.5, 15.5, 20, 12)


def _draw_about(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(12, 8), 1.1, 1.1)
    p.setPen(_pen(color, 1.8))
    _line(p, 12, 11, 12, 16.5)


def _draw_label(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 6.5, 17, 11), 2, 2)
    _line(p, 7, 10, 17, 10)
    _line(p, 7, 14, 13, 14)


def _draw_detect(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    _line(p, 15, 15, 20, 20)
    _line(p, 7.5, 9.5, 13.5, 9.5)
    _line(p, 7.5, 12, 11.5, 12)


def _draw_file(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(6, 3.5)
    path.lineTo(14, 3.5)
    path.lineTo(18, 7.5)
    path.lineTo(18, 20.5)
    path.lineTo(6, 20.5)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 14, 3.5, 14, 7.5)
    _line(p, 14, 7.5, 18, 7.5)


def _draw_edit(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(5, 19)
    path.lineTo(6.5, 14.5)
    path.lineTo(16, 5)
    path.lineTo(19, 8)
    path.lineTo(9.5, 17.5)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 6.5, 14.5, 9.5, 17.5)


def _draw_view(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(3, 12)
    path.quadTo(12, 4, 21, 12)
    path.quadTo(12, 20, 3, 12)
    p.drawPath(path)
    p.drawEllipse(QPointF(12, 12), 3, 3)


def _draw_help(p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    path = QPainterPath()
    path.moveTo(9, 9.5)
    path.quadTo(9.5, 6.5, 12, 6.5)
    path.quadTo(15, 6.5, 15, 9)
    path.quadTo(15, 11, 12, 11.5)
    path.lineTo(12, 13.5)
    p.setPen(_pen(color, 1.8))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(12, 16.5), 1.1, 1.1)


_DRAW = {
    "text": _draw_text,
    "image": _draw_image,
    "barcode": _draw_barcode,
    "qr": _draw_qr,
    "line": _draw_line,
    "rect": _draw_rect,
    "front": _draw_front,
    "back": _draw_back,
    "delete": _draw_delete,
    "zoom_in": _draw_zoom_in,
    "zoom_out": _draw_zoom_out,
    "zoom_fit": _draw_zoom_fit,
    "print": _draw_print,
    "quit": _draw_quit,
    "about": _draw_about,
    "label": _draw_label,
    "detect": _draw_detect,
    "file": _draw_file,
    "edit": _draw_edit,
    "view": _draw_view,
    "help": _draw_help,
}

__all__ = ["icon", "text_color", "available", "GRID"]
