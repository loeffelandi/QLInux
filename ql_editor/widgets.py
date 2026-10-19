"""Kleine Widget-Helfer.

* :func:`install_wheel_guard` verhindert, dass ein Steuerelement (Spinbox,
  Combobox, ...) seinen Wert aendert, waehrend man nur mit dem Mausrad
  darueber faehrt. Statt das Ereignis zu schlucken, wird es an den umgebenden
  Scrollbereich weitergereicht - so scrollt das Panel, wie man es erwartet.
* :class:`SmoothScrollArea` und :class:`SmoothScroller` sorgen fuer weiches,
  animiertes Scrollen (wie auf dem Mac) statt harter Spruenge pro Raste.
* :class:`ToolbarSeparator` zeichnet die Trenner in der Werkzeugleiste aus
  der Palette (Mid), hell und dunkel lesbar.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRect,
    QObject,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QWidget,
)


class ToolbarSeparator(QWidget):
    """Senkrechter Trenner in der Werkzeugleiste.

    Fusion malt ``QToolBarSeparator`` mit Dark. Auf dem dunklen Fenstergrund
    liegt die Linie dann dunkler als die Leiste und verschwindet. Mid ist auf
    Hell grau und auf Dunkel hell genug. Kein Stylesheet: sonst loesen sich
    die Toolbar-Knoepfe von der Anwendungspalette.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolbar_separator")
        self.setFixedWidth(6)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self):  # noqa: N802
        return self.minimumSizeHint()

    def minimumSizeHint(self):  # noqa: N802
        return QSize(6, 22)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorRole.Mid)
        painter.setPen(QPen(color, 1))
        x = self.width() // 2
        margin = 4
        painter.drawLine(x, margin, x, max(margin, self.height() - margin))


def add_toolbar_separator(bar: QToolBar) -> QAction:
    """Trenner in ``bar`` einfuegen. Rueckgabe wie ``QToolBar.addSeparator``."""
    return bar.addWidget(ToolbarSeparator(bar))


class _TitleBox(QGroupBox):
    """Gruppenkasten mit fetter Ueberschrift und normalem Inhalt.

    ``QGroupBox::title`` setzt Fusion nicht um. Fett an der Schrift des
    Kastens schon. Ein Stylesheet dafuer wuerde die Felder aus der
    Anwendungspalette loesen: auf einem dunklen Desktop blieben die
    Auswahllisten dunkel, auch im hellen Modus.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        title_font = QFont(self.font())
        title_font.setBold(True)
        self.setFont(title_font)
        self._body_font = QFont(title_font)
        self._body_font.setBold(False)

    def childEvent(self, event) -> None:  # noqa: N802
        super().childEvent(event)
        if event.type() != QEvent.Type.ChildAdded:
            return
        child = event.child()
        if isinstance(child, QWidget):
            child.setFont(self._body_font)


def title_box(title: str, parent: QWidget | None = None) -> QGroupBox:
    """Gruppenkasten, dessen Ueberschrift fett ist und der Inhalt nicht."""
    return _TitleBox(title, parent)


#: Pixel, die eine Mausrad-Raste (120 Einheiten) scrollt.
WHEEL_PIXELS_PER_NOTCH = 64
#: Dauer der Scroll-Animation in Millisekunden.
SMOOTH_SCROLL_MS = 160


def wheel_deltas(event) -> tuple[float, float]:
    """(dx, dy) in Pixeln aus einem Rad-Ereignis.

    Trackpads liefern ``pixelDelta()`` (feine Werte) - die werden bevorzugt,
    damit das Scrollen fluessig bleibt; sonst wird ``angleDelta()`` in Pixel
    umgerechnet. Positiv = Rad nach oben/rechts.
    """
    pixel = event.pixelDelta()
    if not pixel.isNull():
        return float(pixel.x()), float(pixel.y())
    angle = event.angleDelta()
    return (
        angle.x() / 120.0 * WHEEL_PIXELS_PER_NOTCH,
        angle.y() / 120.0 * WHEEL_PIXELS_PER_NOTCH,
    )


class SmoothScroller(QObject):
    """Animiert den Wert einer Scrollbar fuer weiches Rad-Scrollen."""

    def __init__(self, parent: QObject, bar, duration: int = SMOOTH_SCROLL_MS):
        super().__init__(parent)
        self._bar = bar
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def scroll_by(self, delta_px: float) -> None:
        """Scrolle relativ um ``delta_px`` (positiv = Wert erhoehen)."""
        if not delta_px:
            return
        running = self._anim.state() == QPropertyAnimation.State.Running
        # Bei laufender Animation vom *Ziel* aufaddieren, damit schnelles
        # Radeln nicht ins Leere laeuft.
        base = float(self._anim.endValue()) if running else float(self._bar.value())
        target = max(
            float(self._bar.minimum()),
            min(float(self._bar.maximum()), base + delta_px),
        )
        self._anim.stop()
        self._anim.setStartValue(float(self._bar.value()))
        self._anim.setEndValue(target)
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()


class SmoothScrollArea(QScrollArea):
    """``QScrollArea`` mit weichem, animiertem Mausrad-Scrollen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = SmoothScroller(self, self.verticalScrollBar())
        self._h = SmoothScroller(self, self.horizontalScrollBar())
        self.verticalScrollBar().sliderPressed.connect(self._v.stop)
        self.horizontalScrollBar().sliderPressed.connect(self._h.stop)

    def smooth_scroll_by(self, dx: float, dy: float) -> None:
        """Scrolle um (dx, dy) Pixel (positiv = nach unten/rechts)."""
        if self.verticalScrollBar().maximum() > 0:
            self._v.scroll_by(dy)
        if self.horizontalScrollBar().maximum() > 0:
            self._h.scroll_by(dx)

    def wheelEvent(self, event) -> None:  # noqa: N802
        vmax = self.verticalScrollBar().maximum()
        hmax = self.horizontalScrollBar().maximum()
        if vmax <= 0 and hmax <= 0:
            super().wheelEvent(event)
            return
        dx, dy = wheel_deltas(event)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and hmax > 0:
            dx, dy = (dy or dx), 0.0
        # Rad nach oben -> Inhalt nach unten -> Wert verkleinern.
        self.smooth_scroll_by(-dx, -dy)
        event.accept()


