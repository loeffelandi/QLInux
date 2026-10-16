"""Canvas: ``QGraphicsView``/``QGraphicsScene`` mit fester Groesse sowie
mm-Linealen und sichtbarer, nicht bedruckbarer Randzone.

* **Feste Pixelgroesse**: ``sceneRect`` ist exakt ``(label.width_dots, hoehe)``
  - dieselbe Flaeche, die der Renderer 1:1 in ein ``PIL.Image`` uebergibt.
* **mm-Lineale** an Ober-/Unterkante.
* **Randbegrenzung**: der nicht bedruckbare Bandrand (``label.side_border_dots``
  pro Seite) wird schraffiert dargestellt; Items werden durch
  :mod:`ql_editor.items` auf die bedruckbare Flaeche geklemmt.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from . import items as items_mod
from .media import LabelSpec, dots_to_mm, mm_to_dots

RULER_WIDTH = 24
MIN_ZOOM = 0.05
MAX_ZOOM = 8.0
HANDLE_SIZE_PX = 9


class MmRuler(QWidget):
    """Lineal in Millimetern, synchron zum Viewport eines :class:`LabelCanvas`."""

    def __init__(self, view: "LabelCanvas", orientation: Qt.Orientation):
        super().__init__(view)
        self._view = view
        self._orientation = orientation
        self._total_mm = 0.0
        self.setFixedHeight(RULER_WIDTH) if orientation == Qt.Orientation.Horizontal else self.setFixedWidth(RULER_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_total_mm(self, total_mm: float) -> None:
        self._total_mm = total_mm
        self.update()

    def _scene_to_widget(self, scene_pt: QPointF) -> QPoint:
        """Szenenkoordinate -> Koordinate in diesem Lineal-Widget."""
        vp_pt = self._view.mapFromScene(scene_pt)
        view_pt = self._view.viewport().mapTo(self._view, vp_pt)
        return self.mapFrom(self._view, view_pt)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._total_mm <= 0 or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#fafafa"))
        painter.setPen(QPen(QColor("#bbbbbb")))
        if self._orientation == Qt.Orientation.Horizontal:
            painter.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())
        else:
            painter.drawLine(self.rect().topRight(), self.rect().bottomRight())

        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)

        # Schrittweite der Beschriftung abhaengig vom Zoom waehlen.
        step = self._label_step_mm()
        mm = 0.0
        guard = 0
        while mm <= self._total_mm + 1e-6 and guard < 5000:
            guard += 1
            scene_pt = QPointF(mm_to_dots(mm), 0) if self._orientation == Qt.Orientation.Horizontal else QPointF(0, mm_to_dots(mm))
            widget_pt = self._scene_to_widget(scene_pt)
            pos = widget_pt.x() if self._orientation == Qt.Orientation.Horizontal else widget_pt.y()
            major = abs(mm / step - round(mm / step)) < 1e-6
            if self._orientation == Qt.Orientation.Horizontal:
                painter.setPen(QPen(QColor("#999999" if major else "#cccccc")))
                painter.drawLine(pos, self.height() - (RULER_WIDTH // 2 if major else RULER_WIDTH // 3), pos, self.height())
                if major:
                    painter.setPen(QPen(QColor("#555555")))
                    painter.drawText(pos + 2, self.height() - RULER_WIDTH // 2 - 1, f"{mm / 10:.0f}" if step >= 10 else f"{mm:.0f}")
            else:
                painter.setPen(QPen(QColor("#999999" if major else "#cccccc")))
                painter.drawLine(self.width() - (RULER_WIDTH // 2 if major else RULER_WIDTH // 3), pos, self.width(), pos)
                if major:
                    painter.setPen(QPen(QColor("#555555")))
                    painter.drawText(2, pos - 2, f"{mm / 10:.0f}" if step >= 10 else f"{mm:.0f}")
            mm += 1.0
        painter.end()

    def _label_step_mm(self) -> float:
        """Beschriftungsabstand so waehlen, dass Labels nicht ueberlappen."""
        if self._total_mm <= 0:
            return 10.0
        span = (self.width() if self._orientation == Qt.Orientation.Horizontal else self.height())
        for step in (1, 2, 5, 10, 20, 50):
            px = span * (step / self._total_mm)
            if px >= 28:
                return float(step)
        return 100.0


class LabelCanvas(QGraphicsView):
    """Editor-Canvas mit fester Pixelgroesse.

    Interaktion (Mac-App-Gefuehl):

    * **Doppelklick ins Leere** -> ``text_requested`` (Textfeld anlegen/bearbeiten)
    * **Doppelklick auf Item** -> Text wird inline editiert, andere Items werden
      nur ausgewaehlt (Eigenschaften im Inspector)
    * **Ziehen am Eckgriff** -> Groesse aendern (``resizable``-Items)
    * **Pfeiltasten** -> verschieben (1 Dot, mit Shift 10), **Entf** -> loeschen
    * **Rechtsklick** -> ``context_menu_requested``
    """

    text_requested = Signal(QPointF)
    item_double_clicked = Signal(object)
    context_menu_requested = Signal(QPoint, QPointF)
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(QRectF(0, 0, 554, 472))
        self.setScene(self._scene)
        self.setSceneRect(QRectF(0, 0, 554, 472))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setBackgroundBrush(QColor("#dfe3e8"))
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._label: LabelSpec | None = None
        self._height_dots = 0
        self._needs_fit = True
        self._resize_item = None
        self._resize_start_size: tuple[float, float] = (0.0, 0.0)
        self._resize_start_scene = QPointF()
        self._pan_active = False
        self._pan_start = QPoint()
        self._pan_origin = (0, 0)

        self._h_ruler = MmRuler(self, Qt.Orientation.Horizontal)
        self._v_ruler = MmRuler(self, Qt.Orientation.Vertical)
        self.setViewportMargins(RULER_WIDTH, RULER_WIDTH, 0, 0)
        self._h_ruler.show()
        self._v_ruler.show()

    # -- Setup --------------------------------------------------------------
    def set_label(self, label: LabelSpec, height_dots: int, refit: bool | None = None) -> None:
        """Setze Band + Canvas-Hoehe. Die Breite ist immer ``label.width_dots``.

        ``refit``:
            ``None`` (Default) passt nur bei einem Bandwechsel (Breiten-
            aenderung) oder beim ersten Setzen ein. So bleibt ein vom Nutzer
            gewaehlter Zoom beim Editieren (Auto-Length waechst) erhalten und
            der Canvas wird scrollbar.
        """
        first = self._label is None
        width_changed = first or round(self.sceneRect().width()) != round(label.width_dots)
        self._label = label
        self._height_dots = int(height_dots)
        size = QRectF(0, 0, label.width_dots, height_dots)
        self._scene.setSceneRect(size)
        self.setSceneRect(size)
        self._h_ruler.set_total_mm(dots_to_mm(label.width_dots + 2 * label.side_border_dots))
        self._v_ruler.set_total_mm(dots_to_mm(height_dots))
        if refit is None:
            refit = width_changed
        if refit:
            self._needs_fit = True
            self.fit_tape()
        self._update_rulers()

    @property
    def label(self) -> LabelSpec | None:
        return self._label

    @property
    def height_dots(self) -> int:
        return self._height_dots

    def tape_rect(self) -> QRectF:
        """Volle Bandflaeche inkl. nicht bedruckbarer Raender (Szenenkoordinaten)."""
        if self._label is None:
            return self.sceneRect()
        b = self._label.side_border_dots
        return QRectF(self.sceneRect()).adjusted(-b, 0, b, 0)

    def fit_tape(self) -> None:
        """Zoom so, dass das gesamte Band in den Viewport passt."""
        if self.viewport().width() <= 2 or self.viewport().height() <= 2:
            self._needs_fit = True
            return
        self.fitInView(self.tape_rect().adjusted(-8, -8, 8, 8), Qt.AspectRatioMode.KeepAspectRatio)
        self._clamp_zoom()
        self._needs_fit = False
        self._update_rulers()
        self._emit_zoom()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(self.transform().m11() * 100.0)

    def _clamp_zoom(self) -> None:
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current))
        if abs(target - current) > 1e-9:
            self.scale(target / current, target / current)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._needs_fit:
            self.fit_tape()
        self._emit_zoom()

    # -- Zoom / Scrollen ----------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        """Adaptiv: scrollen, wenn es etwas zu scrollen gibt, sonst zoomen.

        * **Ctrl + Rad**  -> immer zoomen
        * **Shift + Rad** -> horizontal scrollen
        * **Rad**         -> vertikal scrollen; ist nichts zu scrollen (alles
          sichtbar), wird gezoomt - so tut das Rad nie „nichts".
        """
        mods = event.modifiers()
        delta = event.angleDelta()
        dy = delta.y()
        dx = delta.x()

        if mods & Qt.KeyboardModifier.ControlModifier:
            if dy:
                self.zoom_by(1.15 if dy > 0 else 1 / 1.15)
            event.accept()
            return

        vbar = self.verticalScrollBar()
        hbar = self.horizontalScrollBar()

        if mods & Qt.KeyboardModifier.ShiftModifier:
            step = dy or dx
            if hbar.maximum() > 0:
                hbar.setValue(hbar.value() - step)
                event.accept()
                return

        if vbar.maximum() > 0 or hbar.maximum() > 0:
            super().wheelEvent(event)
            return

        if dy:
            self.zoom_by(1.15 if dy > 0 else 1 / 1.15)
        event.accept()

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(target - current) < 1e-6:
            return
        self.scale(target / current, target / current)
        self._update_rulers()
        self._emit_zoom()

    def zoom_in(self) -> None:
        self.zoom_by(1.25)

    def zoom_out(self) -> None:
        self.zoom_by(1 / 1.25)

    def zoom_fit(self) -> None:
        self.fit_tape()
        self._update_rulers()

    # -- Zeichnen -----------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        if self._label is None:
            return
        tape = self.tape_rect()
        printable = self.sceneRect()
        side = self._label.side_border_dots

        # Bandflaeche (inkl. nicht bedruckbarer Raender)
        painter.fillRect(tape, QColor("#f4f4f4"))
        # Nicht bedruckbare Randzonen schraffieren
        pen = QPen(QColor("#c8b6b6"))
        pen.setWidthF(0)
        brush = QBrush(QColor("#e6d7d7"), Qt.BrushStyle.BDiagPattern)
        painter.setPen(pen)
        painter.setBrush(brush)
        if side > 0:
            painter.drawRect(QRectF(printable.left() - side, printable.top(), side, printable.height()))
            painter.drawRect(QRectF(printable.right(), printable.top(), side, printable.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Bedruckbare Flaeche weiss
        painter.fillRect(printable, QColor("#ffffff"))
        # Grenze des bedruckbaren Bereichs
        pen = QPen(QColor("#7a9ec2"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(0)
        painter.setPen(pen)
        painter.drawRect(printable)
        painter.setPen(Qt.PenStyle.NoPen)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        # Auswahlrahmen + Eckgriff fuer genau ein ausgewaehltes, skalierbares Item.
        for item in self.selected_items():
            pen = QPen(QColor("#1f6feb"))
            pen.setWidthF(0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(item.sceneBoundingRect())
        handle = self._handle_scene_rect()
        if handle is not None:
            painter.setBrush(QColor("#ffffff"))
            pen = QPen(QColor("#1f6feb"))
            pen.setWidthF(0)
            painter.setPen(pen)
            painter.drawRect(handle)

    def _handle_scene_rect(self) -> QRectF | None:
        selection = self.selected_items()
        if len(selection) != 1 or not getattr(selection[0], "resizable", False):
            return None
        item = selection[0]
        if getattr(item, "is_editing", False):
            return None
        br = item.sceneBoundingRect()
        size = HANDLE_SIZE_PX / max(1e-6, self.transform().m11())
        return QRectF(br.right() - size / 2, br.bottom() - size / 2, size, size)

    def _top_serializable_item_at(self, view_pos: QPoint):
        item = self.itemAt(view_pos)
        while item is not None and not hasattr(item, "to_dict"):
            item = item.parentItem()
        return item

    # -- Maus ---------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = event.pos()
            self._pan_origin = (
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._handle_scene_rect()
            if handle is not None and handle.contains(self.mapToScene(event.pos())):
                item = self.selected_items()[0]
                self._resize_item = item
                self._resize_start_size = (item.boundingRect().width(), item.boundingRect().height())
                self._resize_start_scene = self.mapToScene(event.pos())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_active:
            delta = event.pos() - self._pan_start
            self.horizontalScrollBar().setValue(self._pan_origin[0] - delta.x())
            self.verticalScrollBar().setValue(self._pan_origin[1] - delta.y())
            event.accept()
            return
        if self._resize_item is not None:
            current = self.mapToScene(event.pos())
            dw = current.x() - self._resize_start_scene.x()
            dh = current.y() - self._resize_start_scene.y()
            width = max(4.0, self._resize_start_size[0] + dw)
            height = max(4.0, self._resize_start_size[1] + dh)
            self._resize_item.apply_resize(width, height)
            self.viewport().update()
            event.accept()
            return
        # Cursor ueber dem Griff
        handle = self._handle_scene_rect()
        if handle is not None and handle.contains(self.mapToScene(event.pos())):
            self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_active and event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.viewport().unsetCursor()
            event.accept()
            return
        if self._resize_item is not None and event.button() == Qt.MouseButton.LeftButton:
            self._resize_item = None
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        item = self._top_serializable_item_at(event.pos())
        if item is None:
            self.text_requested.emit(self.mapToScene(event.pos()))
        elif getattr(item, "kind", None) == "text":
            item.start_editing()
        else:
            self._scene.clearSelection()
            item.setSelected(True)
            self.item_double_clicked.emit(item)
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.context_menu_requested.emit(event.globalPos(), self.mapToScene(event.pos()))
        event.accept()

    # -- Tastatur -----------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        focus = self._scene.focusItem()
        if focus is not None and getattr(focus, "is_editing", False):
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            event.accept()
            return
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        dx = dy = 0.0
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        elif key == Qt.Key.Key_Down:
            dy = step
        if dx or dy:
            for item in self.selected_items():
                item.moveBy(dx, dy)
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.cancel_editing()
            self._scene.clearSelection()
            event.accept()
            return
        super().keyPressEvent(event)

    def cancel_editing(self) -> None:
        focus = self._scene.focusItem()
        if focus is not None and getattr(focus, "is_editing", False):
            focus.finish_editing()
            focus.clearFocus()

    # -- Items --------------------------------------------------------------
    def add_item(self, item) -> None:
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)

    def selected_items(self) -> list:
        return list(self._scene.selectedItems())

    def delete_selected(self) -> None:
        for item in self.selected_items():
            self._scene.removeItem(item)

    def items_serialized(self) -> list[dict[str, Any]]:
        result = [it.to_dict() for it in self._scene.items() if hasattr(it, "to_dict")]
        result.sort(key=lambda d: d.get("z", 0.0))
        return result

    def load_items(self, data: list[dict[str, Any]]) -> None:
        for existing in list(self._scene.items()):
            if hasattr(existing, "to_dict"):
                self._scene.removeItem(existing)
        for d in data:
            self._scene.addItem(items_mod.item_from_dict(d))

    def clear_items(self) -> None:
        for existing in list(self._scene.items()):
            if hasattr(existing, "to_dict"):
                self._scene.removeItem(existing)

    # -- Geometrie ----------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        vp = self.viewport().geometry()
        self._h_ruler.setGeometry(vp.left(), 0, vp.width(), RULER_WIDTH)
        self._v_ruler.setGeometry(0, vp.top(), RULER_WIDTH, vp.height())
        self._update_rulers()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        super().scrollContentsBy(dx, dy)
        self._update_rulers()

    def _update_rulers(self) -> None:
        self._h_ruler.update()
        self._v_ruler.update()


__all__ = ["LabelCanvas", "MmRuler", "RULER_WIDTH"]
