"""Canvas: ``QGraphicsView``/``QGraphicsScene`` mit fester Groesse sowie
mm-Linealen und sichtbarer, nicht bedruckbarer Randzone.

* **Feste Pixelgroesse**: die bedruckbare Flaeche (``printable_rect()`` bzw.
  ``scene.sceneRect()``) ist exakt ``(label.width_dots, hoehe)`` - dieselbe
  Flaeche, die der Renderer 1:1 in ein ``PIL.Image`` uebergibt.
* **Arbeitsflaeche (Pasteboard)**: der *View* zeigt zusaetzlich einen Rand um
  die Designflaeche (und alles, was ueber sie hinausragt). Dadurch sind
  Scrollbalken in beide Richtungen vorhanden und auch sehr breite Objekte
  (z. B. ein grosses Foto) mit der Maus erreichbar, ohne herauszoomen zu
  muessen. Der Renderer ist davon unberuehrt.
* **mm-Lineale** an Ober-/Unterkante.
* **Randbegrenzung**: das Etikett auf dem Canvas ist das fertige Mass
  (volle Bandhoehe und Laenge inkl. Vorschub, wie die Ergebnis-Anzeige).
  Schraffur markiert, was der Drucker nicht bedruckt: Seitenkanten und
  den Vorschub in Bandrichtung. Die graue Bandflaeche beginnt erst
  dahinter. Eigene Labelraender liegen in der bedruckbaren Flaeche und
  bleiben ein gepunkteter Rahmen. Items bleiben dort geklemmt.

Direkte Bearbeitung mit der Maus (modernes Editor-Gefuehl):

* **Verschieben**: Item mit der linken Maustaste ziehen (Mehrfachauswahl
  bewegt sich gemeinsam), mit **magnetischem Einrasten** an Bandkanten,
  Bandmitte und anderen Objekten - Einrastlinien werden angezeigt.
* **Groesse**: 8 Anfasser (Ecken + Kanten) am ausgewaehlten Objekt; der
  gegenueberliegende Griff bleibt stehen (auch bei gedrehten Objekten), der
  Cursor dreht sich mit.
* **Drehen**: Kreisfoermiger Griff ueber dem Objekt, gedreht wird um die
  Objektmitte (Shift rastet auf 15 Grad).
* **Mehrfachauswahl**: Gummiband auf freier Flaeche; **Ctrl+Klick** schaltet
  einzelne Objekte zur Auswahl hinzu/ab.
* **Drag & Drop**: Bilddateien aus dem Dateimanager auf den Canvas ziehen.
* **Tabelle**: Klick waehlt die Zelle, Doppelklick bearbeitet den Text,
  Ziehen an einer inneren Trennlinie aendert Zeile oder Spalte.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Any, Iterator

from PySide6.QtCore import QEvent, QLocale, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget
from PIL import Image

from . import items as items_mod
from .i18n import tr
from .icons import ROTATE_CURSOR_SIZE, cursor
from .renderer import render_scene_to_image
from .media import (
    CUT_OFFSET_DOTS,
    DOTS_PER_MM,
    LabelSpec,
    Orientation,
    canvas_size_for_orientation,
    dots_to_mm,
    mm_to_dots,
)
from .widgets import SmoothScroller, wheel_deltas

RULER_WIDTH = 24
#: Schriftgroesse der Lineal-Beschriftung (Bildschirmpixel).
RULER_FONT_PX = 9
#: Farben der Lineale.
RULER_BACKGROUND = "#fafafa"
#: Unterlegter Streifen: der Bereich, den das Etikett einnimmt.
RULER_LABEL_BACKGROUND = "#e4e4e4"
RULER_LINE_COLOR = "#bbbbbb"
RULER_TICK_MAJOR_COLOR = "#999999"
RULER_TICK_MINOR_COLOR = "#cccccc"
RULER_TEXT_COLOR = "#555555"
#: Abstand, den Lineal-Striche mindestens haben sollen (Bildschirmpixel).
RULER_MIN_TICK_PX = 5.0
#: Abstand, den beschriftete Striche mindestens haben sollen (Bildschirmpixel).
RULER_MIN_LABEL_PX = 26.0
#: Ziel-Abstand der mittleren Striche in Millimetern (Strich-Hierarchie 1/5/10).
RULER_MEDIUM_MM = 5.0
#: Erlaubte Strich-Schrittweiten in Millimetern (aufsteigend).
RULER_STEPS = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
#: Sicherheitsgrenze fuer die Anzahl gezeichneter Striche.
MAX_RULER_TICKS = 4000
#: Schriftgroesse der Groessen-Angabe am Etikett (Bildschirmpixel).
SIZE_LABEL_FONT_PX = 11
#: Abstand der Groessen-Angabe zum Etikett (Bildschirmpixel).
SIZE_LABEL_GAP_PX = 6
#: Farbe der Groessen-Angabe (dunkler als die Arbeitsflaeche).
SIZE_LABEL_COLOR = "#5a6472"
#: Rand um das Band beim Einpassen: Platz fuer die Groessen-Angabe.
FIT_MARGIN_MM = 2.5
#: Arbeitsflaeche um das Etikett (View-Hintergrund).
WORKSPACE_COLOR = "#dfe3e8"
#: Durchgehender Bandstreifen: andere Graustufe als die Arbeitsflaeche.
TAPE_BAND_COLOR = "#c8cfd6"
#: Mit dieser Taste zoomt das Mausrad, statt zu scrollen (auf dem Mac Cmd).
ZOOM_MODIFIER = Qt.KeyboardModifier.ControlModifier
#: Faktor pro Rad-Raste beim Zoomen.
ZOOM_STEP = 1.15
MIN_ZOOM = 0.05
MAX_ZOOM = 8.0
HANDLE_SIZE_PX = 9
ROTATE_OFFSET_PX = 24
SNAP_TOLERANCE_PX = 6
#: Tabellen-Zellklick: erst ab dieser View-Distanz (Manhattan) verschieben.
_TABLE_MOVE_THRESHOLD_PX = 4
#: Drehrasten (alle 90 Grad), wirken ohne Modifier. Sticky: man fängt die Rast
#: nur knapp ein, hält sie dann bis zum Weg-Drehen über ROTATE_DETENT_RELEASE_DEG.
ROTATE_DETENT_DEG = 90.0
ROTATE_DETENT_CAPTURE_DEG = 2.0
ROTATE_DETENT_RELEASE_DEG = 8.0
MIN_ITEM_SIZE = 4.0
# Arbeitsflaeche ("Pasteboard") um die Designflaeche herum: genug Platz, um
# Objekte zu greifen, die ueber die bedruckbare Flaeche hinausragen.
PASTEBOARD_MARGIN_MM = 8.0

HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

_OPPOSITE_HANDLE = {
    "nw": "se",
    "n": "s",
    "ne": "sw",
    "e": "w",
    "se": "nw",
    "s": "n",
    "sw": "ne",
    "w": "e",
}

# Griffrichtung in Item-Koordinaten (y zeigt nach unten).
_HANDLE_DIRECTIONS = {
    "e": (1.0, 0.0),
    "se": (1.0, 1.0),
    "s": (0.0, 1.0),
    "sw": (-1.0, 1.0),
    "w": (-1.0, 0.0),
    "nw": (-1.0, -1.0),
    "n": (0.0, -1.0),
    "ne": (1.0, -1.0),
}

# Cursor nach Bildschirmrichtung des Griffs (0 Grad = Osten, im Uhrzeigersinn).
_CURSOR_BY_DIRECTION = (
    Qt.CursorShape.SizeHorCursor,  # 0   -> Osten
    Qt.CursorShape.SizeFDiagCursor,  # 45  -> Suedost
    Qt.CursorShape.SizeVerCursor,  # 90  -> Sueden
    Qt.CursorShape.SizeBDiagCursor,  # 135 -> Suedwest
    Qt.CursorShape.SizeHorCursor,  # 180 -> Westen
    Qt.CursorShape.SizeFDiagCursor,  # 225 -> Nordwest
    Qt.CursorShape.SizeVerCursor,  # 270 -> Norden
    Qt.CursorShape.SizeBDiagCursor,  # 315 -> Nordost
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


def _local_handle_point(rect: QRectF, name: str) -> QPointF:
    """Griffpunkt in Item-Koordinaten, bezogen auf ``rect`` (Bounding-Box)."""
    center = rect.center()
    if name == "nw":
        return rect.topLeft()
    if name == "n":
        return QPointF(center.x(), rect.top())
    if name == "ne":
        return rect.topRight()
    if name == "e":
        return QPointF(rect.right(), center.y())
    if name == "se":
        return rect.bottomRight()
    if name == "s":
        return QPointF(center.x(), rect.bottom())
    if name == "sw":
        return rect.bottomLeft()
    if name == "w":
        return QPointF(rect.left(), center.y())
    raise KeyError(name)


def size_label_text(value_mm: float, decimals: int) -> str:
    """Groessen-Angabe wie im P-touch Editor, z. B. ``62 mm`` oder ``19,7 mm``.

    Die Zahl folgt der Oberflaechensprache (Dezimaltrennzeichen), die Einheit
    ist in beiden Sprachen gleich.
    """
    return tr("{value} mm").format(value=QLocale().toString(value_mm, "f", decimals))


def nice_ruler_step(px_per_mm: float, min_px: float) -> float:
    """Kleinste glatte mm-Schrittweite, die mindestens ``min_px`` Pixel belegt."""
    for step in RULER_STEPS:
        if step * px_per_mm >= min_px:
            return step
    return RULER_STEPS[-1]


def _is_multiple(value: float, step: float) -> bool:
    """Liegt ``value`` (fast) auf einem Vielfachen von ``step``?"""
    return abs(value / step - round(value / step)) < 1e-6


class RulerCorner(QWidget):
    """Ecke zwischen den beiden Linealen - traegt die Einheit."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(RULER_WIDTH, RULER_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(RULER_BACKGROUND))
        painter.setPen(QPen(QColor(RULER_LINE_COLOR)))
        painter.drawLine(self.rect().topRight(), self.rect().bottomRight())
        painter.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())
        font = QFont()
        font.setPixelSize(RULER_FONT_PX)
        painter.setFont(font)
        painter.setPen(QPen(QColor(RULER_TEXT_COLOR)))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("mm"))
        painter.end()


