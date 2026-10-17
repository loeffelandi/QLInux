"""Media-Panel (Vorbild: P-touch Editor "Paper"-Tab).

Bandauswahl, Laenge (auto/fest, Gesamt- oder Inhaltsmass), Margins in mm,
Farbe (schwarz / schwarz-rot) und Drucker-Einstellungen.

Das Panel ist die einzige Stelle, an der die Band-/Laengen-Parameter gesetzt
werden. Es emittiert :attr:`changed`, sobald sich die Konfiguration aendert;
das Hauptfenster liest dann die Werte ueber die Getter aus.

Alle Masse kommen dynamisch aus :mod:`ql_editor.media` - keine Magic Numbers.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import media
from .icons import icon
from .media import (
    DEFAULT_MODEL,
    LabelSpec,
    LengthMode,
    Margins,
    ModelSpec,
    Orientation,
)
from .printer import ADDRESS_EXAMPLES, DEFAULT_ADDRESS, backend_for_address, backend_supports_readback


class MediaPanel(QWidget):
    """Bedienfeld fuer Band, Laenge, Margins, Farbe und Drucker."""

    changed = Signal()
    detect_requested = Signal()
    usb_search_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Ausrichtung ist eine Dokument-Eigenschaft (Bedienelement liegt in der
        # Toolbar, damit sie ohne Panel-Gefummel erreichbar ist); das Panel
        # haelt den Zustand und ist damit die einzige Quelle der Wahrheit.
        self._orientation = Orientation.ACROSS
        # Aktuelle Inhaltslaenge in Bandrichtung - nur fuer die Ergebnis-Anzeige;
        # das Hauptfenster meldet sie nach jeder Neuberechnung.
        self._content_dots = 0
        self._build_ui()
        self._populate_models()
        self._populate_bands()
        self._sync_enabled()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        # -- Drucker --------------------------------------------------------
        printer_box = QGroupBox("Drucker")
        printer_form = QFormLayout(printer_box)
        printer_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        printer_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._model_combo = QComboBox()
        self._address_edit = QLineEdit(DEFAULT_ADDRESS)
        self._address_edit.setToolTip(
            "Ein Feld für alle Anschlüsse - das Backend wird aus der Adresse "
            "abgeleitet:\n"
            f"  {ADDRESS_EXAMPLES[0]}   Netzwerk (TCP 9100)\n"
            f"  {ADDRESS_EXAMPLES[1]}        USB über libusb (pyusb)\n"
            f"  {ADDRESS_EXAMPLES[2]}               USB über den Kernel-Treiber"
        )
        # Zeigt, was aus der Adresse folgt - vor allem, ob der Anschluss einen
        # Rueckkanal hat (nur dann geht die Band-Erkennung).
        self._backend_label = QLabel()
        self._backend_label.setWordWrap(True)
        self._backend_label.setStyleSheet("color:#777;")
        self._detect_button = QPushButton(icon("detect"), "Band erkennen")
        self._detect_button.setToolTip(
            "Band am Drucker erfragen (Statusabfrage).\n"
            "Geht nur über USB: der Netzwerk-Anschluss (TCP 9100) ist eine reine "
            "Druckschnittstelle und antwortet nicht."
        )
        self._usb_button = QPushButton(icon("detect"), "USB suchen")
        self._usb_button.setToolTip(
            "Angeschlossene USB-Drucker suchen und die Adresse eintragen."
        )
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self._detect_button, 1)
        buttons.addWidget(self._usb_button, 1)
        printer_form.addRow("Modell", self._model_combo)
        printer_form.addRow("Adresse", self._address_edit)
        printer_form.addRow("", self._backend_label)
        printer_form.addRow("", buttons)
        outer.addWidget(printer_box)

        # -- Band -----------------------------------------------------------
        media_box = QGroupBox("Band")
        media_form = QFormLayout(media_box)
        media_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        media_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._band_combo = QComboBox()
        self._color_combo = QComboBox()
        self._color_combo.addItem("schwarz", "black")
        self._color_combo.addItem("schwarz/rot", "red")
        self._border_label = QLabel("-")
        self._border_label.setWordWrap(True)
        self._orientation_label = QLabel("-")
        media_form.addRow("Band", self._band_combo)
        media_form.addRow("Farbe", self._color_combo)
        media_form.addRow("Ausrichtung", self._build_orientation_row())
        media_form.addRow("Nicht bedruckbar", self._border_label)
        outer.addWidget(media_box)

        # -- Laenge ---------------------------------------------------------
        length_box = QGroupBox("Laenge")
        length_form = QFormLayout(length_box)
        length_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        length_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._auto_check = QCheckBox("Auto Length (Inhalt)")
        self._auto_check.setChecked(True)
        self._length_spin = QDoubleSpinBox()
        self._length_spin.setSuffix(" mm")
        self._length_spin.setDecimals(1)
        self._length_spin.setRange(1.0, 1000.0)
        self._length_spin.setValue(40.0)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Gesamtlänge (inkl. Rand)", LengthMode.FINISHED.value)
        self._mode_combo.addItem("nur Inhalt", LengthMode.CONTENT.value)
        self._size_label = QLabel("-")
        self._size_label.setStyleSheet("color:#444;")
        length_form.addRow(self._auto_check)
        length_form.addRow("Länge", self._length_spin)
        length_form.addRow("Bedeutung", self._mode_combo)
        length_form.addRow("Ergebnis", self._size_label)
        outer.addWidget(length_box)

        # -- Margins --------------------------------------------------------
        margin_box = QGroupBox("Margins (mm)")
        margin_form = QFormLayout(margin_box)
        margin_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        margin_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._margin_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (("left", "links"), ("right", "rechts"), ("top", "oben"), ("bottom", "unten")):
            spin = QDoubleSpinBox()
            spin.setSuffix(" mm")
            spin.setDecimals(1)
            spin.setRange(0.0, 200.0)
            spin.setSingleStep(0.5)
            self._margin_spins[key] = spin
            margin_form.addRow(label, spin)
        outer.addWidget(margin_box)
        outer.addStretch(1)

        # -- Signale --------------------------------------------------------
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._band_combo.currentIndexChanged.connect(self._on_band_changed)
        self._color_combo.currentIndexChanged.connect(self._on_media_changed)
        self._auto_check.toggled.connect(self._on_media_changed)
        self._length_spin.valueChanged.connect(self._on_media_changed)
        self._mode_combo.currentIndexChanged.connect(self._on_media_changed)
        for spin in self._margin_spins.values():
            spin.valueChanged.connect(self._on_media_changed)
        self._detect_button.clicked.connect(self.detect_requested.emit)
        self._usb_button.clicked.connect(self.usb_search_requested.emit)
        self._address_edit.textChanged.connect(self._on_address_changed)
        self._sync_backend_label()

    def _build_orientation_row(self) -> QWidget:
        """Zwei Umschaltknoepfe (quer / laengs) fuer die Ausrichtung.

        Die Aktionen gehoeren dem Panel (es ist die Quelle der Wahrheit) und
        werden von Toolbar und Menue mitbenutzt - so bleiben Icon, Tooltip und
        Haekchen ueberall automatisch synchron.
        """
        self._act_orient_across = QAction(icon("orient_across"), "Quer zum Band", self)
        self._act_orient_across.setCheckable(True)
        self._act_orient_across.setChecked(True)
        self._act_orient_across.setToolTip(
            "Ausrichtung: quer zum Band\n"
            "Der Inhalt läuft über die Bandbreite; die Länge ergibt sich aus der "
            "Inhaltshöhe (spart Band bei langen, flachen Inhalten)."
        )
        self._act_orient_along = QAction(icon("orient_along"), "Längs des Bandes", self)
        self._act_orient_along.setCheckable(True)
        self._act_orient_along.setToolTip(
            "Ausrichtung: längs des Bandes\n"
            "Der Inhalt läuft in Bandrichtung; die Länge ergibt sich aus der "
            "Inhaltsbreite (spart Band bei hohen, mehrzeiligen Inhalten)."
        )
        self._orientation_group = QActionGroup(self)
        self._orientation_group.setExclusive(True)
        for action, orientation in (
            (self._act_orient_across, Orientation.ACROSS),
            (self._act_orient_along, Orientation.ALONG),
        ):
            self._orientation_group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, value=orientation: self.set_orientation(value)
            )

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._orientation_buttons: list[QToolButton] = []
        for action in (self._act_orient_across, self._act_orient_along):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setIconSize(QSize(20, 20))
            button.setMinimumSize(38, 26)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            layout.addWidget(button)
            self._orientation_buttons.append(button)
        layout.addWidget(self._orientation_label, 1)
        return row

    def orientation_actions(self) -> tuple[QAction, QAction]:
        """Die beiden Ausrichtungs-Aktionen (fuer Toolbar und Menue)."""
        return self._act_orient_across, self._act_orient_along

    # --------------------------------------------------------------- Daten --
    def _populate_models(self) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in media.all_models():
            self._model_combo.addItem(model.identifier, model.identifier)
        index = self._model_combo.findData(DEFAULT_MODEL)
        self._model_combo.setCurrentIndex(index if index >= 0 else 0)
        self._model_combo.blockSignals(False)

    def _populate_bands(self) -> None:
        current = self._band_combo.currentData()
        if current is None:
            current = media.DEFAULT_LABEL
        self._band_combo.blockSignals(True)
        self._band_combo.clear()
        for label in media.labels_for_model(self.model_id()):
            self._band_combo.addItem(label.display_name, label.identifier)
        # Vorherige Auswahl beibehalten, sonst erstes Band.
        index = self._band_combo.findData(current)
        self._band_combo.setCurrentIndex(index if index >= 0 else 0)
        self._band_combo.blockSignals(False)
        self._on_band_changed()

    # ----------------------------------------------------------- Getter ----
    def model_id(self) -> str:
        return self._model_combo.currentData() or DEFAULT_MODEL

    @property
    def model(self) -> ModelSpec:
        return media.get_model(self.model_id())

    def address(self) -> str:
        return self._address_edit.text().strip() or DEFAULT_ADDRESS

    def label_id(self) -> str:
        return self._band_combo.currentData()

    @property
    def label(self) -> LabelSpec:
        return media.get_label(self.label_id())

    def auto_length(self) -> bool:
        return self._auto_check.isChecked()

    def length_mm(self) -> float:
        return self._length_spin.value()

    def length_mode(self) -> LengthMode:
        return LengthMode(self._mode_combo.currentData())

    def orientation(self) -> Orientation:
        return self._orientation

    def set_orientation(self, orientation: Orientation | str) -> None:
        """Ausrichtung setzen (loest bei Aenderung :attr:`changed` aus)."""
        orientation = Orientation(orientation)
        if orientation is self._orientation:
            self._sync_orientation_actions()
            return
        self._orientation = orientation
        self._sync_orientation_actions()
        self._sync_enabled()
        self.changed.emit()

    def _sync_orientation_actions(self) -> None:
        along = self._orientation is Orientation.ALONG
        self._act_orient_along.setChecked(along)
        self._act_orient_across.setChecked(not along)

    def margins(self) -> Margins:
        return Margins(
            left=self._margin_spins["left"].value(),
            right=self._margin_spins["right"].value(),
            top=self._margin_spins["top"].value(),
            bottom=self._margin_spins["bottom"].value(),
        )

    def use_red(self) -> bool:
        return self._color_combo.currentData() == "red"

    def canvas_size(self, content_length_dots: int = 0) -> tuple[int, int]:
        return media.canvas_size_dots(
            self.label,
            self.model,
            auto_length=self.auto_length(),
            fixed_length_mm=self.length_mm(),
            content_length_dots=content_length_dots,
            length_mode=self.length_mode(),
            orientation=self._orientation,
        )

    def label_length_dots(self, content_length_dots: int = 0) -> int:
        """Etikettenlaenge in Bandrichtung (Dots) - unabhaengig von der Ausrichtung."""
        return media.label_length_dots(
            self.label,
            self.model,
            auto_length=self.auto_length(),
            fixed_length_mm=self.length_mm(),
            content_length_dots=content_length_dots,
            length_mode=self.length_mode(),
        )

    def printer_config(self):
        from .printer import PrinterConfig

        return PrinterConfig(model=self.model_id(), address=self.address())

    # ----------------------------------------------------------- Setter ----
    def select_label(self, label_id: str) -> bool:
        index = self._band_combo.findData(label_id)
        if index < 0:
            return False
        self._band_combo.setCurrentIndex(index)
        return True

    def set_address(self, address: str) -> None:
        """Druckeradresse setzen (loest bei Aenderung :attr:`changed` aus)."""
        if address and address != self._address_edit.text():
            self._address_edit.setText(address)

    def apply_label_defaults(self, label: LabelSpec) -> None:
        """Setze Margin-Startwerte aus ``feed_margin`` des Bandes."""
        margins = label.default_margins()
        for key, value in margins.as_dict().items():
            spin = self._margin_spins[key]
            spin.blockSignals(True)
            spin.setValue(round(value, 1))
            spin.blockSignals(False)

    def set_content_dots(self, content_dots: int) -> None:
        """Aktuelle Inhaltslaenge (Dots, Bandrichtung) fuer die Ergebnis-Anzeige.

        Aendert nur die Darstellung - es wird bewusst **kein** :attr:`changed`
        emittiert (sonst Rueckkopplung mit der Neuberechnung des Canvas).
        """
        content_dots = max(0, int(content_dots))
        if content_dots == self._content_dots:
            return
        self._content_dots = content_dots
        self._update_result()

    # ----------------------------------------------------------- Slots -----
    def _on_address_changed(self) -> None:
        """Adresse getippt: Backend-Hinweis nachziehen und Aenderung melden."""
        self._sync_backend_label()
        self.changed.emit()

    def _sync_backend_label(self) -> None:
        """Zeigen, welches Backend die Adresse ergibt - und ob es antwortet."""
        backend = backend_for_address(self.address())
        names = {
            "network": "Netzwerk (TCP 9100)",
            "pyusb": "USB (libusb)",
            "linux_kernel": "USB (Kernel-Treiber)",
        }
        name = names.get(backend, backend)
        if backend_supports_readback(backend):
            text = f"{name} – Statusabfrage möglich (Band erkennen)."
        else:
            text = f"{name} – kein Status: Band bitte von Hand wählen."
        self._backend_label.setText(text)

    def _on_model_changed(self) -> None:
        self._populate_bands()
        self._sync_enabled()
        self.changed.emit()

    def _on_band_changed(self) -> None:
        # Margin-Startwerte aus feed_margin des neuen Bandes uebernehmen.
        self.apply_label_defaults(self.label)
        self._on_media_changed()

    def _on_media_changed(self) -> None:
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self) -> None:
        auto = self._auto_check.isChecked()
        self._length_spin.setEnabled(not auto)
        self._mode_combo.setEnabled(not auto)

        label = self.label
        # Rot nur bei Zwei-Farb-Modell UND farbigem Band.
        red_possible = self.model.two_color and label.color.supports_red
        self._color_combo.setEnabled(red_possible)
        if not red_possible and self._color_combo.currentData() == "red":
            self._color_combo.setCurrentIndex(0)

        self._border_label.setText(
            f"{label.side_border_mm:.2f} mm je Seite (schraffiert)"
        )
        self._orientation_label.setText(self._orientation.label_de)
        self._update_result()

    def _update_result(self) -> None:
        """Zeige Designflaeche und fertige Etikettenlaenge (mit echter Inhaltslaenge)."""
        label = self.label
        length = self.label_length_dots(self._content_dots)
        width, height = self.canvas_size(self._content_dots)
        total = (
            media.finished_length_mm(label, length)
            if label.is_endless
            else media.dots_to_mm(length)
        )
        self._size_label.setText(
            f"{media.dots_to_mm(width):.1f} x {media.dots_to_mm(height):.1f} mm Inhalt\n"
            f"→ Etikett ~{total:.1f} mm"
        )


__all__ = ["MediaPanel"]
