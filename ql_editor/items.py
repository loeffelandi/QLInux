"""Canvas-Items fuer den Editor: Text, Bild, Barcode, QR, Linie, Rahmen, Tabelle, Datum, Clip Art.

Jedes Item:

* ist ein ``QGraphicsItem`` (direkt in der Szene platzierbar/verschiebbar),
* **klemmt beim Ziehen** die Position auf den bedruckbaren Bereich
  (``scene.sceneRect()``) - Maus und Pfeiltasten bleiben innerhalb der
  Designflaeche. Die Klemme gilt nicht fuer die Randverschiebung (dort wird
  sie kurz ausgesetzt, damit der Inhalt mit dem linken/oberen Rand wandern
  kann). Was hinter dem Rand liegt, wird beim Rendern abgeschnitten,
* kann sich per :meth:`to_dict` / :meth:`from_dict` serialisieren
  (Grundlage fuer Vorlagen, M4).

Codierung (Barcode/QR) geschieht mit ``python-barcode`` bzw. ``qrcode`` und
wird in ein ``QPixmap`` umgewandelt.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
    QTextListFormat,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyle,
    QStyleOptionGraphicsItem,
)

from .datetime_text import (
    DATE_DEFAULT,
    DATE_FORMATS,
    MODE_DEFAULT,
    OFFSET_UNITS,
    TIME_DEFAULT,
    TIME_FORMATS,
    UNIT_DEFAULT,
    format_stamp,
    shift,
)
from .i18n import tr
from .symbols import known_symbol, paint_symbol

# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #


def normalize_binding(binding: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Binding normalisieren: ``database``+Feld, ``serial``, oder ``None`` (D4).

    Delegiert an die headless Merge-Engine (eine Pure-Funktion); ``MergeError``
    wird hier als ``ValueError`` weitergereicht (Item-API).
    """
    # Lazy Import: ``merge`` importiert ``document``, nicht ``items``.
    from .merge import MergeError, normalize_binding as _normalize

    try:
        return _normalize(binding)
    except MergeError as exc:
        raise ValueError(str(exc)) from exc