class MmRuler(QWidget):
    """Lineal in Millimetern, synchron zum sichtbaren Ausschnitt des Canvas.

    Beschriftet wird die **ganze** Laenge des Lineals - also das, was gerade zu
    sehen ist, nicht nur das Etikett. Die Schrittweiten richten sich nach dem
    Zoom (1 mm fein, 5 mm mittel, dann die beschrifteten Striche), damit die
    Striche in jeder Darstellung so aussehen wie im P-touch Editor. Den Bereich,
    den das Etikett einnimmt, unterlegt ein grauer Streifen - so ist auf einen
    Blick zu sehen, wie gross das Etikett ist.
    """

    def __init__(self, view: "LabelCanvas", orientation: Qt.Orientation):
        super().__init__(view)
        self._view = view
        self._orientation = orientation
        self._total_mm = 0.0
        #: Szenendots, an denen mm 0 liegt (Bandkante kann vor der Designflaeche sein).
        self._origin_dots = 0.0
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(RULER_WIDTH)
        else:
            self.setFixedWidth(RULER_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_total_mm(self, total_mm: float, origin_dots: float = 0.0) -> None:
        """Etikettenlaenge auf diesem Lineal in mm (fuer die graue Unterlegung).

        ``origin_dots`` ist die Szenenposition von 0 mm. Die volle Bandbreite
        beginnt an der physischen Kante, nicht an der bedruckbaren Flaeche.
        """
        self._total_mm = total_mm
        self._origin_dots = float(origin_dots)
        self.update()

    @property
    def total_mm(self) -> float:
        """Beschriftete Gesamtlaenge des Lineals in mm."""
        return self._total_mm

    # -- Geometrie ----------------------------------------------------------
    def _scene_to_widget(self, scene_pt: QPointF) -> QPoint:
        """Szenenkoordinate -> Koordinate in diesem Lineal-Widget."""
        vp_pt = self._view.mapFromScene(scene_pt)
        view_pt = self._view.viewport().mapTo(self._view, vp_pt)
        return self.mapFrom(self._view, view_pt)

    def _position_px(self, mm: float) -> float:
        """Bildschirmposition (Bildschirmpixel) des mm-Werts auf diesem Lineal.

        Die Millimeter werden direkt in Szenendots umgerechnet (nicht ueber
        :func:`mm_to_dots`): vor dem Etikett liegt die Arbeitsflaeche, dort sind
        die Werte negativ.
        """
        horizontal = self._orientation == Qt.Orientation.Horizontal
        dots = self._origin_dots + mm * DOTS_PER_MM
        scene_pt = QPointF(dots, 0.0) if horizontal else QPointF(0.0, dots)
        widget_pt = self._scene_to_widget(scene_pt)
        return float(widget_pt.x()) if horizontal else float(widget_pt.y())

    def _visible_mm_range(self) -> tuple[float, float]:
        """mm-Bereich, den das Lineal gerade abdeckt (Szenenkoordinaten)."""
        rect = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
        if self._orientation == Qt.Orientation.Horizontal:
            return self._mm_of(rect.left()), self._mm_of(rect.right())
        return self._mm_of(rect.top()), self._mm_of(rect.bottom())

    def _mm_of(self, dots: float) -> float:
        return (dots - self._origin_dots) / DOTS_PER_MM

    def _px_per_mm(self) -> float:
        """Wie viele Bildschirmpixel ein Millimeter gerade belegt."""
        return abs(self._view.transform().m11()) * DOTS_PER_MM

    def _steps(self) -> tuple[float, float, float]:
        """(fein, mittel, beschriftet) Strich-Schrittweiten in mm.

        Die drei Ebenen liegen aufeinander (fein teilt beschriftet), damit kein
        Strich uebersprungen wird. Ist das feine Raster groeber als 1 mm (stark
        herausgezoomt), gibt es nur zwei Ebenen - dafuer sitzen die Striche dann
        weiter auseinander als im P-touch Editor ueblich.
        """
        px_per_mm = self._px_per_mm()
        minor = nice_ruler_step(px_per_mm, RULER_MIN_TICK_PX)
        major = nice_ruler_step(px_per_mm, RULER_MIN_LABEL_PX)
        major = math.ceil(major / minor) * minor
        medium = RULER_MEDIUM_MM if minor <= 1.0 else major
        return minor, medium, major

    def label_band_rect(self) -> QRectF:
        """Bereich des Lineals, den das Etikett einnimmt (grau unterlegt)."""
        if self._total_mm <= 0:
            return QRectF()
        start = self._position_px(0.0)
        end = self._position_px(self._total_mm)
        low, high = min(start, end), max(start, end)
        if self._orientation == Qt.Orientation.Horizontal:
            band = QRectF(low, 0.0, high - low, float(self.height()))
        else:
            band = QRectF(0.0, low, float(self.width()), high - low)
        return band.intersected(QRectF(self.rect()))

    # -- Darstellung --------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        if self.width() <= 0 or self.height() <= 0:
            return
        horizontal = self._orientation == Qt.Orientation.Horizontal
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(RULER_BACKGROUND))
        band = self.label_band_rect()
        if not band.isEmpty():
            painter.fillRect(band, QColor(RULER_LABEL_BACKGROUND))

        painter.setPen(QPen(QColor(RULER_LINE_COLOR)))
        if horizontal:
            painter.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())
        else:
            painter.drawLine(self.rect().topRight(), self.rect().bottomRight())

        font = QFont()
        font.setPixelSize(RULER_FONT_PX)
        painter.setFont(font)

        minor, medium, major = self._steps()
        low_mm, high_mm = self._visible_mm_range()
        mm = math.floor(low_mm / minor) * minor
        ticks = 0
        while mm <= high_mm + 1e-6 and ticks < MAX_RULER_TICKS:
            ticks += 1
            self._draw_tick(painter, mm, medium=medium, major=major)
            mm += minor
        painter.end()

    def _draw_tick(self, painter: QPainter, mm: float, medium: float, major: float) -> None:
        """Einen Strich samt Beschriftung zeichnen (Position kommt aus der Szene)."""
        horizontal = self._orientation == Qt.Orientation.Horizontal
        pos = self._position_px(mm)
        labelled = _is_multiple(mm, major)
        if labelled:
            tick = RULER_WIDTH // 2
        elif _is_multiple(mm, medium):
            tick = RULER_WIDTH // 2 - 2
        else:
            tick = RULER_WIDTH // 3
        painter.setPen(QPen(QColor(RULER_TICK_MAJOR_COLOR if labelled else RULER_TICK_MINOR_COLOR)))
        if horizontal:
            painter.drawLine(QPointF(pos, float(self.height() - tick)), QPointF(pos, float(self.height())))
        else:
            painter.drawLine(QPointF(float(self.width() - tick), pos), QPointF(float(self.width()), pos))
        if not labelled:
            return
        # Beschriftung immer in Millimetern - die Einheit steht in der Ecke.
        painter.setPen(QPen(QColor(RULER_TEXT_COLOR)))
        label = f"{int(round(mm))}"
        if horizontal:
            painter.drawText(QPointF(pos + 2, float(self.height() - RULER_WIDTH // 2 - 1)), label)
        else:
            # Wie im P-touch Editor laengs der Achse gedreht.
            painter.save()
            painter.translate(RULER_WIDTH // 2, pos - 2)
            painter.rotate(-90)
            painter.drawText(0, 0, label)
            painter.restore()


class LabelCanvas(QGraphicsView):
    """Editor-Canvas mit fester Pixelgroesse und direkter Mausbearbeitung."""

    text_requested = Signal(QPointF)
    item_double_clicked = Signal(object)
    context_menu_requested = Signal(QPoint, QPointF)
    zoom_changed = Signal(float)
    items_changed = Signal()
    #: Vor einer Mausgeste (Ziehen, Groesse, Drehen) - fuer den Undo-Schnappschuss.
    gesture_begun = Signal()
    image_dropped = Signal(str, QPointF)
    text_dropped = Signal(str, QPointF)
    print_preview_exit_requested = Signal()
    #: Kurzer Bedienhinweis fuer die Statusleiste (leer = kein Hinweis).
    hint_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(QRectF(0, 0, 554, 472))
        self.setScene(self._scene)
        self.setSceneRect(QRectF(0, 0, 554, 472))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setBackgroundBrush(QColor(WORKSPACE_COLOR))
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        # Wie im P-touch Editor: Etikett oben links, nicht in der Mitte.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        # Hintergrund (Bandstreifen) cachen -> fluessigeres Scrollen.
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self._v_scroller = SmoothScroller(self, self.verticalScrollBar())
        self._h_scroller = SmoothScroller(self, self.horizontalScrollBar())
        # Zieht man die Scrollbar selbst, darf keine Animation dagegenlaufen.
        self.verticalScrollBar().sliderPressed.connect(self._v_scroller.stop)
        self.horizontalScrollBar().sliderPressed.connect(self._h_scroller.stop)

        self._label: LabelSpec | None = None
        self._length_dots = 0
        self._margins_mm: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._orientation = Orientation.ACROSS
        self._needs_fit = True
        self._auto_fit = True
        self._fitting = False
        self._canvas_size: tuple[int, int] = (0, 0)

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
        self._hint = ""
        self._rotate_detent: float | None = None
        self._op_div_index = 0
        self._op_start_widths: list[float] = []
        self._op_start_heights: list[float] = []
        self._move_items: list[tuple[Any, QPointF]] = []
        self._guides: list[tuple[str, float]] = []
        # Tabellen-Zellklick: Verschieben erst ab Drag-Schwelle (Auswahl ohne Move).
        self._pending_move_start: QPointF | None = None

        self._pan_active = False
        self._pan_start = QPoint()
        self._pan_origin = (0, 0)

        self._h_ruler = MmRuler(self, Qt.Orientation.Horizontal)
        self._v_ruler = MmRuler(self, Qt.Orientation.Vertical)
        self._corner = RulerCorner(self)
        self.setViewportMargins(RULER_WIDTH, RULER_WIDTH, 0, 0)
        self._h_ruler.show()
        self._v_ruler.show()
        self._corner.show()

    # -- Setup --------------------------------------------------------------
    def set_label(
        self,
        label: LabelSpec,
        length_dots: int,
        refit: bool | None = None,
        orientation: Orientation = Orientation.ACROSS,
    ) -> None:
        """Setze Band, Etikettenlaenge und Ausrichtung.

        ``length_dots`` ist die Laenge **in Bandrichtung**; welche Canvas-Achse
        sie belegt, entscheidet ``orientation`` (siehe :class:`~ql_editor.media.Orientation`).
        Die Designflaeche enthaelt immer die bedruckbare Bandbreite.

        ``refit``:
            ``None`` (Default) passt nur bei einem Bandwechsel (Breiten-
            aenderung), beim ersten Setzen oder beim Wechsel der Ausrichtung ein.
        """
        first = self._label is None
        orientation = Orientation(orientation)
        size = canvas_size_for_orientation(label, int(length_dots), orientation)
        # Nur ein anderer Bandtyp (andere Bandbreite) oder die Ausrichtung
        # rechtfertigen einen Refit - eine Laengenaenderung darf den manuell
        # gewaehlten Zoom nicht wegwerfen (bei ALONG ist die Laenge die Breite!).
        tape_changed = first or self._label.width_dots != label.width_dots
        orientation_changed = orientation is not self._orientation
        self._label = label
        self._length_dots = int(length_dots)
        self._orientation = orientation
        rect = QRectF(0, 0, size[0], size[1])
        self._scene.setSceneRect(rect)
        self._update_pasteboard()
        self._update_ruler_totals()
        self.resetCachedContent()
        if refit is None:
            refit = tape_changed or orientation_changed
        if refit:
            self._needs_fit = True
            self.fit_tape()
        self._update_rulers()

    def printable_rect(self) -> QRectF:
        """Bedruckbare Designflaeche in Szenenkoordinaten.

        Das ist die Flaeche, die der Renderer 1:1 in ein ``PIL.Image`` uebergibt
        (``scene.sceneRect()``). Der **View** zeigt darueber hinaus eine
        Arbeitsflaeche (siehe :meth:`_pasteboard_rect`), damit auch Objekte
        erreichbar bleiben, die ueber die Flaeche hinausragen.
        """
        return QRectF(self._scene.sceneRect())

    def _pasteboard_rect(self) -> QRectF:
        """Scrollbare Flaeche: Designflaeche + ueberstehende Objekte + Rand."""
        rect = self.printable_rect()
        if self._label is not None:
            rect = rect.united(self.tape_rect())
        items = self._scene.itemsBoundingRect()
        if not items.isNull():
            rect = rect.united(items)
        margin = mm_to_dots(PASTEBOARD_MARGIN_MM)
        rect = rect.adjusted(-margin, -margin, margin, margin)
        # Rechts und unten weit genug, damit das Etikett oben links stehen
        # kann und der Rest der Arbeitsflaeche frei bleibt (P-touch).
        scale = self._scale()
        vp = self.viewport().rect()
        if self._label is not None and scale > 0 and vp.width() > 2 and vp.height() > 2:
            inset = mm_to_dots(FIT_MARGIN_MM)
            tape = self.tape_rect()
            rect = rect.united(
                QRectF(
                    tape.left() - inset,
                    tape.top() - inset,
                    vp.width() / scale,
                    vp.height() / scale,
                )
            )
        return rect

    def _update_pasteboard(self) -> None:
        """Scrollbereich des Views an den Inhalt anpassen (Scrollbalken!).

        Der sichtbare Ausschnitt bleibt dabei stehen (Mitte merken) - sonst
        springt der Canvas, sobald ein Objekt den Scrollbereich vergroessert.
        """
        rect = self._pasteboard_rect()
        if rect == self.sceneRect():
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.setSceneRect(rect)
        if not self._needs_fit:
            self.centerOn(center)

    def _tape_width_mm(self) -> float:
        """Physische Bandbreite in mm (bedruckbare Breite + nicht bedruckbare Raender)."""
        label = self._label
        if label is None:
            return 0.0
        return dots_to_mm(label.width_dots + 2 * label.side_border_dots)

    def _unprintable_length(self) -> tuple[float, float]:
        """Nicht bedruckbare Dots an erster und letzter Druckzeile.

        Endlos: beide Enden ``feed_margin``. Der Schnittversatz kommt nur
        hinter die letzte Zeile, weil die Schneide hinter dem Druckkopf
        liegt. Die-cut: Differenz aus Gesamt- und Druckflaeche, haelftig.
        """
        label = self._label
        if label is None:
            return (0.0, 0.0)
        if label.is_endless:
            feed = float(label.feed_margin)
            return (feed, feed + float(CUT_OFFSET_DOTS))
        extra = max(0, int(label.dots_total[1]) - int(label.dots_printable[1]))
        first = extra // 2
        return (float(first), float(extra - first))

    def _canvas_length_margins(self) -> tuple[float, float]:
        """(niedrige, hohe) Achse in Szenenkoordinaten.

        ACROSS druckt von oben nach unten, die letzte Zeile liegt unten.
        ALONG wird zum Druck 90 Grad gegen den Uhrzeigersinn gedreht
        (:meth:`render_scene_to_image`), dadurch liegt die letzte Zeile links.
        """
        first, last = self._unprintable_length()
        if self._orientation is Orientation.ALONG:
            return (last, first)
        return (first, last)

    def _length_mm(self) -> float:
        """Fertige Etikettenlaenge in mm, inklusive nicht bedruckbarem Vorschub."""
        lead, trail = self._unprintable_length()
        return dots_to_mm(self._length_dots + lead + trail)

    def size_labels(self) -> tuple[str, str]:
        """Beschriftung der Lineale in mm: ``(waagerecht, senkrecht)``.

        Bei ``ACROSS`` liegt die Bandbreite waagerecht, bei ``ALONG`` die Laenge.
        """
        if self._label is None:
            return ("", "")
        tape = size_label_text(self._tape_width_mm(), 0)
        length = size_label_text(self._length_mm(), 1)
        if self._orientation is Orientation.ALONG:
            return (length, tape)
        return (tape, length)

    def _update_ruler_totals(self) -> None:
        """Lineale an Ausrichtung anpassen: quer zur Bandkante zeigt die Bandbreite."""
        if self._label is None:
            return
        tape_mm = self._tape_width_mm()
        length_mm = self._length_mm()
        edge = -float(self._label.side_border_dots)
        lead, _trail = self._canvas_length_margins()
        if self._orientation is Orientation.ALONG:
            self._h_ruler.set_total_mm(length_mm, -lead)
            self._v_ruler.set_total_mm(tape_mm, edge)
        else:
            self._h_ruler.set_total_mm(tape_mm, edge)
            self._v_ruler.set_total_mm(length_mm, -lead)

    @property
    def label(self) -> LabelSpec | None:
        return self._label

    @property
    def orientation(self) -> Orientation:
        return self._orientation

    @property
    def length_dots(self) -> int:
        """Etikettenlaenge in Bandrichtung (Dots)."""
        return self._length_dots

    @property
    def height_dots(self) -> int:
        """Hoehe der Designflaeche in Dots (Canvas-Achse)."""
        return int(round(self.printable_rect().height()))

    def item_scene_size(self, item) -> tuple[float, float]:
        """Aktuelle Groesse eines Items in Szenen-Einheiten (ohne Rotation).

        Genau das Mass, das ``apply_resize`` erwartet - auch bei Items, die
        ueber ihre eigene Transform-Matrix skaliert sind (Bilder).
        """
        rect = item.transform().mapRect(item.boundingRect())
        return (rect.width(), rect.height())

    def tape_rect(self) -> QRectF:
        """Physisches Etikett: volle Bandhoehe und fertige Laenge.

        Quer zur Bandrichtung inklusive der Kanten, die der Druckkopf nicht
        erreicht. In Bandrichtung inklusive Vorschub vor dem Inhalt und
        Vorschub plus Schnittversatz danach.
        """
        printable = self.printable_rect()
        if self._label is None:
            return printable
        side = float(self._label.side_border_dots)
        lead, trail = self._canvas_length_margins()
        if self._orientation is Orientation.ALONG:
            return printable.adjusted(-lead, -side, trail, side)
        return printable.adjusted(-side, -lead, side, trail)

    def tape_band_rect(self, exposed: QRectF) -> QRectF:
        """Grauer Bandstreifen: volle Medienhoehe, erst hinter dem Etikett.

        Wie im P-touch Editor liegt das Etikett vorn, die graue Fortsetzung
        des Bandes beginnt an seiner Hinterkante und laeuft bis zum Rand
        der Arbeitsflaeche.
        """
        tape = self.tape_rect()
        if self._orientation is Orientation.ALONG:
            left = tape.right()
            return QRectF(left, tape.top(), max(0.0, exposed.right() - left), tape.height())
        top = tape.bottom()
        return QRectF(tape.left(), top, tape.width(), max(0.0, exposed.bottom() - top))

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

    @contextmanager
    def suspend_text_caret(self) -> Iterator[None]:
        """Waehrend des Renderns die Textmarke ausblenden.

        ``QGraphicsTextItem`` malt beim Bearbeiten die Textmarke mit. Die Szene
        wird 1:1 gerendert - die Textmarke landete damit als duenne Linie in
        Druckvorschau und Etikett. Ausgeblendet wird **im Item selbst**
        (:meth:`~ql_editor.items.TextItem.set_caret_hidden`); die Bearbeitung
        bleibt dabei unberuehrt (Cursorposition, Auswahl, Tippen).

        Frueher wurden hier die Interaktionsflags umgeschaltet - das nimmt dem
        Feld aber den Fokus, beendet die Bearbeitung und liess ein frisch
        angelegtes, noch leeres Textfeld sofort wieder verschwinden (der
        Refresh nach dem Anlegen rendert die Vorschau).
        """
        editing = [item for item in self._scene.items() if getattr(item, "is_editing", False)]
        for item in editing:
            item.set_caret_hidden(True)
        try:
            yield
        finally:
            for item in editing:
                item.set_caret_hidden(False)

    def render_printable(self, *, rotate: bool = False, scale: int = 1) -> Image.Image:
        """Die bedruckbare Flaeche 1:1 als ``PIL.Image`` rendern.

        Zentraler Weg fuer Druckvorschau **und** Druck: die Szene wird in exakt
        ``printable_rect()``-Groesse gerendert und Bearbeitungs-Dekorationen
        (Textmarke) sind ausgeblendet. ``rotate=True`` dreht das Ergebnis in die
        Bandorientierung (Ausrichtung ``ALONG``).

        ``scale`` rendert feiner (600-dpi-Modus: ``scale=2``). Die Szene wird
        dabei in beiden Achsen mit ``scale`` gerendert - das ist genau die
        Groesse, die ``convert()`` im 600-dpi-Modus erwartet (quer weiterhin
        300 dpi, in Bandlaufrichtung 600 dpi).
        """
        rect = self.printable_rect()
        # Alles hinter dem Randrahmen wird abgeschnitten (Druck und Vorschau).
        inner = self.margin_rect()
        clip = QRectF(
            inner.x() * scale,
            inner.y() * scale,
            inner.width() * scale,
            inner.height() * scale,
        )
        for item in self._scene.items():
            refresh = getattr(item, "refresh_for_output", None)
            if refresh is not None:
                refresh()
        with self.suspend_text_caret():
            return render_scene_to_image(
                self.scene(),
                int(rect.width()) * scale,
                int(rect.height()) * scale,
                rotate=rotate,
                clip_dots=clip,
            )

    # -- Zoom / Scrollen ----------------------------------------------------
    def fit_tape(self) -> None:
        """Zoom so, dass das Band passt, und lege es oben links an.

        ``fitInView`` wuerde das Band in der Mitte lassen. Danach rueckt
        :meth:`_pin_top_left` die Ecke an den Viewport - der graue Streifen
        wandert mit.
        """
        if self._fitting:
            return
        if self.viewport().width() <= 2 or self.viewport().height() <= 2:
            self._needs_fit = True
            return
        margin = mm_to_dots(FIT_MARGIN_MM)
        target = self.tape_rect().adjusted(-margin, -margin, margin, margin)
        self._fitting = True
        try:
            self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
            self._clamp_zoom()
            self._update_pasteboard()
            self._pin_top_left(target.topLeft())
        finally:
            self._fitting = False
        self._needs_fit = False
        self._auto_fit = True
        self._update_rulers()
        self._emit_zoom()

    def _pin_top_left(self, scene_point: QPointF) -> None:
        """Lege einen Szenenpunkt in die linke obere Ecke des Viewports.

        Der Scrollbereich muss dafuer mindestens ein Viewport gross sein,
        sonst klemmt Qt die Position und das Etikett bleibt mittig.
        """
        scale = self._scale()
        if scale <= 0:
            return
        vp = self.viewport().rect()
        needed = QRectF(
            scene_point.x(),
            scene_point.y(),
            max(1.0, vp.width() / scale),
            max(1.0, vp.height() / scale),
        )
        rect = self.sceneRect().united(needed)
        if rect != self.sceneRect():
            self.setSceneRect(rect)
        self.centerOn(needed.center())

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
        """Rad scrollt; gezoomt wird nur mit :data:`ZOOM_MODIFIER` oder Zoomgeste.

        Weiches Scrollen: Rad nach oben -> Inhalt nach unten -> Wert verkleinern.
        """
        mods = event.modifiers()
        dx, dy = wheel_deltas(event)

        if mods & ZOOM_MODIFIER:
            if dy:
                self.zoom_by(ZOOM_STEP if dy > 0 else 1 / ZOOM_STEP)
            event.accept()
            return

        vbar = self.verticalScrollBar()
        hbar = self.horizontalScrollBar()
        if mods & Qt.KeyboardModifier.ShiftModifier and hbar.maximum() > 0:
            dx, dy = (dy or dx), 0.0

        if vbar.maximum() > 0:
            self._v_scroller.scroll_by(-dy)
        if hbar.maximum() > 0:
            self._h_scroller.scroll_by(-dx)
        event.accept()

    def event(self, event) -> bool:  # noqa: N802
        """Zoomgeste am Touchpad (Pinch) vergroessert/verkleinert den Canvas."""
        if event.type() == QEvent.Type.NativeGesture:
            gesture = event
            if gesture.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                factor = 1.0 + gesture.value()
                if factor > 0:
                    self.zoom_by(factor)
                return True
        return super().event(event)

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

    def zoom_100(self) -> None:
        """Zoom auf 1:1 (100 %) und das Etikett oben links anlegen.

        Nur bei 1:1 (oder Vergroesserung) zeigt der Bildschirm die echten
        Druckpunkte: ein 1-bit-Bild verliert beim *Verkleinern* feine Linien.
        """
        self.zoom_by(1.0 / self._scale())
        if self._label is not None:
            margin = mm_to_dots(FIT_MARGIN_MM)
            origin = self.tape_rect().topLeft()
            self._pin_top_left(QPointF(origin.x() - margin, origin.y() - margin))
        self._update_rulers()
        self._emit_zoom()

    # -- Zeichnen -----------------------------------------------------------
    def _scale(self) -> float:
        return max(1e-6, self.transform().m11())

    def _handle_size(self) -> float:
        return HANDLE_SIZE_PX / self._scale()

    def set_margins(self, left: float, right: float, top: float, bottom: float) -> None:
        """Eigene Labelraender in mm, innerhalb der bedruckbaren Flaeche.

        Sichtbar als gepunkteter Rahmen. Die Schraffur daneben ist etwas
        anderes: die Kanten, die der Druckkopf nicht bedrucken kann.
        """
        self._margins_mm = (float(left), float(right), float(top), float(bottom))
        # Der Hintergrund (Band, Rahmen) ist zwischengespeichert - ein normales
        # update() wuerde nur die Objekte neu zeichnen, der Rahmen bliebe stehen.
        self.resetCachedContent()
        self.viewport().update()

    def translate_items(self, dx: float, dy: float, *, clamp: bool = True) -> None:
        """Alle verschiebbaren Objekte um (dx, dy) Punkte verschieben.

        ``clamp=False`` setzt die Positionsklemme aus - noetig, wenn der
        linke/obere Rand die Objekte mitzieht und die Laenge erst danach aus
        der neuen Huelle kommt (sonst schluckt das alte ``sceneRect`` die
        Verschiebung).
        """
        for item in self._scene.items():
            if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                if not clamp:
                    item._clamp_suspended = True
                try:
                    item.moveBy(dx, dy)
                finally:
                    if not clamp:
                        item._clamp_suspended = False
        self.viewport().update()

    def margin_rect(self) -> QRectF:
        """Innenfläche innerhalb der Ränder (Szenenkoordinaten)."""
        printable = self.printable_rect()
        left, right, top, bottom = (mm_to_dots(v) for v in self._margins_mm)
        return QRectF(
            printable.left() + left,
            printable.top() + top,
            max(0.0, printable.width() - left - right),
            max(0.0, printable.height() - top - bottom),
        )

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        if self._label is None:
            return
        tape = self.tape_rect()
        printable = self.printable_rect()
        band = self.tape_band_rect(rect)
        painter.fillRect(band, QColor(TAPE_BAND_COLOR))
        painter.fillRect(tape, QColor("#ffffff"))
        self._hatch_nonprintable(painter, tape, printable)
        pen = QPen(QColor("#9aa3ad"))
        pen.setWidthF(0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(tape)
        if self._orientation is Orientation.ALONG:
            painter.drawLine(band.topLeft(), band.topRight())
            painter.drawLine(band.bottomLeft(), band.bottomRight())
        else:
            painter.drawLine(band.topLeft(), band.bottomLeft())
            painter.drawLine(band.topRight(), band.bottomRight())
        if any(self._margins_mm):
            margin_pen = QPen(QColor("#9aa5b1"))
            margin_pen.setStyle(Qt.PenStyle.DotLine)
            margin_pen.setWidthF(0)
            painter.setPen(margin_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.margin_rect())
        painter.setPen(Qt.PenStyle.NoPen)

    def _hatch_nonprintable(
        self, painter: QPainter, tape: QRectF, printable: QRectF
    ) -> None:
        """Schraffur fuer alles, was der Drucker am fertigen Etikett nicht bedruckt.

        Das sind die Seitenkanten (Druckkopf) und der Vorschub in
        Bandrichtung. Eigene Labelraender im bedruckbaren Bereich gehoeren
        nicht dazu.
        """
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#8b949e"), Qt.BrushStyle.BDiagPattern))
        side = float(self._label.side_border_dots) if self._label is not None else 0.0
        lead, trail = self._canvas_length_margins()
        if self._orientation is Orientation.ALONG:
            if side > 0:
                painter.drawRect(QRectF(tape.left(), tape.top(), tape.width(), side))
                painter.drawRect(QRectF(tape.left(), printable.bottom(), tape.width(), side))
            if lead > 0:
                painter.drawRect(QRectF(tape.left(), tape.top(), lead, tape.height()))
            if trail > 0:
                painter.drawRect(QRectF(printable.right(), tape.top(), trail, tape.height()))
        else:
            if side > 0:
                painter.drawRect(QRectF(tape.left(), tape.top(), side, tape.height()))
                painter.drawRect(QRectF(printable.right(), tape.top(), side, tape.height()))
            if lead > 0:
                painter.drawRect(QRectF(tape.left(), tape.top(), tape.width(), lead))
            if trail > 0:
                painter.drawRect(QRectF(tape.left(), printable.bottom(), tape.width(), trail))
        painter.restore()

    def _draw_size_labels(self, painter: QPainter) -> None:
        """Bandbreite und Etikettenlaenge am Etikett anschreiben.

        Wie im P-touch Editor: die Angabe sitzt am Lineal und waechst nicht mit
        dem Zoom (deshalb wird die Skalierung des Painters herausgerechnet).
        """
        if self._label is None:
            return
        horizontal_text, vertical_text = self.size_labels()
        if not horizontal_text or not vertical_text:
            return

        scale = self._scale()
        if scale <= 0:
            return
        tape = self.tape_rect()
        font = QFont()
        font.setPixelSize(SIZE_LABEL_FONT_PX)
        metrics = QFontMetricsF(font)
        # Sichtbare Positionen in Viewport-Pixeln entscheiden, ob Platz ist.
        top_left = self.mapFromScene(tape.topLeft())
        top_right = self.mapFromScene(tape.topRight())
        bottom_left = self.mapFromScene(tape.bottomLeft())
        room = metrics.height() + SIZE_LABEL_GAP_PX

        painter.save()
        painter.setFont(font)
        painter.setPen(QColor(SIZE_LABEL_COLOR))
        if top_left.y() >= room:
            advance = metrics.horizontalAdvance(horizontal_text)
            painter.save()
            painter.translate(tape.center().x(), tape.top() - SIZE_LABEL_GAP_PX / scale)
            painter.scale(1.0 / scale, 1.0 / scale)
            painter.drawText(QPointF(-advance / 2.0, 0.0), horizontal_text)
            painter.restore()
        tape_height_px = abs(bottom_left.y() - top_left.y())
        if top_left.x() >= room and tape_height_px >= metrics.horizontalAdvance(vertical_text) + 2 * SIZE_LABEL_GAP_PX:
            painter.save()
            painter.translate(tape.left() - SIZE_LABEL_GAP_PX / scale, tape.center().y())
            painter.scale(1.0 / scale, 1.0 / scale)
            painter.rotate(-90)
            painter.drawText(QPointF(-metrics.horizontalAdvance(vertical_text) / 2.0, 0.0), vertical_text)
            painter.restore()
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)

        # Druckvorschau: das binarisierte 1-bit-Bild deckt die Items ab.
        if self._print_preview:
            if self._print_image is not None and not self._print_image.isNull():
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                painter.drawImage(self.printable_rect(), self._print_image)
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

        self._draw_size_labels(painter)

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
        return {
            name: item.mapToScene(_local_handle_point(br, name)) for name in HANDLE_NAMES
        }

    def _rotate_handle_point(self, item) -> QPointF:
        """Drehgriff: oberhalb der Oberkante, **im Item-System** gedreht.

        Der Abstand ist in Bildschirmpixeln konstant - auch bei skalierten
        Items (Bilder), deren lokale Einheiten nicht den Szeneneinheiten
        entsprechen.
        """
        top = self._handle_points(item)["n"]
        # Richtung "nach oben" im Item-System als Szenenrichtung (normiert).
        origin = item.mapToScene(QPointF(0.0, 0.0))
        up = item.mapToScene(QPointF(0.0, -1.0)) - origin
        length = math.hypot(up.x(), up.y())
        if length < 1e-9:
            return QPointF(top.x(), top.y() - ROTATE_OFFSET_PX / self._scale())
        offset = ROTATE_OFFSET_PX / self._scale()
        return QPointF(
            top.x() + up.x() / length * offset, top.y() + up.y() / length * offset
        )

    def _cursor_for_handle(self, item, name: str):
        """Cursor passend zur **gedrehten** Griffrichtung (sonst irrefuehrend)."""
        vx, vy = _HANDLE_DIRECTIONS[name]
        theta = math.radians(item.rotation())
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        screen_x = vx * cos_t - vy * sin_t
        screen_y = vx * sin_t + vy * cos_t
        step = round(math.degrees(math.atan2(screen_y, screen_x)) / 45.0) % 8
        return _CURSOR_BY_DIRECTION[step]

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
        r = self.printable_rect()
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
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if getattr(item, "kind", None) == "table" and item.is_editing:
                raw = self.itemAt(self._event_pos(event))
                if raw is not None and (raw is item.editor or raw.parentItem() is item.editor):
                    super().mousePressEvent(event)
                    return
                item.finish_editing()
                handle = self._handle_at(scene_pos)
                if handle is not None:
                    self._begin_handle_op(handle[0], handle[1], scene_pos)
                    event.accept()
                    return
            if item is not None and not getattr(item, "is_editing", False):
                table_cell_click = False
                if getattr(item, "kind", None) == "table" and not ctrl:
                    local = item.mapFromScene(scene_pos)
                    divider = item.divider_at(local, 5.0 / self._scale())
                    if divider is not None:
                        if not item.isSelected():
                            self._scene.clearSelection()
                            item.setSelected(True)
                        self._begin_table_divider(item, divider, scene_pos)
                        event.accept()
                        return
                    item.select_cell_at(local, extend=shift)
                    table_cell_click = True
                if ctrl:
                    item.setSelected(not item.isSelected())
                else:
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    if table_cell_click:
                        # Zellauswahl (auch Umschalt) ohne sofortiges Verschieben;
                        # Move startet erst nach Drag-Schwelle in mouseMoveEvent.
                        self._pending_move_start = QPointF(scene_pos)
                    else:
                        self._begin_move(scene_pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def _begin_handle_op(self, handle: str, item, scene_pos: QPointF) -> None:
        self.gesture_begun.emit()
        self._op_item = item
        self._op_handle = handle
        self._op_start_scene = scene_pos
        self._op_start_bbox = item.sceneBoundingRect()
        self._op_start_size = self.item_scene_size(item)
        self._op_start_rotation = item.rotation()
        if handle == "rotate":
            self._op = "rotate"
            self._rotate_detent = None
            self._op_rotate_center = item.mapToScene(item.boundingRect().center())
            self._op_rotate_start = math.atan2(
                scene_pos.y() - self._op_rotate_center.y(),
                scene_pos.x() - self._op_rotate_center.x(),
            )
        else:
            self._op = "resize"

    def _begin_table_divider(self, item, divider: tuple[str, int], scene_pos: QPointF) -> None:
        self.gesture_begun.emit()
        self._op = "table-divider"
        self._op_item = item
        self._op_handle = divider[0]
        self._op_div_index = divider[1]
        self._op_start_scene = scene_pos
        self._op_start_widths = item.col_widths
        self._op_start_heights = item.row_heights

    def _begin_move(self, scene_pos: QPointF) -> None:
        self.gesture_begun.emit()
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
        if (
            self._pending_move_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            start = self._pending_move_start
            p0 = self.mapFromScene(start)
            p1 = self.mapFromScene(scene_pos)
            if (p1 - p0).manhattanLength() >= _TABLE_MOVE_THRESHOLD_PX:
                self._pending_move_start = None
                self._begin_move(start)
                self._do_move(scene_pos)
                event.accept()
                return
        if self._op == "move":
            self._do_move(scene_pos)
            event.accept()
            return
        if self._op == "table-divider":
            name = "e" if self._op_handle == "col" else "s"
            self.viewport().setCursor(self._cursor_for_handle(self._op_item, name))
            self._do_table_divider(scene_pos)
            event.accept()
            return
        if self._op == "resize":
            self._do_resize(scene_pos)
            event.accept()
            return
        if self._op == "rotate":
            self._do_rotate(scene_pos, snap=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
            return

        # Cursor je nach Griff (mitgedreht wie das Item)
        handle = self._handle_at(scene_pos)
        if handle is not None:
            if handle[0] == "rotate":
                # Eigenes Rotations-Symbol: Qt hat keinen passenden Cursor,
                # ein Fadenkreuz sagt hier nichts ueber "drehen".
                self.viewport().setCursor(cursor("rotate", ROTATE_CURSOR_SIZE))
            else:
                self.viewport().setCursor(self._cursor_for_handle(handle[1], handle[0]))
        else:
            hovered = self._top_serializable_item_at(self._event_pos(event))
            divider = None
            if getattr(hovered, "kind", None) == "table":
                divider = hovered.divider_at(
                    hovered.mapFromScene(scene_pos), 5.0 / self._scale()
                )
            if divider is not None:
                name = "e" if divider[0] == "col" else "s"
                self.viewport().setCursor(self._cursor_for_handle(hovered, name))
            else:
                self.viewport().unsetCursor()
        hint = ""
        if handle is not None and handle[0] == "rotate":
            hint = tr("Shift: 15°-Schritte")
        else:
            item = self._top_serializable_item_at(self._event_pos(event))
            if item is None:
                hint = tr("Strg+Rad: zoomen")
            elif not item.isSelected():
                hint = tr("Strg+Klick: zur Auswahl hinzufügen")
        self._set_hint(hint)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hint("")
        super().leaveEvent(event)

    def _set_hint(self, text: str) -> None:
        if text != self._hint:
            self._hint = text
            self.hint_changed.emit(text)

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

        # Der gegenueberliegende Griff bleibt in Szenenkoordinaten stehen -
        # das gilt auch fuer gedrehte und skalierte Items. Vorher merken,
        # nach dem Resize nachfuehren.
        anchor_name = _OPPOSITE_HANDLE[name]
        anchor_before = self._handle_points(item)[anchor_name]
        item.apply_resize(new_w, new_h)
        anchor_local = _local_handle_point(item.boundingRect(), anchor_name)
        anchor_after = item.mapToScene(anchor_local)
        item.moveBy(anchor_before.x() - anchor_after.x(), anchor_before.y() - anchor_after.y())

        self._guides = guides
        self.viewport().update()

    def _do_table_divider(self, scene_pos: QPointF) -> None:
        item = self._op_item
        dx = scene_pos.x() - self._op_start_scene.x()
        dy = scene_pos.y() - self._op_start_scene.y()
        angle = item.rotation()
        if angle:
            theta = math.radians(angle)
            local_dx = dx * math.cos(theta) + dy * math.sin(theta)
            local_dy = -dx * math.sin(theta) + dy * math.cos(theta)
        else:
            local_dx, local_dy = dx, dy
        delta = local_dx if self._op_handle == "col" else local_dy
        item.drag_divider(
            self._op_handle,
            self._op_div_index,
            delta,
            self._op_start_widths,
            self._op_start_heights,
        )
        self.viewport().update()

    def _do_rotate(self, scene_pos: QPointF, *, snap: bool = False) -> None:
        """Drehen um die **Item-Mitte** (nicht um die obere linke Ecke).

        Der Drehpunkt des Items liegt in Qt links oben; damit sich das Objekt
        natuerlich um seine Mitte dreht, wird die Position entsprechend
        nachgefuehrt. Ohne Modifier magnetet der Winkel nahe an 90-Grad-Rasten,
        mit ``snap`` (Shift) rastet er auf 15 Grad.
        """
        item = self._op_item
        center = self._op_rotate_center
        angle = math.degrees(
            math.atan2(scene_pos.y() - center.y(), scene_pos.x() - center.x()) - self._op_rotate_start
        ) + self._op_start_rotation
        if snap:
            angle = round(angle / 15.0) * 15.0
            self._rotate_detent = None
        elif self._rotate_detent is not None and abs(angle - self._rotate_detent) <= ROTATE_DETENT_RELEASE_DEG:
            angle = self._rotate_detent
        else:
            self._rotate_detent = None
            detent = round(angle / ROTATE_DETENT_DEG) * ROTATE_DETENT_DEG
            if abs(angle - detent) <= ROTATE_DETENT_CAPTURE_DEG:
                self._rotate_detent = detent
                angle = detent
        angle = round(angle, 1)

        was_inside = self._inside_printable(item)
        old_rotation, old_pos = item.rotation(), item.pos()
        local_center = item.boundingRect().center()
        before = item.mapToScene(local_center)
        item.setRotation(angle)
        after = item.mapToScene(local_center)
        item.moveBy(before.x() - after.x(), before.y() - after.y())
        if was_inside and not self._inside_printable(item):
            # Gedreht wuerde das Objekt ueber den Rand ragen und beim Druck abgeschnitten.
            item.setRotation(old_rotation)
            item.setPos(old_pos)
        self.viewport().update()

    def keep_inside_printable(self, item) -> None:
        """Objekt in die bedruckbare Flaeche schieben, falls es darueber hinausragt."""
        item.setPos(items_mod._clamp_pos(item, item.pos()))

    def _inside_printable(self, item) -> bool:
        """Liegt die (gedrehte) Huelle des Objekts komplett in der bedruckbaren Flaeche?"""
        hull = item.mapToScene(item.boundingRect()).boundingRect()
        return self._scene.sceneRect().adjusted(-0.5, -0.5, 0.5, 0.5).contains(hull)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_active and event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            self.viewport().unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pending_move_start is not None:
            self._pending_move_start = None
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
            if finished in ("move", "resize", "rotate", "table-divider"):
                # Nach der Geste: Scrollbereich an die neue Objektlage anpassen.
                self._update_pasteboard()
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
            # Oeffnet das Feld und markiert den Text (im offenen Feld ebenso).
            item.start_editing()
        elif getattr(item, "kind", None) == "table":
            # Der zweite Klick kann eine (schwebende) Verschiebung aufgemacht
            # haben. Die Bearbeitung ersetzt sie; sonst wuerde das Loslassen
            # einen leeren Schritt „Bearbeiten" aus dem Schnappschuss machen.
            self._pending_move_start = None
            self._op = None
            self._op_item = None
            self._move_items = []
            self._guides = []
            item.begin_edit_at(item.mapFromScene(self.mapToScene(self._event_pos(event))))
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
        key = event.key()
        editing_item = self._focused_editor()
        editing = editing_item is not None
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            table = editing_item if getattr(editing_item, "kind", None) == "table" else None
            if table is None:
                selected = self.selected_items()
                if len(selected) == 1 and getattr(selected[0], "kind", None) == "table":
                    table = selected[0]
            if table is not None:
                if table.is_editing:
                    table.finish_editing()
                backward = key == Qt.Key.Key_Backtab or bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                table.advance_cell(backward)
                table.begin_edit_current()
                event.accept()
                return
        if key == Qt.Key.Key_Escape:
            # Esc beendet die Inline-Bearbeitung und die Auswahl. Qt laesst ein
            # Textfeld in Bearbeitung von sich aus offen - deshalb hier zuerst.
            self.cancel_editing()
            self._scene.clearSelection()
            event.accept()
            return
        if editing:
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
            selected = self.selected_items()
            if len(selected) == 1 and getattr(selected[0], "kind", None) == "table":
                selected[0].begin_edit_current()
                event.accept()
                return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_items():
                self.gesture_begun.emit()
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
            self.gesture_begun.emit()
            for item in self.selected_items():
                item.moveBy(dx, dy)
            self.items_changed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _focused_editor(self):
        """Das Objekt, das gerade Text annimmt - auch wenn der Fokus im Kind liegt."""
        item = self._scene.focusItem()
        while item is not None:
            if getattr(item, "is_editing", False):
                return item
            item = item.parentItem()
        return None

    def cancel_editing(self) -> None:
        focus = self._scene.focusItem()
        item = self._focused_editor()
        if item is not None:
            item.finish_editing()
        if focus is not None:
            focus.clearFocus()

    # -- Items --------------------------------------------------------------
    def add_item(self, item) -> None:
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)
        self._update_pasteboard()
        # Die Objektliste hat sich geaendert - nicht erst nach einer Geste.
        self.items_changed.emit()

    def selected_items(self) -> list:
        return list(self._scene.selectedItems())

    def delete_selected(self) -> None:
        for item in self.selected_items():
            self._scene.removeItem(item)
        self._update_pasteboard()
        self.items_changed.emit()

    def remove_item(self, item) -> None:
        """Ein einzelnes Item entfernen (Auswahl der uebrigen bleibt)."""
        if item.scene() is self._scene:
            self._scene.removeItem(item)
            self._update_pasteboard()
            self.items_changed.emit()

    def ordered_items(self) -> list:
        """Serialisierbare Objekte in derselben Reihenfolge wie ``items_serialized``.

        Ein Objekt mit ``_pending_discard`` (leeres Textfeld, das gerade
        verworfen wird) zaehlt nicht mit - der Undo-Schnappschuss der
        naechsten Geste soll es nicht mehr sehen.
        """
        items = [
            it
            for it in self._scene.items()
            if hasattr(it, "to_dict") and not getattr(it, "_pending_discard", False)
        ]
        items.sort(key=lambda it: it.zValue())
        return items

    def items_serialized(self) -> list[dict[str, Any]]:
        return [it.to_dict() for it in self.ordered_items()]

    def load_items(self, data: list[dict[str, Any]]) -> list:
        """Objekte ersetzen. Liefert die neuen Items in ``data``-Reihenfolge."""
        for existing in list(self._scene.items()):
            if hasattr(existing, "to_dict"):
                self._scene.removeItem(existing)
        loaded = []
        for d in data:
            item = items_mod.item_from_dict(d)
            self._scene.addItem(item)
            loaded.append(item)
        self._update_pasteboard()
        return loaded

    def clear_items(self) -> None:
        for existing in list(self._scene.items()):
            if hasattr(existing, "to_dict"):
                self._scene.removeItem(existing)
        self._update_pasteboard()

    # -- Geometrie ----------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        vp = self.viewport().geometry()
        self._h_ruler.setGeometry(vp.left(), 0, vp.width(), RULER_WIDTH)
        self._v_ruler.setGeometry(0, vp.top(), RULER_WIDTH, vp.height())
        self._corner.setGeometry(0, 0, RULER_WIDTH, RULER_WIDTH)
        self._update_rulers()
        outer = (self.width(), self.height())
        if outer != self._canvas_size:
            self._canvas_size = outer
            if self._auto_fit:
                self.fit_tape()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        super().scrollContentsBy(dx, dy)
        self._update_rulers()

    def _update_rulers(self) -> None:
        self._h_ruler.update()
        self._v_ruler.update()
        self._corner.update()


__all__ = ["LabelCanvas", "MmRuler", "RulerCorner", "RULER_WIDTH"]
