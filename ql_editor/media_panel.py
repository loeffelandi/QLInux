"""Media-Panel (Vorbild: P-touch Editor "Paper"-Tab).

Bandauswahl, Laenge (auto/fest, Gesamt- oder Inhaltsmass), Margins in mm,
Farbe (schwarz / schwarz-rot) und Drucker-Einstellungen.

Das Panel ist die einzige Stelle, an der die Band-/Laengen-Parameter gesetzt
werden. Es emittiert :attr:`changed`, sobald sich die Konfiguration aendert;
das Hauptfenster liest dann die Werte ueber die Getter aus.

Alle Masse kommen dynamisch aus :mod:`ql_editor.media` - keine Magic Numbers.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import media
from .icons import icon
from .media import DEFAULT_MODEL, LabelSpec, LengthMode, Margins, ModelSpec
from .printer import DEFAULT_ADDRESS


class MediaPanel(QWidget):
    """Bedienfeld fuer Band, Laenge, Margins, Farbe und Drucker."""

    changed = Signal()
    detect_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
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
        self._detect_button = QPushButton(icon("detect"), "Band erkennen")
        self._detect_button.setToolTip("Band am Drucker erkennen (Statusabfrage)")
        printer_form.addRow("Modell", self._model_combo)
        printer_form.addRow("Adresse", self._address_edit)
        printer_form.addRow("", self._detect_button)
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
        media_form.addRow("Band", self._band_combo)
        media_form.addRow("Farbe", self._color_combo)
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

    def apply_label_defaults(self, label: LabelSpec) -> None:
        """Setze Margin-Startwerte aus ``feed_margin`` des Bandes."""
        margins = label.default_margins()
        for key, value in margins.as_dict().items():
            spin = self._margin_spins[key]
            spin.blockSignals(True)
            spin.setValue(round(value, 1))
            spin.blockSignals(False)

    # ----------------------------------------------------------- Slots -----
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
        width, height = self.canvas_size()
        total = media.finished_length_mm(label, height) if label.is_endless else media.dots_to_mm(height)
        self._size_label.setText(
            f"{media.dots_to_mm(width):.1f} x {media.dots_to_mm(height):.1f} mm Inhalt\n"
            f"→ Etikett ~{total:.1f} mm"
        )


__all__ = ["MediaPanel"]
