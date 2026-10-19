"""Bogen als PDF oder über den Systemdrucker.

Die Etiketten sind schon gerenderte Bilder. Hier werden sie nur noch in das
Raster gelegt, in Originalgröße, ohne „an Seite anpassen“. Ein Versatz in
Millimetern schiebt das ganze Raster, wenn der Drucker nicht am Papierrand
anfängt.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
)
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from .i18n import tr
from .stationery import Placement, SheetError, SheetTemplate

_PREVIEW_DPI = 72


def system_printers() -> list[str]:
    """Namen der Drucker, die CUPS der Sitzung anbietet."""
    return list(QPrinterInfo.availablePrinterNames())


def render_page_image(
    template: SheetTemplate,
    images: list[Image.Image],
    placements: list[Placement],
    *,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    dpi: int = _PREVIEW_DPI,
    page: int = 0,
) -> QImage:
    """Erste Seite als Bild, mit dem Raster in Grau — nur für die Vorschau."""
    image = QImage(
        _px_i(template.page_width_mm, dpi),
        _px_i(template.page_height_mm, dpi),
        QImage.Format.Format_RGB32,
    )
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    paint_page(
        painter,
        template,
        images,
        placements,
        page=page,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
        dpi=dpi,
        outlines=True,
    )
    painter.end()
    return image


def write_pdf(
    path: str | Path,
    template: SheetTemplate,
    images: list[Image.Image],
    placements: list[Placement],
    *,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    dpi: int = 300,
) -> None:
    """PDF mit exaktem Seitenformat. Kein Rand, keine Skalierung auf die Seite."""
    writer = QPdfWriter(str(path))
    writer.setResolution(dpi)
    writer.setPageLayout(_page_layout(template))
    painter = QPainter(writer)
    if not painter.isActive():
        raise SheetError(tr("PDF konnte nicht geschrieben werden."))
    try:
        _paint_document(
            painter,
            template,
            images,
            placements,
            offset_x_mm=offset_x_mm,
            offset_y_mm=offset_y_mm,
            dpi=dpi,
            new_page=writer.newPage,
        )
    finally:
        painter.end()


def print_sheets(
    printer_name: str,
    template: SheetTemplate,
    images: list[Image.Image],
    placements: list[Placement],
    *,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> None:
    """An einen CUPS-Drucker, volle Seite, Seitengröße des Bogens."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPrinterName(printer_name)
    printer.setFullPage(True)
    printer.setPageLayout(_page_layout(template))
    dpi = printer.resolution() or 300
    painter = QPainter(printer)
    if not painter.isActive():
        raise SheetError(tr("Der Drucker hat den Auftrag nicht angenommen."))
    try:
        _paint_document(
            painter,
            template,
            images,
            placements,
            offset_x_mm=offset_x_mm,
            offset_y_mm=offset_y_mm,
            dpi=dpi,
            new_page=printer.newPage,
        )
    finally:
        painter.end()


def paint_page(
    painter: QPainter,
    template: SheetTemplate,
    images: list[Image.Image],
    placements: list[Placement],
    *,
    page: int,
    offset_x_mm: float,
    offset_y_mm: float,
    dpi: int,
    outlines: bool,
) -> None:
    """Eine Seite. Koordinaten sind Gerätepixel bei ``dpi``."""
    if outlines:
        pen = QPen(QColor(180, 180, 180))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(template.per_sheet):
            x_mm, y_mm = template.slot_origin(index)
            painter.drawPath(
                _label_path(
                    template,
                    x_mm + offset_x_mm,
                    y_mm + offset_y_mm,
                    dpi,
                )
            )
    for place in placements:
        if place.page != page:
            continue
        if place.image_index < 0 or place.image_index >= len(images):
            continue
        _draw_label(
            painter,
            template,
            images[place.image_index],
            place.x_mm + offset_x_mm,
            place.y_mm + offset_y_mm,
            dpi,
        )


def _paint_document(
    painter: QPainter,
    template: SheetTemplate,
    images: list[Image.Image],
    placements: list[Placement],
    *,
    offset_x_mm: float,
    offset_y_mm: float,
    dpi: int,
    new_page,
) -> None:
    if not placements:
        raise SheetError(tr("Keine Etiketten für den Bogen."))
    last = placements[-1].page
    for page in range(last + 1):
        if page:
            new_page()
        paint_page(
            painter,
            template,
            images,
            placements,
            page=page,
            offset_x_mm=offset_x_mm,
            offset_y_mm=offset_y_mm,
            dpi=dpi,
            outlines=False,
        )


def _draw_label(
    painter: QPainter,
    template: SheetTemplate,
    image: Image.Image,
    x_mm: float,
    y_mm: float,
    dpi: int,
) -> None:
    painter.save()
    painter.setClipPath(_label_path(template, x_mm, y_mm, dpi))
    target = QRectF(
        _px(x_mm, dpi),
        _px(y_mm, dpi),
        _px(template.label_width_mm, dpi),
        _px(template.label_height_mm, dpi),
    )
    painter.drawImage(target, _pil_to_qimage(image))
    painter.restore()


def _label_path(
    template: SheetTemplate, x_mm: float, y_mm: float, dpi: int
) -> QPainterPath:
    rect = QRectF(
        _px(x_mm, dpi),
        _px(y_mm, dpi),
        _px(template.label_width_mm, dpi),
        _px(template.label_height_mm, dpi),
    )
    path = QPainterPath()
    if template.hole_radius_mm > 0:
        path.addEllipse(rect)
        hole = _px(template.hole_radius_mm, dpi)
        center = rect.center()
        path.addEllipse(
            QRectF(center.x() - hole, center.y() - hole, hole * 2.0, hole * 2.0)
        )
        path.setFillRule(Qt.FillRule.OddEvenFill)
        return path
    if template.corner_radius_mm > 0:
        radius = _px(template.corner_radius_mm, dpi)
        path.addRoundedRect(rect, radius, radius)
        return path
    path.addRect(rect)
    return path


def _page_layout(template: SheetTemplate) -> QPageLayout:
    size = QPageSize(
        QSizeF(template.page_width_mm, template.page_height_mm),
        QPageSize.Unit.Millimeter,
    )
    return QPageLayout(
        size,
        QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0),
        QPageLayout.Unit.Millimeter,
    )


def _px(mm: float, dpi: int) -> float:
    return mm * dpi / 25.4


def _px_i(mm: float, dpi: int) -> int:
    return max(1, int(round(mm * dpi / 25.4)))


def _pil_to_qimage(image: Image.Image) -> QImage:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(
        data,
        rgb.width,
        rgb.height,
        rgb.width * 3,
        QImage.Format.Format_RGB888,
    )
    return qimage.copy()


__all__ = [
    "paint_page",
    "print_sheets",
    "render_page_image",
    "system_printers",
    "write_pdf",
]
