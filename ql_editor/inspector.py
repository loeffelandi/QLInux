"""Inspector-Panel: kontextabhaengige Eigenschaften des ausgewaehlten Items.

Statt alles ueber Menues zu steuern, erscheinen die Eigenschaften direkt beim
Auswaehlen (wie in einer guten Desktop-App). Das Panel baut seine Steuerelemente
je nach Item-Typ neu auf und meldet Aenderungen ueber :attr:`changed`.

Das Panel kennt nur die oeffentlichen Setter der Items aus
:mod:`ql_editor.items` - keine Render- oder Drucklogik.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .media import dots_to_mm, mm_to_dots
from .widgets import install_wheel_guard_recursive

BARCODE_SYMBOLOGIES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"]


class InspectorPanel(QWidget):
    """Zeigt die Eigenschaften des aktuell ausgewaehlten Items."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._item = None
        self._allow_red = False
        self._loading = False

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(8, 8, 8, 8)
        self._root.setSpacing(6)
        self._title = QLabel("Nichts ausgewählt")
        self._title.setStyleSheet("font-weight:600; color:#333;")
        self._root.addWidget(self._title)
        self._root.addStretch(1)

    # --------------------------------------------------------------- API --
    def set_item(self, item, allow_red: bool = False) -> None:
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
            self._title.setText("Nichts ausgewählt")
            self._root.addStretch(1)
            return

        kind = getattr(item, "kind", "?")
        self._title.setText(_KIND_TITLES.get(kind, "Objekt"))

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
        }.get(kind)
        if builder is not None:
            builder(item, form)

        self._build_common(item, form)
        self._root.addWidget(body)
        self._root.addStretch(1)
        install_wheel_guard_recursive(body)

    # -- Typ-spezifisch -----------------------------------------------------
    def _build_text(self, item, form: QFormLayout) -> None:
        edit = QPlainTextEdit(item.text_value)
        edit.setFixedHeight(64)
        edit.textChanged.connect(lambda: self._apply(lambda: item.set_text_value(edit.toPlainText())))
        form.addRow("Text", edit)

        family = QFontComboBox()
        family.setCurrentFont(QFont(item.font_family))
        family.currentFontChanged.connect(lambda f: self._apply(lambda: item.set_font_family(f.family())))
        form.addRow("Schrift", family)

        size = QSpinBox()
        size.setRange(4, 2000)
        size.setValue(item.font_pixel_size)
        size.valueChanged.connect(lambda v: self._apply(lambda: item.set_font_pixel_size(v)))
        form.addRow("Größe (px)", size)

        bold = QCheckBox("Fett")
        bold.setChecked(item.bold)
        bold.toggled.connect(lambda v: self._apply(lambda: item.set_bold(v)))
        form.addRow("", bold)

        italic = QCheckBox("Kursiv")
        italic.setChecked(item.italic)
        italic.toggled.connect(lambda v: self._apply(lambda: item.set_italic(v)))
        form.addRow("", italic)

        color = QComboBox()
        color.addItem("schwarz", "black")
        color.addItem("rot", "red")
        color.setCurrentIndex(0 if item.color == "black" else 1)
        color.setEnabled(self._allow_red)
        color.currentIndexChanged.connect(lambda: self._apply(lambda: item.set_text_color(color.currentData())))
        form.addRow("Farbe", color)

    def _build_qr(self, item, form: QFormLayout) -> None:
        data = QLineEdit(item._data)
        data.editingFinished.connect(lambda: self._apply(lambda: item.set_data(data.text())))
        form.addRow("Inhalt", data)

        size = QSpinBox()
        size.setRange(20, 4000)
        size.setValue(item._size_dots)
        size.valueChanged.connect(lambda v: self._apply(lambda: item.set_size_dots(v)))
        form.addRow("Größe (Dots)", size)

    def _build_barcode(self, item, form: QFormLayout) -> None:
        value = QLineEdit(item.value)
        value.editingFinished.connect(lambda: self._guard(item, lambda: item.set_value(value.text())))
        form.addRow("Inhalt", value)

        sym = QComboBox()
        for name in BARCODE_SYMBOLOGIES:
            sym.addItem(name, name)
        idx = sym.findData(item.symbology)
        sym.setCurrentIndex(idx if idx >= 0 else 0)
        sym.currentIndexChanged.connect(lambda: self._guard(item, lambda: item.set_symbology(sym.currentData())))
        form.addRow("Symbologie", sym)

        show_text = QCheckBox("Klartext")
        show_text.setChecked(item._show_text)
        show_text.toggled.connect(lambda v: self._guard(item, lambda: item.set_show_text(v)))
        form.addRow("", show_text)

        height = QSpinBox()
        height.setRange(20, 2000)
        height.setValue(item._height_dots)
        height.valueChanged.connect(lambda v: self._guard(item, lambda: item.set_height_dots(v)))
        form.addRow("Höhe (Dots)", height)

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
            self._apply(lambda: item.apply_resize(w_dots, w_dots * ratio))
            sync(w_dots, w_dots * ratio)

        def resize_height(value: float) -> None:
            if self._loading:
                return
            h_dots = mm_to_dots(value)
            w_dots = h_dots / ratio if ratio > 0 else h_dots
            self._apply(lambda: item.apply_resize(w_dots, h_dots))
            sync(w_dots, h_dots)

        width.valueChanged.connect(resize_width)
        height.valueChanged.connect(resize_height)
        form.addRow("Breite", width)
        form.addRow("Höhe", height)

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
        width.valueChanged.connect(lambda v: self._apply(lambda: item.set_line_width(v)))
        form.addRow("Linienbreite", width)

    def _build_rect(self, item, form: QFormLayout) -> None:
        width = QDoubleSpinBox()
        width.setRange(0.5, 200.0)
        width.setSuffix(" px")
        width.setValue(item._width_px)
        width.valueChanged.connect(lambda v: self._apply(lambda: item.set_line_width(v)))
        form.addRow("Linienbreite", width)

        filled = QCheckBox("Gefüllt")
        filled.setChecked(item._filled)
        filled.toggled.connect(lambda v: self._apply(lambda: item.set_filled(v)))
        form.addRow("", filled)

    # -- Gemeinsam ----------------------------------------------------------
    def _build_common(self, item, form: QFormLayout) -> None:
        pos = item.pos()
        x = QSpinBox()
        x.setRange(-10000, 10000)
        x.setValue(int(pos.x()))
        x.valueChanged.connect(lambda v: self._apply(lambda: item.setPos(v, item.pos().y())))
        form.addRow("X (Dots)", x)

        y = QSpinBox()
        y.setRange(-10000, 10000)
        y.setValue(int(pos.y()))
        y.valueChanged.connect(lambda v: self._apply(lambda: item.setPos(item.pos().x(), v)))
        form.addRow("Y (Dots)", y)

        rot = QSpinBox()
        rot.setRange(-180, 180)
        rot.setSuffix(" °")
        rot.setValue(int(item.rotation()))
        rot.valueChanged.connect(lambda v: self._apply(lambda: item.setRotation(v)))
        form.addRow("Drehung", rot)

    # -- Helpers ------------------------------------------------------------
    def _apply(self, action) -> None:
        if self._loading:
            return
        action()
        self.changed.emit()

    def _guard(self, item, action) -> None:
        """Wie :meth:`_apply`, faengt aber ungueltige Barcode-Inhalte ab."""
        if self._loading:
            return
        try:
            action()
        except ValueError:
            # Ungueltiger Inhalt (z. B. Buchstaben in EAN): alten Zustand behalten.
            pass
        else:
            self.changed.emit()


_KIND_TITLES = {
    "text": "Text",
    "image": "Bild",
    "barcode": "Barcode",
    "qr": "QR-Code",
    "line": "Linie",
    "rect": "Rahmen",
}


__all__ = ["InspectorPanel", "BARCODE_SYMBOLOGIES"]