def _scroll_area_ancestor(widget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class _WheelGuard(QObject):
    """Event-Filter: leitet Rad-Ereignisse ohne Fokus an den Scrollbereich."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            area = _scroll_area_ancestor(obj)
            if area is not None:
                dx, dy = wheel_deltas(event)
                if hasattr(area, "smooth_scroll_by"):
                    area.smooth_scroll_by(-dx, -dy)
                else:
                    vbar = area.verticalScrollBar()
                    vbar.setValue(int(round(vbar.value() - dy)))
            return True  # Wert des Feldes bleibt unveraendert
        return super().eventFilter(obj, event)


_guard: _WheelGuard | None = None


def _get_guard() -> _WheelGuard:
    # Lazy, damit kein QObject vor der QApplication entsteht.
    global _guard
    if _guard is None:
        _guard = _WheelGuard()
    return _guard


def install_wheel_guard(widget):
    """Rad-Ereignisse nur bei Fokus zulassen (z. B. fuer Spinboxen)."""
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_get_guard())
    return widget


def install_wheel_guard_recursive(root) -> None:
    """Wendet den Guard auf alle Spinboxen/Comboboxen unter ``root`` an."""
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

    targets = list(root.findChildren(QAbstractSpinBox)) + list(root.findChildren(QComboBox))
    for widget in targets:
        install_wheel_guard(widget)


__all__ = [
    "install_wheel_guard",
    "install_wheel_guard_recursive",
    "SmoothScrollArea",
    "SmoothScroller",
    "wheel_deltas",
    "WHEEL_PIXELS_PER_NOTCH",
]


class FeedIndicator(QWidget):
    """Animierter Papierstreifen, solange der Drucker den Auftrag ausgibt."""

    TICK_PX = 10
    STEP_PX = 2
    TAPE_PX = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        self._offset = (self._offset + self.STEP_PX) % self.TICK_PX
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        band = self.rect().adjusted(0, 0, -1, 0)
        top = band.center().y() - self.TAPE_PX // 2
        rect = QRect(band.left(), top, band.width(), self.TAPE_PX)
        painter.setPen(QPen(QColor("#999"), 1))
        painter.setBrush(QColor("#fff"))
        painter.drawRect(rect)
        painter.setClipRect(rect.adjusted(1, 1, -1, -1))
        painter.setPen(QPen(QColor("#333"), 2))
        x = rect.left() - self.TICK_PX + self._offset
        while x < rect.right():
            painter.drawLine(x, rect.top() + 2, x + 4, rect.bottom() - 2)
            x += self.TICK_PX
        painter.end()

