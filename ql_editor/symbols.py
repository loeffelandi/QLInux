"""Eigene Clip-Art-Symbole für Etiketten.

Scharfe, gefüllte Zeichen in einem 100×100-Feld. Sie sind absichtlich keine
Nachzeichnung der Brother-Bibliothek: einfache Formen, die auf einem
monochromen (oder schwarz/roten) Band lesbar bleiben.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr

DEFAULT_SYMBOL = "warning"
_FIELD = 100.0

CATEGORY_KEYS: tuple[str, ...] = ("signs", "arrows", "shapes", "everyday")


@dataclass(frozen=True)
class SymbolSpec:
    id: str
    category: str


SYMBOLS: tuple[SymbolSpec, ...] = (
    SymbolSpec("warning", "signs"),
    SymbolSpec("info", "signs"),
    SymbolSpec("ban", "signs"),
    SymbolSpec("check", "signs"),
    SymbolSpec("cross", "signs"),
    SymbolSpec("diamond_alert", "signs"),
    SymbolSpec("arrow_up", "arrows"),
    SymbolSpec("arrow_down", "arrows"),
    SymbolSpec("arrow_left", "arrows"),
    SymbolSpec("arrow_right", "arrows"),
    SymbolSpec("arrow_corner", "arrows"),
    SymbolSpec("arrow_both", "arrows"),
    SymbolSpec("star", "shapes"),
    SymbolSpec("heart", "shapes"),
    SymbolSpec("plus", "shapes"),
    SymbolSpec("circle", "shapes"),
    SymbolSpec("ring", "shapes"),
    SymbolSpec("bolt", "shapes"),
    SymbolSpec("home", "everyday"),
    SymbolSpec("lock", "everyday"),
    SymbolSpec("phone", "everyday"),
    SymbolSpec("mail", "everyday"),
    SymbolSpec("key", "everyday"),
    SymbolSpec("clock", "everyday"),
    SymbolSpec("gear", "everyday"),
    SymbolSpec("flame", "everyday"),
    SymbolSpec("drop", "everyday"),
    SymbolSpec("leaf", "everyday"),
    SymbolSpec("bell", "everyday"),
)

_BY_ID = {spec.id: spec for spec in SYMBOLS}
_PATHS: dict[str, QPainterPath] = {}


def known_symbol(symbol_id: str) -> str:
    """Bekannte Kennung, sonst das Standardsymbol."""
    return symbol_id if symbol_id in _BY_ID else DEFAULT_SYMBOL


def category_label(key: str) -> str:
    return {
        "signs": tr("Hinweise"),
        "arrows": tr("Pfeile"),
        "shapes": tr("Formen"),
        "everyday": tr("Alltag"),
    }.get(key, key)


def symbol_label(symbol_id: str) -> str:
    return {
        "warning": tr("Achtung"),
        "info": tr("Info"),
        "ban": tr("Verbot"),
        "check": tr("Haken"),
        "cross": tr("Kreuz"),
        "diamond_alert": tr("Raute"),
        "arrow_up": tr("Pfeil hoch"),
        "arrow_down": tr("Pfeil runter"),
        "arrow_left": tr("Pfeil links"),
        "arrow_right": tr("Pfeil rechts"),
        "arrow_corner": tr("Eckpfeil"),
        "arrow_both": tr("Doppelpfeil"),
        "star": tr("Stern"),
        "heart": tr("Herz"),
        "plus": tr("Plus"),
        "circle": tr("Kreis"),
        "ring": tr("Ring"),
        "bolt": tr("Blitz"),
        "home": tr("Haus"),
        "lock": tr("Schloss"),
        "phone": tr("Telefon"),
        "mail": tr("Brief"),
        "key": tr("Schlüssel"),
        "clock": tr("Uhr"),
        "gear": tr("Zahnrad"),
        "flame": tr("Flamme"),
        "drop": tr("Tropfen"),
        "leaf": tr("Blatt"),
        "bell": tr("Glocke"),
    }.get(symbol_id, symbol_id)


def symbols_in(category: str | None) -> tuple[SymbolSpec, ...]:
    if not category:
        return SYMBOLS
    return tuple(spec for spec in SYMBOLS if spec.category == category)


def path_for(symbol_id: str) -> QPainterPath:
    symbol_id = known_symbol(symbol_id)
    cached = _PATHS.get(symbol_id)
    if cached is None:
        cached = _BUILDERS[symbol_id]()
        _PATHS[symbol_id] = cached
    return cached


def paint_symbol(painter: QPainter, symbol_id: str, rect: QRectF, color: str) -> None:
    """Symbol in ``rect`` füllen. Löcher bleiben frei (Bandgrund)."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("red" if color == "red" else "black"))
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / _FIELD, rect.height() / _FIELD)
    painter.drawPath(path_for(symbol_id))
    painter.restore()


