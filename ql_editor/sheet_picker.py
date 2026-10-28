"""Klickbare Zeichnung eines Avery-Zweckform-Bogens.

Zeigt jedes Feld mit seiner Nummer. Ein Klick nennt die erste Zelle. Der
Druck bleibt in :mod:`ql_editor.sheet_output`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget

from .stationery import SheetTemplate

_MIN_NUMBER_PX = 6


class SheetStartPicker(QWidget):
    """Bogen in echter Proportion. Nummern ab 1, links oben, zeilenweise."""

    start_picked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sheet_start_picker")
        self._template: SheetTemplate | None = None
        self._start = 1
        policy = QSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(80)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        template = self._template
        if template is None or template.page_width_mm <= 0 or width <= 0:
            return 0
        return max(1, round(width * template.page_height_mm / template.page_width_mm))

    def set_template(self, template: SheetTemplate) -> None:
        self._template = template
        self._fit_height()
        self.update()

    def set_start(self, start: int) -> None:
        """Hervorhebung setzen. Sendet kein Signal."""
        number = max(1, int(start))
        if self._template is not None:
            number = min(number, self._template.per_sheet)
        if number == self._start:
            return
        self._start = number
        self.update()

    def start(self) -> int:
        return self._start

    def index_at(self, pos: QPointF) -> int | None:
        """Feldnummer unter ``pos``, 1-basiert. Das Loch eines Rings zählt mit."""
        template = self._template
        if template is None or self._scale() <= 0:
            return None
        for index in range(template.per_sheet):
            if self._outer_path(index).contains(pos):
                return index + 1
        return None

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_height()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        number = self.index_at(event.position())
        if number is None:
            super().mousePressEvent(event)
            return
        self.start_picked.emit(number)

    def paintEvent(self, _event) -> None:  # noqa: N802
        template = self._template
        if template is None or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        paper = self.palette().color(QPalette.ColorRole.Base)
        painter.fillRect(self.rect(), paper)
        for index in range(template.per_sheet):
            self._paint_slot(painter, index, paper)
        painter.end()

    def _fit_height(self) -> None:
        height = self.heightForWidth(self._draw_width())
        if height <= 0 or self.height() == height:
            return
        self.setFixedHeight(height)

    def _draw_width(self) -> int:
        """Breite, aus der die Proportion kommt.

        Wäre der Bogen bei voller Breite höher als die Scrollfläche, rechnet
        die Höhe mit der Breite, die nach der Leiste übrig bleibt. Sonst
        klappt die Leiste auf und wieder zu.
        """
        width = max(0, self.width())
        if width <= 0:
            return 0
        area = self._scroll_area()
        if area is None:
            return width
        bar = area.verticalScrollBar()
        if bar.isVisible():
            return width
        viewport = area.viewport()
        if viewport is None or self.heightForWidth(width) <= viewport.height():
            return width
        return max(1, width - bar.sizeHint().width())

    def _scroll_area(self) -> QScrollArea | None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def _scale(self) -> float:
        template = self._template
        width = self._draw_width()
        if template is None or template.page_width_mm <= 0 or width <= 0:
            return 0.0
        return width / template.page_width_mm

    def _slot_rect(self, index: int) -> QRectF:
        template = self._template
        assert template is not None
        scale = self._scale()
        x_mm, y_mm = template.slot_origin(index)
        return QRectF(
            x_mm * scale,
            y_mm * scale,
            template.label_width_mm * scale,
            template.label_height_mm * scale,
        )

    def _outer_path(self, index: int) -> QPainterPath:
        template = self._template
        assert template is not None
        rect = self._slot_rect(index)
        path = QPainterPath()
        if template.hole_radius_mm > 0:
            path.addEllipse(rect)
            return path
        if template.corner_radius_mm > 0:
            radius = template.corner_radius_mm * self._scale()
            path.addRoundedRect(rect, radius, radius)
            return path
        path.addRect(rect)
        return path

    def _paint_slot(self, painter: QPainter, index: int, paper: QColor) -> None:
        template = self._template
        assert template is not None
        number = index + 1
        palette = self.palette()
        if number < self._start:
            fill = palette.color(QPalette.ColorRole.Mid)
            ink = palette.color(QPalette.ColorRole.PlaceholderText)
        elif number == self._start:
            fill = palette.color(QPalette.ColorRole.Highlight)
            # Die Zahl steht in der Mitte. Beim CD-Ring ist das das
            # Papierloch, HighlightedText wäre dort weiß auf weiß.
            role = (
                QPalette.ColorRole.Highlight
                if template.hole_radius_mm > 0
                else QPalette.ColorRole.HighlightedText
            )
            ink = palette.color(role)
        else:
            fill = paper
            ink = palette.color(QPalette.ColorRole.Text)
        outline = palette.color(QPalette.ColorRole.Mid)
        painter.setPen(QPen(outline, 1))
        painter.setBrush(fill)
        painter.drawPath(self._outer_path(index))
        if template.hole_radius_mm > 0:
            radius = template.hole_radius_mm * self._scale()
            center = self._slot_rect(index).center()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(paper)
            painter.drawEllipse(center, radius, radius)
        rect = self._slot_rect(index)
        font = QFont(painter.font())
        pixels = min(rect.width() * 0.45, rect.height() * 0.55)
        font.setPixelSize(max(_MIN_NUMBER_PX, int(pixels)))
        painter.setFont(font)
        painter.setPen(ink)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(number))
