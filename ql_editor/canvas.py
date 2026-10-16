"""Canvas: ``QGraphicsView``/``QGraphicsScene`` mit fester Groesse sowie
mm-Linealen und sichtbarer, nicht bedruckbarer Randzone.

* **Feste Pixelgroesse**: ``sceneRect`` ist exakt ``(label.width_dots, hoehe)``
  - dieselbe Flaeche, die der Renderer 1:1 in ein ``PIL.Image`` uebergibt.
* **mm-Lineale** an Ober-/Unterkante.
* **Randbegrenzung**: der nicht bedruckbare Bandrand (``label.side_border_dots``
  pro Seite) wird schraffiert dargestellt; Items werden durch
  :mod:`ql_editor.items` auf die bedruckbare Flaeche geklemmt.

Direkte Bearbeitung mit der Maus (modernes Editor-Gefuehl):

* **Verschieben**: Item mit der linken Maustaste ziehen (Mehrfachauswahl
  bewegt sich gemeinsam), mit **magnetischem Einrasten** an Bandkanten,
  Bandmitte und anderen Objekten - Einrastlinien werden angezeigt.
* **Groesse**: 8 Anfasser (Ecken + Kanten) am ausgewaehlten Objekt.
* **Drehen**: Kreisfoermiger Griff ueber dem Objekt (Shift rastet auf 15°).
* **Mehrfachauswahl**: Gummiband auf freier Flaeche; **Ctrl+Klick** schaltet
  einzelne Objekte zur Auswahl hinzu/ab.
* **Drag & Drop**: Bilddateien aus dem Dateimanager auf den Canvas ziehen.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from . import items as items_mod
from .media import LabelSpec, dots_to_mm, mm_to_dots
from .widgets import SmoothScroller, wheel_deltas

RULER_WIDTH = 24
MIN_ZOOM = 0.05
MAX_ZOOM = 8.0
HANDLE_SIZE_PX = 9
ROTATE_OFFSET_PX = 24
SNAP_TOLERANCE_PX = 6
MIN_ITEM_SIZE = 4.0

HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

_HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "rotate": Qt.CursorShape.CrossCursor,
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


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
    """Editor-Canvas mit fester Pixelgroesse und direkter Mausbearbeitung."""

    text_requested = Signal(QPointF)
    item_double_clicked = Signal(object)
    context_menu_requested = Signal(QPoint, QPointF)
    zoom_changed = Signal(float)
    items_changed = Signal()
    image_dropped = Signal(str, QPointF)
    text_dropped = Signal(str, QPointF)
    print_preview_exit_requested = Signal()

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
        self.setAcceptDrops(True)
        # Hintergrund (Band, Schraffur) cachen -> fluessigeres Scrollen.
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self._v_scroller = SmoothScroller(self, self.verticalScrollBar())
        self._h_scroller = SmoothScroller(self, self.horizontalScrollBar())
        # Zieht man die Scrollbar selbst, darf keine Animation dagegenlaufen.
        self.verticalScrollBar().sliderPressed.connect(self._v_scroller.stop)
        self.horizontalScrollBar().sliderPressed.connect(self._h_scroller.stop)

        self._label: LabelSpec | None = None
        self._height_dots = 0
        self._needs_fit = True
        self._auto_fit = True

        # Druckvorschau: 1-bit-Bild des Druckergebnisses ueber die Szene legen.
        self._print_preview = False
        self._print_image: QImage | None = None

        # Interaktionszustand
        self._op: str | None = None
        self._op_item = None
        self._op_handle = ""
        self._op_start_scene = QPointF()
        self._op_start_bbox = QRectF()
        self._op_start_size = (0.0, 0.0)
        self._op_start_rotation = 0.0
        self._op_rotate_center = QPointF()
        self._op_rotate_start = 0.0
        self._move_items: list[tuple[Any, QPointF]] = []
        self._guides: list[tuple[str, float]] = []

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
            aenderung) oder beim ersten Setzen ein.
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

    def is_interacting(self) -> bool:
        return self._op is not None or self._pan_active

    # -- Druckvorschau ------------------------------------------------------
    @property
    def print_preview(self) -> bool:
        """``True``, wenn der Canvas die 1-bit-Druckansicht zeigt."""
        return self._print_preview

    def set_print_preview(self, enabled: bool) -> None:
        """Druckvorschau-Modus ein-/ausschalten.

        Im Modus wird das fertige 1-bit-Bild ueber die Szene gelegt; die
        Bearbeitung ist deaktiviert (Zoom/Pan bleiben moeglich).
        """
        enabled = bool(enabled)
        if enabled == self._print_preview:
            self.viewport().update()
            return
        self._print_preview = enabled
        if enabled:
            self.cancel_editing()
            self._scene.clearSelection()
            self.setInteractive(False)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setInteractive(True)
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.viewport().update()

    def set_print_image(self, image: QImage | None) -> None:
        """Setze das binarisierte Bild fuer die Druckvorschau (oder ``None``)."""
        self._print_image = image
        if self._print_preview:
            self.viewport().update()

    # -- Zoom / Scrollen ----------------------------------------------------
    def fit_tape(self) -> None:
        """Zoom so, dass das gesamte Band in den Viewport passt."""
        if self.viewport().width() <= 2 or self.viewport().height() <= 2:
            self._needs_fit = True
            return
        self.fitInView(self.tape_rect().adjusted(-8, -8, 8, 8), Qt.AspectRatioMode.KeepAspectRatio)
        self._clamp_zoom()
        self._needs_fit = False
        self._auto_fit = True
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

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Adaptiv: weich scrollen, wenn es etwas zu scrollen gibt, sonst zoomen."""
        mods = event.modifiers()
        dx, dy = wheel_deltas(event)

        if mods & Qt.KeyboardModifier.ControlModifier:
            if dy:
                self.zoom_by(1.15 if dy > 0 else 1 / 1.15)
            event.accept()
            return

        vbar = self.verticalScrollBar()
        hbar = self.horizontalScrollBar()
        vmax = vbar.maximum()
        hmax = hbar.maximum()

        if mods & Qt.KeyboardModifier.ShiftModifier and hmax > 0:
            dx, dy = (dy or dx), 0.0

        if vmax > 0 or hmax > 0:
            # Rad nach oben -> Inhalt nach unten -> Wert verkleinern.
            if vmax > 0:
                self._v_scroller.scroll_by(-dy)
            if hmax > 0:
                self._h_scroller.scroll_by(-dx)
            event.accept()
            return

        if dy:
            self.zoom_by(1.15 if dy > 0 else 1 / 1.15)
        event.accept()

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(target - current) < 1e-6:
            return
        self._auto_fit = False
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
    def _scale(self) -> float:
        return max(1e-6, self.transform().m11())

    def _handle_size(self) -> float:
        return HANDLE_SIZE_PX / self._scale()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        if self._label is None:
            return
        tape = self.tape_rect()
        printable = self.sceneRect()
        side = self._label.side_border_dots

        painter.fillRect(tape, QColor("#f4f4f4"))
        pen = QPen(QColor("#c8b6b6"))
        pen.setWidthF(0)
        brush = QBrush(QColor("#e6d7d7"), Qt.BrushStyle.BDiagPattern)
        painter.setPen(pen)
        painter.setBrush(brush)
        if side > 0:
            painter.drawRect(QRectF(printable.left() - side, printable.top(), side, printable.height()))
            painter.drawRect(QRectF(printable.right(), printable.top(), side, printable.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.fillRect(printable, QColor("#ffffff"))
        pen = QPen(QColor("#7a9ec2"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(0)
        painter.setPen(pen)
        painter.drawRect(printable)
        painter.setPen(Qt.PenStyle.NoPen)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)

        # Druckvorschau: das binarisierte 1-bit-Bild deckt die Items ab.
        if self._print_preview:
            if self._print_image is not None and not self._print_image.isNull():
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                painter.drawImage(self.sceneRect(), self._print_image)
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Auswahlrahmen (rotationsfest) fuer alle ausgewaehlten Items.
        outline = QPen(QColor("#1f6feb"))
        outline.setWidthF(0)
        for item in self.selected_items():
            if not hasattr(item, "to_dict"):
                continue
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(item.mapToScene(item.boundingRect()))

        # Griffe nur bei genau einem, nicht in Bearbeitung befindlichen Item.
        item = self._editable_selection()
        if item is not None:
            size = self._handle_size()
            handle_pen = QPen(QColor("#1f6feb"))
            handle_pen.setWidthF(0)
            if getattr(item, "resizable", False):
                painter.setPen(handle_pen)
                painter.setBrush(QColor("#ffffff"))
                for pt in self._handle_points(item).values():
                    painter.drawRect(QRectF(pt.x() - size / 2, pt.y() - size / 2, size, size))
            # Drehgriff (Kreis + Verbindungslinie)
            top = self._handle_points(item)["n"]
            rot = self._rotate_handle_point(item)
            painter.setPen(handle_pen)
            painter.drawLine(top, rot)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(rot, size * 0.6, size * 0.6)

        # Einrastlinien
        if self._guides:
            guide_pen = QPen(QColor("#e0007a"))
            guide_pen.setWidthF(0)
            guide_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            tape = self.tape_rect()
            for axis, coord in self._guides:
                if axis == "v":
                    painter.drawLine(QPointF(coord, tape.top()), QPointF(coord, tape.bottom()))
                else:
                    painter.drawLine(QPointF(tape.left(), coord), QPointF(tape.right(), coord))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # -- Griff-Geometrie ----------------------------------------------------
    def _editable_selection(self):
        selection = self.selected_items()
        if len(selection) != 1:
            return None
        item = selection[0]
        if getattr(item, "is_editing", False):
            return None
        return item

    def _handle_points(self, item) -> dict[str, QPointF]:
        br = item.boundingRect()
        local = {
            "nw": br.topLeft(),
            "n": QPointF(br.center().x(), br.top()),
            "ne": br.topRight(),
            "e": QPointF(br.right(), br.center().y()),
            "se": br.bottomRight(),
            "s": QPointF(br.center().x(), br.bottom()),
            "sw": br.bottomLeft(),
            "w": QPointF(br.left(), br.center().y()),
        }
        return {name: item.mapToScene(pt) for name, pt in local.items()}

    def _rotate_handle_point(self, item) -> QPointF:
        br = item.boundingRect()
        offset = ROTATE_OFFSET_PX / self._scale()
        return item.mapToScene(QPointF(br.center().x(), br.top() - offset))

    def _handle_scene_rect(self) -> QRectF | None:
        """Kompatibilitaet: Rect des Sued-Ost-Griffs (oder ``None``)."""
        item = self._editable_selection()
        if item is None or not getattr(item, "resizable", False):
            return None
        se = self._handle_points(item)["se"]
        size = self._handle_size()
        return QRectF(se.x() - size / 2, se.y() - size / 2, size, size)

    def _handle_at(self, scene_pos: QPointF) -> tuple[str, Any] | None:
        item = self._editable_selection()
        if item is None:
            return None
        tol = self._handle_size()
        rot = self._rotate_handle_point(item)
        if abs(scene_pos.x() - rot.x()) <= tol and abs(scene_pos.y() - rot.y()) <= tol:
            return "rotate", item
        if getattr(item, "resizable", False):
            for name, pt in self._handle_points(item).items():
                if abs(scene_pos.x() - pt.x()) <= tol and abs(scene_pos.y() - pt.y()) <= tol:
                    return name, item
        return None

    def _top_serializable_item_at(self, view_pos: QPoint):
        item = self.itemAt(view_pos)
        while item is not None and not hasattr(item, "to_dict"):
            item = item.parentItem()
        return item

    # -- Einrasten ----------------------------------------------------------
    def _snap_targets(self, exclude) -> tuple[list[float], list[float]]:
        if exclude is None:
            excluded: set[int] = set()
        elif isinstance(exclude, (list, tuple, set, frozenset)):
            excluded = {id(it) for it in exclude}
        else:
            excluded = {id(exclude)}
        targets_x: list[float] = []
        targets_y: list[float] = []
        r = self.sceneRect()
        targets_x += [r.left(), r.center().x(), r.right()]
        targets_y += [r.top(), r.center().y(), r.bottom()]
        for it in self._scene.items():
            if id(it) in excluded or not hasattr(it, "to_dict"):
                continue
            br = it.sceneBoundingRect()
            targets_x += [br.left(), br.center().x(), br.right()]
            targets_y += [br.top(), br.center().y(), br.bottom()]
        return targets_x, targets_y

    def _snap_value(self, values: list[float], targets: list[float], tol: float) -> tuple[float, float | None]:
        """Kleinstes Delta, das einen der ``values`` auf ein Ziel rastet."""
        best_delta: float | None = None
        best_target: float | None = None
        for target in targets:
            for value in values:
                delta = target - value
                if abs(delta) <= tol and (best_delta is None or abs(delta) < abs(best_delta)):
                    best_delta = delta
                    best_target = target
        if best_delta is None:
            return 0.0, None
        return best_delta, best_target

    def _snap_move(self, bbox: QRectF, dx: float, dy: float, exclude) -> tuple[float, float, list]:
        tol = SNAP_TOLERANCE_PX / self._scale()
        tx, ty = self._snap_targets(exclude)
        moved = bbox.translated(dx, dy)
        guides: list[tuple[str, float]] = []
        ddx, gx = self._snap_value([moved.left(), moved.center().x(), moved.right()], tx, tol)
        ddy, gy = self._snap_value([moved.top(), moved.center().y(), moved.bottom()], ty, tol)
        if gx is not None:
            guides.append(("v", gx))
        if gy is not None:
            guides.append(("h", gy))
        return dx + ddx, dy + ddy, guides

    # -- Maus ---------------------------------------------------------------
    @staticmethod
    def _event_pos(event) -> QPoint:
        """Mausposition als ``QPoint`` (Qt6 nutzt ``position()``)."""
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    @staticmethod
    def _event_global_pos(event) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = self._event_pos(event)
            self._pan_origin = (
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if self._print_preview:
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(self._event_pos(event))
            handle = self._handle_at(scene_pos)
            if handle is not None:
                self._begin_handle_op(handle[0], handle[1], scene_pos)
                event.accept()
                return

            item = self._top_serializable_item_at(self._event_pos(event))
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if item is not None and not getattr(item, "is_editing", False):
                if ctrl:
                    item.setSelected(not item.isSelected())
                else:
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    self._begin_move(scene_pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def _begin_handle_op(self, handle: str, item, scene_pos: QPointF) -> None:
        self._op_item = item
        self._op_handle = handle
        self._op_start_scene = scene_pos
        self._op_start_bbox = item.sceneBoundingRect()
        self._op_start_size = (item.boundingRect().width(), item.boundingRect().height())
        self._op_start_rotation = item.rotation()
        if handle == "rotate":
            self._op = "rotate"
            self._op_rotate_center = item.mapToScene(item.boundingRect().center())
            self._op_rotate_start = math.atan2(
                scene_pos.y() - self._op_rotate_center.y(),
                scene_pos.x() - self._op_rotate_center.x(),
            )
        else:
            self._op = "resize"

    def _begin_move(self, scene_pos: QPointF) -> None:
        self._op = "move"
        self._op_start_scene = scene_pos
        self._move_items = [(it, QPointF(it.pos())) for it in self.selected_items()]
        self._op_start_bbox = self._selection_bbox()

    def _selection_bbox(self) -> QRectF:
        rect = QRectF()
        for item in self.selected_items():
            rect = item.sceneBoundingRect() if rect.isNull() else rect.united(item.sceneBoundingRect())
        return rect

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_active:
            delta = self._event_pos(event) - self._pan_start
            self.horizontalScrollBar().setValue(self._pan_origin[0] - delta.x())
            self.verticalScrollBar().setValue(self._pan_origin[1] - delta.y())
            event.accept()
            return

        if self._print_preview:
            event.accept()
            return

        scene_pos = self.mapToScene(self._event_pos(event))
        if self._op == "move":
            self._do_move(scene_pos)
            event.accept()
            return
        if self._op == "resize":
            self._do_resize(scene_pos)
            event.accept()
            return
        if self._op == "rotate":
            self._do_rotate(scene_pos)
            event.accept()
            return

        # Cursor je nach Griff
        handle = self._handle_at(scene_pos)
        if handle is not None:
            self.viewport().setCursor(_HANDLE_CURSORS.get(handle[0], Qt.CursorShape.ArrowCursor))
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def _do_move(self, scene_pos: QPointF) -> None:
        dx = scene_pos.x() - self._op_start_scene.x()
        dy = scene_pos.y() - self._op_start_scene.y()
        moving = [item for item, _ in self._move_items]
        dx, dy, guides = self._snap_move(self._op_start_bbox, dx, dy, exclude=moving)
        for item, start in self._move_items:
            item.setPos(start.x() + dx, start.y() + dy)
        self._guides = guides
        self.viewport().update()

    def _do_resize(self, scene_pos: QPointF) -> None:
        item = self._op_item
        name = self._op_handle
        start_w, start_h = self._op_start_size
        bbox = self._op_start_bbox

        dx = scene_pos.x() - self._op_start_scene.x()
        dy = scene_pos.y() - self._op_start_scene.y()

        angle = item.rotation()
        if angle:
            theta = math.radians(angle)
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            local_dx = dx * cos_t + dy * sin_t
            local_dy = -dx * sin_t + dy * cos_t
        else:
            local_dx, local_dy = dx, dy

        new_w = start_w + local_dx if "e" in name else (start_w - local_dx if "w" in name else start_w)
        new_h = start_h + local_dy if "s" in name else (start_h - local_dy if "n" in name else start_h)

        guides: list[tuple[str, float]] = []
        # Einrasten nur fuer unrotierte Items (verstaendliche Kanten).
        if not angle:
            tol = SNAP_TOLERANCE_PX / self._scale()
            tx, ty = self._snap_targets(item)
            if "e" in name:
                delta, target = self._snap_value([bbox.left() + new_w], tx, tol)
                if target is not None:
                    new_w += delta
                    guides.append(("v", target))
            elif "w" in name:
                delta, target = self._snap_value([bbox.right() - new_w], tx, tol)
                if target is not None:
                    new_w -= delta
                    guides.append(("v", target))
            if "s" in name:
                delta, target = self._snap_value([bbox.top() + new_h], ty, tol)
                if target is not None:
                    new_h += delta
                    guides.append(("h", target))
            elif "n" in name:
                delta, target = self._snap_value([bbox.bottom() - new_h], ty, tol)
                if target is not None:
                    new_h -= delta
                    guides.append(("h", target))

        new_w = max(MIN_ITEM_SIZE, new_w)
        new_h = max(MIN_ITEM_SIZE, new_h)

        # Gegenkante verankern - mit der tatsaechlichen Groesse nach dem
        # Resize (Text kann minimal von der angeforderten Hoehe abweichen).
        if not angle:
            item.apply_resize(new_w, new_h)
            current = item.sceneBoundingRect()
            target_left = bbox.right() - current.width() if "w" in name else bbox.left()
            target_top = bbox.bottom() - current.height() if "n" in name else bbox.top()
            item.moveBy(target_left - current.left(), target_top - current.top())
        else:
            item.apply_resize(new_w, new_h)

        self._guides = guides
        self.viewport().update()

    def _do_rotate(self, scene_pos: QPointF) -> None:
        item = self._op_item
        center = self._op_rotate_center
        angle = math.degrees(
            math.atan2(scene_pos.y() - center.y(), scene_pos.x() - center.x()) - self._op_rotate_start
        ) + self._op_start_rotation
        item.setRotation(round(angle, 1))
        self.viewport().update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_active and event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.viewport().unsetCursor()
            event.accept()
            return
        if self._op is not None and event.button() == Qt.MouseButton.LeftButton:
            finished = self._op
            self._op = None
            self._op_item = None
            self._op_handle = ""
            self._move_items = []
            self._guides = []
            self.viewport().update()
            if finished in ("move", "resize", "rotate"):
                self.items_changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        item = self._top_serializable_item_at(self._event_pos(event))
        if item is None:
            self.text_requested.emit(self.mapToScene(self._event_pos(event)))
        elif getattr(item, "kind", None) == "text":
            item.start_editing()
        else:
            self._scene.clearSelection()
            item.setSelected(True)
            self.item_double_clicked.emit(item)
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            event.accept()
            return
        self.context_menu_requested.emit(
            self._event_global_pos(event), self.mapToScene(self._event_pos(event))
        )
        event.accept()

    # -- Drag & Drop --------------------------------------------------------
    @staticmethod
    def _drop_paths(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path.lower().endswith(_IMAGE_SUFFIXES):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            event.ignore()
            return
        if self._drop_paths(event.mimeData()) or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            event.ignore()
            return
        if self._drop_paths(event.mimeData()) or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            event.ignore()
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        paths = self._drop_paths(event.mimeData())
        if paths:
            for path in paths:
                self.image_dropped.emit(path, scene_pos)
            event.acceptProposedAction()
            return
        if event.mimeData().hasText():
            self.text_dropped.emit(event.mimeData().text(), scene_pos)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # -- Tastatur -----------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._print_preview:
            if event.key() == Qt.Key.Key_Escape:
                self.print_preview_exit_requested.emit()
            event.accept()
            return
        focus = self._scene.focusItem()
        if focus is not None and getattr(focus, "is_editing", False):
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            self.items_changed.emit()
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
            self.items_changed.emit()
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
        if self._auto_fit:
            self.fit_tape()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        super().scrollContentsBy(dx, dy)
        self._update_rulers()

    def _update_rulers(self) -> None:
        self._h_ruler.update()
        self._v_ruler.update()


__all__ = ["LabelCanvas", "MmRuler", "RULER_WIDTH"]
