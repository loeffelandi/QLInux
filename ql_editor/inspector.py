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

from PySide6.QtCore import QDate, QEvent, QSize, QTime, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .datetime_text import (
    DATE_FORMATS,
    OFFSET_UNITS,
    TIME_FORMATS,
    format_date,
    format_time,
    unit_label,
)
from .i18n import tr
from .icons import icon
from .items import (
    FILL_CHOICES,
    LINE_STYLE_CHOICES,
    fill_label,
    line_style_label,
)
from .sheet import show_widget
from .symbols import SymbolPicker, symbol_label
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
        #: Letzte Registerkarte im Tabellen-Inspector (Text / Zelle / Tabelle).
        self._table_page = 0
        self._datetime_example_item = None
        self._datetime_example_refresh = None

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
        self._detach_datetime_examples()
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
            "table": self._build_table,
            "datetime": self._build_datetime,
            "clipart": self._build_clipart,
        }.get(kind)
        if builder is not None:
            builder(item, form)

        self._build_common(item, form)
        self._root.addWidget(body)
        # addWidget zeigt das neue Formular nicht immer (z. B. nach
        # Zellenwechsel). Versteckt bliebe der Inspector sonst leer.
        body.show()
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
        form.addRow(self._check(tr("Breite automatisch"), item.auto_width, item.set_auto_width))
        form.addRow(self._check(tr("Umbruch"), item.wrap, item.set_wrap))
        form.addRow(self._check(tr("Höhe automatisch"), item.auto_height, item.set_auto_height))

    # -- Textleiste (Symbol-Knoepfe) -----------------------------------------
    def _bar(self, *widgets: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addStretch(1)
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

    def _color_menu_button(self, tip: str, current, apply_fn) -> QToolButton:
        """„A“-Knopf: Menue mit Schwarz/Rot. ``current`` ist None bei Mischauswahl."""
        button = QToolButton()
        button.setText("A")
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        group = QActionGroup(menu)
        for label, value in ((tr("schwarz"), "black"), (tr("rot"), "red")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(current == value)
            group.addAction(act)
            act.triggered.connect(
                lambda _=False, v=value: self._apply_now(lambda: apply_fn(v))
            )
        button.setMenu(menu)
        return button

    def _color_button(self, item) -> QToolButton:
        """„A“-Knopf wie in Textverarbeitungen: Menue mit Schwarz/Rot."""
        return self._color_menu_button(tr("Farbe"), item.color, item.set_text_color)

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

    def _build_datetime(self, item, form: QFormLayout) -> None:
        """Format, aktuelle oder feste Zeit, Versatz. Die Liste zeigt Beispiele."""
        self._loading = True
        try:
            mode = QComboBox()
            mode.addItem(tr("Datum"), "date")
            mode.addItem(tr("Uhrzeit"), "time")
            mode.addItem(tr("Beides"), "both")
            mode.setCurrentIndex(max(0, mode.findData(item.mode)))

            date_format = QComboBox()
            time_format = QComboBox()
            unit = QComboBox()
            for key in OFFSET_UNITS:
                unit.addItem(unit_label(key), key)
            unit.setCurrentIndex(max(0, unit.findData(item.offset_unit)))

            direction = QComboBox()
            direction.addItem(tr("Nach"), "after")
            direction.addItem(tr("Vor"), "before")
            direction.setCurrentIndex(1 if item.offset < 0 else 0)

            amount = QSpinBox()
            amount.setRange(0, 9999)
            amount.setValue(abs(item.offset))

            live = QCheckBox(tr("Aktuell"))
            live.setToolTip(
                tr("Zeigt die jetzige Zeit und übernimmt sie auch beim Drucken.")
            )
            live.setChecked(item.live)

            fixed = item.fixed
            date_edit = QDateEdit(QDate(fixed.year, fixed.month, fixed.day))
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("dd.MM.yyyy")
            time_edit = QTimeEdit(QTime(fixed.hour, fixed.minute, fixed.second))
            time_edit.setDisplayFormat("HH:mm")

            def refresh_examples() -> None:
                if self._loading:
                    return
                moment = item.moment()
                self._loading = True
                try:
                    for index, key in enumerate(DATE_FORMATS):
                        date_format.setItemText(index, format_date(moment, key))
                    for index, key in enumerate(TIME_FORMATS):
                        time_format.setItemText(index, format_time(moment, key))
                finally:
                    self._loading = False

            def fill_formats() -> None:
                moment = item.moment()
                for key in DATE_FORMATS:
                    date_format.addItem(format_date(moment, key), key)
                for key in TIME_FORMATS:
                    time_format.addItem(format_time(moment, key), key)
                date_format.setCurrentIndex(max(0, date_format.findData(item.date_format)))
                time_format.setCurrentIndex(max(0, time_format.findData(item.time_format)))

            def sync_enabled() -> None:
                has_date = item.mode in ("date", "both")
                has_time = item.mode in ("time", "both")
                date_format.setEnabled(has_date)
                time_format.setEnabled(has_time)
                date_edit.setEnabled(has_date and not item.live)
                time_edit.setEnabled(has_time and not item.live)

            def sync_fixed_editors() -> None:
                current = item.fixed
                self._loading = True
                try:
                    date_edit.setDate(QDate(current.year, current.month, current.day))
                    time_edit.setTime(QTime(current.hour, current.minute, current.second))
                    direction.setCurrentIndex(1 if item.offset < 0 else 0)
                    amount.setValue(abs(item.offset))
                finally:
                    self._loading = False

            fill_formats()
            sync_enabled()

            def apply_mode() -> None:
                if self._loading:
                    return
                self._apply_now(lambda: item.set_mode(mode.currentData()))
                sync_enabled()
                refresh_examples()

            def apply_offset(*, commit: bool) -> None:
                if self._loading:
                    return
                sign = -1 if direction.currentData() == "before" else 1
                chosen = sign * amount.value()
                action = self._apply_now if commit else self._apply_live
                action(lambda: item.set_offset(chosen, unit.currentData()))
                refresh_examples()

            def apply_live(checked: bool) -> None:
                if self._loading:
                    return
                self._apply_now(lambda: item.set_live(checked))
                sync_fixed_editors()
                sync_enabled()
                refresh_examples()

            def apply_date(qdate: QDate) -> None:
                if self._loading:
                    return

                def apply() -> None:
                    current = item.fixed
                    item.set_fixed(
                        current.replace(year=qdate.year(), month=qdate.month(), day=qdate.day())
                    )

                self._apply_now(apply)
                refresh_examples()

            def apply_time(qtime: QTime) -> None:
                if self._loading:
                    return

                def apply() -> None:
                    current = item.fixed
                    item.set_fixed(
                        current.replace(
                            hour=qtime.hour(), minute=qtime.minute(), second=qtime.second()
                        )
                    )

                self._apply_now(apply)
                refresh_examples()

            def apply_date_format() -> None:
                if self._loading:
                    return
                self._apply_now(lambda: item.set_date_format(date_format.currentData()))
                refresh_examples()

            def apply_time_format() -> None:
                if self._loading:
                    return
                self._apply_now(lambda: item.set_time_format(time_format.currentData()))
                refresh_examples()

            mode.currentIndexChanged.connect(apply_mode)
            date_format.currentIndexChanged.connect(apply_date_format)
            time_format.currentIndexChanged.connect(apply_time_format)
            live.toggled.connect(apply_live)
            date_edit.dateChanged.connect(apply_date)
            time_edit.timeChanged.connect(apply_time)
            amount.valueChanged.connect(lambda: apply_offset(commit=False))
            amount.editingFinished.connect(self._finish_edit)
            direction.currentIndexChanged.connect(lambda: apply_offset(commit=True))
            unit.currentIndexChanged.connect(lambda: apply_offset(commit=True))
            self._attach_datetime_examples(item, refresh_examples)

            form.addRow(tr("Anzeige"), mode)
            form.addRow(tr("Datumsformat"), date_format)
            form.addRow(tr("Uhrzeitformat"), time_format)
            form.addRow("", live)
            form.addRow(tr("Datum"), date_edit)
            form.addRow(tr("Uhrzeit"), time_edit)

            offset_row = QWidget()
            offset_layout = QHBoxLayout(offset_row)
            offset_layout.setContentsMargins(0, 0, 0, 0)
            offset_layout.addWidget(amount)
            offset_layout.addWidget(direction)
            offset_layout.addWidget(unit)
            form.addRow(tr("Versatz"), offset_row)
        finally:
            self._loading = False

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

        bold = QCheckBox(tr("Fett"))
        bold.setChecked(item.bold)
        bold.toggled.connect(lambda v: self._apply_now(lambda: item.set_bold(v)))
        form.addRow("", bold)

        italic = QCheckBox(tr("Kursiv"))
        italic.setChecked(item.italic)
        italic.toggled.connect(lambda v: self._apply_now(lambda: item.set_italic(v)))
        form.addRow("", italic)

        color = QComboBox()
        color.addItem(tr("schwarz"), "black")
        color.addItem(tr("rot"), "red")
        color.setCurrentIndex(0 if item.color == "black" else 1)
        color.setEnabled(self._allow_red)
        color.currentIndexChanged.connect(
            lambda: self._apply_now(lambda: item.set_text_color(color.currentData()))
        )
        form.addRow(tr("Farbe"), color)

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

    def _build_table(self, item, form: QFormLayout) -> None:
        """Drei Register wie im P-touch Editor: Text, Zelle, Tabelle."""
        self._loading = True
        try:
            tabs = QTabBar()
            tabs.setObjectName("table_inspector_tabs")
            tabs.setDocumentMode(True)
            tabs.setExpanding(True)
            tabs.setDrawBase(False)
            tabs.addTab(tr("Text"))
            tabs.addTab(tr("Zelle"))
            tabs.addTab(tr("Tabelle"))
            stack = QStackedWidget()
            for page in (
                self._table_text_page(item),
                self._table_cell_page(item),
                self._table_frame_page(item),
            ):
                stack.addWidget(page)
            count = tabs.count()
            index = 0 if count <= 0 else max(0, min(self._table_page, count - 1))
            self._table_page = index

            def show_page(page: int) -> None:
                # currentChanged(-1) beim Abbauen der alten Leiste nicht merken.
                if page < 0:
                    return
                self._table_page = page
                stack.setCurrentIndex(page)

            tabs.currentChanged.connect(show_page)
            if tabs.currentIndex() != index:
                tabs.setCurrentIndex(index)
            stack.setCurrentIndex(index)
            form.addRow(tabs)
            form.addRow(stack)
        finally:
            self._loading = False

    def _table_text_page(self, item) -> QWidget:
        """Dieselbe Textleiste wie beim freien Textfeld, auf die gewaehlten Zellen."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 8, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        same_text, text = item.selected_uniform("text")
        edit = QPlainTextEdit("" if not same_text else str(text or ""))
        edit.setFixedHeight(52)
        if not same_text:
            edit.setPlaceholderText(tr("Mehrere Zellen"))
        edit.textChanged.connect(
            lambda: self._apply_live(lambda: item.set_selected("text", edit.toPlainText()))
        )
        edit.installEventFilter(self)
        form.addRow(edit)

        same_font, family = item.selected_uniform("font_family")
        font_box = QFontComboBox()
        font_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        font_box.setMinimumContentsLength(8)
        if same_font and family:
            font_box.setCurrentFont(QFont(family))
        font_box.currentFontChanged.connect(
            lambda f: self._apply_now(lambda: item.set_selected("font_family", f.family()))
        )
        form.addRow(tr("Schrift"), font_box)

        _same_size, size_px = item.selected_uniform("font_pixel_size")
        size = QSpinBox()
        size.setRange(4, 2000)
        size.setValue(int(size_px or 28))
        self._wire_spin(size, lambda v: item.set_selected("font_pixel_size", v))
        form.addRow(tr("Größe (px)"), size)

        form.addRow(self._rule())
        style = [
            self._cell_toggle(item, "bold", "bold", tr("Fett")),
            self._cell_toggle(item, "italic", "italic", tr("Kursiv")),
            self._cell_toggle(item, "underline", "underline", tr("Unterstrichen")),
        ]
        if self._allow_red:
            style.extend((self._divider(), self._cell_color_button(item)))
        form.addRow(self._bar(*style))

        form.addRow(self._rule())
        form.addRow(
            tr("Textausrichtung"),
            self._cell_choice(
                item,
                "align",
                [
                    ("align_left", tr("Links"), "left"),
                    ("align_hcenter", tr("Mitte"), "center"),
                    ("align_right", tr("Rechts"), "right"),
                ],
            ),
        )
        form.addRow(
            tr("Vertikal ausrichten"),
            self._cell_choice(
                item,
                "valign",
                [
                    ("align_top", tr("Oben"), "top"),
                    ("align_vcenter", tr("Mitte"), "middle"),
                    ("align_bottom", tr("Unten"), "bottom"),
                ],
            ),
        )
        return page

    def _table_cell_page(self, item) -> QWidget:
        """Zelle: Verbindung, Masse, Fuellung."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 8, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(
            self._bar(
                self._icon_action(
                    "cells_merge",
                    tr("Zellen verbinden"),
                    item.merge_selected,
                    item.can_merge(),
                    tr("Umschalt-Klick markiert mehrere Zellen"),
                ),
                self._icon_action(
                    "cells_split",
                    tr("Verbindung aufheben"),
                    item.unmerge_selected,
                    item.can_unmerge(),
                ),
            )
        )
        _same_h, row_h = item.selected_row_height()
        height = QDoubleSpinBox()
        height.setRange(1.0, 500.0)
        height.setDecimals(1)
        height.setSuffix(" mm")
        height.setValue(dots_to_mm(row_h))
        self._wire_spin(height, lambda v: item.set_selected_row_height(mm_to_dots(v)))
        form.addRow(tr("Zeilenhöhe"), height)

        _same_w, col_w = item.selected_col_width()
        width = QDoubleSpinBox()
        width.setRange(1.0, 500.0)
        width.setDecimals(1)
        width.setSuffix(" mm")
        width.setValue(dots_to_mm(col_w))
        self._wire_spin(width, lambda v: item.set_selected_col_width(mm_to_dots(v)))
        form.addRow(tr("Spaltenbreite"), width)

        same_fill, fill_value = item.selected_uniform("fill")
        fill = QComboBox()
        for key in FILL_CHOICES:
            fill.addItem(fill_label(key), key)
        if same_fill:
            fill.setCurrentIndex(max(0, fill.findData(fill_value)))
        else:
            fill.setCurrentIndex(-1)
        fill.currentIndexChanged.connect(
            lambda: self._apply_now(lambda: item.set_selected("fill", fill.currentData()))
            if fill.currentIndex() >= 0
            else None
        )
        form.addRow(tr("Füllung"), fill)
        return page

    def _table_frame_page(self, item) -> QWidget:
        """Tabelle: Zeilen, Spalten, Linien."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 8, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(
            self._bar(
                self._icon_action("row_above", tr("Zeile darüber"), item.insert_row_above),
                self._icon_action("col_left", tr("Spalte links"), item.insert_column_left),
                self._divider(),
                self._icon_action(
                    "row_delete",
                    tr("Zeile löschen"),
                    item.delete_selected_rows,
                    item.can_delete_row(),
                ),
                self._icon_action(
                    "col_delete",
                    tr("Spalte löschen"),
                    item.delete_selected_columns,
                    item.can_delete_column(),
                ),
            )
        )
        form.addRow(
            self._bar(
                self._icon_action(
                    "distribute_heights",
                    tr("Höhen verteilen"),
                    item.distribute_selected_heights,
                    item.can_distribute_heights(),
                ),
                self._icon_action(
                    "distribute_widths",
                    tr("Breiten verteilen"),
                    item.distribute_selected_widths,
                    item.can_distribute_widths(),
                ),
            )
        )
        fixed = QCheckBox(tr("Feste Tabellengröße"))
        fixed.setToolTip(
            tr("Feste Größe: eine Spalte oder Zeile wächst auf Kosten der Nachbarn")
        )
        fixed.setChecked(item.fixed_size)
        fixed.toggled.connect(lambda v: self._apply_now(lambda: item.set_fixed_size(v)))
        form.addRow(fixed)

        line = QDoubleSpinBox()
        line.setRange(0.5, 40.0)
        line.setSuffix(" px")
        line.setValue(item.line_width)
        self._wire_spin(line, lambda v: item.set_line_width(v))
        form.addRow(tr("Linienbreite"), line)

        style = QComboBox()
        for key in LINE_STYLE_CHOICES:
            style.addItem(line_style_label(key), key)
        idx = style.findData(item.line_style)
        style.setCurrentIndex(idx if idx >= 0 else 0)
        style.currentIndexChanged.connect(
            lambda: self._apply_now(lambda: item.set_line_style(style.currentData()))
        )
        form.addRow(tr("Linienart"), style)
        return page

    def _cell_toggle(self, item, name: str, icon_name: str, tip: str) -> QToolButton:
        same, value = item.selected_uniform(name)
        button = self._toggle(
            icon_name,
            tip if same else tr("Mehrere Zellen"),
            bool(value) if same else False,
            lambda v, field=name: item.set_selected(field, v),
        )
        return button

    def _cell_choice(self, item, name: str, options) -> QWidget:
        same, value = item.selected_uniform(name)
        return self._choice(
            options,
            value if same else None,
            lambda chosen, field=name: item.set_selected(field, chosen),
        )

    def _cell_color_button(self, item) -> QToolButton:
        same, color_value = item.selected_uniform("color")
        return self._color_menu_button(
            tr("Farbe") if same else tr("Mehrere Zellen"),
            color_value if same else None,
            lambda value: item.set_selected("color", value),
        )

    def _icon_action(
        self,
        name: str,
        tip: str,
        fn,
        enabled: bool = True,
        extra_tip: str = "",
    ) -> QToolButton:
        """Symbolknopf ohne Beschriftung (Tabellenbefehle)."""
        button = QToolButton()
        button.setIcon(icon(name))
        button.setToolTip(tip if not extra_tip else f"{tip}\n{extra_tip}")
        button.setAutoRaise(True)
        button.setEnabled(enabled)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda _checked=False, call=fn: self._apply_now(call))
        return button

    def _build_clipart(self, item, form: QFormLayout) -> None:
        name = QLabel(symbol_label(item.symbol))
        swap = QPushButton(tr("Austauschen…"))
        swap.clicked.connect(lambda: self._pick_clipart(item, name))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(name, 1)
        row_layout.addWidget(swap)
        form.addRow(tr("Symbol"), row)

        color = QComboBox()
        color.addItem(tr("schwarz"), "black")
        color.addItem(tr("rot"), "red")
        color.setCurrentIndex(0 if item.color == "black" else 1)
        color.setEnabled(self._allow_red)
        color.currentIndexChanged.connect(
            lambda: self._apply_now(lambda: item.set_color(color.currentData()))
        )
        form.addRow(tr("Farbe"), color)

        aspect = QCheckBox(tr("Seitenverhältnis festhalten"))
        aspect.setChecked(item.keep_aspect)
        aspect.toggled.connect(lambda value: self._apply_now(lambda: item.set_keep_aspect(value)))
        form.addRow("", aspect)

    def _pick_clipart(self, item, name: QLabel) -> None:
        """Anderes Symbol aus demselben Raster wie beim Einfügen."""
        host = self.window()
        if host is None:
            return
        picker = SymbolPicker()
        sheet = show_widget(
            host,
            title=tr("Clip Art"),
            content=picker,
            max_size=QSize(560, 640),
        )

        def _picked(symbol_id: str) -> None:
            sheet.close_sheet()

            def _apply() -> None:
                item.set_symbol(symbol_id)
                name.setText(symbol_label(item.symbol))

            self._apply_now(_apply)

        picker.chosen.connect(_picked)

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

        y = QSpinBox()
        y.setRange(-10000, 10000)
        y.setValue(int(pos.y()))
        self._wire_spin(y, lambda v: item.setPos(item.pos().x(), v))

        xy_row = QWidget()
        xy_layout = QHBoxLayout(xy_row)
        xy_layout.setContentsMargins(0, 0, 0, 0)
        xy_layout.setSpacing(6)
        xy_layout.addWidget(QLabel(tr("X")))
        xy_layout.addWidget(x, 1)
        xy_layout.addWidget(QLabel(tr("Y")))
        xy_layout.addWidget(y, 1)
        form.addRow(xy_row)

        rot = QSpinBox()
        rot.setRange(-180, 180)
        rot.setSuffix(" °")
        rot.setValue(int(item.rotation()))
        self._wire_spin(rot, lambda v: item.setRotation(v))

        # Eigene Zeile, linksbuendig: die Formularspalte schiebt das Feld
        # sonst nach rechts und zieht es auf die Feldspalte auf.
        rot_row = QWidget()
        rot_layout = QHBoxLayout(rot_row)
        rot_layout.setContentsMargins(0, 0, 0, 0)
        rot_layout.setSpacing(6)
        rot_layout.addWidget(QLabel(tr("Drehung")))
        rot_layout.addWidget(rot)
        rot_layout.addStretch(1)
        form.addRow(rot_row)

    # -- Helpers ------------------------------------------------------------
    def _wire_spin(self, spin, apply_fn) -> None:
        spin.valueChanged.connect(lambda v: self._apply_live(lambda: apply_fn(v)))
        spin.editingFinished.connect(self._finish_edit)

    def _attach_datetime_examples(self, item, refresh) -> None:
        """Format-Beispiele bei Live-Ticks aktualisieren, solange das Panel sichtbar ist."""
        self._detach_datetime_examples()
        self._datetime_example_item = item
        self._datetime_example_refresh = refresh
        item.display_changed.connect(self._on_datetime_examples_tick)

    def _detach_datetime_examples(self) -> None:
        item = self._datetime_example_item
        if item is not None:
            try:
                item.display_changed.disconnect(self._on_datetime_examples_tick)
            except (RuntimeError, TypeError):
                pass
        self._datetime_example_item = None
        self._datetime_example_refresh = None

    def _on_datetime_examples_tick(self) -> None:
        refresh = self._datetime_example_refresh
        if refresh is not None:
            refresh()

    def eventFilter(self, watched, event):  # noqa: N802
        # Tabellen-Textfeld: FocusOut schliesst den Undo-Schritt (kein editingFinished).
        if event.type() == QEvent.Type.FocusOut:
            self._finish_edit()
        return super().eventFilter(watched, event)

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
    "table": "Tabelle",
    "datetime": "Datum/Uhrzeit",
    "clipart": "Clip Art",
}


__all__ = ["InspectorPanel", "BARCODE_SYMBOLOGIES"]
