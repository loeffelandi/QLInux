"""Media-Panel (Vorbild: P-touch Editor "Paper"-Tab).

Bandauswahl, Laenge (auto/fest, Gesamt- oder Inhaltsmass), Margins in mm,
Farbe (schwarz / schwarz-rot) und Drucker-Einstellungen.

Das Panel ist die einzige Stelle, an der die Band-/Laengen-Parameter gesetzt
werden. Es emittiert :attr:`changed`, sobald sich die Konfiguration aendert;
das Hauptfenster liest dann die Werte ueber die Getter aus.

Alle Masse kommen dynamisch aus :mod:`ql_editor.media` - keine Magic Numbers.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from PySide6.QtCore import QLocale, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QButtonGroup,
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
from .i18n import tr
from .icons import icon
from .media import (
    DEFAULT_MODEL,
    LabelSpec,
    LengthMode,
    Margins,
    ModelSpec,
    Orientation,
)
from .printer import (
    DEFAULT_ADDRESS,
    NETWORK_PORT,
    backend_for_address,
    backend_supports_readback,
    model_for_address,
    network_host,
    parse_network_address,
    preferred_usb_address,
    usb_access,
    usb_device_detail,
    usb_device_label,
    usb_device_labels,
    usb_printers,
)

#: Anschlussarten der Druckerauswahl. Die Werte entsprechen den Backend-Namen
#: (``network``) bzw. fassen die beiden USB-Backends zusammen.
CONNECTION_NETWORK = "network"
CONNECTION_USB = "usb"

def usb_placeholder() -> str:
    """Eintrag in der USB-Liste, solange kein Geraet gewaehlt ist (Datenwert leer)."""
    return tr("Bitte Gerät wählen")

logger = logging.getLogger(__name__)


class MediaPanel(QWidget):
    """Bedienfeld fuer Band, Laenge, Margins, Farbe und Drucker."""

    changed = Signal()
    detect_requested = Signal()
    usb_search_requested = Signal()
    usb_permission_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Ausrichtung ist eine Dokument-Eigenschaft (Bedienelement liegt in der
        # Toolbar, damit sie ohne Panel-Gefummel erreichbar ist); das Panel
        # haelt den Zustand und ist damit die einzige Quelle der Wahrheit.
        self._orientation = Orientation.ACROSS
        # Aktuelle Inhaltslaenge in Bandrichtung - nur fuer die Ergebnis-Anzeige;
        # das Hauptfenster meldet sie nach jeder Neuberechnung.
        self._content_dots = 0
        # Unterdrueckt Nebenwirkungen, waehrend Felder programmatisch gesetzt
        # werden (z. B. beim Laden der Einstellungen).
        self._adjusting = False
        # Rechte am gewaehlten USB-Geraet (True/False, None = unklar/kein USB).
        self.access_allowed: bool | None = None
        self._build_ui()
        self._populate_models()
        self._populate_bands()
        self._sync_enabled()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        # -- Drucker --------------------------------------------------------
        # Kein Adressfeld zum Auswendiglernen: erst den Anschluss waehlen
        # ("Netzwerk" braucht nur die IP, "USB" findet das Geraet selbst),
        # darunter erscheint nur das, was dazu noetig ist.
        printer_box = QGroupBox(tr("Drucker"))
        printer_form = QFormLayout(printer_box)
        printer_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        printer_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._printer_form = printer_form

        self._model_combo = QComboBox()

        self._conn_buttons: dict[str, QToolButton] = {}
        self._conn_group = QButtonGroup(self)
        self._conn_group.setExclusive(True)
        for mode, label, icon_name, tip in (
            (
                CONNECTION_NETWORK,
                tr("Netzwerk"),
                "network",
                tr(
                    "Drucker im Netzwerk (WLAN/LAN).\n"
                    "Es genügt die IP-Adresse - der Druckport "
                    "{port} wird automatisch ergänzt."
                ).format(port=NETWORK_PORT),
            ),
            (
                CONNECTION_USB,
                tr("USB"),
                "usb",
                tr(
                    "Drucker am USB-Kabel.\n"
                    "„Suchen“ liest die angeschlossenen Geräte ein; nur über USB "
                    "geht auch die Band-Erkennung."
                ),
            ),
        ):
            button = QToolButton()
            button.setCheckable(True)
            button.setText(label)
            button.setIcon(icon(icon_name))
            button.setIconSize(QSize(16, 16))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(tip)
            self._conn_group.addButton(button)
            self._conn_buttons[mode] = button

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("192.168.178.62")
        self._host_edit.setToolTip(
            tr(
                "IP-Adresse oder Name des Druckers, z. B. 192.168.178.62.\n"
                "Der Druckport {port} wird automatisch ergänzt; ein anderer "
                "Port geht als 192.168.178.62:9101."
            ).format(port=NETWORK_PORT)
        )

        self._usb_combo = QComboBox()
        self._usb_combo.setToolTip(
            tr("Angeschlossene USB-Drucker. Die Auswahl setzt Adresse und – wenn "
            "sie sich aus der USB-Kennung ableiten lässt – auch das Modell.")
        )
        self._usb_button = QPushButton(icon("detect"), tr("Suchen"))
        self._usb_button.setToolTip(
            tr("Angeschlossene USB-Drucker suchen und in die Liste eintragen.")
        )

        # Fehlende Rechte sind der haeufigste Grund, warum ein gefundener
        # Drucker nicht druckt. Das steht deshalb direkt hier - mit einem
        # Knopf, der die udev-Regel einrichtet (Passwort-Dialog des Systems).
        self._access_label = QLabel()
        self._access_label.setWordWrap(True)
        self._access_label.setStyleSheet("color:#b3261e;")
        self._access_button = QPushButton(icon("detect"), tr("Zugriff einrichten"))
        self._access_button.setToolTip(
            tr("Richtet eine udev-Regel ein, die den USB-Drucker für dich "
            "freigibt (das System fragt nach dem Passwort).")
        )

        # Band-Erkennung braucht einen Rueckkanal - den gibt es nur ueber USB.
        # Deshalb steht der Knopf nur dort (siehe _sync_connection_rows).
        self._detect_button = QPushButton(icon("detect"), tr("Band erkennen"))
        self._detect_button.setToolTip(
            tr("Band am Drucker erfragen (Statusabfrage).")
        )

        printer_form.addRow(tr("Modell"), self._model_combo)
        printer_form.addRow(tr("Anschluss"), self._build_connection_row())
        self._row_host = printer_form.rowCount()
        printer_form.addRow(tr("IP-Adresse"), self._host_edit)
        self._row_usb = printer_form.rowCount()
        printer_form.addRow(tr("USB"), self._build_usb_row())
        self._row_access = printer_form.rowCount()
        printer_form.addRow(tr("Zugriff"), self._build_access_row())
        self._row_detect = printer_form.rowCount()
        printer_form.addRow("", self._detect_button)
        outer.addWidget(printer_box)
        # Startzustand: Netzwerk mit der gespeicherten/Standardadresse. Die
        # USB-Liste wird erst bei Bedarf gefuellt (Anschlusswechsel/Suche) -
        # so fragt der Programmstart nicht ungefragt libusb ab.
        self._conn_buttons[CONNECTION_NETWORK].setChecked(True)
        self._host_edit.setText(network_host(DEFAULT_ADDRESS))
        self._sync_connection_rows()

        # -- Band -----------------------------------------------------------
        media_box = QGroupBox(tr("Band"))
        media_form = QFormLayout(media_box)
        media_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        media_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._band_combo = QComboBox()
        self._color_combo = QComboBox()
        self._color_combo.addItem(tr("schwarz"), "black")
        self._color_combo.addItem(tr("schwarz/rot"), "red")
        self._border_label = QLabel("-")
        self._border_label.setWordWrap(True)
        self._orientation_label = QLabel("-")
        media_form.addRow(tr("Band"), self._band_combo)
        media_form.addRow(tr("Farbe"), self._color_combo)
        media_form.addRow(tr("Ausrichtung"), self._build_orientation_row())
        media_form.addRow(tr("Nicht bedruckbar"), self._border_label)
        outer.addWidget(media_box)

        # -- Laenge ---------------------------------------------------------
        length_box = QGroupBox(tr("Laenge"))
        length_form = QFormLayout(length_box)
        length_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        length_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._auto_check = QCheckBox(tr("Auto Length (Inhalt)"))
        self._auto_check.setChecked(True)
        self._length_spin = QDoubleSpinBox()
        self._length_spin.setSuffix(" mm")
        self._length_spin.setDecimals(1)
        self._length_spin.setRange(1.0, 1000.0)
        self._length_spin.setValue(40.0)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem(tr("Gesamtlänge (inkl. Rand)"), LengthMode.FINISHED.value)
        self._mode_combo.addItem(tr("nur Inhalt"), LengthMode.CONTENT.value)
        self._size_label = QLabel("-")
        self._size_label.setStyleSheet("color:#444;")
        length_form.addRow(self._auto_check)
        length_form.addRow(tr("Länge"), self._length_spin)
        length_form.addRow(tr("Bedeutung"), self._mode_combo)
        length_form.addRow(tr("Ergebnis"), self._size_label)
        outer.addWidget(length_box)

        # -- Margins --------------------------------------------------------
        margin_box = QGroupBox(tr("Margins (mm)"))
        margin_form = QFormLayout(margin_box)
        margin_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        margin_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._margin_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (
            ("left", tr("links")),
            ("right", tr("rechts")),
            ("top", tr("oben")),
            ("bottom", tr("unten")),
        ):
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
        self._access_button.clicked.connect(self.usb_permission_requested.emit)
        self._host_edit.textChanged.connect(self._on_host_changed)
        self._usb_combo.currentIndexChanged.connect(self._on_usb_combo_changed)
        for mode, button in self._conn_buttons.items():
            button.toggled.connect(
                lambda checked, value=mode: self._on_connection_toggled(value, checked)
            )

    def _build_connection_row(self) -> QWidget:
        """Anschluss waehlen: Netzwerk oder USB (zwei Umschaltknoepfe)."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for mode in (CONNECTION_NETWORK, CONNECTION_USB):
            button = self._conn_buttons[mode]
            button.setMinimumSize(88, 26)
            layout.addWidget(button)
        layout.addStretch(1)
        return row

    def _build_usb_row(self) -> QWidget:
        """Gefundene USB-Drucker waehlen + Suche neu starten."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._usb_combo, 1)
        layout.addWidget(self._usb_button)
        return row

    def _build_access_row(self) -> QWidget:
        """Hinweis auf fehlende Rechte + Knopf zum Einrichten (nur bei Bedarf)."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._access_label, 1)
        layout.addWidget(self._access_button)
        return row

    def _build_orientation_row(self) -> QWidget:
        """Zwei Umschaltknoepfe (quer / laengs) fuer die Ausrichtung.

        Die Aktionen gehoeren dem Panel (es ist die Quelle der Wahrheit) und
        werden von Toolbar und Menue mitbenutzt - so bleiben Icon, Tooltip und
        Haekchen ueberall automatisch synchron.
        """
        self._act_orient_across = QAction(icon("orient_across"), tr("Quer zum Band"), self)
        self._act_orient_across.setCheckable(True)
        self._act_orient_across.setChecked(True)
        self._act_orient_across.setToolTip(
            tr("Ausrichtung: quer zum Band\n"
            "Der Inhalt läuft über die Bandbreite; die Länge ergibt sich aus der "
            "Inhaltshöhe (spart Band bei langen, flachen Inhalten).")
        )
        self._act_orient_along = QAction(icon("orient_along"), tr("Längs des Bandes"), self)
        self._act_orient_along.setCheckable(True)
        self._act_orient_along.setToolTip(
            tr("Ausrichtung: längs des Bandes\n"
            "Der Inhalt läuft in Bandrichtung; die Länge ergibt sich aus der "
            "Inhaltsbreite (spart Band bei hohen, mehrzeiligen Inhalten).")
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
        """Vollstaendige Adresse aus der aktuellen Auswahl (leer = nicht gewaehlt)."""
        if self.connection() == CONNECTION_NETWORK:
            return parse_network_address(self._host_edit.text())
        return self._usb_combo.currentData() or ""

    def connection(self) -> str:
        """Gewaehlter Anschluss (:data:`CONNECTION_NETWORK` / :data:`CONNECTION_USB`)."""
        return CONNECTION_USB if self._conn_buttons[CONNECTION_USB].isChecked() else CONNECTION_NETWORK

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

    # ------------------------------------------------- Zustand (Neuaufbau) --
    def state(self) -> dict[str, Any]:
        """Alles, was ein Neuaufbau der Oberflaeche braucht (Sprachwechsel).

        Adresse und Modell kommen mit, weil die Anzeigeform (IP bzw.
        USB-Listeneintrag) nicht aus den Einstellungen rekonstruierbar ist.
        """
        return {
            "connection": self.connection(),
            "host": self._host_edit.text(),
            "address": self.address(),
            "model": self.model_id(),
            "label": self.label_id(),
            "color": self._color_combo.currentData(),
            "auto_length": self._auto_check.isChecked(),
            "length_mm": self._length_spin.value(),
            "length_mode": self._mode_combo.currentData(),
            "margins": {key: spin.value() for key, spin in self._margin_spins.items()},
            "orientation": self._orientation.value,
        }

    def apply_state(self, state: Mapping[str, Any]) -> None:
        """Zustand aus :meth:`state` uebernehmen (nach einem Neuaufbau)."""
        address = str(state.get("address") or "")
        self._adjusting = True
        try:
            if address:
                self.set_address(address)
            else:
                # Keine Adresse: Anschluss und Feldinhalt genau so lassen.
                connection = str(state.get("connection") or CONNECTION_NETWORK)
                self._conn_buttons[connection].setChecked(True)
                self._host_edit.setText(str(state.get("host") or ""))
        finally:
            self._adjusting = False
        model = str(state.get("model") or "")
        index = self._model_combo.findData(model)
        if index >= 0:
            self._model_combo.setCurrentIndex(index)
        label = str(state.get("label") or "")
        if label:
            self.select_label(label)
        color = self._color_combo.findData(state.get("color"))
        if color >= 0:
            self._color_combo.setCurrentIndex(color)
        self._auto_check.setChecked(bool(state.get("auto_length", True)))
        self._length_spin.setValue(
            float(state.get("length_mm", self._length_spin.value()))
        )
        mode = self._mode_combo.findData(state.get("length_mode"))
        if mode >= 0:
            self._mode_combo.setCurrentIndex(mode)
        margins = state.get("margins") or {}
        for key, spin in self._margin_spins.items():
            if key in margins:
                spin.setValue(float(margins[key]))
        self.set_orientation(str(state.get("orientation") or Orientation.ACROSS.value))
        self._sync_connection_rows()
        self.changed.emit()

    # ----------------------------------------------------------- Setter ----
    def select_label(self, label_id: str) -> bool:
        index = self._band_combo.findData(label_id)
        if index < 0:
            return False
        self._band_combo.setCurrentIndex(index)
        return True

    def set_address(self, address: str) -> None:
        """Adresse uebernehmen - Anschluss, Feld und (falls ableitbar) Modell.

        Die Anzeigeform ist die einfache: im Netzwerk die IP (``host``), am USB
        der Listeneintrag. Alte ``tcp://…:9100``-Adressen aus den Einstellungen
        landen damit automatisch im passenden Feld.
        """
        address = (address or "").strip()
        if not address:
            return
        mode = (
            CONNECTION_NETWORK
            if backend_for_address(address) == "network"
            else CONNECTION_USB
        )
        self._adjusting = True
        try:
            self._conn_buttons[mode].setChecked(True)
            if mode == CONNECTION_NETWORK:
                self._host_edit.setText(network_host(address))
            else:
                index = self._ensure_usb_entry(address)
                self._usb_combo.setCurrentIndex(index)
        finally:
            self._adjusting = False
        self._apply_model_for_address(address)
        self._sync_connection_rows()
        self.changed.emit()

    def refresh_usb_devices(self, devices: list[str] | None = None) -> list[str]:
        """USB-Liste neu einlesen und die Auswahl fuellen.

        Ohne ``devices`` wird selbst gesucht (:func:`printer.usb_printers`):
        **ein** Eintrag pro Drucker, auch wenn er ueber Kernel und libusb
        auffindbar waere. ``devices`` erwartet bereits bevorzugte Adressen.
        Rueckgabe: die gefundenen Adressen - der Aufrufer kann damit melden,
        was los ist. Die aktuelle Auswahl bleibt erhalten; ein gerade nicht
        angeschlossenes Geraet bleibt als Eintrag stehen (so geht die
        gespeicherte Adresse nicht verloren).
        """
        if devices is None:
            try:
                devices = usb_printers()
            except Exception as exc:  # pragma: no cover - haengt an libusb
                logger.info("USB-Suche fehlgeschlagen: %s", exc)
                devices = []
        devices = [address for address in devices if address]
        current = preferred_usb_address(self._usb_combo.currentData() or "", devices)
        missing = current if current and current not in devices else ""
        apply_single = False

        self._usb_combo.blockSignals(True)
        try:
            self._usb_combo.clear()
            if not devices and not missing:
                self._usb_combo.addItem(tr("Kein USB-Drucker gefunden"), "")
            else:
                labels = usb_device_labels(devices)
                for address, label in zip(devices, labels):
                    self._usb_combo.addItem(label, address)
                    self._usb_combo.setItemData(
                        self._usb_combo.count() - 1,
                        usb_device_detail(address),
                        Qt.ItemDataRole.ToolTipRole,
                    )
                if missing:
                    self._usb_combo.addItem(
                        f"{usb_device_label(missing)} {tr('– nicht angeschlossen')}",
                        missing,
                    )
                if current:
                    self._usb_combo.setCurrentIndex(self._usb_combo.findData(current))
                elif len(devices) == 1:
                    # Genau ein Geraet: gleich auswaehlen.
                    self._usb_combo.setCurrentIndex(0)
                    apply_single = True
                else:
                    self._usb_combo.insertItem(0, usb_placeholder(), "")
                    self._usb_combo.setCurrentIndex(0)
        finally:
            self._usb_combo.blockSignals(False)

        if apply_single:
            self._apply_usb_selection()
        else:
            # Auch ohne neues Geraet: die Rechte koennen sich geaendert haben
            # (Regel eingerichtet, Drucker umgesteckt).
            self._sync_access()
        return list(devices)

    def refresh_access(self) -> bool | None:
        """Rechte am gewaehlten Geraet neu pruefen (z. B. nach dem Einrichten)."""
        self._sync_access()
        return self.access_allowed

    def select_usb_device(self, address: str) -> bool:
        """USB-Geraet auswaehlen und uebernehmen (Adresse + Modell).

        Schaltet dabei auf den USB-Anschluss - die Adresse gilt fuer alles.
        ``True``, wenn sich die Adresse geaendert hat.
        """
        address = (address or "").strip()
        if not address or address == self.address():
            return False
        index = self._ensure_usb_entry(address)
        self._adjusting = True
        try:
            self._conn_buttons[CONNECTION_USB].setChecked(True)
            self._usb_combo.setCurrentIndex(index)
        finally:
            self._adjusting = False
        self._apply_usb_selection()
        return True

    def set_model(self, model_id: str) -> bool:
        """Modell setzen (z. B. nach einer USB-Suche).

        ``False``, wenn das Modell unbekannt ist oder schon gewaehlt war - der
        Aufrufer muss also nicht selbst vergleichen. Ein Wechsel zieht die
        Bandliste nach und meldet :attr:`changed`.
        """
        index = self._model_combo.findData(model_id)
        if index < 0 or index == self._model_combo.currentIndex():
            return False
        self._model_combo.setCurrentIndex(index)
        return True

    # --------------------------------------------------------- Intern ----
    def _ensure_usb_entry(self, address: str) -> int:
        """Eintrag fuer ``address`` in der USB-Liste sicherstellen.

        Liefert den Index. Ein bereits gesetztes Geraet bleibt damit auch dann
        sichtbar, wenn es gerade nicht angeschlossen ist (z. B. beim Laden der
        Einstellungen); ein Platzhalter ohne Datenwert faellt dabei weg.
        """
        index = self._usb_combo.findData(address)
        if index >= 0:
            return index
        if self._usb_combo.count() == 1 and not self._usb_combo.itemData(0):
            self._usb_combo.clear()
        self._usb_combo.addItem(usb_device_label(address), address)
        self._usb_combo.setItemData(
            self._usb_combo.count() - 1,
            usb_device_detail(address),
            Qt.ItemDataRole.ToolTipRole,
        )
        return self._usb_combo.findData(address)

    def _apply_usb_selection(self) -> None:
        """Gewaehltes USB-Geraet uebernehmen - Modell zieht nach, wenn ableitbar."""
        self._apply_model_for_address(self._usb_combo.currentData() or "")
        self._sync_connection_rows()
        self.changed.emit()

    def _apply_model_for_address(self, address: str) -> bool:
        """Modell zur Adresse setzen, wenn die Kennung es verraet.

        Am USB kann ein anderes Modell haengen als gewaehlt (QL-700 statt
        QL-820NWB) - mit falschem Modell waere der Rasterauftrag falsch. Bei
        Netzwerkadressen gibt es nichts abzuleiten; dann bleibt die Wahl stehen.
        """
        model = model_for_address(address)
        return bool(model) and self.set_model(model)

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
    def _on_host_changed(self) -> None:
        """IP/Name getippt: Zeilen nachziehen und Aenderung melden."""
        if self._adjusting:
            return
        self._sync_connection_rows()
        self.changed.emit()

    def _on_usb_combo_changed(self) -> None:
        """Nutzer hat ein USB-Geraet gewaehlt."""
        if self._adjusting:
            return
        self._apply_usb_selection()

    def _on_connection_toggled(self, mode: str, checked: bool) -> None:
        """Anschluss umgeschaltet (nur der aktive Knopf meldet ``checked``)."""
        if not checked:
            return
        if self._adjusting:
            self._sync_connection_rows()
            return
        if mode == CONNECTION_USB:
            # Beim Wechsel auf USB gleich nachsehen, was angeschlossen ist -
            # so muss niemand wissen, dass es den "Suchen"-Knopf gibt.
            self.refresh_usb_devices()
        self._sync_connection_rows()
        self.changed.emit()

    def _sync_connection_rows(self) -> None:
        """Nur zeigen, was zum gewaehlten Anschluss gehoert."""
        usb = self.connection() == CONNECTION_USB
        self._printer_form.setRowVisible(self._row_host, not usb)
        self._printer_form.setRowVisible(self._row_usb, usb)
        # Band-Erkennung braucht einen Rueckkanal: ueber Netzwerk (TCP 9100)
        # gibt es keinen - dort waere der Knopf nur ein Fehlschlag.
        self._printer_form.setRowVisible(
            self._row_detect,
            backend_supports_readback(backend_for_address(self.address())),
        )
        self._sync_access()

    def _sync_access(self) -> None:
        """Fehlende Rechte anzeigen - der haeufigste Grund, warum USB nicht druckt."""
        address = self.address()
        self.access_allowed = usb_access(address) if address else None
        needed = self.access_allowed is False
        self._printer_form.setRowVisible(self._row_access, needed)
        if needed:
            self._access_label.setText(
                tr("Kein Zugriff auf {address}.").format(address=address)
            )

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
            tr("{mm} mm je Seite (schraffiert)").format(
                mm=QLocale().toString(label.side_border_mm, "f", 2)
            )
        )
        self._orientation_label.setText(tr(self._orientation.label_de))
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
            tr(
                "{width} x {height} mm Inhalt\n→ Etikett ~{total} mm"
            ).format(
                width=QLocale().toString(media.dots_to_mm(width), "f", 1),
                height=QLocale().toString(media.dots_to_mm(height), "f", 1),
                total=QLocale().toString(total, "f", 1),
            )
        )


__all__ = ["MediaPanel"]
