"""Einklappbare Seitenpanels mit Hover-Overlay ueber dem Canvas.

Aufbau (siehe :class:`PanelHost`): der Canvas ist das zentrale Widget, die
Panels liegen als Kinder darueber - ihre Geometrie wird direkt gesetzt (kein
Layout, kein ``QDockWidget``). Dadurch sind drei Zustaende moeglich:

* **angedockt** (``docked``): das Panel ist offen und der Canvas wird schmaler -
  so arbeitet man mit den Formularen.
* **eingeklappt**: es bleibt nur ein schmaler Streifen mit Pfeil am Rand; der
  Canvas bekommt die volle Breite.
* **Peek**: liegt der Mauszeiger auf dem eingeklappten Streifen, klappt das
  Panel als **Overlay ueber dem Canvas** auf - ohne den Canvas zu verschieben.

Der Pfeil sitzt *im* Panel (nicht in der Toolbar); F9 / Umschalt+F9
schalten dasselbe. Die Inhalte (Bandauswahl, Inspector, Druckoptionen) bleiben
unveraendert und scrollen bei Platzmangel.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QToolButton,
    QWidget,
)

from .i18n import tr
from .icons import icon

#: Breite des eingeklappten Streifens (Pfeil + senkrechte Beschriftung).
STRIP_WIDTH = 22
#: Standardbreite eines offenen Panels (wie in P-touch Editor).
PANEL_WIDTH = 300
#: Schmaler wird ein offenes Panel nicht; der Inhalt scrollt dann.
PANEL_MIN_WIDTH = 200
#: (Inhalt + senkrechte Scrollleiste; darunter wuerde horizontal gescrollt.)
#: Groesse des Pfeil-Knopfes im Streifen.
BUTTON_SIZE = 20
#: Dauer der Ein-/Ausklapp-Animation in Millisekunden.
ANIMATION_MS = 150
#: So breit sollte der Canvas zum Arbeiten mindestens bleiben. Wird das
#: Fenster schmaler, klappt der Host Panels von selbst ein.
CANVAS_COMFORT_PX = 520
#: Ab dieser Fensterbreite verschwindet das rechte Panel (Canvas + 2 Panels).
AUTO_COLLAPSE_RIGHT_PX = CANVAS_COMFORT_PX + 2 * PANEL_WIDTH
#: Noch schmaler: dann klappt auch das linke Panel ein (Canvas + Panel + Streifen).
AUTO_COLLAPSE_LEFT_PX = CANVAS_COMFORT_PX + PANEL_WIDTH + STRIP_WIDTH


class OverlayPanel(QWidget):
    """Seitenpanel mit Pfeil, Einklappen und Hover-Overlay.

    Der Zustand ``docked`` ist die Nutzerentscheidung (Pfeil, Menue,
    Shortcut, Settings); ``peeking`` ist der fluechtige Hover-Zustand des
    eingeklappten Panels. Zusaetzlich kann der Host ein Panel bei zu schmalem
    Fenster **automatisch** einklappen (:meth:`set_auto_collapsed`) - die
    Nutzerentscheidung bleibt dabei gespeichert.
    """

    #: Die sichtbare Breite hat sich geaendert (Animation) -> Host neu layouten.
    width_changed = Signal()
    #: ``docked`` hat sich geaendert (Pfeil, Menue/Shortcut oder Settings).
    docked_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        content: QWidget,
        side: Qt.Edge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._side = side
        self._docked = True
        self._auto_collapsed = False
        self._auto_override = False
        self._peeking = False
        #: Offen, aber ueber dem Canvas statt daneben (schmales Fenster).
        self._overlay = False
        self._width = float(PANEL_WIDTH)
        self._expanded = float(PANEL_WIDTH)

        self._content = content
        content.setParent(self)

        self._button = QToolButton(self)
        self._button.setAutoRaise(True)
        self._button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._button.clicked.connect(self.toggle_docked)

        self._anim = QPropertyAnimation(self, b"visibleWidth", self)
        self._anim.setDuration(ANIMATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_animation_finished)

        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

        self._update_button()
        self._content.setVisible(True)
        self._place_children()

    # -- Zustand ------------------------------------------------------------
    @property
    def side(self) -> Qt.Edge:
        return self._side

    @property
    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        """Streifenbeschriftung, z. B. Band oder Etikettenbogen."""
        self._title = title
        self.update()

    @property
    def content(self) -> QWidget:
        return self._content

    @property
    def docked(self) -> bool:
        """``True``: Panel ist offen und nimmt dem Canvas Platz weg.

        Bei automatisch eingeklappten Panels (kleines Fenster) ``False`` -
        die Nutzerwahl bleibt aber in :attr:`wanted_docked` erhalten.
        """
        return self._is_open()

    @property
    def wanted_docked(self) -> bool:
        """Nutzerwahl: so soll das Panel sein, wenn Platz da ist."""
        return self._docked

    @property
    def auto_collapsed(self) -> bool:
        """``True``: nur wegen eines zu kleinen Fensters eingeklappt."""
        return self._auto_collapsed

    @property
    def peeking(self) -> bool:
        """``True``: Panel liegt gerade als Hover-Overlay ueber dem Canvas."""
        return self._peeking

    def _is_open(self) -> bool:
        """Effektiv offen: Nutzerwahl *und* nicht automatisch eingeklappt."""
        return self._docked and not self._auto_collapsed

    def set_docked(self, docked: bool) -> None:
        """Panel offen (angedockt) oder eingeklappt zeigen."""
        docked = bool(docked)
        if docked == self._docked:
            return
        self._docked = docked
        if not docked:
            # Einklappen: Peek erst wieder bei neuer Beruehrung.
            self._peeking = False
        self._sync_content_visibility()
        self._animate_to(self._target_width())
        self._update_button()
        self.docked_changed.emit(docked)

    def set_auto_collapsed(self, collapsed: bool) -> None:
        """Zu kleines Fenster: Panel einklappen, ohne die Nutzerwahl zu aendern.

        Anders als :meth:`set_docked` wird hier kein ``docked_changed``
        gemeldet - die Einstellung bleibt also gespeichert und das Panel klappt
        beim Vergroessern von selbst wieder auf. Wer im kleinen Fenster bewusst
        aufklappt (Pfeil), behaelt das, bis die Schwelle wieder ueberschritten
        wird.
        """
        collapsed = bool(collapsed)
        if not collapsed:
            self._auto_override = False
        elif self._auto_override:
            return
        if collapsed == self._auto_collapsed:
            return
        self._auto_collapsed = collapsed
        if collapsed:
            self._peeking = False
        self._sync_content_visibility()
        self._animate_to(self._target_width())
        self._update_button()

    def toggle_docked(self) -> None:
        """Pfeil im Panel: zwischen offen und eingeklappt wechseln.

        In einem zu schmalen Fenster klappt der Pfeil das Panel trotzdem auf -
        die Automatik greift erst wieder, wenn das Fenster groesser wird.
        """
        if self._auto_collapsed:
            self.set_auto_collapsed(False)
            self._auto_override = True
            return
        self.set_docked(not self._docked)

    @property
    def reserved_width(self) -> int:
        """Platz, den das Panel im offenen Zustand beansprucht."""
        return int(round(self._expanded))

    @property
    def canvas_reserved(self) -> int:
        """Platz, den das Panel dem Canvas nimmt.

        Beim Peek nur der Streifen - das aufgeklappte Panel liegt dann *ueber*
        dem Canvas und verschiebt ihn nicht.
        """
        if self._is_open() and not self._overlay:
            return self.visible_width
        return STRIP_WIDTH

    @property
    def visible_width(self) -> int:
        """Aktuell sichtbare Breite (waehrend der Animation)."""
        return int(round(self._width))

    def set_overlay(self, overlay: bool) -> None:
        """Offenes Panel liegt ueber dem Canvas statt ihn zu verkleinern."""
        if overlay == self._overlay:
            return
        self._overlay = overlay
        self.width_changed.emit()

    def set_expanded_width(self, width: int) -> None:
        """Zielbreite im offenen Zustand - der Host passt sie dem Fenster an.

        Bewusst ohne Animation: beim Fenster-Resize soll das Panel sofort
        mitgehen (sonst haengt der Canvas kurz an der alten Breite).
        """
        width = int(width)
        if width == int(self._expanded):
            return
        self._expanded = float(width)
        if self._is_open() or self._peeking:
            self._anim.stop()
            self._set_visible_width(self._target_width())

    def _target_width(self) -> float:
        if self._is_open() or self._peeking:
            return self._expanded
        return float(STRIP_WIDTH)

    # -- Animation ----------------------------------------------------------
    def _get_visible_width(self) -> float:
        return self._width

    def _set_visible_width(self, value: float) -> None:
        value = float(value)
        if abs(value - self._width) < 1e-9:
            return
        self._width = value
        self.width_changed.emit()

    #: Animierte Breite (QPropertyAnimation-Ziel).
    visibleWidth = Property(float, _get_visible_width, _set_visible_width)

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        if abs(target - self._width) < 0.5:
            self._set_visible_width(target)
            self._on_animation_finished()
            return
        self._anim.setStartValue(self._width)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def finish_animation(self) -> None:
        """Animation sofort beenden (deterministisch, z. B. in Tests)."""
        self._anim.stop()
        self._set_visible_width(self._target_width())
        self._on_animation_finished()

    def _on_animation_finished(self) -> None:
        self._sync_content_visibility()

    def _sync_content_visibility(self) -> None:
        """Inhalt nur zeigen, wenn das Panel (fast) offen ist."""
        self._content.setVisible(self._is_open() or self._peeking or self._width > STRIP_WIDTH + 1)

    # -- Hover --------------------------------------------------------------
    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.set_hovered(True)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.set_hovered(False)

    def set_hovered(self, hovered: bool) -> None:
        """Mauszeiger auf dem Panel: eingeklappt als Overlay aufklappen.

        Beim Verlassen wird nur eingeklappt, wenn nicht gerade im Inhalt
        gearbeitet wird (Fokus in einem Formularfeld) - sonst verschwindet das
        Panel unter dem Cursor.
        """
        if not hovered:
            if self._peeking and not self._content_has_focus():
                self._set_peeking(False)
            return
        if not self._is_open() and not self._peeking:
            self._set_peeking(True)

    def _on_focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        if self._peeking and not self._content_has_focus():
            self._set_peeking(False)

    def _content_has_focus(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is not None and (focus is self._content or self._content.isAncestorOf(focus))

    def _set_peeking(self, peeking: bool) -> None:
        peeking = bool(peeking)
        if peeking == self._peeking:
            return
        self._peeking = peeking
        self._apply_elevation()
        self._sync_content_visibility()
        self._animate_to(self._target_width())

    def _apply_elevation(self) -> None:
        """Peek-Panel liegt ueber dem Canvas - der Schatten macht das sichtbar."""
        if not self._peeking:
            self.setGraphicsEffect(None)
            return
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(24)
        effect.setColor(QColor(0, 0, 0, 150))
        effect.setOffset(2.0 if self._side == Qt.Edge.LeftEdge else -2.0, 0.0)
        self.setGraphicsEffect(effect)

    # -- Darstellung --------------------------------------------------------
    def _strip_rect(self) -> QRectF:
        if self._side == Qt.Edge.LeftEdge:
            return QRectF(0.0, 0.0, float(STRIP_WIDTH), float(self.height()))
        return QRectF(
            float(max(0, self.width() - STRIP_WIDTH)), 0.0, float(STRIP_WIDTH), float(self.height())
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_children()

    def _place_children(self) -> None:
        height = self.height()
        strip = self._strip_rect()
        content_width = max(0, self.width() - STRIP_WIDTH)
        content_x = STRIP_WIDTH if self._side == Qt.Edge.LeftEdge else 0
        self._content.setGeometry(content_x, 0, content_width, height)
        self._button.move(
            int(strip.x() + (STRIP_WIDTH - BUTTON_SIZE) / 2),
            6,
        )
        self._button.raise_()

    def _update_button(self) -> None:
        open_ = self._is_open()
        if self._side == Qt.Edge.LeftEdge:
            name = "chevron_left" if open_ else "chevron_right"
        else:
            name = "chevron_right" if open_ else "chevron_left"
        self._button.setIcon(icon(name))
        shortcut = tr("F9") if self._side == Qt.Edge.LeftEdge else tr("Umschalt+F9")
        if open_:
            self._button.setToolTip(
                tr("{panel} einklappen ({shortcut})").format(
                    panel=self._title, shortcut=shortcut
                )
            )
        else:
            self._button.setToolTip(
                tr("{panel} ausklappen ({shortcut})").format(
                    panel=self._title, shortcut=shortcut
                )
            )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        palette = self.palette()
        window = palette.color(QPalette.ColorRole.Window)
        painter.fillRect(self.rect(), window)

        strip = self._strip_rect()
        painter.fillRect(strip, window.darker(106))
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
        if self._side == Qt.Edge.LeftEdge:
            painter.drawLine(QPointF(strip.right(), 0.0), QPointF(strip.right(), float(self.height())))
        else:
            painter.drawLine(QPointF(strip.left(), 0.0), QPointF(strip.left(), float(self.height())))

        self._draw_strip_title(painter, strip)

    def _draw_strip_title(self, painter: QPainter, strip: QRectF) -> None:
        """Senkrechte Beschriftung im Streifen (wie eine Tab-Leiste)."""
        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        colour = self.palette().color(QPalette.ColorRole.WindowText)
        colour.setAlpha(150)
        painter.setPen(colour)

        available = max(0.0, strip.height() - BUTTON_SIZE - 26)
        text = QFontMetrics(font).elidedText(self._title, Qt.TextElideMode.ElideRight, int(available))
        if not text or available < 20:
            return
        centre = QPointF(strip.center().x(), strip.y() + BUTTON_SIZE + 14 + available / 2)
        painter.save()
        painter.setClipRect(strip)
        painter.translate(centre)
        painter.rotate(-90 if self._side == Qt.Edge.LeftEdge else 90)
        painter.drawText(
            QRectF(-available / 2, -STRIP_WIDTH / 2, available, float(STRIP_WIDTH)),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )
        painter.restore()


class PanelHost(QWidget):
    """Zentrale Flaeche: Canvas mit zwei einklappbaren Seitenpanels.

    Der Host setzt die Geometrien direkt (kein Layout): der Canvas bekommt den
    Platz, den die Panels uebrig lassen, und die Panels sitzen am linken bzw.
    rechten Rand darueber.
    """

    def __init__(self, canvas: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        canvas.setParent(self)
        self._left: OverlayPanel | None = None
        self._right: OverlayPanel | None = None
        # Der Host setzt die Geometrien direkt - ohne eigene Mindestbreite
        # liesse sich das Fenster so weit schrumpfen, dass der Canvas
        # verschwindet.
        self.setMinimumWidth(canvas.minimumWidth() + 2 * STRIP_WIDTH)

    @property
    def canvas(self) -> QWidget:
        return self._canvas

    @property
    def left_panel(self) -> OverlayPanel | None:
        return self._left

    @property
    def right_panel(self) -> OverlayPanel | None:
        return self._right

    def add_panel(self, panel: OverlayPanel) -> None:
        panel.setParent(self)
        if panel.side == Qt.Edge.LeftEdge:
            self._left = panel
        else:
            self._right = panel
        panel.width_changed.connect(self._relayout)
        panel.docked_changed.connect(lambda _docked: self._relayout())
        self._update_expanded_widths()
        self._relayout()
        panel.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_auto_collapse()
        self._update_expanded_widths()
        self._relayout()

    def _apply_auto_collapse(self) -> None:
        """Schmales Fenster: erst das rechte Panel einklappen, dann das linke.

        Reihenfolge ergibt sich aus den Schwellen: :data:`AUTO_COLLAPSE_RIGHT_PX`
        liegt ueber :data:`AUTO_COLLAPSE_LEFT_PX`, also verschwindet zuerst das
        rechte Panel (Inspector) und erst bei noch weniger Platz auch das linke
        (Bandauswahl). Die Nutzerwahl bleibt gespeichert; der Streifen mit Pfeil
        bleibt sichtbar, sodass der Inhalt per Hover-Overlay erreichbar ist.
        """
        width = self.width()
        if self._left is not None:
            self._left.set_auto_collapsed(width < AUTO_COLLAPSE_LEFT_PX)
        if self._right is not None:
            self._right.set_auto_collapsed(width < AUTO_COLLAPSE_RIGHT_PX)

    def _update_expanded_widths(self) -> None:
        """Offene Panels so breit machen, wie es das Fenster zulaesst.

        Beide Panels bekommen dieselbe Breite: bei viel Platz die
        Standardbreite, bei knappem Fenster einen fairen Anteil - so bleibt die
        Oberflaeche symmetrisch und der Canvas behaelt seine Mindestbreite.
        """
        panels = [panel for panel in (self._left, self._right) if panel is not None]
        open_panels = [panel for panel in panels if panel.docked or panel.peeking]
        if not open_panels:
            return
        strips = sum(panel.canvas_reserved for panel in panels if panel not in open_panels)
        share = (max(1, self.width()) - self._canvas.minimumWidth() - strips) / len(open_panels)
        target = int(min(PANEL_WIDTH, max(PANEL_MIN_WIDTH, share)))
        # Passen die offenen Panels nicht mehr neben den Canvas, liegen sie
        # darueber (Overlay) - der Canvas wird nicht zusammengedrueckt.
        overlay = share < PANEL_MIN_WIDTH
        for panel in panels:
            panel.set_overlay(overlay)
            panel.set_expanded_width(target)

    def _relayout(self) -> None:
        width, height = self.width(), self.height()
        left = self._left.canvas_reserved if self._left is not None else 0
        right = self._right.canvas_reserved if self._right is not None else 0
        self._canvas.setGeometry(left, 0, max(0, width - left - right), height)
        if self._left is not None:
            self._left.setGeometry(0, 0, self._left.visible_width, height)
        if self._right is not None:
            panel_width = self._right.visible_width
            self._right.setGeometry(width - panel_width, 0, panel_width, height)


__all__ = [
    "OverlayPanel",
    "PanelHost",
    "PANEL_WIDTH",
    "STRIP_WIDTH",
    "AUTO_COLLAPSE_LEFT_PX",
    "AUTO_COLLAPSE_RIGHT_PX",
]
