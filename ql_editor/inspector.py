"""Inspector-Panel: kontextabhaengige Eigenschaften des ausgewaehlten Items.

Statt alles ueber Menues zu steuern, erscheinen die Eigenschaften direkt beim
Auswaehlen (wie in einer guten Desktop-App). Das Panel baut seine Steuerelemente
je nach Item-Typ neu auf und meldet Aenderungen ueber :attr:`changed`.

Das Panel kennt nur die oeffentlichen Setter der Items aus
:mod:`ql_editor.items` - keine Render- oder Drucklogik.

Undo: :attr:`edit_begun` vor der ersten Aenderung eines Feldes,
:attr:`edit_committed` wenn das Feld fertig ist (``editingFinished`` bzw.
sofort bei Schaltern).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import icon
from .media import dots_to_mm, mm_to_dots
from .widgets import install_wheel_guard_recursive

BARCODE_SYMBOLOGIES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"]


class InspectorPanel(QWidget):
    """Zeigt die Eigenschaften des aktuell ausgewaehlten Items."""

    changed = Signal()
    edit_begun = Signal()
    edit_committed = Signal()
    #: Eingabe abgelehnt (Barcode passt nicht zur Symbologie) - mit Begruendung.
    rejected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._item = None
        self._allow_red = False
        self._loading = False
        self._edit_open = False

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(8, 8, 8, 8)
        self._root.setSpacing(6)
        self._title = QLabel(tr("Nichts ausgewählt"))
        self._title.setStyleSheet("font-weight:600; color:#333;")
        self._root.addWidget(self._title)
        self._root.addStretch(1)

    # --------------------------------------------------------------- API --
    def set_item(self, item, allow_red: bool = False) -> None:
        self._finish_edit()
        self._item = item
        self._allow_red = allow_red
        self._rebuild()
        self.updateGeometry()

    # ------------------------------------------------------------ Aufbau --
    def _clear_body(self) -> None:
        while self._root.count() > 1:
            child = self._root.takeAt(1)
            widget = child.widget()
            if widget is not None:
                # Sofort verstecken: deleteLater() laeuft erst im Event-Loop,
                # sonst ueberlappen alte Steuerelemente die neuen.
                widget.hide()
                widget.deleteLater()
        self._root.invalidate()

    def _rebuild(self) -> None:
        self._clear_body()
        item = self._item
        if item is None:
            self._title.setText(tr("Nichts ausgewählt"))
            self._root.addStretch(1)
            return

        kind = getattr(item, "kind", "?")
        title = _KIND_TITLES.get(kind)
        self._title.setText(tr(title) if title else tr("Objekt"))

        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        builder = {
            "text": self._build_text,
            "qr": self._build_qr,
            "barcode": self._build_barcode,
            "image": self._build_image,
            "line": self._build_line,
            "rect": self._build_rect,
            "shape": self._build_shape,
        }.get(kind)
        if builder is not None:
            builder(item, form)

        self._build_common(item, form)
        self._root.addWidget(body)
        self._root.addStretch(1)
        install_wheel_guard_recursive(body)

    # -- Typ-spezifisch -----------------------------------------------------
    def _build_text(self, item, form: QFormLayout) -> None:
        family = QFontComboBox()
        family.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        family.setMinimumContentsLength(8)
        family.setCurrentFont(QFont(item.font_family))
        family.currentFontChanged.connect(
            lambda f: self._apply_now(lambda: item.set_font_family(f.family()))
        )
        form.addRow(tr("Schrift"), family)

        size = QSpinBox()
        size.setRange(4, 2000)
        size.setValue(item.font_pixel_size)
        self._wire_spin(size, lambda v: item.set_font_pixel_size(v))
        form.addRow(tr("Größe (px)"), size)

        form.addRow(self._rule())
        form.addRow(
            self._bar(
                self._toggle("bold", tr("Fett"), item.bold, item.set_bold),
                self._toggle("italic", tr("Kursiv"), item.italic, item.set_italic),
                self._toggle("underline", tr("Unterstrichen"), item.underline, item.set_underline),
                self._toggle("strike", tr("Durchgestrichen"), item.strike, item.set_strike),
                self._divider(),
                self._toggle("invert", tr("Invertiert"), item.inverted, item.set_inverted),
                *([self._divider(), self._color_button(item)] if self._allow_red else []),
            )
        )

        form.addRow(self._rule())
        form.addRow(
            tr("Textausrichtung"),
            self._choice(
                [
                    ("align_left", tr("Links"), "left"),
                    ("align_hcenter", tr("Mitte"), "center"),
                    ("align_right", tr("Rechts"), "right"),
                ],
                item.align,
                item.set_align,
            ),
        )
        form.addRow(
            tr("Vertikal ausrichten"),
            self._choice(
                [
                    ("align_top", tr("Oben"), "top"),
                    ("align_vcenter", tr("Mitte"), "middle"),
                    ("align_bottom", tr("Unten"), "bottom"),
                ],
                item.valign,
                item.set_valign,
            ),
        )
        form.addRow(
            tr("Aufzählung"),
            self._choice(
                [
                    ("list_none", tr("Keine"), "none"),
                    ("list_bullet", tr("Punkte"), "bullet"),
                    ("list_number", tr("Nummern"), "number"),
                ],
                item.list_style,
                item.set_list,
            ),
        )
        form.addRow(
            tr("Textrichtung"),
            self._choice(
                [
                    ("dir_horizontal", tr("Horizontal"), False),
                    ("dir_vertical", tr("Vertikal"), True),
                ],
                item.vertical,
                item.set_vertical,
            ),
        )

        form.addRow(self._rule())
        letter = QDoubleSpinBox()
        letter.setRange(-20.0, 200.0)
        letter.setDecimals(1)
        letter.setSuffix(" px")
        letter.setValue(item.letter_spacing)
        self._wire_spin(letter, lambda v: item.set_letter_spacing(v))
        form.addRow(tr("Zeichenabstand"), letter)

        line = QDoubleSpinBox()
        line.setRange(0.5, 3.0)
        line.setDecimals(2)
        line.setSingleStep(0.1)
        line.setValue(item.line_spacing)
        self._wire_spin(line, lambda v: item.set_line_spacing(v))
        form.addRow(tr("Zeilenabstand"), line)

        form.addRow(self._rule())
        form.addRow(
            self._bar(
                self._check(tr("Breite automatisch"), item.auto_width, item.set_auto_width),
                self._check(tr("Umbruch"), item.wrap, item.set_wrap),
                self._check(tr("Höhe automatisch"), item.auto_height, item.set_auto_height),
            )
        )

    # -- Textleiste (Symbol-Knoepfe) -----------------------------------------
    def _bar(self, *widgets: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return row

    def _toggle(self, name: str, tip: str, checked: bool, apply_fn) -> QToolButton:
        """Ein-/Aus-Knopf mit Symbol (Fett, Kursiv, Invertiert ...)."""
        button = QToolButton()
        button.setIcon(icon(name))
        button.setToolTip(tip)
        button.setCheckable(True)
        button.setChecked(bool(checked))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.toggled.connect(lambda v: self._apply_now(lambda: apply_fn(v)))
        return button

    def _color_button(self, item) -> QToolButton:
        """„A“-Knopf wie in Textverarbeitungen: Menue mit Schwarz/Rot."""
        button = QToolButton()
        button.setText("A")
        button.setToolTip(tr("Farbe"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        group = QActionGroup(menu)
        for label, value in ((tr("schwarz"), "black"), (tr("rot"), "red")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(item.color == value)
            group.addAction(act)
            act.triggered.connect(
                lambda _=False, v=value: self._apply_now(lambda: item.set_text_color(v))
            )
        button.setMenu(menu)
        return button

    def _choice(self, options, current, apply_fn) -> QWidget:
        """Gruppe von Symbol-Knoepfen, genau einer ist aktiv (Ausrichtung, Richtung ...)."""
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons = []
        for name, tip, value in options:
            button = QToolButton()
            button.setIcon(icon(name))
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setChecked(value == current)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.toggled.connect(
                lambda v, val=value: v and self._apply_now(lambda: apply_fn(val))
            )
            group.addButton(button)
            buttons.append(button)
        return self._bar(*buttons)

    def _check(self, label: str, checked: bool, apply_fn) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(bool(checked))
        box.toggled.connect(lambda v: self._apply_now(lambda: apply_fn(v)))
        return box

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _rule(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _build_shape(self, item, form: QFormLayout) -> None:
        shape = QComboBox()
        for label, value in (
            (tr("Ellipse"), "ellipse"),
            (tr("Dreieck"), "triangle"),
            (tr("Stern"), "star"),
            (tr("Pfeil rechts"), "arrow_right"),
            (tr("Pfeil links"), "arrow_left"),
            (tr("Doppelpfeil"), "arrow_double"),
        ):
            shape.addItem(label, value)
        shape.setCurrentIndex(max(0, shape.findData(item.shape_name)))
        shape.currentIndexChanged.connect(
            lambda: self._apply_now(lambda: item.set_shape(shape.currentData()))
        )
        form.addRow(tr("Form"), shape)

        width = QDoubleSpinBox()
        width.setRange(0.5, 200.0)
        width.setSuffix(" px")
        width.setValue(item.width_px)
        self._wire_spin(width, lambda v: item.set_line_width(v))
        form.addRow(tr("Linienbreite"), width)

        filled = QCheckBox(tr("Gefüllt"))
        filled.setChecked(item.filled)
        filled.toggled.connect(lambda v: self._apply_now(lambda: item.set_filled(v)))
        form.addRow("", filled)

    def _build_qr(self, item, form: QFormLayout) -> None:
        data = QLineEdit(item._data)
        data.editingFinished.connect(
            lambda: self._apply_now(lambda: item.set_data(data.text()))
        )
        form.addRow(tr("Inhalt"), data)

        size = QSpinBox()
        size.setRange(20, 4000)
        size.setValue(item._size_dots)
        self._wire_spin(size, lambda v: item.set_size_dots(v))
        form.addRow(tr("Größe (Dots)"), size)

    def _build_barcode(self, item, form: QFormLayout) -> None:
        value = QLineEdit(item.value)
        value.editingFinished.connect(
            lambda: self._guard_now(item, lambda: item.set_value(value.text()))
        )
        form.addRow(tr("Inhalt"), value)

        sym = QComboBox()
        for name in BARCODE_SYMBOLOGIES:
            sym.addItem(name, name)
        idx = sym.findData(item.symbology)
        sym.setCurrentIndex(idx if idx >= 0 else 0)
        sym.currentIndexChanged.connect(
            lambda: self._guard_now(item, lambda: item.set_symbology(sym.currentData()))
        )
        form.addRow(tr("Symbologie"), sym)

        show_text = QCheckBox(tr("Klartext"))
        show_text.setChecked(item._show_text)
        show_text.toggled.connect(
            lambda v: self._guard_now(item, lambda: item.set_show_text(v))
        )
        form.addRow("", show_text)

        height = QSpinBox()
        height.setRange(20, 2000)
        height.setValue(item._height_dots)
        height.valueChanged.connect(
            lambda v: self._guard_live(item, lambda: item.set_height_dots(v))
        )
        height.editingFinished.connect(self._finish_edit)
        form.addRow(tr("Höhe (Dots)"), height)

    def _build_image(self, item, form: QFormLayout) -> None:
        """Groesse in Millimetern (statt Prozent der Originalpixel).

        Bei Fotos ist "100 %" die Pixelgroesse der Datei - ein 2400-px-Bild
        waere damit 203 mm breit. Millimeter sind das Mass, in dem man auf
        einem Etikett denkt. Breite und Hoehe bleiben dabei im
        Seitenverhaeltnis (verzerren geht mit den Anfassern am Canvas).
        """
        width_dots, height_dots = self._image_size(item)
        ratio = (height_dots / width_dots) if width_dots > 0 else 1.0

        width = QDoubleSpinBox()
        width.setRange(1.0, 1000.0)
        width.setDecimals(1)
        width.setSuffix(" mm")
        width.setValue(dots_to_mm(width_dots))

        height = QDoubleSpinBox()
        height.setRange(1.0, 1000.0)
        height.setDecimals(1)
        height.setSuffix(" mm")
        height.setValue(dots_to_mm(height_dots))

        def sync(w_dots: float, h_dots: float) -> None:
            """Beide Felder nachziehen, ohne erneut zu resizen."""
            self._loading = True
            try:
                width.setValue(dots_to_mm(w_dots))
                height.setValue(dots_to_mm(h_dots))
            finally:
                self._loading = False

        def resize_width(value: float) -> None:
            if self._loading:
                return
            w_dots = mm_to_dots(value)
            self._apply_live(lambda: item.apply_resize(w_dots, w_dots * ratio))
            sync(w_dots, w_dots * ratio)

        def resize_height(value: float) -> None:
            if self._loading:
                return
            h_dots = mm_to_dots(value)
            w_dots = h_dots / ratio if ratio > 0 else h_dots
            self._apply_live(lambda: item.apply_resize(w_dots, h_dots))
            sync(w_dots, h_dots)

        width.valueChanged.connect(resize_width)
        height.valueChanged.connect(resize_height)
        width.editingFinished.connect(self._finish_edit)
        height.editingFinished.connect(self._finish_edit)
        form.addRow(tr("Breite"), width)
        form.addRow(tr("Höhe"), height)

    @staticmethod
    def _image_size(item) -> tuple[float, float]:
        """Angezeigte Groesse eines Bild-Items in Dots (ohne Drehung)."""
        rect = item.transform().mapRect(item.boundingRect())
        return (rect.width(), rect.height())

    def _build_line(self, item, form: QFormLayout) -> None:
        width = QDoubleSpinBox()
        width.setRange(0.5, 200.0)
        width.setSuffix(" px")
        width.setValue(item._width_px)
        self._wire_spin(width, lambda v: item.set_line_width(v))
        form.addRow(tr("Linienbreite"), width)

    def _build_rect(self, item, form: QFormLayout) -> None:
        width = QDoubleSpinBox()
        width.setRange(0.5, 200.0)
        width.setSuffix(" px")
        width.setValue(item._width_px)
        self._wire_spin(width, lambda v: item.set_line_width(v))
        form.addRow(tr("Linienbreite"), width)

        filled = QCheckBox(tr("Gefüllt"))
        filled.setChecked(item._filled)
        filled.toggled.connect(lambda v: self._apply_now(lambda: item.set_filled(v)))
        form.addRow("", filled)

    # -- Gemeinsam ----------------------------------------------------------
    def _build_common(self, item, form: QFormLayout) -> None:
        pos = item.pos()
        x = QSpinBox()
        x.setRange(-10000, 10000)
        x.setValue(int(pos.x()))
        self._wire_spin(x, lambda v: item.setPos(v, item.pos().y()))
        form.addRow(tr("X (Dots)"), x)

        y = QSpinBox()
        y.setRange(-10000, 10000)
        y.setValue(int(pos.y()))
        self._wire_spin(y, lambda v: item.setPos(item.pos().x(), v))
        form.addRow(tr("Y (Dots)"), y)

        rot = QSpinBox()
        rot.setRange(-180, 180)
        rot.setSuffix(" °")
        rot.setValue(int(item.rotation()))
        self._wire_spin(rot, lambda v: item.setRotation(v))
        form.addRow(tr("Drehung"), rot)

    # -- Helpers ------------------------------------------------------------
    def _wire_spin(self, spin, apply_fn) -> None:
        spin.valueChanged.connect(lambda v: self._apply_live(lambda: apply_fn(v)))
        spin.editingFinished.connect(self._finish_edit)

    @property
    def edit_open(self) -> bool:
        """Eine Feld-Aenderung ist angefangen, aber noch nicht abgeschlossen."""
        return self._edit_open

    def flush_edit(self) -> None:
        """Offene Bearbeitung abschliessen (Undo-Schritt „Eigenschaften")."""
        self._finish_edit()

    def cancel_edit_tracking(self) -> None:
        """Flag loeschen, ohne ``edit_committed`` - der Aufrufer committet selbst."""
        self._edit_open = False

    def _begin_edit(self) -> None:
        if self._edit_open:
            return
        self._edit_open = True
        self.edit_begun.emit()

    def _finish_edit(self) -> None:
        if not self._edit_open:
            return
        self._edit_open = False
        self.edit_committed.emit()

    def _apply_live(self, action) -> None:
        if self._loading:
            return
        self._begin_edit()
        action()
        self.changed.emit()

    def _apply_now(self, action) -> None:
        if self._loading:
            return
        self._begin_edit()
        action()
        self.changed.emit()
        self._finish_edit()

    def _guard_live(self, item, action) -> None:
        if self._loading:
            return
        self._begin_edit()
        try:
            action()
        except ValueError as exc:
            # Nichts angewandt: den Schnappschuss nicht offen stehen lassen.
            self._finish_edit()
            self.rejected.emit(str(exc))
        else:
            self.changed.emit()

    def _guard_now(self, item, action) -> None:
        if self._loading:
            return
        self._begin_edit()
        try:
            action()
        except ValueError as exc:
            # Ungueltig (z. B. Buchstaben in EAN, zu lang fuer EAN-8): nichts
            # geaendert - der Benutzer erfaehrt warum. Trotzdem abschliessen,
            # damit der Undo-Schnappschuss nicht offen bleibt.
            self._finish_edit()
            self.rejected.emit(str(exc))
            # Feld wieder auf den gueltigen Wert - verzoegert, weil der
            # Aufruf aus dem Signal genau dieses Feldes kommt.
            QTimer.singleShot(0, self._rebuild_if_same(item))
            return
        self.changed.emit()
        self._finish_edit()

    def _rebuild_if_same(self, item):
        """Neu aufbauen, sofern inzwischen kein anderes Objekt gewaehlt ist."""

        def rebuild() -> None:
            if self._item is item:
                self._rebuild()

        return rebuild


_KIND_TITLES = {
    "text": "Text",
    "image": "Bild",
    "barcode": "Barcode",
    "qr": "QR-Code",
    "line": "Linie",
    "rect": "Rahmen",
    "shape": "Form",
}


__all__ = ["InspectorPanel", "BARCODE_SYMBOLOGIES"]