def symbol_icon(symbol_id: str, size: int = 48) -> QIcon:
    """Kleines Vorschaubild für die Auswahl."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_symbol(painter, symbol_id, QRectF(1, 1, size - 2, size - 2), "black")
    painter.end()
    return QIcon(pixmap)


class SymbolPicker(QWidget):
    """Kategorie und Raster. Ein Klick meldet die Symbolkennung."""

    chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("clipart_picker")
        # Niedrige Mindestmasse: im kleinen Fenster muss das Sheet den
        # Scrollbalken noch zeigen koennen (sonst wird er unten abgeschnitten).
        self.setMinimumSize(260, 140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Kategorie")))
        self._category = QComboBox()
        self._category.setObjectName("clipart_category")
        self._category.addItem(tr("Alle"), "")
        for key in CATEGORY_KEYS:
            self._category.addItem(category_label(key), key)
        self._category.currentIndexChanged.connect(self._refill)
        row.addWidget(self._category, 1)
        layout.addLayout(row)

        scroll = QScrollArea()
        scroll.setObjectName("clipart_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(72)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        scroll.setWidget(self._host)
        layout.addWidget(scroll, 1)
        self._refill()

    def _refill(self) -> None:
        while self._grid.count():
            child = self._grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        specs = symbols_in(self._category.currentData())
        columns = 5
        for index, spec in enumerate(specs):
            button = QToolButton(self._host)
            button.setObjectName(f"symbol_{spec.id}")
            button.setIcon(symbol_icon(spec.id))
            button.setIconSize(QSize(40, 40))
            button.setToolTip(symbol_label(spec.id))
            button.setAutoRaise(True)
            button.setFixedSize(72, 72)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, sid=spec.id: self.chosen.emit(sid))
            self._grid.addWidget(button, index // columns, index % columns)


# --------------------------------------------------------------------------- #
# Pfade
# --------------------------------------------------------------------------- #
def _P(*pts: tuple[float, float]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def _R(x: float, y: float, w: float, h: float) -> QPainterPath:
    path = QPainterPath()
    path.addRect(x, y, w, h)
    return path


def _E(cx: float, cy: float, rx: float, ry: float | None = None) -> QPainterPath:
    ry = rx if ry is None else ry
    path = QPainterPath()
    path.addEllipse(cx - rx, cy - ry, rx * 2, ry * 2)
    return path


def _round(x: float, y: float, w: float, h: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(x, y, w, h, radius, radius)
    return path


def _rot(path: QPainterPath, degrees: float, cx: float = 50, cy: float = 50) -> QPainterPath:
    transform = QTransform().translate(cx, cy).rotate(degrees).translate(-cx, -cy)
    return transform.map(path)


def _flip_x(path: QPainterPath) -> QPainterPath:
    return QTransform().translate(_FIELD, 0).scale(-1, 1).map(path)


def _bar(length: float, thickness: float, degrees: float) -> QPainterPath:
    return _rot(_R(50 - length / 2, 50 - thickness / 2, length, thickness), degrees)


def _star() -> QPainterPath:
    points: list[tuple[float, float]] = []
    for index in range(10):
        radius = 40 if index % 2 == 0 else 16
        angle = math.radians(-90 + index * 36)
        points.append((50 + radius * math.cos(angle), 52 + radius * math.sin(angle)))
    return _P(*points)


def _heart() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(50, 86)
    path.cubicTo(16, 62, 8, 46, 8, 34)
    path.cubicTo(8, 16, 24, 8, 38, 20)
    path.cubicTo(46, 28, 50, 36, 50, 36)
    path.cubicTo(50, 36, 54, 28, 62, 20)
    path.cubicTo(76, 8, 92, 16, 92, 34)
    path.cubicTo(92, 46, 84, 62, 50, 86)
    return path


def _flame() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(50, 8)
    path.cubicTo(78, 30, 86, 52, 74, 68)
    path.cubicTo(88, 78, 72, 94, 50, 94)
    path.cubicTo(28, 94, 12, 78, 26, 68)
    path.cubicTo(14, 52, 22, 30, 50, 8)
    inner = QPainterPath()
    inner.moveTo(50, 46)
    inner.cubicTo(62, 58, 66, 74, 50, 84)
    inner.cubicTo(34, 74, 38, 58, 50, 46)
    return path.subtracted(inner)


def _drop() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(50, 8)
    path.cubicTo(50, 8, 90, 48, 90, 66)
    path.cubicTo(90, 86, 72, 94, 50, 94)
    path.cubicTo(28, 94, 10, 86, 10, 66)
    path.cubicTo(10, 48, 50, 8, 50, 8)
    return path


def _warning() -> QPainterPath:
    return _P((50, 8), (92, 90), (8, 90)).subtracted(_R(46, 40, 8, 26)).subtracted(_E(50, 76, 5))


def _info() -> QPainterPath:
    return _E(50, 50, 40).subtracted(_E(50, 32, 5.5)).subtracted(_R(44.5, 42, 11, 28))


def _ban() -> QPainterPath:
    disc = _E(50, 50, 40)
    ring = disc.subtracted(_E(50, 50, 26))
    return ring.united(_bar(76, 12, -42).intersected(disc))


def _check() -> QPainterPath:
    left = _P((16, 50), (32, 46), (50, 80), (32, 88))
    right = _P((34, 84), (52, 76), (90, 24), (74, 16))
    return left.united(right)


def _diamond_alert() -> QPainterPath:
    return _P((50, 6), (94, 50), (50, 94), (6, 50)).subtracted(_R(46, 30, 8, 28)).subtracted(_E(50, 70, 5))


def _arrow_right() -> QPainterPath:
    return _P((8, 34), (56, 34), (56, 16), (92, 50), (56, 84), (56, 66), (8, 66))


def _arrow_corner() -> QPainterPath:
    shaft = _R(14, 18, 48, 16).united(_R(46, 18, 16, 36))
    head = _P((38, 54), (70, 54), (54, 90))
    return shaft.united(head)


def _arrow_both() -> QPainterPath:
    return _P(
        (6, 50),
        (26, 30),
        (26, 42),
        (74, 42),
        (74, 30),
        (94, 50),
        (74, 70),
        (74, 58),
        (26, 58),
        (26, 70),
    )


def _home() -> QPainterPath:
    body = _P((50, 8), (92, 46), (76, 46), (76, 90), (24, 90), (24, 46), (8, 46))
    return body.subtracted(_R(42, 58, 16, 32))


def _lock() -> QPainterPath:
    shackle = _E(50, 38, 20).subtracted(_E(50, 40, 11)).intersected(_R(20, 10, 60, 34))
    body = _round(24, 40, 52, 48, 6)
    return shackle.united(body).subtracted(_E(50, 58, 6)).subtracted(_R(46, 60, 8, 16))


def _phone() -> QPainterPath:
    return _round(30, 6, 40, 88, 8).subtracted(_R(42, 14, 16, 5)).subtracted(_round(40, 74, 20, 8, 3))


def _mail() -> QPainterPath:
    notch = _P((16, 32), (50, 58), (84, 32), (76, 32), (50, 48), (24, 32))
    return _R(10, 24, 80, 54).subtracted(notch)


def _key() -> QPainterPath:
    bow = _E(32, 46, 20).subtracted(_E(32, 46, 9))
    return bow.united(_R(48, 40, 40, 12)).united(_R(70, 52, 8, 16)).united(_R(82, 52, 8, 12))


def _clock() -> QPainterPath:
    ring = _E(50, 50, 40).subtracted(_E(50, 50, 32))
    return ring.united(_R(47, 22, 6, 30)).united(_R(50, 47, 22, 6))


def _gear() -> QPainterPath:
    body = _E(50, 50, 24)
    for index in range(8):
        tooth = _rot(_R(43, 6, 14, 20), index * 45)
        body = body.united(tooth)
    return body.subtracted(_E(50, 50, 9))


def _leaf() -> QPainterPath:
    blade = QPainterPath()
    blade.moveTo(22, 86)
    blade.quadTo(6, 40, 76, 16)
    blade.quadTo(98, 48, 22, 86)
    vein = _P((34, 74), (28, 66), (64, 30), (70, 38))
    return blade.subtracted(vein)


def _bell() -> QPainterPath:
    dome = _P((50, 16), (76, 36), (84, 58), (16, 58), (24, 36))
    return _E(50, 14, 6).united(dome).united(_R(14, 56, 72, 12)).united(_E(50, 78, 8))


_BUILDERS = {
    "warning": _warning,
    "info": _info,
    "ban": _ban,
    "check": _check,
    "cross": lambda: _bar(62, 14, 45).united(_bar(62, 14, -45)),
    "diamond_alert": _diamond_alert,
    "arrow_up": lambda: _rot(_arrow_right(), -90),
    "arrow_down": lambda: _rot(_arrow_right(), 90),
    "arrow_left": lambda: _flip_x(_arrow_right()),
    "arrow_right": _arrow_right,
    "arrow_corner": _arrow_corner,
    "arrow_both": _arrow_both,
    "star": _star,
    "heart": _heart,
    "plus": lambda: _R(40, 14, 20, 72).united(_R(14, 40, 72, 20)),
    "circle": lambda: _E(50, 50, 38),
    "ring": lambda: _E(50, 50, 40).subtracted(_E(50, 50, 24)),
    "bolt": lambda: _P((58, 6), (24, 52), (44, 52), (36, 94), (80, 42), (56, 42)),
    "home": _home,
    "lock": _lock,
    "phone": _phone,
    "mail": _mail,
    "key": _key,
    "clock": _clock,
    "gear": _gear,
    "flame": _flame,
    "drop": _drop,
    "leaf": _leaf,
    "bell": _bell,
}
