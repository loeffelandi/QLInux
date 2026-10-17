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

from PySide6.QtCore import QSize, Qt, Signal
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
    usb_device_label,
    usb_devices,
)

#: Anschlussarten der Druckerauswahl. Die Werte entsprechen den Backend-Namen
#: (``network``) bzw. fassen die beiden USB-Backends zusammen.
CONNECTION_NETWORK = "network"
CONNECTION_USB = "usb"

#: Eintrag in der USB-Liste, solange kein Geraet gewaehlt ist (Datenwert leer).
USB_PLACEHOLDER = "Bitte Gerät wählen"

logger = logging.getLogger(__name__)


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
        # Unterdrueckt Nebenwirkungen, waehrend Felder programmatisch gesetzt
        # werden (z. B. beim Laden der Einstellungen).
        self._adjusting = False
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
        printer_box = QGroupBox("Drucker")
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
                "Netzwerk",
                "network",
                "Drucker im Netzwerk (WLAN/LAN).\n"
                "Es genügt die IP-Adresse - der Druckport "
                f"{NETWORK_PORT} wird automatisch ergänzt.",
            ),
            (
                CONNECTION_USB,
                "USB",
                "usb",
                "Drucker am USB-Kabel.\n"
                "„Suchen“ liest die angeschlossenen Geräte ein; nur über USB "
                "geht auch die Band-Erkennung.",
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
            "IP-Adresse oder Name des Druckers, z. B. 192.168.178.62.\n"
            f"Der Druckport {NETWORK_PORT} wird automatisch ergänzt; ein anderer "
            "Port geht als 192.168.178.62:9101."
        )

        self._usb_combo = QComboBox()
        self._usb_combo.setToolTip(
            "Angeschlossene USB-Drucker. Die Auswahl setzt Adresse und – wenn "
            "sie sich aus der USB-Kennung ableiten lässt – auch das Modell."
        )
        self._usb_button = QPushButton(icon("detect"), "Suchen")
        self._usb_button.setToolTip(
            "Angeschlossene USB-Drucker suchen und in die Liste eintragen."
        )

        # Zeigt, was aus der Auswahl folgt - vor allem, ob der Anschluss einen
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

        printer_form.addRow("Modell", self._model_combo)
        printer_form.addRow("Anschluss", self._build_connection_row())
        self._row_host = printer_form.rowCount()
        printer_form.addRow("IP-Adresse", self._host_edit)
        self._row_usb = printer_form.rowCount()
        printer_form.addRow("USB", self._build_usb_row())
        printer_form.addRow("", self._backend_label)
        printer_form.addRow("", self._detect_button)
        outer.addWidget(printer_box)
        # Startzustand: Netzwerk mit der gespeicherten/Standardadresse. Die
        # USB-Liste wird erst bei Bedarf gefuellt (Anschlusswechsel/Suche) -
        # so fragt der Programmstart nicht ungefragt libusb ab.
        self._conn_buttons[CONNECTION_NETWORK].setChecked(True)
        self._host_edit.setText(network_host(DEFAULT_ADDRESS))
        self._sync_connection_rows()

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
        self._host_edit.textChanged.connect(self._on_host_changed)
        self._usb_combo.currentIndexChanged.connect(self._on_usb_combo_changed)
        for mode, button in self._conn_buttons.items():
            button.toggled.connect(
                lambda checked, value=mode: self._on_connection_toggled(value, checked)
            )
        self._sync_backend_label()

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
        self._sync_backend_label()
        self.changed.emit()

    def refresh_usb_devices(self, devices: list[str] | None = None) -> list[str]:
        """USB-Liste neu einlesen und die Auswahl fuellen.

        Ohne ``devices`` wird selbst gesucht (:func:`printer.usb_devices`).
        Rueckgabe: die gefundenen Adressen - der Aufrufer kann damit melden,
        was los ist. Die aktuelle Auswahl bleibt erhalten; ein gerade nicht
        angeschlossenes Geraet bleibt als Eintrag stehen (so geht die
        gespeicherte Adresse nicht verloren).
        """
        if devices is None:
            try:
                devices = usb_devices()
            except Exception as exc:  # pragma: no cover - haengt an libusb
                logger.info("USB-Suche fehlgeschlagen: %s", exc)
                devices = []
        devices = [address for address in devices if address]
        current = self._usb_combo.currentData() or ""
        missing = current if current and current not in devices else ""
        apply_single = False

        self._usb_combo.blockSignals(True)
        try:
            self._usb_combo.clear()
            if not devices and not missing:
                self._usb_combo.addItem("Kein USB-Drucker gefunden", "")
            else:
                for address in devices:
                    self._usb_combo.addItem(usb_device_label(address), address)
                if missing:
                    self._usb_combo.addItem(
                        f"{usb_device_label(missing)} – nicht angeschlossen", missing
                    )
                if current:
                    self._usb_combo.setCurrentIndex(self._usb_combo.findData(current))
                elif len(devices) == 1:
                    # Genau ein Geraet: gleich auswaehlen.
                    self._usb_combo.setCurrentIndex(0)
                    apply_single = True
                else:
                    self._usb_combo.insertItem(0, USB_PLACEHOLDER, "")
                    self._usb_combo.setCurrentIndex(0)
        finally:
            self._usb_combo.blockSignals(False)

        if apply_single:
            self._apply_usb_selection()
        return list(devices)

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
        return self._usb_combo.findData(address)

    def _apply_usb_selection(self) -> None:
        """Gewaehltes USB-Geraet uebernehmen - Modell zieht nach, wenn ableitbar."""
        self._apply_model_for_address(self._usb_combo.currentData() or "")
        self._sync_connection_rows()
        self._sync_backend_label()
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
        """IP/Name getippt: Hinweis nachziehen und Aenderung melden."""
        if self._adjusting:
            return
        self._sync_connection_rows()
        self._sync_backend_label()
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
        self._sync_backend_label()
        self.changed.emit()

    def _sync_connection_rows(self) -> None:
        """Nur zeigen, was zum gewaehlten Anschluss gehoert."""
        usb = self.connection() == CONNECTION_USB
        self._printer_form.setRowVisible(self._row_host, not usb)
        self._printer_form.setRowVisible(self._row_usb, usb)
        # Band-Erkennung nur, wo sie auch gehen kann (USB mit Rueckkanal).
        self._detect_button.setEnabled(
            backend_supports_readback(backend_for_address(self.address()))
        )

    def _sync_backend_label(self) -> None:
        """Zeigen, welches Backend die Auswahl ergibt - und ob es antwortet."""
        address = self.address()
        if not address:
            self._backend_label.setText("Noch kein Drucker gewählt.")
            return
        backend = backend_for_address(address)
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
