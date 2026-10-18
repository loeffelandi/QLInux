"""Canvas-Items fuer den Editor: Text, Bild, Barcode, QR, Linie, Rahmen.

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
from typing import Any, Mapping

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt, Signal
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
    QTextListFormat,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyle,
    QStyleOptionGraphicsItem,
)

from .i18n import tr

# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #


def normalize_binding(binding: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Binding normalisieren: ``database``+Feld, ``serial``, oder ``None`` (D4)."""
    if binding is None:
        return None
    source = binding.get("source")
    if source in (None, "", "none"):
        return None
    if source == "database":
        field = binding.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError(tr("Datenbank-Binding braucht einen Spaltennamen."))
        return {"source": "database", "field": field}
    if source == "serial":
        return {"source": "serial"}
    raise ValueError(
        tr("Unbekannte Binding-Quelle: {source!r}.").format(source=source)
    )


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


ITEM_TYPES: dict[str, type] = {
    TextItem.kind: TextItem,
    ImageItem.kind: ImageItem,
    QRItem.kind: QRItem,
    BarcodeItem.kind: BarcodeItem,
    LineItem.kind: LineItem,
    RectItem.kind: RectItem,
    ShapeItem.kind: ShapeItem,
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
    "ITEM_TYPES",
    "item_from_dict",
]