class _BindingMixin:
    """Optionales Datenbank-/Serien-Binding an Text, Barcode und QR (D4).

    Der Snapshot bleibt in ``text`` / ``value`` / ``data``; das Binding steuert
    spaeter den Merge. Ohne Binding-Schluessel verhalten sich Format-1-Dateien
    unveraendert.
    """

    _binding: dict[str, Any] | None = None

    @property
    def binding(self) -> dict[str, Any] | None:
        return dict(self._binding) if self._binding else None

    def set_binding(self, binding: Mapping[str, Any] | None) -> None:
        self._binding = normalize_binding(binding)

    def clear_binding(self) -> None:
        self._binding = None

    def _binding_to_dict(self, d: dict[str, Any]) -> None:
        if self._binding is not None:
            d["binding"] = dict(self._binding)

    def _apply_binding(self, d: Mapping[str, Any]) -> None:
        raw = d.get("binding")
        self._binding = normalize_binding(raw if isinstance(raw, Mapping) else None)


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Wandle ein ``PIL.Image`` in ein ``QPixmap`` (Alpha-sicher)."""
    image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    qimg = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def make_qr_image(data: str, *, box_size: int = 10, border: int = 1) -> Image.Image:
    """Erzeuge ein QR-Code-Bild (schwarz auf weiss)."""
    import qrcode

    qr = qrcode.QRCode(border=border, box_size=box_size, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _check_barcode_matches(value: str, full: str) -> None:
    """Der gedruckte Code muss der Eingabe entsprechen.

    ``python-barcode`` kuerzt zu lange Werte stillschweigend (13 Stellen in
    EAN-8 werden zu 7 + Pruefziffer) und ersetzt eine falsch eingegebene
    Pruefziffer kommentarlos. Beides druckt einen anderen Code als den, den
    der Benutzer eingegeben hat. Erlaubt bleiben nur die regulaeren
    Ergaenzungen: angehaengte Pruefziffer, fuehrende Null bei ITF (ungerade
    Stellenzahl) und Grossschreibung bei Code 39.
    """
    for candidate in (value, value.upper()):
        if full in (candidate, "0" + candidate) or full[:-1] == candidate:
            return
    raise ValueError(
        tr(
            "Eingabe '{value}' passt nicht zur Symbologie - gedruckt würde '{full}'."
        ).format(value=value, full=full)
    )


def make_barcode_image(
    value: str,
    symbology: str = "code128",
    *,
    write_text: bool = True,
    module_height: float = 10.0,
    module_width: float = 0.3,
) -> Image.Image:
    """Erzeuge ein Barcode-Bild bei 300 dpi mit ``python-barcode``."""
    import barcode
    from barcode.writer import ImageWriter

    barcode_class = barcode.get_barcode_class(symbology)
    bc = barcode_class(value, writer=ImageWriter())
    _check_barcode_matches(value, bc.get_fullcode())
    return bc.render(
        writer_options={
            "module_height": module_height,
            "module_width": module_width,
            "quiet_zone": 1.0,
            "write_text": write_text,
            "dpi": 300,
        }
    )


def _clamp_pos(item: QGraphicsItem, new_pos: QPointF) -> QPointF:
    """Klemme ``new_pos`` so, dass die Item-Huelle im ``sceneRect`` bleibt.

    Die Huelle ist die achsenparallele Box des **gedrehten und skalierten**
    Items - die Randbegrenzung gilt fuer das, was auf dem Band sichtbar ist.
    """
    scene = item.scene()
    if scene is None:
        return new_pos
    rect = scene.sceneRect()
    hull = item.mapToScene(item.boundingRect()).boundingRect()
    hull.translate(new_pos - item.pos())
    if hull.width() > rect.width() or hull.height() > rect.height():
        return new_pos  # Item groesser als Flaeche -> nicht klemmen
    dx = min(max(0.0, rect.left() - hull.left()), rect.right() - hull.right())
    dy = min(max(0.0, rect.top() - hull.top()), rect.bottom() - hull.bottom())
    return QPointF(new_pos.x() + dx, new_pos.y() + dy)


class _ClampMixin:
    """Klemmt die Position beim Ziehen/Pfeiltasten auf die aktuelle Szene.

    Der bedruckbare Rand schneidet erst beim Rendern ab - Objekte duerfen
    deshalb mit dem linken/oberen Rand wandern, bevor die Laenge neu berechnet
    wird. ``_clamp_suspended`` setzt die Klemme dafuer kurz aus (siehe
    :meth:`ql_editor.canvas.LabelCanvas.translate_items`).
    """

    kind = "item"
    _clamp_suspended = False

    def itemChange(self, change, value):  # noqa: N802 (Qt-API)
        suspend = getattr(self, "_clamp_suspended", False)
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
            and not suspend
        ):
            value = _clamp_pos(self, value)
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        """Ohne Qt-Standard-Auswahlrahmen malen.

        ``QGraphicsItem`` malt bei Auswahl (und Fokus) einen gestrichelten
        Kasten um das Objekt. Die Szene wird 1:1 gerendert und gedruckt - der
        Rahmen landete damit **im Etikett**. Die Auswahl zeigt der Canvas
        selbst (rotationsfester blauer Rahmen + Anfasser), und der ist
        View-Sache und damit nicht Teil des Druckbilds.
        """
        option = QStyleOptionGraphicsItem(option)
        option.state &= ~QStyle.StateFlag.State_Selected
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, widget)

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstrakt
        raise NotImplementedError

    def _base_dict(self) -> dict[str, Any]:
        p = self.pos()
        return {
            "type": self.kind,
            "x": p.x(),
            "y": p.y(),
            "rotation": self.rotation(),
            "z": self.zValue(),
        }

    def _apply_base(self, d: dict[str, Any]) -> None:
        self.setPos(QPointF(float(d.get("x", 0.0)), float(d.get("y", 0.0))))
        self.setRotation(float(d.get("rotation", 0.0)))
        self.setZValue(float(d.get("z", 0.0)))


# --------------------------------------------------------------------------- #
# Basis
# --------------------------------------------------------------------------- #
class LabelItem(_ClampMixin):
    """Gemeinsame Basis (nur Serialisierung/Annotation, kein Qt-Zustand)."""

    kind = "item"


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
class TextItem(_BindingMixin, _ClampMixin, QGraphicsTextItem):
    kind = "text"

    #: Bearbeitung begonnen (Doppelklick, neues Feld). Die App nimmt hier den
    #: Undo-Schnappschuss - *vor* dem ersten Zeichen, nicht erst danach.
    editing_started = Signal()
    #: Bearbeitung beendet (Fokus weg oder Esc). Die App raeumt damit leere
    #: Textfelder auf, die nur durch einen Doppelklick entstanden sind.
    editing_finished = Signal()

    def __init__(self, text: str = "", font_family: str = "Sans", font_pixel_size: int = 48):
        super().__init__(text)
        self._binding = None
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._font_family = font_family
        self._font_pixel_size = font_pixel_size
        self._bold = False
        self._italic = False
        self._underline = False
        self._strike = False
        self._letter_spacing = 0.0
        self._line_spacing = 1.0
        self._color = "black"
        self._inverted = False
        self._align = "left"
        self._valign = "top"
        self._vertical = False
        self._list = "none"
        self._wrap = False
        #: Feste Box-Breite/-Hoehe in Dots; 0 = automatisch (passt sich dem Text an).
        self._box_width = 0.0
        self._box_height = 0.0
        self._caret_hidden = False
        self.setTextWidth(-1)
        self._apply_font()
        self._apply_colors()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        """Text malen - beim Rendern ohne Textmarke und ohne Auswahl.

        ``QGraphicsTextItem`` malt im Bearbeitungsmodus die blinkende Textmarke
        mit; die Szene wird 1:1 gerendert, sie landete damit in Vorschau und
        Etikett. Waehrend des Renderns (``set_caret_hidden``) wird deshalb nur
        der Dokumentinhalt gezeichnet.

        Der naheliegende Weg ueber die Interaktionsflags ist bewusst **nicht**
        gewaehlt: ``NoTextInteraction`` nimmt dem Feld den Fokus, beendet damit
        die Bearbeitung und liess ein frisch angelegtes (noch leeres) Textfeld
        sofort wieder verschwinden.

        Invertiert: die Box wird in der Objektfarbe gefuellt, der Text ist weiss
        (siehe :meth:`_apply_colors`). Vertikal ausgerichtet wird innerhalb der
        festen Box-Hoehe.
        """
        box = self._box_rect()
        offset = self._valign_offset(box)
        opt = QStyleOptionGraphicsItem(option)
        opt.exposedRect = box.translated(0, -offset)
        painter.save()
        if self._inverted:
            painter.fillRect(box, QColor(self._color))
        painter.translate(0, offset)
        if self._caret_hidden:
            self.document().drawContents(painter, opt.exposedRect)
        else:
            super().paint(painter, opt, widget)
        painter.restore()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return super().boundingRect().united(self._box_rect())

    def shape(self) -> QPainterPath:  # noqa: N802
        """Hit-Test-Form: die feste Box, nicht nur der Textumriss."""
        path = QPainterPath()
        path.addRect(self._box_rect())
        return path

    def contains(self, point: QPointF) -> bool:  # noqa: N802
        return self._box_rect().contains(point)

    def _box_rect(self) -> QRectF:
        size = self.document().size()
        width = self._box_width if self._box_width > 0 else size.width()
        height = self._box_height if self._box_height > 0 else size.height()
        return QRectF(0, 0, width, height)

    def _valign_offset(self, box: QRectF) -> float:
        free = box.height() - self.document().size().height()
        if free <= 0 or self._valign == "top":
            return 0.0
        return free / 2 if self._valign == "middle" else free

    def set_caret_hidden(self, hidden: bool) -> None:
        """Textmarke (und Auswahl) fuers Rendern ausblenden - ohne Fokus anzutasten."""
        hidden = bool(hidden)
        if hidden == self._caret_hidden:
            return
        self._caret_hidden = hidden
        self.update()

    @property
    def caret_hidden(self) -> bool:
        return self._caret_hidden

    def _apply_font(self) -> None:
        font = QFont(self._font_family)
        font.setPixelSize(self._font_pixel_size)
        font.setBold(self._bold)
        font.setItalic(self._italic)
        font.setUnderline(self._underline)
        font.setStrikeOut(self._strike)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self._letter_spacing)
        self.setFont(font)

    def _apply_colors(self) -> None:
        self.setDefaultTextColor(QColor("white") if self._inverted else QColor(self._color))

    def _reflow(self, text: str | None = None) -> None:
        """Dokument neu aufbauen: Umbruch (vertikal), Zeilenabstand und Liste.

        ``setPlainText`` verwirft alle Absatzformate, deshalb werden sie hier
        jedes Mal neu gesetzt. Der gespeicherte Text bleibt ohne Aufzaehlungs-
        zeichen - die Liste ist ein Absatzformat, kein Text.
        """
        if text is None:
            text = self.text_value
        if self._vertical:
            text = "\n".join(text.replace("\n", ""))
        self.prepareGeometryChange()
        self.setPlainText(text)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setLineHeight(
            self._line_spacing * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
        )
        cursor.mergeBlockFormat(block)
        if self._list != "none":
            fmt = QTextListFormat()
            fmt.setStyle(
                QTextListFormat.Style.ListDisc
                if self._list == "bullet"
                else QTextListFormat.Style.ListDecimal
            )
            cursor.createList(fmt)
        self.update()

    # -- Properties ---------------------------------------------------------
    def set_font_pixel_size(self, size: int) -> None:
        self._font_pixel_size = max(4, int(size))
        self._apply_font()

    def set_bold(self, value: bool) -> None:
        self._bold = bool(value)
        self._apply_font()

    def set_italic(self, value: bool) -> None:
        self._italic = bool(value)
        self._apply_font()

    def set_underline(self, value: bool) -> None:
        self._underline = bool(value)
        self._apply_font()

    @property
    def underline(self) -> bool:
        return self._underline

    def set_strike(self, value: bool) -> None:
        self._strike = bool(value)
        self._apply_font()

    @property
    def strike(self) -> bool:
        return self._strike

    def set_font_family(self, family: str) -> None:
        self._font_family = family
        self._apply_font()

    @property
    def font_family(self) -> str:
        return self._font_family

    @property
    def font_pixel_size(self) -> int:
        return self._font_pixel_size

    @property
    def bold(self) -> bool:
        return self._bold

    @property
    def italic(self) -> bool:
        return self._italic

    def set_letter_spacing(self, px: float) -> None:
        self._letter_spacing = float(px)
        self._apply_font()

    @property
    def letter_spacing(self) -> float:
        return self._letter_spacing

    def set_line_spacing(self, factor: float) -> None:
        self._line_spacing = max(0.5, float(factor))
        self._reflow()

    @property
    def line_spacing(self) -> float:
        return self._line_spacing

    @property
    def color(self) -> str:
        return self._color

    def set_text_color(self, color: str) -> None:
        self._color = color
        self._apply_colors()

    def set_inverted(self, value: bool) -> None:
        self._inverted = bool(value)
        self._apply_colors()
        self.update()

    @property
    def inverted(self) -> bool:
        return self._inverted

    @property
    def align(self) -> str:
        return self._align

    def set_align(self, align: str) -> None:
        """Horizontale Ausrichtung: ``left``, ``center`` oder ``right``.

        Wirkt erst, wenn eine Umbruchbreite gesetzt ist - sonst ist das
        Textfeld nur so breit wie der Text und hat nichts zu zentrieren.
        """
        align = align if align in ("left", "center", "right") else "left"
        self._align = align
        flags = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }[align]
        option = QTextOption(self.document().defaultTextOption())
        option.setAlignment(flags | Qt.AlignmentFlag.AlignTop)
        self.document().setDefaultTextOption(option)

    @property
    def valign(self) -> str:
        return self._valign

    def set_valign(self, valign: str) -> None:
        """Vertikale Ausrichtung in der festen Box: ``top``, ``middle``, ``bottom``."""
        self._valign = valign if valign in ("top", "middle", "bottom") else "top"
        self.update()

    @property
    def vertical(self) -> bool:
        return self._vertical

    def set_vertical(self, value: bool) -> None:
        """Vertikale Schrift: jedes Zeichen steht in einer eigenen Zeile.

        Den logischen Text **vor** dem Flag-Wechsel lesen: ``text_value``
        haengt von ``_vertical`` ab (entfernt Newlines im Vertikalmodus).
        Sonst zerlegt ein Toggle ein→aus den gespeicherten Text.
        """
        value = bool(value)
        if value == self._vertical:
            return
        text = self.text_value
        self._vertical = value
        self._reflow(text)

    @property
    def list_style(self) -> str:
        return self._list

    def set_list(self, style: str) -> None:
        """Aufzaehlung: ``none``, ``bullet`` (Punkte) oder ``number`` (Nummern)."""
        self._list = style if style in ("none", "bullet", "number") else "none"
        self._reflow()

    @property
    def wrap(self) -> bool:
        return self._wrap

    def set_wrap(self, value: bool) -> None:
        self._wrap = bool(value)
        self._apply_wrap()

    @property
    def auto_width(self) -> bool:
        return self._box_width <= 0

    def set_auto_width(self, auto: bool) -> None:
        """Box-Breite automatisch (wie der Text) oder mit der aktuellen Breite fixiert."""
        new_width = 0.0 if auto else self._box_rect().width()
        self.prepareGeometryChange()
        self._box_width = new_width
        self.setTextWidth(self._box_width if self._wrap and self._box_width > 0 else -1)
        self.update()

    @property
    def auto_height(self) -> bool:
        return self._box_height <= 0

    def set_auto_height(self, auto: bool) -> None:
        self.set_box_height(0.0 if auto else self._box_rect().height())

    def set_box_height(self, height: float) -> None:
        self.prepareGeometryChange()
        self._box_height = max(0.0, float(height))
        self.update()

    def set_text_width(self, width: float) -> None:
        self.prepareGeometryChange()
        self._box_width = float(width) if width > 0 else 0.0
        self.setTextWidth(self._box_width if self._wrap and self._box_width > 0 else -1)
        self.update()

    def _apply_wrap(self) -> None:
        self.prepareGeometryChange()
        self.setTextWidth(self._box_width if self._wrap and self._box_width > 0 else -1)
        self.update()

    # -- Inline-Bearbeitung -------------------------------------------------
    def start_editing(self) -> None:
        """Doppelklick: Bearbeitung starten und den Text **vorauswaehlen**.

        Die Vorauswahl ist gewollt - ein Doppelklick oeffnet das Feld zum
        Ersetzen (wie "Umbenennen"), ein Doppelklick im bereits offenen Feld
        markiert ebenfalls alles, ein *einfacher* Klick setzt den Cursor genau.
        Ein **neu** angelegtes Feld ist leer: dort gibt es nichts zu markieren,
        deshalb stoert die Vorauswahl beim Erstellen nicht mehr.
        """
        was_editing = self.is_editing
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.setTextCursor(cursor)
        if not was_editing:
            self.editing_started.emit()

    def finish_editing(self) -> None:
        was_editing = self.is_editing
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        if was_editing:
            # Eine stehengebliebene Textmarkierung wird sonst weitergemalt -
            # im 1-bit-Bild als Block, also im Etikett. Beim Schliessen des
            # Feldes ist die Auswahl zu Ende.
            cursor = self.textCursor()
            cursor.clearSelection()
            self.setTextCursor(cursor)
            if self._vertical:
                # Beim Tippen im Vertikal-Modus landen Zeichen in einer Zeile -
                # hier wieder Zeichen fuer Zeichen umbrechen.
                self._reflow()
            self.editing_finished.emit()

    @property
    def is_editing(self) -> bool:
        return self.textInteractionFlags() != Qt.TextInteractionFlag.NoTextInteraction

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.finish_editing()

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        rect = self._box_rect()
        # Nur waagerechtes Ziehen setzt die Umbruchbreite. Sonst wuerde ein
        # Hoehen-Drag (Schrift skalieren) den Text zusaetzlich umbrechen und
        # die Hoehe unkontrolliert wachsen.
        if self._box_width > 0 or abs(width - rect.width()) > 0.5:
            self.set_text_width(width)
            self.set_wrap(True)
        if self._box_height > 0:
            self.set_box_height(height)
        elif rect.height() > 0 and height > 0:
            factor = height / rect.height()
            self.set_font_pixel_size(max(4, round(self._font_pixel_size * factor)))

    @property
    def text_value(self) -> str:
        text = self.toPlainText()
        return text.replace("\n", "") if self._vertical else text

    def set_text_value(self, value: str) -> None:
        self._reflow(value)

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        d.update(
            text=self.text_value,
            font_family=self._font_family,
            font_pixel_size=self._font_pixel_size,
            bold=self._bold,
            italic=self._italic,
            underline=self._underline,
            strike=self._strike,
            letter_spacing=self._letter_spacing,
            line_spacing=self._line_spacing,
            color=self._color,
            inverted=self._inverted,
            align=self._align,
            valign=self._valign,
            vertical=self._vertical,
            list=self._list,
            text_width=self._box_width,
            wrap=self._wrap,
            box_height=self._box_height,
        )
        self._binding_to_dict(d)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TextItem":
        item = cls(d.get("text", "Text"), d.get("font_family", "Sans"), int(d.get("font_pixel_size", 48)))
        item.set_bold(bool(d.get("bold", False)))
        item.set_italic(bool(d.get("italic", False)))
        item.set_underline(bool(d.get("underline", False)))
        item.set_strike(bool(d.get("strike", False)))
        item.set_letter_spacing(float(d.get("letter_spacing", 0.0)))
        item.set_line_spacing(float(d.get("line_spacing", 1.0)))
        item.set_text_color(d.get("color", "black"))
        item.set_inverted(bool(d.get("inverted", False)))
        item.set_align(d.get("align", "left"))
        item.set_valign(d.get("valign", "top"))
        width = float(d.get("text_width", -1))
        item.set_text_width(width)
        # Alte Dateien kennen keinen Umbruch-Schalter: eine Breite hiess dort Umbruch.
        item.set_wrap(bool(d.get("wrap", width > 0)))
        item.set_box_height(float(d.get("box_height", 0.0)))
        item.set_list(d.get("list", "none"))
        item.set_vertical(bool(d.get("vertical", False)))
        item._apply_base(d)
        item._apply_binding(d)
        return item


# --------------------------------------------------------------------------- #
# Datum / Uhrzeit
# --------------------------------------------------------------------------- #
class DateTimeItem(_ClampMixin, QGraphicsTextItem):
    """Stempel mit aktuellem oder festem Datum, Format und Versatz.

    Der sichtbare Text wird berechnet und nicht mitgetippt. Gespeichert werden
    Format, Quelle und Versatz - die Uhrzeit selbst nur, wenn sie fest ist.
    Ein Tick der Uhr erzeugt deshalb keinen Undo-Schritt. ``display_changed``
    feuert nur, wenn sich der Text wirklich ändert, damit die Bandlänge
    nachziehen kann.
    """

    kind = "datetime"
    resizable = True
    display_changed = Signal()

    def __init__(self, font_family: str = "Sans", font_pixel_size: int = 48):
        super().__init__("")
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._font_family = font_family
        self._font_pixel_size = font_pixel_size
        self._bold = False
        self._italic = False
        self._color = "black"
        self._align = "left"
        self._mode = MODE_DEFAULT
        self._date_format = DATE_DEFAULT
        self._time_format = TIME_DEFAULT
        self._live = True
        self._fixed = datetime.now().replace(microsecond=0)
        self._offset = 0
        self._offset_unit = UNIT_DEFAULT
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._apply_font()
        self.refresh()

    def itemChange(self, change, value):  # noqa: N802
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            self._sync_timer()
        return result

    def _sync_timer(self) -> None:
        """Nur ticken, solange der Stempel auf der Fläche liegt und live ist."""
        if self.scene() is not None and self._live:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _apply_font(self) -> None:
        font = QFont(self._font_family)
        font.setPixelSize(self._font_pixel_size)
        font.setBold(self._bold)
        font.setItalic(self._italic)
        self.setFont(font)

    def set_font_pixel_size(self, size: int) -> None:
        self._font_pixel_size = max(4, int(size))
        self._apply_font()

    def set_bold(self, value: bool) -> None:
        self._bold = bool(value)
        self._apply_font()

    def set_italic(self, value: bool) -> None:
        self._italic = bool(value)
        self._apply_font()

    def set_font_family(self, family: str) -> None:
        self._font_family = family
        self._apply_font()

    @property
    def font_family(self) -> str:
        return self._font_family

    @property
    def font_pixel_size(self) -> int:
        return self._font_pixel_size

    @property
    def bold(self) -> bool:
        return self._bold

    @property
    def italic(self) -> bool:
        return self._italic

    @property
    def color(self) -> str:
        return self._color

    def set_text_color(self, color: str) -> None:
        self._color = color if color in ("black", "red") else "black"
        self.setDefaultTextColor(QColor(self._color))

    @property
    def align(self) -> str:
        return self._align

    def set_align(self, align: str) -> None:
        align = align if align in ("left", "center", "right") else "left"
        self._align = align
        flags = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }[align]
        option = QTextOption(self.document().defaultTextOption())
        option.setAlignment(flags | Qt.AlignmentFlag.AlignTop)
        self.document().setDefaultTextOption(option)

    def set_text_width(self, width: float) -> None:
        self.setTextWidth(width if width > 0 else -1)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("date", "time", "both") else MODE_DEFAULT
        self.refresh()

    @property
    def date_format(self) -> str:
        return self._date_format

    def set_date_format(self, key: str) -> None:
        self._date_format = key if key in DATE_FORMATS else DATE_DEFAULT
        self.refresh()

    @property
    def time_format(self) -> str:
        return self._time_format

    def set_time_format(self, key: str) -> None:
        self._time_format = key if key in TIME_FORMATS else TIME_DEFAULT
        self.refresh()

    @property
    def live(self) -> bool:
        return self._live

    def set_live(self, live: bool) -> None:
        """Aktuelle Zeit, oder das bisherige Datum festhalten.

        Beim Abschalten wird die jetzige Uhrzeit zum festen Wert - ohne den
        Versatz noch einmal einzurechnen. Die Anzeige bleibt dadurch stehen,
        wo sie war.
        """
        live = bool(live)
        if live == self._live:
            return
        if not live:
            self._fixed = datetime.now().replace(microsecond=0)
        self._live = live
        self._sync_timer()
        self.refresh()

    @property
    def fixed(self) -> datetime:
        return self._fixed

    def set_fixed(self, when: datetime) -> None:
        self._fixed = when.replace(microsecond=0)
        self.refresh()

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def offset_unit(self) -> str:
        return self._offset_unit

    def set_offset(self, amount: int, unit: str | None = None) -> None:
        self._offset = int(amount)
        if unit is not None and unit in OFFSET_UNITS:
            self._offset_unit = unit
        self.refresh()

    def moment(self, now: datetime | None = None) -> datetime:
        """Der Zeitpunkt, den der Stempel gerade zeigt, inklusive Versatz.

        ``now`` ersetzt die Uhr nur im Live-Modus (Tests, Druck). Ein festes
        Datum ignoriert sie.
        """
        if self._live:
            base = now if now is not None else datetime.now()
        else:
            base = self._fixed
        return shift(base.replace(microsecond=0), self._offset, self._offset_unit)

    def refresh(self, now: datetime | None = None) -> None:
        """Text aus dem Zeitpunkt neu setzen. Still, wenn sich nichts ändert."""
        text = format_stamp(self.moment(now), self._mode, self._date_format, self._time_format)
        if text == self.toPlainText():
            return
        self.setPlainText(text)
        self.display_changed.emit()

    def refresh_for_output(self) -> None:
        """Vor Vorschau und Druck die aktuelle Minute nachziehen."""
        if self._live:
            self.refresh()

    def apply_resize(self, width: float, height: float) -> None:
        rect = self.boundingRect()
        if self.textWidth() > 0 or abs(width - rect.width()) > 0.5:
            self.set_text_width(width)
        if rect.height() > 0 and height > 0:
            factor = height / rect.height()
            self.set_font_pixel_size(max(4, round(self._font_pixel_size * factor)))

    def to_dict(self) -> dict[str, Any]:
        data = self._base_dict()
        data.update(
            font_family=self._font_family,
            font_pixel_size=self._font_pixel_size,
            bold=self._bold,
            italic=self._italic,
            color=self._color,
            align=self._align,
            text_width=self.textWidth(),
            mode=self._mode,
            date_format=self._date_format,
            time_format=self._time_format,
            live=self._live,
            fixed=self._fixed.isoformat(timespec="seconds"),
            offset=self._offset,
            offset_unit=self._offset_unit,
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DateTimeItem":
        item = cls(data.get("font_family", "Sans"), int(data.get("font_pixel_size", 48)))
        item.set_bold(bool(data.get("bold", False)))
        item.set_italic(bool(data.get("italic", False)))
        item.set_text_color(data.get("color", "black"))
        item.set_align(data.get("align", "left"))
        item.set_text_width(float(data.get("text_width", -1)))
        item._mode = data.get("mode") if data.get("mode") in ("date", "time", "both") else MODE_DEFAULT
        item._date_format = data.get("date_format") if data.get("date_format") in DATE_FORMATS else DATE_DEFAULT
        item._time_format = data.get("time_format") if data.get("time_format") in TIME_FORMATS else TIME_DEFAULT
        item._live = bool(data.get("live", True))
        item._offset = int(data.get("offset", 0))
        unit = data.get("offset_unit", UNIT_DEFAULT)
        item._offset_unit = unit if unit in OFFSET_UNITS else UNIT_DEFAULT
        try:
            item._fixed = datetime.fromisoformat(str(data.get("fixed"))).replace(microsecond=0)
        except (TypeError, ValueError):
            item._fixed = datetime.now().replace(microsecond=0)
        item._apply_base(data)
        item.refresh()
        return item


# --------------------------------------------------------------------------- #
# Bild
# --------------------------------------------------------------------------- #
#: Groesste Kante, mit der ein Foto im Objekt gehalten wird. Ein Etikett hat
#: hoechstens ~1200 Druckpunkte (50 mm bei 600 dpi) - mehr Pixel bringen beim
#: Druck nichts, kosten aber bei jedem Speichern und Rendern Zeit.
IMAGE_MAX_SIDE_PX = 2048


class ImageItem(_ClampMixin, QGraphicsPixmapItem):
    kind = "image"

    def __init__(self, pixmap: QPixmap | None = None):
        super().__init__(pixmap if pixmap is not None else QPixmap())
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._source_path: str | None = None
        #: Kodierung des Pixmaps (WebP) - wird nur einmal erzeugt (siehe to_dict).
        self._encoded: bytes | None = None

    @classmethod
    def from_file(cls, path: str) -> "ImageItem":
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError(tr("Bild konnte nicht geladen werden: {path}").format(path=path))
        original = pixmap.size()
        if max(original.width(), original.height()) > IMAGE_MAX_SIDE_PX:
            pixmap = pixmap.scaled(
                IMAGE_MAX_SIDE_PX,
                IMAGE_MAX_SIDE_PX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        item = cls(pixmap)
        item._source_path = path
        if pixmap.size() != original:
            # Die Anzeigegroesse bleibt wie vor dem Verkleinern: die Transformation gleicht aus.
            item.setTransform(
                QTransform().scale(
                    original.width() / pixmap.width(),
                    original.height() / pixmap.height(),
                )
            )
        return item

    @classmethod
    def from_pil(cls, image: Image.Image) -> "ImageItem":
        return cls(pil_to_qpixmap(image))

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        base = self.boundingRect()
        if base.width() <= 0 or base.height() <= 0:
            return
        self.setTransform(QTransform().scale(width / base.width(), height / base.height()))

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        if self._encoded is None:
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            # Verlustfrei: die Pixel bleiben exakt (Schwelle und Dithering haengen daran).
            self.pixmap().toImage().save(buf, "WEBP", 100)
            self._encoded = bytes(buf.data())
            buf.close()
        d.update(
            data_b64=base64.b64encode(self._encoded).decode("ascii"),
            source_path=self._source_path,
            scale_x=self.transform().m11(),
            scale_y=self.transform().m22(),
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImageItem":
        raw = base64.b64decode(d["data_b64"])
        pixmap = QPixmap()
        # Ohne Formatangabe: alte Dateien enthalten PNG, neue WebP.
        pixmap.loadFromData(raw)
        item = cls(pixmap)
        item._encoded = raw
        item._source_path = d.get("source_path")
        sx = float(d.get("scale_x", 1.0))
        sy = float(d.get("scale_y", 1.0))
        item.setTransform(QTransform().scale(sx, sy))
        item._apply_base(d)
        return item


# --------------------------------------------------------------------------- #
# QR-Code
# --------------------------------------------------------------------------- #
class QRItem(_BindingMixin, _ClampMixin, QGraphicsPixmapItem):
    kind = "qr"

    def __init__(self, data: str = "https://example.org", size_dots: int = 200):
        super().__init__()
        self._binding = None
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._data = data
        self._size_dots = size_dots
        self._regenerate()

    def _regenerate(self) -> None:
        img = make_qr_image(self._data)
        pixmap = pil_to_qpixmap(img).scaled(
            self._size_dots,
            self._size_dots,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)

    def set_data(self, data: str) -> None:
        self._data = data
        self._regenerate()

    def set_size_dots(self, size: int) -> None:
        self._size_dots = max(20, int(size))
        self._regenerate()

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        # QR-Codes bleiben quadratisch.
        self.set_size_dots(int(max(20, min(width, height))))

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        d.update(data=self._data, size_dots=self._size_dots)
        self._binding_to_dict(d)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QRItem":
        item = cls(d.get("data", ""), int(d.get("size_dots", 200)))
        item._apply_base(d)
        item._apply_binding(d)
        return item


# --------------------------------------------------------------------------- #
# Barcode
# --------------------------------------------------------------------------- #
class BarcodeItem(_BindingMixin, _ClampMixin, QGraphicsPixmapItem):
    kind = "barcode"

    def __init__(
        self,
        value: str = "123456789",
        symbology: str = "code128",
        *,
        show_text: bool = True,
        height_dots: int = 120,
    ):
        super().__init__()
        self._binding = None
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._value = value
        self._symbology = symbology
        self._show_text = show_text
        self._height_dots = height_dots
        self._regenerate()

    def _regenerate(self) -> None:
        try:
            img = make_barcode_image(self._value, self._symbology, write_text=self._show_text)
        except Exception as exc:  # ungueltiger Inhalt fuer die Symbologie
            raise ValueError(
                tr("Barcode '{value}' ({symbology}): {error}").format(
                    value=self._value, symbology=self._symbology, error=exc
                )
            ) from exc
        pixmap = pil_to_qpixmap(img)
        if pixmap.height() > 0:
            pixmap = pixmap.scaledToHeight(self._height_dots, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pixmap)

    def _update(self, **changes: Any) -> None:
        """Eigenschaften setzen und neu zeichnen - oder *nichts* aendern.

        Schlaegt das Zeichnen fehl (ungueltiger Inhalt fuer die Symbologie),
        bleibt der alte Zustand vollstaendig stehen. Sonst zeigte das Bild den
        alten Code, waehrend ``_value`` schon den ungueltigen trug - und die
        gespeicherte Datei liess sich nicht mehr oeffnen.
        """
        previous = {key: getattr(self, key) for key in changes}
        for key, value in changes.items():
            setattr(self, key, value)
        try:
            self._regenerate()
        except ValueError:
            for key, value in previous.items():
                setattr(self, key, value)
            raise

    def set_value(self, value: str) -> None:
        self._update(_value=value)

    def set_symbology(self, symbology: str) -> None:
        self._update(_symbology=symbology)

    def set_height_dots(self, height: int) -> None:
        self._update(_height_dots=max(20, int(height)))

    def set_show_text(self, show: bool) -> None:
        self._update(_show_text=bool(show))

    @property
    def value(self) -> str:
        return self._value

    @property
    def symbology(self) -> str:
        return self._symbology

    # -- Groesse ------------------------------------------------------------
    resizable = True  # nur Hoehe (Breite folgt dem Inhalt -> Scanbarkeit)

    def apply_resize(self, width: float, height: float) -> None:
        self.set_height_dots(int(max(20, height)))

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        d.update(value=self._value, symbology=self._symbology, show_text=self._show_text, height_dots=self._height_dots)
        self._binding_to_dict(d)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BarcodeItem":
        item = cls(
            d.get("value", ""), d.get("symbology", "code128"),
            show_text=bool(d.get("show_text", True)), height_dots=int(d.get("height_dots", 120)),
        )
        item._apply_base(d)
        item._apply_binding(d)
        return item


# --------------------------------------------------------------------------- #
# Linie / Rahmen
# --------------------------------------------------------------------------- #
class LineItem(_ClampMixin, QGraphicsLineItem):
    kind = "line"

    def __init__(self, x1: float = 0, y1: float = 0, x2: float = 200, y2: float = 0, width_px: float = 2):
        super().__init__(x1, y1, x2, y2)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._width_px = width_px
        self._apply_pen()

    def _apply_pen(self) -> None:
        pen = QPen(QColor("black"))
        pen.setWidthF(self._width_px)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.setPen(pen)

    def set_line_width(self, width_px: float) -> None:
        self._width_px = max(0.5, float(width_px))
        self._apply_pen()

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        self.setLine(0.0, 0.0, max(1.0, width), height)

    def to_dict(self) -> dict[str, Any]:
        ln = self.line()
        d = self._base_dict()
        d.update(x1=ln.x1(), y1=ln.y1(), x2=ln.x2(), y2=ln.y2(), width_px=self._width_px)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LineItem":
        item = cls(d.get("x1", 0), d.get("y1", 0), d.get("x2", 200), d.get("y2", 0), d.get("width_px", 2))
        item._apply_base(d)
        return item


class RectItem(_ClampMixin, QGraphicsRectItem):
    kind = "rect"

    def __init__(self, rect: QRectF | None = None, width_px: float = 2, filled: bool = False):
        super().__init__(rect if rect is not None else QRectF(0, 0, 200, 100))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._width_px = width_px
        self._filled = filled
        self._apply_pen()

    def _apply_pen(self) -> None:
        pen = QPen(QColor("black"))
        pen.setWidthF(self._width_px)
        self.setPen(pen)
        self.setBrush(QBrush(QColor("black")) if self._filled else QBrush(Qt.BrushStyle.NoBrush))

    def set_line_width(self, width_px: float) -> None:
        self._width_px = max(0.5, float(width_px))
        self._apply_pen()

    def set_filled(self, filled: bool) -> None:
        self._filled = bool(filled)
        self._apply_pen()

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        self.setRect(QRectF(0.0, 0.0, max(1.0, width), max(1.0, height)))

    def to_dict(self) -> dict[str, Any]:
        r = self.rect()
        d = self._base_dict()
        # Position steckt in ``x``/``y`` (Szene); die lokale Rechteckursprung
        # ist ueblich 0/0 und darf die Position nicht ueberschreiben.
        d.update(
            w=r.width(),
            h=r.height(),
            width_px=self._width_px,
            filled=self._filled,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RectItem":
        rect = QRectF(0.0, 0.0, d.get("w", 200), d.get("h", 100))
        item = cls(rect, d.get("width_px", 2), bool(d.get("filled", False)))
        item._apply_base(d)
        return item


# --------------------------------------------------------------------------- #
# Formen (Pfeile, Ellipse, Dreieck, Stern)
# --------------------------------------------------------------------------- #
SHAPES: tuple[str, ...] = ("ellipse", "triangle", "star", "arrow_right", "arrow_left", "arrow_double")


def _shape_path(shape: str, r: QRectF) -> QPainterPath:
    """Umriss einer Form im Rechteck ``r``. Pfeile haben einen Schaft von halber Hoehe."""
    path = QPainterPath()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    cx, cy = x + w / 2, y + h / 2
    if shape == "ellipse":
        path.addEllipse(r)
        return path
    if shape == "triangle":
        points = [QPointF(cx, y), QPointF(x + w, y + h), QPointF(x, y + h)]
    elif shape == "star":
        # Einheitstern um den Ursprung, dann so skalieren/verschieben, dass
        # path.boundingRect() exakt ``r`` fuellt (sonst driftens die Handles).
        unit: list[QPointF] = []
        for i in range(10):
            ratio = 1.0 if i % 2 == 0 else 0.45
            angle = -math.pi / 2 + i * math.pi / 5
            unit.append(QPointF(ratio * math.cos(angle), ratio * math.sin(angle)))
        xs = [p.x() for p in unit]
        ys = [p.y() for p in unit]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bw, bh = max_x - min_x, max_y - min_y
        points = [
            QPointF(x + (p.x() - min_x) / bw * w, y + (p.y() - min_y) / bh * h)
            for p in unit
        ]
    else:
        shaft = h / 4
        head = min(w / 2, h / 2)
        if shape == "arrow_right":
            points = [
                QPointF(x, cy - shaft), QPointF(x + w - head, cy - shaft), QPointF(x + w - head, y),
                QPointF(x + w, cy), QPointF(x + w - head, y + h), QPointF(x + w - head, cy + shaft),
                QPointF(x, cy + shaft),
            ]
        elif shape == "arrow_left":
            points = [
                QPointF(x + w, cy - shaft), QPointF(x + head, cy - shaft), QPointF(x + head, y),
                QPointF(x, cy), QPointF(x + head, y + h), QPointF(x + head, cy + shaft),
                QPointF(x + w, cy + shaft),
            ]
        else:
            points = [
                QPointF(x, cy), QPointF(x + head, y), QPointF(x + head, cy - shaft),
                QPointF(x + w - head, cy - shaft), QPointF(x + w - head, y), QPointF(x + w, cy),
                QPointF(x + w - head, y + h), QPointF(x + w - head, cy + shaft),
                QPointF(x + head, cy + shaft), QPointF(x + head, y + h),
            ]
    path.addPolygon(QPolygonF(points))
    path.closeSubpath()
    return path


class ShapeItem(_ClampMixin, QGraphicsPathItem):
    kind = "shape"

    def __init__(self, rect: QRectF | None = None, shape: str = "ellipse", width_px: float = 2, filled: bool = False):
        super().__init__()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._rect = rect if rect is not None else QRectF(0, 0, 200, 100)
        self._shape = shape if shape in SHAPES else "ellipse"
        self._width_px = width_px
        self._filled = bool(filled)
        self._apply_path()

    def _apply_path(self) -> None:
        pen = QPen(QColor("black"))
        pen.setWidthF(self._width_px)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.setPen(pen)
        self.setBrush(QBrush(QColor("black")) if self._filled else QBrush(Qt.BrushStyle.NoBrush))
        self.setPath(_shape_path(self._shape, self._rect))

    @property
    def shape_name(self) -> str:
        return self._shape

    def set_shape(self, shape: str) -> None:
        self._shape = shape if shape in SHAPES else "ellipse"
        self._apply_path()

    def set_line_width(self, width_px: float) -> None:
        self._width_px = max(0.5, float(width_px))
        self._apply_path()

    def set_filled(self, filled: bool) -> None:
        self._filled = bool(filled)
        self._apply_path()

    @property
    def filled(self) -> bool:
        return self._filled

    @property
    def width_px(self) -> float:
        return self._width_px

    # -- Groesse ------------------------------------------------------------
    resizable = True

    def apply_resize(self, width: float, height: float) -> None:
        self._rect = QRectF(0.0, 0.0, max(1.0, width), max(1.0, height))
        self._apply_path()

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        d.update(
            w=self._rect.width(),
            h=self._rect.height(),
            shape=self._shape,
            width_px=self._width_px,
            filled=self._filled,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShapeItem":
        rect = QRectF(0.0, 0.0, d.get("w", 200), d.get("h", 100))
        item = cls(rect, d.get("shape", "ellipse"), d.get("width_px", 2), bool(d.get("filled", False)))
        item._apply_base(d)
        return item

# --------------------------------------------------------------------------- #
# Clip Art
# --------------------------------------------------------------------------- #
class ClipArtItem(_ClampMixin, QGraphicsObject):
    """Gefülltes Vektorsymbol. Die Auswahl malt der Canvas, nicht das Objekt."""

    kind = "clipart"
    resizable = True

    def __init__(
        self,
        symbol: str = "warning",
        size: float = 160.0,
        *,
        width: float | None = None,
        height: float | None = None,
        color: str = "black",
        keep_aspect: bool = True,
    ) -> None:
        super().__init__()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self._symbol = known_symbol(symbol)
        self._w = max(16.0, float(size if width is None else width))
        self._h = max(16.0, float(size if height is None else height))
        self._color = color if color in ("black", "red") else "black"
        self._keep_aspect = bool(keep_aspect)
        self._ratio = self._w / self._h if self._h else 1.0

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0.0, 0.0, self._w, self._h)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        paint_symbol(painter, self._symbol, self.boundingRect(), self._color)

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def color(self) -> str:
        return self._color

    @property
    def keep_aspect(self) -> bool:
        return self._keep_aspect

    def set_symbol(self, symbol: str) -> None:
        self._symbol = known_symbol(symbol)
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color if color in ("black", "red") else "black"
        self.update()

    def set_keep_aspect(self, keep: bool) -> None:
        self._keep_aspect = bool(keep)
        if self._keep_aspect and self._h > 0:
            self._ratio = self._w / self._h

    def apply_resize(self, width: float, height: float) -> None:
        width = max(16.0, float(width))
        height = max(16.0, float(height))
        if self._keep_aspect and self._ratio > 0:
            if abs(width - self._w) >= abs(height - self._h):
                height = width / self._ratio
            else:
                width = height * self._ratio
        self.prepareGeometryChange()
        self._w = width
        self._h = height
        self.update()

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        d.update(
            symbol=self._symbol,
            w=self._w,
            h=self._h,
            color=self._color,
            keep_aspect=self._keep_aspect,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipArtItem":
        item = cls(
            str(d.get("symbol", "warning")),
            width=float(d.get("w", 160)),
            height=float(d.get("h", 160)),
            color=str(d.get("color", "black")),
            keep_aspect=bool(d.get("keep_aspect", True)),
        )
        item._apply_base(d)
        return item


# --------------------------------------------------------------------------- #
# Tabelle
# --------------------------------------------------------------------------- #
#: Kleinste Zeile/Spalte in Dots. Darunter laesst sich eine Zelle nicht
#: mehr treffen und der Text hat keinen Platz.
_MIN_CELL = 12.0
#: Abstand des Texts zum Gitter, zusaetzlich zur halben Linienbreite.
_CELL_PAD = 5.0

#: Fuellungen, die auf einem monochromen Etikett als Muster drucken.
FILL_CHOICES: tuple[str, ...] = (
    "none",
    "gray25",
    "gray50",
    "gray75",
    "black",
    "horizontal",
    "vertical",
    "diagonal",
    "cross",
    "dots",
)


def fill_label(key: str) -> str:
    """Anzeigename einer Fuellung. ``tr`` steht literal, damit die Uebersetzung greift."""
    return {
        "none": tr("Keine Füllung"),
        "gray25": tr("Hellgrau"),
        "gray50": tr("Grau"),
        "gray75": tr("Dunkelgrau"),
        "black": tr("Schwarz"),
        "horizontal": tr("Waagerecht"),
        "vertical": tr("Senkrecht"),
        "diagonal": tr("Diagonal"),
        "cross": tr("Kreuz"),
        "dots": tr("Punktmuster"),
    }.get(key, key)
_FILL_BRUSH = {
    "none": Qt.BrushStyle.NoBrush,
    "gray25": Qt.BrushStyle.Dense6Pattern,
    "gray50": Qt.BrushStyle.Dense4Pattern,
    "gray75": Qt.BrushStyle.Dense2Pattern,
    "black": Qt.BrushStyle.SolidPattern,
    "horizontal": Qt.BrushStyle.HorPattern,
    "vertical": Qt.BrushStyle.VerPattern,
    "diagonal": Qt.BrushStyle.BDiagPattern,
    "cross": Qt.BrushStyle.DiagCrossPattern,
    "dots": Qt.BrushStyle.Dense7Pattern,
}

LINE_STYLE_CHOICES: tuple[str, ...] = ("solid", "dashed", "dotted", "none")


def line_style_label(key: str) -> str:
    return {
        "solid": tr("Durchgezogen"),
        "dashed": tr("Gestrichelt"),
        "dotted": tr("Gepunktet"),
        "none": tr("Keine Linie"),
    }.get(key, key)
_LINE_QT = {
    "solid": Qt.PenStyle.SolidLine,
    "dashed": Qt.PenStyle.DashLine,
    "dotted": Qt.PenStyle.DotLine,
    "none": Qt.PenStyle.NoPen,
}

ALIGN_CHOICES: tuple[str, ...] = ("left", "center", "right", "justify")
VALIGN_CHOICES: tuple[str, ...] = ("top", "middle", "bottom")


def align_label(key: str) -> str:
    return {
        "left": tr("Linksbündig"),
        "center": tr("Zentriert"),
        "right": tr("Rechtsbündig"),
        "justify": tr("Blocksatz"),
    }.get(key, key)


def valign_label(key: str) -> str:
    return {
        "top": tr("Oben"),
        "middle": tr("Mitte"),
        "bottom": tr("Unten"),
    }.get(key, key)
_H_ALIGN = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
    "justify": Qt.AlignmentFlag.AlignJustify,
}


@dataclass
class TableCell:
    """Eine Zelle. ``skip`` heisst: von einer verbundenen Zelle oben links bedeckt."""

    text: str = ""
    row_span: int = 1
    col_span: int = 1
    skip: bool = False
    font_family: str = "Sans"
    font_pixel_size: int = 28
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: str = "left"
    valign: str = "middle"
    fill: str = "none"
    color: str = "black"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "row_span": self.row_span,
            "col_span": self.col_span,
            "skip": self.skip,
            "font_family": self.font_family,
            "font_pixel_size": self.font_pixel_size,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "align": self.align,
            "valign": self.valign,
            "fill": self.fill,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "TableCell":
        if not raw:
            return cls()
        align = raw.get("align", "left")
        valign = raw.get("valign", "middle")
        fill = raw.get("fill", "none")
        color = str(raw.get("color", "black"))
        return cls(
            text=str(raw.get("text", "")),
            row_span=max(1, int(raw.get("row_span", 1))),
            col_span=max(1, int(raw.get("col_span", 1))),
            skip=bool(raw.get("skip", False)),
            font_family=str(raw.get("font_family", "Sans")),
            font_pixel_size=max(4, int(raw.get("font_pixel_size", 28))),
            bold=bool(raw.get("bold", False)),
            italic=bool(raw.get("italic", False)),
            underline=bool(raw.get("underline", False)),
            align=align if align in _H_ALIGN else "left",
            valign=valign if valign in ("top", "middle", "bottom") else "middle",
            fill=fill if fill in _FILL_BRUSH else "none",
            color=color if color in ("black", "red") else "black",
        )


class _CellEditor(QGraphicsTextItem):
    """Inline-Editor einer Zelle. Nicht selbst ein Etiketten-Objekt."""

    def __init__(self, parent: QGraphicsItem):
        super().__init__(parent)
        self._caret_hidden = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.document().setDocumentMargin(0)

    def set_caret_hidden(self, hidden: bool) -> None:
        hidden = bool(hidden)
        if hidden == self._caret_hidden:
            return
        self._caret_hidden = hidden
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        if not self._caret_hidden:
            super().paint(painter, option, widget)
            return
        painter.save()
        self.document().drawContents(painter, option.exposedRect)
        painter.restore()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        parent = self.parentItem()
        super().focusOutEvent(event)
        if isinstance(parent, TableItem) and parent.editor is self:
            parent.finish_editing()


class TableItem(_ClampMixin, QGraphicsObject):
    """Tabelle als ein Objekt: Gitter, Zellen mit Text, verbinden, Zeilen/Spalten.

    Wie im P-touch Editor ist die Tabelle **ein** Objekt (verschieben, drehen,
    an den Anfassern skalieren). Ein Klick waehlt die Zelle, ein Doppelklick
    bearbeitet den Text. Trennlinien zwischen den Zellen aendern die
    Zeilen- bzw. Spaltenmasse; bei fester Tabellengroesse nimmt die Nachbarzelle
    die Differenz auf.
    """

    kind = "table"
    resizable = True

    #: Andere Zelle gewaehlt - der Inspector baut sich neu auf.
    cell_selection_changed = Signal()
    #: Zeilen, Spalten oder Verbindungen haben sich geaendert.
    structure_changed = Signal()
    editing_started = Signal()
    editing_finished = Signal()
    #: Getippt, waehrend eine Zelle offen ist (Undo-Schnappschuss + Vorschau).
    content_changed = Signal()

    def __init__(
        self,
        rows: int = 3,
        cols: int = 2,
        width: float = 420.0,
        height: float = 240.0,
        font_pixel_size: int = 28,
    ):
        super().__init__()
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        self._default_font = max(4, int(font_pixel_size))
        self._col_widths = [max(_MIN_CELL, float(width) / cols) for _ in range(cols)]
        self._row_heights = [max(_MIN_CELL, float(height) / rows) for _ in range(rows)]
        self._cells: list[list[TableCell]] = [
            [TableCell(font_pixel_size=self._default_font) for _ in range(cols)]
            for _ in range(rows)
        ]
        self._line_width = 2.0
        self._line_style = "solid"
        self._fixed_size = True
        self._selection: set[tuple[int, int]] = {(0, 0)}
        self._range_origin: tuple[int, int] = (0, 0)
        self._editor: _CellEditor | None = None
        self._editing_cell: tuple[int, int] | None = None
        self._finishing = False
        self._editor_block = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape
        )

    # -- Masse --------------------------------------------------------------
    @property
    def rows(self) -> int:
        return len(self._row_heights)

    @property
    def cols(self) -> int:
        return len(self._col_widths)

    @property
    def table_width(self) -> float:
        return float(sum(self._col_widths))

    @property
    def table_height(self) -> float:
        return float(sum(self._row_heights))

    @property
    def col_widths(self) -> list[float]:
        return list(self._col_widths)

    @property
    def row_heights(self) -> list[float]:
        return list(self._row_heights)

    @property
    def line_width(self) -> float:
        return self._line_width

    @property
    def line_style(self) -> str:
        return self._line_style

    @property
    def fixed_size(self) -> bool:
        return self._fixed_size

    @property
    def editor(self) -> _CellEditor | None:
        return self._editor

    @property
    def is_editing(self) -> bool:
        return self._editor is not None

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0.0, 0.0, self.table_width, self.table_height)

    def _geom(self) -> None:
        if self.scene() is not None:
            self.prepareGeometryChange()

    # -- Zellen -------------------------------------------------------------
    def anchor_at(self, row: int, col: int) -> tuple[int, int]:
        """Ursprung der Zelle, die ``(row, col)`` bedeckt (auch bei Verbindungen)."""
        row = max(0, min(self.rows - 1, int(row)))
        col = max(0, min(self.cols - 1, int(col)))
        if not self._cells[row][col].skip:
            return row, col
        for rr in range(row, -1, -1):
            for cc in range(col, -1, -1):
                cell = self._cells[rr][cc]
                if cell.skip:
                    continue
                if rr <= row < rr + cell.row_span and cc <= col < cc + cell.col_span:
                    return rr, cc
        return row, col

    def index_at(self, pos: QPointF) -> tuple[int, int] | None:
        """Rohindex (Zeile, Spalte) unter einem lokalen Punkt."""
        if pos.x() < 0 or pos.y() < 0 or pos.x() > self.table_width or pos.y() > self.table_height:
            return None
        return self._row_index_at(pos.y()), self._col_index_at(pos.x())

    def _row_index_at(self, y: float) -> int:
        acc = 0.0
        for r, h in enumerate(self._row_heights):
            acc += h
            if y < acc or r == self.rows - 1:
                return r
        return self.rows - 1

    def _col_index_at(self, x: float) -> int:
        acc = 0.0
        for c, w in enumerate(self._col_widths):
            acc += w
            if x < acc or c == self.cols - 1:
                return c
        return self.cols - 1

    def cell_rect(self, row: int, col: int) -> QRectF:
        cell = self._cells[row][col]
        x = sum(self._col_widths[:col])
        y = sum(self._row_heights[:row])
        w = sum(self._col_widths[col : col + cell.col_span])
        h = sum(self._row_heights[row : row + cell.row_span])
        return QRectF(x, y, w, h)

    def _content_rect(self, row: int, col: int) -> QRectF:
        pad = _CELL_PAD + self._line_width / 2.0
        rect = self.cell_rect(row, col).adjusted(pad, pad, -pad, -pad)
        if rect.width() < 1.0:
            rect.setWidth(1.0)
        if rect.height() < 1.0:
            rect.setHeight(1.0)
        return rect

    def _anchors(self) -> list[tuple[int, int]]:
        found = []
        for row, col in self._selection:
            if not (0 <= row < self.rows and 0 <= col < self.cols):
                continue
            anchor = self.anchor_at(row, col)
            if anchor not in found and not self._cells[anchor[0]][anchor[1]].skip:
                found.append(anchor)
        if not found:
            found = [self.anchor_at(0, 0)]
        return found

    def _set_selection(self, anchors: set[tuple[int, int]], origin: tuple[int, int] | None = None) -> None:
        clean = {self.anchor_at(r, c) for r, c in anchors}
        clean = {a for a in clean if not self._cells[a[0]][a[1]].skip}
        if not clean:
            clean = {self.anchor_at(0, 0)}
        if origin is not None:
            self._range_origin = origin
        if clean == self._selection:
            self.update()
            return
        self._selection = clean
        self.update()
        self.cell_selection_changed.emit()

    def select_cell_at(self, pos: QPointF, *, extend: bool = False) -> None:
        idx = self.index_at(pos)
        if idx is None:
            return
        if extend:
            a = self._range_origin
            r0, r1 = sorted((a[0], idx[0]))
            c0, c1 = sorted((a[1], idx[1]))
            anchors = set()
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    anchors.add(self.anchor_at(r, c))
            self._set_selection(anchors)
            return
        self._set_selection({self.anchor_at(*idx)}, origin=idx)

    def selected_uniform(self, name: str) -> tuple[bool, Any]:
        """``(einheitlich, wert)``. Bei gemischter Auswahl ist der Wert der erste."""
        vals = [getattr(self._cells[r][c], name) for r, c in self._anchors()]
        if not vals:
            return True, None
        return all(v == vals[0] for v in vals), vals[0]

    def set_selected(self, name: str, value: Any) -> None:
        if name == "color":
            value = value if value in ("black", "red") else "black"
        for r, c in self._anchors():
            setattr(self._cells[r][c], name, value)
        if self._editing_cell in self._anchors():
            self._place_editor()
            if name == "text" and self._editor is not None and not self._editor_block:
                self._editor_block = True
                try:
                    self._editor.setPlainText(str(value))
                finally:
                    self._editor_block = False
        self.update()

    def _selected_row_indexes(self) -> list[int]:
        rows: set[int] = set()
        for r, c in self._anchors():
            cell = self._cells[r][c]
            rows.update(range(r, r + cell.row_span))
        return sorted(rows) or [0]

    def _selected_col_indexes(self) -> list[int]:
        cols: set[int] = set()
        for r, c in self._anchors():
            cell = self._cells[r][c]
            cols.update(range(c, c + cell.col_span))
        return sorted(cols) or [0]

    def selected_row_height(self) -> tuple[bool, float]:
        indexes = self._selected_row_indexes()
        heights = [self._row_heights[i] for i in indexes]
        return all(abs(h - heights[0]) < 0.5 for h in heights), heights[0]

    def selected_col_width(self) -> tuple[bool, float]:
        indexes = self._selected_col_indexes()
        widths = [self._col_widths[i] for i in indexes]
        return all(abs(w - widths[0]) < 0.5 for w in widths), widths[0]

    def set_selected_row_height(self, height: float) -> None:
        self._set_tracks(self._row_heights, self._selected_row_indexes(), height)

    def set_selected_col_width(self, width: float) -> None:
        self._set_tracks(self._col_widths, self._selected_col_indexes(), width)

    def _set_tracks(self, tracks: list[float], indexes: list[int], size: float) -> None:
        size = max(_MIN_CELL, float(size))
        self._geom()
        chosen = set(indexes)
        if self._fixed_size and len(chosen) < len(tracks):
            old = sum(tracks[i] for i in chosen)
            new = size * len(chosen)
            others = [i for i in range(len(tracks)) if i not in chosen]
            remain = sum(tracks[i] for i in others)
            leftover = remain + old - new
            if remain > 0 and leftover >= _MIN_CELL * len(others):
                scale = leftover / remain
                for i in others:
                    tracks[i] *= scale
                for i in chosen:
                    tracks[i] = size
            else:
                for i in chosen:
                    tracks[i] = size
        else:
            for i in chosen:
                tracks[i] = size
        self._place_editor()
        self.update()

    # -- Zeilen, Spalten, Verbindungen --------------------------------------
    def insert_row_above(self) -> None:
        self._insert_row(self._selected_row_indexes()[0])

    def insert_column_left(self) -> None:
        self._insert_col(self._selected_col_indexes()[0])

    def delete_selected_rows(self) -> None:
        # Nur die Ursprungszeilen der Auswahl. Eine verbundene Zelle belegt
        # mehrere Zeilen, geloest wird aber eine - die Spanne schrumpft.
        indexes = sorted({r for r, _ in self._anchors()})
        if self.rows - len(indexes) < 1:
            indexes = indexes[1:]
        if not indexes:
            return
        self.finish_editing()
        self._geom()
        for index in reversed(indexes):
            self._delete_row(index)
        self._sanitize()
        self._clamp_selection()
        self._place_editor()
        self.update()
        self.structure_changed.emit()

    def delete_selected_columns(self) -> None:
        indexes = sorted({c for _, c in self._anchors()})
        if self.cols - len(indexes) < 1:
            indexes = indexes[1:]
        if not indexes:
            return
        self.finish_editing()
        self._geom()
        for index in reversed(indexes):
            self._delete_col(index)
        self._sanitize()
        self._clamp_selection()
        self._place_editor()
        self.update()
        self.structure_changed.emit()

    def can_delete_row(self) -> bool:
        return self.rows > 1

    def can_delete_column(self) -> bool:
        return self.cols > 1

    def _selection_rect(self) -> tuple[int, int, int, int] | None:
        covered: list[tuple[int, int]] = []
        for r, c in self._anchors():
            cell = self._cells[r][c]
            for rr in range(r, r + cell.row_span):
                for cc in range(c, c + cell.col_span):
                    covered.append((rr, cc))
        if not covered:
            return None
        r0 = min(r for r, _ in covered)
        r1 = max(r for r, _ in covered)
        c0 = min(c for _, c in covered)
        c1 = max(c for _, c in covered)
        full = {(rr, cc) for rr in range(r0, r1 + 1) for cc in range(c0, c1 + 1)}
        if full != set(covered):
            return None
        return r0, c0, r1, c1

    def can_merge(self) -> bool:
        rect = self._selection_rect()
        if rect is None:
            return False
        r0, c0, r1, c1 = rect
        if (r1 - r0 + 1) * (c1 - c0 + 1) < 2:
            return False
        anchors = self._anchors()
        if len(anchors) == 1:
            r, c = anchors[0]
            cell = self._cells[r][c]
            if r == r0 and c == c0 and cell.row_span == r1 - r0 + 1 and cell.col_span == c1 - c0 + 1:
                return False
        return True

    def can_unmerge(self) -> bool:
        return any(
            self._cells[r][c].row_span > 1 or self._cells[r][c].col_span > 1
            for r, c in self._anchors()
        )

    def can_distribute_heights(self) -> bool:
        return len(self._selected_row_indexes()) >= 2

    def can_distribute_widths(self) -> bool:
        return len(self._selected_col_indexes()) >= 2

    def merge_selected(self) -> None:
        rect = self._selection_rect()
        if rect is None or not self.can_merge():
            return
        r0, c0, r1, c1 = rect
        self.finish_editing()
        texts = []
        style = self._cells[r0][c0]
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cell = self._cells[r][c]
                if not cell.skip and cell.text.strip():
                    texts.append(cell.text)
                if (r, c) != (r0, c0):
                    self._cells[r][c] = self._styled_like(style, skip=True)
        origin = self._cells[r0][c0]
        origin.skip = False
        origin.row_span = r1 - r0 + 1
        origin.col_span = c1 - c0 + 1
        if len(texts) > 1 or (texts and not origin.text.strip()):
            origin.text = "\n".join(texts)
        self._sanitize()
        self._selection = {(r0, c0)}
        self._range_origin = (r0, c0)
        self.update()
        self.structure_changed.emit()

    def unmerge_selected(self) -> None:
        if not self.can_unmerge():
            return
        self.finish_editing()
        for r, c in list(self._anchors()):
            cell = self._cells[r][c]
            if cell.row_span == 1 and cell.col_span == 1:
                continue
            rs, cs = cell.row_span, cell.col_span
            cell.row_span = 1
            cell.col_span = 1
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    if (rr, cc) == (r, c):
                        continue
                    self._cells[rr][cc] = self._styled_like(cell, text="", skip=False)
        self._sanitize()
        self.update()
        self.structure_changed.emit()

    def distribute_selected_heights(self) -> None:
        self._distribute(self._row_heights, self._selected_row_indexes())

    def distribute_selected_widths(self) -> None:
        self._distribute(self._col_widths, self._selected_col_indexes())

    def _distribute(self, tracks: list[float], indexes: list[int]) -> None:
        if len(indexes) < 2:
            return
        self._geom()
        each = sum(tracks[i] for i in indexes) / len(indexes)
        for i in indexes:
            tracks[i] = max(_MIN_CELL, each)
        self._place_editor()
        self.update()
        self.structure_changed.emit()

    def _styled_like(self, src: TableCell, **changes: Any) -> TableCell:
        fields = {"text": "", "row_span": 1, "col_span": 1, "skip": False}
        fields.update(changes)
        return replace(src, **fields)

    def _insert_row(self, index: int) -> None:
        self.finish_editing()
        self._geom()
        index = max(0, min(int(index), self.rows))
        total = self.table_height
        ref_h = self._row_heights[min(index, self.rows - 1)]
        if self._fixed_size:
            new_h = total / (self.rows + 1)
            scale = (total - new_h) / total if total else 1.0
            self._row_heights = [h * scale for h in self._row_heights]
        else:
            new_h = ref_h
        style_row = min(index, self.rows - 1)
        new_row = [
            self._styled_like(self._cells[self.anchor_at(style_row, c)[0]][self.anchor_at(style_row, c)[1]])
            for c in range(self.cols)
        ]
        self._cells.insert(index, new_row)
        self._row_heights.insert(index, max(_MIN_CELL, new_h))
        if index > 0:
            for r in range(index):
                for c in range(self.cols):
                    cell = self._cells[r][c]
                    if cell.skip:
                        continue
                    if r + cell.row_span > index:
                        cell.row_span += 1
                        for cc in range(c, min(self.cols, c + cell.col_span)):
                            self._cells[index][cc] = self._styled_like(cell, skip=True)
        self._sanitize()
        self._selection = {self.anchor_at(index, self._selected_col_indexes()[0] if self.cols else 0)}
        self._range_origin = next(iter(self._selection))
        self.update()
        self.structure_changed.emit()

    def _insert_col(self, index: int) -> None:
        self.finish_editing()
        self._geom()
        index = max(0, min(int(index), self.cols))
        total = self.table_width
        ref_w = self._col_widths[min(index, self.cols - 1)]
        if self._fixed_size:
            new_w = total / (self.cols + 1)
            scale = (total - new_w) / total if total else 1.0
            self._col_widths = [w * scale for w in self._col_widths]
        else:
            new_w = ref_w
        style_col = min(index, self.cols - 1)
        for r in range(self.rows):
            src_r, src_c = self.anchor_at(r, style_col)
            self._cells[r].insert(index, self._styled_like(self._cells[src_r][src_c]))
        self._col_widths.insert(index, max(_MIN_CELL, new_w))
        if index > 0:
            for r in range(self.rows):
                for c in range(index):
                    cell = self._cells[r][c]
                    if cell.skip:
                        continue
                    if c + cell.col_span > index:
                        cell.col_span += 1
                        for rr in range(r, min(self.rows, r + cell.row_span)):
                            self._cells[rr][index] = self._styled_like(cell, skip=True)
        self._sanitize()
        self._selection = {self.anchor_at(self._selected_row_indexes()[0] if self.rows else 0, index)}
        self._range_origin = next(iter(self._selection))
        self.update()
        self.structure_changed.emit()

    def _delete_row(self, index: int) -> None:
        total = sum(self._row_heights)
        for c in range(self.cols):
            cell = self._cells[index][c]
            if cell.skip or cell.row_span == 1 or index + 1 >= self.rows:
                continue
            self._move_origin(cell, self._cells[index + 1][c], row_span=cell.row_span - 1, col_span=cell.col_span)
        for r in range(index):
            for c in range(self.cols):
                cell = self._cells[r][c]
                if cell.skip:
                    continue
                if r + cell.row_span - 1 >= index:
                    cell.row_span -= 1
        del self._cells[index]
        self._row_heights.pop(index)
        if self._fixed_size and self._row_heights:
            remain = sum(self._row_heights)
            if remain > 0:
                scale = total / remain
                self._row_heights = [h * scale for h in self._row_heights]

    def _delete_col(self, index: int) -> None:
        total = sum(self._col_widths)
        for r in range(self.rows):
            cell = self._cells[r][index]
            if cell.skip or cell.col_span == 1 or index + 1 >= self.cols:
                continue
            self._move_origin(cell, self._cells[r][index + 1], row_span=cell.row_span, col_span=cell.col_span - 1)
        for r in range(self.rows):
            for c in range(index):
                cell = self._cells[r][c]
                if cell.skip:
                    continue
                if c + cell.col_span - 1 >= index:
                    cell.col_span -= 1
        for row in self._cells:
            del row[index]
        self._col_widths.pop(index)
        if self._fixed_size and self._col_widths:
            remain = sum(self._col_widths)
            if remain > 0:
                scale = total / remain
                self._col_widths = [w * scale for w in self._col_widths]

    @staticmethod
    def _move_origin(src: TableCell, dest: TableCell, *, row_span: int, col_span: int) -> None:
        dest.text = src.text
        dest.font_family = src.font_family
        dest.font_pixel_size = src.font_pixel_size
        dest.bold = src.bold
        dest.italic = src.italic
        dest.underline = src.underline
        dest.align = src.align
        dest.valign = src.valign
        dest.fill = src.fill
        dest.color = src.color
        dest.skip = False
        dest.row_span = max(1, row_span)
        dest.col_span = max(1, col_span)

    def _sanitize(self) -> None:
        """Spannen in die Tabelle klemmen und bedeckte Zellen als ``skip`` markieren."""
        covered: set[tuple[int, int]] = set()
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self._cells[r][c]
                if (r, c) in covered or cell.skip:
                    continue
                cell.row_span = max(1, min(cell.row_span, self.rows - r))
                cell.col_span = max(1, min(cell.col_span, self.cols - c))
                for rr in range(r, r + cell.row_span):
                    for cc in range(c, c + cell.col_span):
                        if (rr, cc) != (r, c):
                            covered.add((rr, cc))
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self._cells[r][c]
                if (r, c) in covered:
                    cell.skip = True
                    cell.row_span = 1
                    cell.col_span = 1
                    cell.text = ""
                elif cell.skip:
                    cell.skip = False

    def _clamp_selection(self) -> None:
        anchors = set()
        for r, c in self._selection:
            if 0 <= r < self.rows and 0 <= c < self.cols:
                anchors.add(self.anchor_at(r, c))
        if not anchors:
            anchors = {self.anchor_at(0, 0)}
        self._selection = anchors
        self._range_origin = next(iter(anchors))

    # -- Trennlinien ziehen -------------------------------------------------
    def divider_at(self, pos: QPointF, tol: float) -> tuple[str, int] | None:
        """``("col", i)`` oder ``("row", i)``: Trennlinie nach Spalte/Zeile ``i``."""
        if tol <= 0:
            return None
        best: tuple[str, int] | None = None
        best_d = tol
        x = 0.0
        for c, w in enumerate(self._col_widths[:-1]):
            x += w
            dist = abs(pos.x() - x)
            if dist <= best_d and self._divider_col_visible(c, pos.y()):
                best = ("col", c)
                best_d = dist
        y = 0.0
        for r, h in enumerate(self._row_heights[:-1]):
            y += h
            dist = abs(pos.y() - y)
            if dist <= best_d and self._divider_row_visible(r, pos.x()):
                best = ("row", r)
                best_d = dist
        return best

    def _divider_col_visible(self, index: int, y: float) -> bool:
        if y < 0 or y > self.table_height:
            return False
        return not self._span_crosses_vline(index + 1, self._row_index_at(y))

    def _divider_row_visible(self, index: int, x: float) -> bool:
        if x < 0 or x > self.table_width:
            return False
        return not self._span_crosses_hline(index + 1, self._col_index_at(x))

    def drag_divider(
        self,
        kind: str,
        index: int,
        delta: float,
        start_widths: list[float],
        start_heights: list[float],
    ) -> None:
        """Trennlinie aus der Startgeometrie um ``delta`` Dots ziehen."""
        if kind == "col":
            widths = list(start_widths)
            left = widths[index]
            if self._fixed_size:
                right = widths[index + 1]
                shift = max(_MIN_CELL - left, min(right - _MIN_CELL, delta))
                widths[index] = left + shift
                widths[index + 1] = right - shift
            else:
                widths[index] = max(_MIN_CELL, left + delta)
            if widths == self._col_widths:
                return
            self._geom()
            self._col_widths = widths
        else:
            heights = list(start_heights)
            top = heights[index]
            if self._fixed_size:
                below = heights[index + 1]
                shift = max(_MIN_CELL - top, min(below - _MIN_CELL, delta))
                heights[index] = top + shift
                heights[index + 1] = below - shift
            else:
                heights[index] = max(_MIN_CELL, top + delta)
            if heights == self._row_heights:
                return
            self._geom()
            self._row_heights = heights
        self._place_editor()
        self.update()

    # -- Linien, die eine Verbindung kreuzt ---------------------------------
    def _span_crosses_hline(self, boundary: int, col: int) -> bool:
        if boundary <= 0 or boundary >= self.rows:
            return False
        r, c = self.anchor_at(boundary - 1, col)
        cell = self._cells[r][c]
        return r + cell.row_span > boundary and c <= col < c + cell.col_span

    def _span_crosses_vline(self, boundary: int, row: int) -> bool:
        if boundary <= 0 or boundary >= self.cols:
            return False
        r, c = self.anchor_at(row, boundary - 1)
        cell = self._cells[r][c]
        return c + cell.col_span > boundary and r <= row < r + cell.row_span

    # -- Schrift und Gitter -------------------------------------------------
    def set_line_width(self, width: float) -> None:
        self._line_width = max(0.5, float(width))
        self._place_editor()
        self.update()

    def set_line_style(self, style: str) -> None:
        self._line_style = style if style in _LINE_QT else "solid"
        self.update()

    def set_fixed_size(self, fixed: bool) -> None:
        self._fixed_size = bool(fixed)

    def _font_for(self, cell: TableCell) -> QFont:
        font = QFont(cell.font_family)
        font.setPixelSize(max(4, int(cell.font_pixel_size)))
        font.setBold(cell.bold)
        font.setItalic(cell.italic)
        font.setUnderline(cell.underline)
        return font

    def _document_for(self, cell: TableCell, width: float) -> QTextDocument:
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._font_for(cell))
        option = QTextOption()
        option.setAlignment(_H_ALIGN.get(cell.align, Qt.AlignmentFlag.AlignLeft))
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        doc.setDefaultTextOption(option)
        doc.setPlainText(cell.text)
        doc.setTextWidth(max(1.0, width))
        return doc

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option  # Auswahlrahmen malt der Canvas, nicht das Objekt
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self._cells[r][c]
                if cell.skip:
                    continue
                rect = self.cell_rect(r, c)
                brush_style = _FILL_BRUSH.get(cell.fill, Qt.BrushStyle.NoBrush)
                if brush_style != Qt.BrushStyle.NoBrush:
                    fill_color = cell.color if cell.color in ("black", "red") else "black"
                    painter.fillRect(rect, QBrush(QColor(fill_color), brush_style))
                if widget is not None and (r, c) in self._selection:
                    painter.fillRect(rect, QColor(0, 120, 215, 36))
                if self._editing_cell == (r, c) or not cell.text:
                    continue
                content = self._content_rect(r, c)
                doc = self._document_for(cell, content.width())
                doc_h = doc.size().height()
                if cell.valign == "middle":
                    y = content.top() + max(0.0, (content.height() - doc_h) / 2.0)
                elif cell.valign == "bottom":
                    y = content.top() + max(0.0, content.height() - doc_h)
                else:
                    y = content.top()
                painter.save()
                painter.setClipRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
                painter.setPen(QColor(cell.color))
                painter.translate(content.left(), y)
                doc.drawContents(painter)
                painter.restore()
        self._paint_grid(painter)
        if widget is not None:
            self._paint_selection_frame(painter)

    def _paint_grid(self, painter: QPainter) -> None:
        if self._line_style == "none":
            return
        pen = QPen(QColor("black"))
        pen.setWidthF(self._line_width)
        pen.setStyle(_LINE_QT.get(self._line_style, Qt.PenStyle.SolidLine))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        w = self.table_width
        h = self.table_height
        m = self._line_width / 2.0
        xs = [m]
        x = 0.0
        for cw in self._col_widths[:-1]:
            x += cw
            xs.append(x)
        xs.append(max(m, w - m))
        ys = [m]
        y = 0.0
        for rh in self._row_heights[:-1]:
            y += rh
            ys.append(y)
        ys.append(max(m, h - m))
        for boundary, yb in enumerate(ys):
            x0 = xs[0]
            for c in range(self.cols):
                x1 = xs[c + 1]
                if boundary == 0 or boundary == self.rows or not self._span_crosses_hline(boundary, c):
                    painter.drawLine(QPointF(x0, yb), QPointF(x1, yb))
                x0 = x1
        for boundary, xb in enumerate(xs):
            y0 = ys[0]
            for r in range(self.rows):
                y1 = ys[r + 1]
                if boundary == 0 or boundary == self.cols or not self._span_crosses_vline(boundary, r):
                    painter.drawLine(QPointF(xb, y0), QPointF(xb, y1))
                y0 = y1

    def _paint_selection_frame(self, painter: QPainter) -> None:
        pen = QPen(QColor("#0078d7"))
        pen.setWidthF(max(1.0, self._line_width))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for r, c in self._anchors():
            rect = self.cell_rect(r, c).adjusted(1.0, 1.0, -1.0, -1.0)
            painter.drawRect(rect)

    # -- Inline-Text --------------------------------------------------------
    def advance_cell(self, backward: bool = False) -> None:
        anchors = [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if not self._cells[r][c].skip
        ]
        if not anchors:
            return
        current = self.anchor_at(*next(iter(self._selection)))
        try:
            index = anchors.index(current)
        except ValueError:
            index = 0
        step = -1 if backward else 1
        nxt = anchors[(index + step) % len(anchors)]
        self._set_selection({nxt}, origin=nxt)

    def begin_edit_current(self) -> None:
        anchor = self.anchor_at(*next(iter(self._selection)))
        self._begin_edit(anchor)

    def begin_edit_at(self, pos: QPointF) -> None:
        idx = self.index_at(pos)
        if idx is None:
            return
        anchor = self.anchor_at(*idx)
        if self._editing_cell == anchor and self._editor is not None:
            self._select_editor_all()
            return
        self._set_selection({anchor}, origin=idx)
        self._begin_edit(anchor)

    def _begin_edit(self, anchor: tuple[int, int]) -> None:
        if self._editing_cell == anchor and self._editor is not None:
            self._select_editor_all()
            return
        self.finish_editing()
        cell = self._cells[anchor[0]][anchor[1]]
        editor = _CellEditor(self)
        self._editor = editor
        self._editing_cell = anchor
        self._editor_block = True
        try:
            editor.setPlainText(cell.text)
        finally:
            self._editor_block = False
        self._place_editor()
        editor.document().contentsChanged.connect(self._on_editor_text)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self._select_editor_all()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self.editing_started.emit()
        self.update()

    def _select_editor_all(self) -> None:
        if self._editor is None:
            return
        cursor = self._editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self._editor.setTextCursor(cursor)
        self._editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def _on_editor_text(self) -> None:
        if self._editor_block or self._editor is None or self._editing_cell is None:
            return
        r, c = self._editing_cell
        self._cells[r][c].text = self._editor.toPlainText()
        self._place_editor()
        self.content_changed.emit()
        self.update()

    def _place_editor(self) -> None:
        if self._editor is None or self._editing_cell is None:
            return
        r, c = self._editing_cell
        if not (0 <= r < self.rows and 0 <= c < self.cols) or self._cells[r][c].skip:
            return
        cell = self._cells[r][c]
        self._editor_block = True
        try:
            content = self._content_rect(r, c)
            self._editor.setTextWidth(max(1.0, content.width()))
            self._editor.setFont(self._font_for(cell))
            self._editor.setDefaultTextColor(QColor(cell.color))
            option = QTextOption()
            option.setAlignment(_H_ALIGN.get(cell.align, Qt.AlignmentFlag.AlignLeft))
            option.setWrapMode(QTextOption.WrapMode.WordWrap)
            self._editor.document().setDefaultTextOption(option)
            doc_h = self._editor.document().size().height()
            if cell.valign == "middle":
                y = content.top() + max(0.0, (content.height() - doc_h) / 2.0)
            elif cell.valign == "bottom":
                y = content.top() + max(0.0, content.height() - doc_h)
            else:
                y = content.top()
            self._editor.setPos(content.left(), y)
        finally:
            self._editor_block = False

    def finish_editing(self) -> None:
        if self._finishing or self._editor is None:
            return
        self._finishing = True
        editor = self._editor
        try:
            if self._editing_cell is not None:
                r, c = self._editing_cell
                if 0 <= r < self.rows and 0 <= c < self.cols:
                    self._cells[r][c].text = editor.toPlainText()
            self._editor = None
            self._editing_cell = None
            editor.hide()
            self.update()
            self.editing_finished.emit()
        finally:
            self._finishing = False
        QTimer.singleShot(0, lambda ed=editor: self._drop_editor(ed))

    def focus_editor(self) -> None:
        if self._editor is not None:
            self._editor.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def _drop_editor(editor: _CellEditor) -> None:
        # Der Timer laeuft nach dem Fokus-Event. Bis dahin kann Undo die
        # Tabelle samt Editor schon zerstoert haben.
        try:
            scene = editor.scene()
        except RuntimeError:
            return
        if scene is not None:
            scene.removeItem(editor)

    def set_caret_hidden(self, hidden: bool) -> None:
        if self._editor is not None:
            self._editor.set_caret_hidden(hidden)

    # -- Groesse der ganzen Tabelle -----------------------------------------
    def apply_resize(self, width: float, height: float) -> None:
        width = max(_MIN_CELL * self.cols, float(width))
        height = max(_MIN_CELL * self.rows, float(height))
        old_w, old_h = self.table_width, self.table_height
        if old_w <= 0 or old_h <= 0:
            return
        self._geom()
        self._col_widths = [max(_MIN_CELL, w * width / old_w) for w in self._col_widths]
        self._row_heights = [max(_MIN_CELL, h * height / old_h) for h in self._row_heights]
        self._place_editor()
        self.update()

    # -- Serialisierung -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        cells = []
        for r, row in enumerate(self._cells):
            for c, cell in enumerate(row):
                raw = cell.to_dict()
                raw["r"] = r
                raw["c"] = c
                cells.append(raw)
        d.update(
            col_widths=self.col_widths,
            row_heights=self.row_heights,
            line_width=self._line_width,
            line_style=self._line_style,
            fixed_size=self._fixed_size,
            cells=cells,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TableItem":
        widths = [float(v) for v in d.get("col_widths") or [200.0, 200.0]]
        heights = [float(v) for v in d.get("row_heights") or [80.0, 80.0, 80.0]]
        item = cls(len(heights), len(widths), sum(widths), sum(heights))
        item._col_widths = [max(_MIN_CELL, w) for w in widths]
        item._row_heights = [max(_MIN_CELL, h) for h in heights]
        item._line_width = max(0.5, float(d.get("line_width", 2.0)))
        style = d.get("line_style", "solid")
        item._line_style = style if style in _LINE_QT else "solid"
        item._fixed_size = bool(d.get("fixed_size", True))
        stored = {}
        for raw in d.get("cells") or []:
            if "r" in raw and "c" in raw:
                stored[(int(raw["r"]), int(raw["c"]))] = raw
        item._cells = [
            [TableCell.from_dict(stored.get((r, c))) for c in range(item.cols)]
            for r in range(item.rows)
        ]
        item._sanitize()
        item._selection = {item.anchor_at(0, 0)}
        item._range_origin = next(iter(item._selection))
        item._apply_base(d)
        return item


ITEM_TYPES: dict[str, type] = {
    TextItem.kind: TextItem,
    ImageItem.kind: ImageItem,
    QRItem.kind: QRItem,
    BarcodeItem.kind: BarcodeItem,
    LineItem.kind: LineItem,
    RectItem.kind: RectItem,
    ShapeItem.kind: ShapeItem,
    ClipArtItem.kind: ClipArtItem,
    TableItem.kind: TableItem,
    DateTimeItem.kind: DateTimeItem,
}


def item_from_dict(d: dict[str, Any]) -> QGraphicsItem:
    """Erzeuge ein Item aus seiner Serialisierung."""
    kind = d.get("type")
    if kind not in ITEM_TYPES:
        raise ValueError(tr("Unbekannter Item-Typ: {kind!r}").format(kind=kind))
    return ITEM_TYPES[kind].from_dict(d)


__all__ = [
    "pil_to_qpixmap",
    "make_qr_image",
    "make_barcode_image",
    "normalize_binding",
    "LabelItem",
    "TextItem",
    "ImageItem",
    "QRItem",
    "BarcodeItem",
    "LineItem",
    "RectItem",
    "ShapeItem",
    "SHAPES",
    "ClipArtItem",
    "TableItem",
    "TableCell",
    "DateTimeItem",
    "FILL_CHOICES",
    "LINE_STYLE_CHOICES",
    "ALIGN_CHOICES",
    "VALIGN_CHOICES",
    "fill_label",
    "line_style_label",
    "align_label",
    "valign_label",
    "ITEM_TYPES",
    "item_from_dict",
]
