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
from PySide6.QtGui import QAction, QActionGroup, QFontMetrics
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
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import media
from .discovery import NetworkPrinter, discover_network_printers
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
#: Beschriftungen der Druckerzeilen. Die breiteste bestimmt die feste Breite
#: der Beschriftungsspalte - so bleibt die Feldspalte beim Umschalten stehen.
PRINTER_LABELS = (
    "Modell",
    "Anschluss",
    "IP-Adresse",
    "Gerät",
    "Zugriff",
)
#: Kleinste Breite eines Anschluss-Knopfs (Bildschirmpixel).
CONNECTION_BUTTON_MIN_WIDTH = 88
#: Hoehe der Anschluss-Knoepfe (Bildschirmpixel).
CONNECTION_BUTTON_HEIGHT = 26
#: Hinweiszeile im Drucker-Formular (zurueckgenommen grau).
HINT_STYLE = "color:#6b7280;"
#: Zeichen, die die USB-Liste mindestens zeigen soll. Laengere Geraetenamen
#: werden abgeschnitten (der volle Text steht im Tooltip) - so bleibt die
#: Feldspalte schmal und das Panel behaelt seine Breite.
USB_COMBO_MIN_CHARS = 12
#: Rolle, unter der ein Listeneintrag sein Modell traegt (Netzwerksuche).
#: Achtung: nicht ``UserRole`` - die traegt schon die Adresse des Eintrags.
MODEL_ROLE = Qt.ItemDataRole.UserRole + 1


def usb_placeholder() -> str:
    """Eintrag in der USB-Liste, solange kein Geraet gewaehlt ist (Datenwert leer)."""
    return tr("Bitte Gerät wählen")

logger = logging.getLogger(__name__)


class MediaPanel(QWidget):
    """Bedienfeld fuer Band, Laenge, Margins, Farbe und Drucker."""

    changed = Signal()
    detect_requested = Signal()
    usb_search_requested = Signal()
    network_search_requested = Signal()
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
        # Zuletzt gefundene Netzwerk-Drucker und ob gerade gesucht wird.
        self._network_found: list[NetworkPrinter] = []
        self._network_searching = False
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
        # Feste Breite der Beschriftungsspalte (breiteste Beschriftung dieser
        # Sprache): sonst wandert die Feldspalte um ein paar Pixel, sobald eine
        # Zeile mit kuerzerer Beschriftung erscheint.
        self._label_width = max(
            QFontMetrics(self.font()).horizontalAdvance(tr(text)) for text in PRINTER_LABELS
        )

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

        # Netzwerk-Drucker im Netz suchen (mDNS + SNMP) - so muss niemand eine
        # IP kennen. Die Liste fuellt sich beim Umschalten auf Netzwerk und
        # ueber den Knopf; das Feld darunter bleibt fuer Handeingabe.
        self._net_combo = QComboBox()
        self._net_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._net_combo.setMinimumContentsLength(USB_COMBO_MIN_CHARS)
        self._net_combo.setToolTip(
            tr("Gefundene Netzwerk-Drucker. Die Auswahl setzt IP-Adresse und – "
            "wenn das Gerät sein Modell meldet – auch das Modell.")
        )
        self._net_button = QPushButton(icon("detect"), tr("Suchen"))
        self._net_button.setToolTip(
            tr("Netzwerk nach Druckern durchsuchen (mDNS und SNMP).")
        )
        self._net_hint = QLabel()
        self._net_hint.setWordWrap(True)
        self._net_hint.setStyleSheet(HINT_STYLE)

        self._usb_combo = QComboBox()
        # Lange Geraetenamen duerfen das Panel nicht breiter machen; der volle
        # Text steht weiterhin im Tooltip des Eintrags.
        self._usb_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._usb_combo.setMinimumContentsLength(USB_COMBO_MIN_CHARS)
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
        # Sein Platz bleibt auch ohne Rueckkanal reserviert: sonst springt der
        # Kasten, sobald ein Geraet gefunden wird oder der Anschluss wechselt.
        self._detect_holder = QWidget()
        detect_layout = QVBoxLayout(self._detect_holder)
        detect_layout.setContentsMargins(0, 0, 0, 0)
        detect_layout.addWidget(self._detect_button)
        self._detect_holder.setMinimumHeight(self._detect_button.sizeHint().height())

        printer_form.addRow(self._printer_label(tr("Modell")), self._model_combo)
        printer_form.addRow(
            self._printer_label(tr("Anschluss")), self._build_connection_row()
        )
        # Netzwerk und USB liegen im Stapel an derselben Stelle. Der Stapel ist
        # so hoch wie die groessere Seite - beim Umschalten verschiebt sich also
        # weder die Feldspalte noch der Rest des Panels.
        self._connection_stack = QStackedWidget()
        self._connection_stack.addWidget(self._build_host_page())
        self._connection_stack.addWidget(self._build_usb_page())
        printer_form.addRow(self._connection_stack)
        outer.addWidget(printer_box)
        # Startzustand: Netzwerk mit der gespeicherten/Standardadresse. Die
        # USB-Liste wird erst bei Bedarf gefuellt (Anschlusswechsel/Suche) -
        # so fragt der Programmstart nicht ungefragt libusb ab.
        self._conn_buttons[CONNECTION_NETWORK].setChecked(True)
        self._host_edit.setText(network_host(DEFAULT_ADDRESS))
        self._rebuild_network_list()
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
        self._net_button.clicked.connect(self.network_search_requested.emit)
        self._access_button.clicked.connect(self.usb_permission_requested.emit)
        self._host_edit.textChanged.connect(self._on_host_changed)
        self._usb_combo.currentIndexChanged.connect(self._on_usb_combo_changed)
        self._net_combo.currentIndexChanged.connect(self._on_net_combo_changed)
        for mode, button in self._conn_buttons.items():
            button.toggled.connect(
                lambda checked, value=mode: self._on_connection_toggled(value, checked)
            )

    def _printer_label(self, text: str) -> QLabel:
        """Beschriftung im Drucker-Formular mit fester Breite.

        Alle Beschriftungen sind gleich breit gesetzt, damit die Feldspalte
        unabhaengig davon stehen bleibt, welche Zeilen gerade sichtbar sind.
        """
        label = QLabel(text)
        label.setFixedWidth(self._label_width)
        label.setWordWrap(True)
        return label

    def _build_host_page(self) -> QWidget:
        """Seite „Netzwerk“: gefundene Drucker waehlen oder die IP tippen."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # Wie am USB: erst die Liste, dann der Knopf in eigener Zeile (daneben
        # waere die Feldspalte im Panel zu eng).
        form.addRow(self._printer_label(tr("Gerät")), self._net_combo)
        form.addRow("", self._net_button)
        form.addRow(self._printer_label(tr("IP-Adresse")), self._host_edit)
        form.addRow("", self._net_hint)
        self._sync_network_hint()
        return page

    def _build_usb_page(self) -> QWidget:
        """Seite „USB“: Geraet waehlen und suchen, Rechte, Band-Erkennung."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._usb_form = form
        # Suchen steht in einer eigenen Zeile: zusammen mit der Liste waere die
        # Feldspalte im Panel zu eng.
        form.addRow(self._printer_label(tr("Gerät")), self._usb_combo)
        form.addRow("", self._usb_button)
        self._row_access = form.rowCount()
        form.addRow(self._printer_label(tr("Zugriff")), self._build_access_row())
        form.addRow("", self._detect_holder)
        return page

    def _build_connection_row(self) -> QWidget:
        """Anschluss waehlen: Netzwerk oder USB (zwei Umschaltknoepfe).

        Beide Knoepfe sind gleich breit; sonst haengt die Kante an der Laenge
        der Beschriftung und wirkt beim Umschalten verschoben.
        """
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        buttons = [self._conn_buttons[mode] for mode in (CONNECTION_NETWORK, CONNECTION_USB)]
        width = max(
            CONNECTION_BUTTON_MIN_WIDTH,
            max(button.sizeHint().width() for button in buttons),
        )
        for button in buttons:
            button.setFixedSize(width, CONNECTION_BUTTON_HEIGHT)
            layout.addWidget(button)
        layout.addStretch(1)
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
                self._rebuild_network_list()
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

    def refresh_network_devices(
        self, printers: list[NetworkPrinter] | None = None
    ) -> list[NetworkPrinter]:
        """Gefundene Netzwerk-Drucker uebernehmen und die Liste fuellen.

        Ohne ``printers`` wird selbst gesucht
        (:func:`ql_editor.discovery.discover_network_printers`) - das blockiert
        bis zu zwei Sekunden, im Fenster laeuft die Suche deshalb im
        Hintergrund. Die aktuelle Adresse bleibt erhalten; wurde sie nicht
        gefunden, steht sie als „Handeingabe“ in der Liste. Ist noch gar keine
        Adresse gesetzt und wird genau ein Drucker gefunden, wird er
        gleich uebernommen (wie am USB).
        """
        if printers is None:
            try:
                printers = discover_network_printers()
            except Exception as exc:  # pragma: no cover - haengt am Netz
                logger.info("Netzwerksuche fehlgeschlagen: %s", exc)
                printers = []
        self._network_found = list(printers)
        self._rebuild_network_list()
        self._sync_network_hint(len(self._network_found))
        if not self.address() and len(self._network_found) == 1:
            self._apply_network_selection()
        return list(self._network_found)

    def set_network_searching(self, searching: bool) -> None:
        """Suche laeuft: Knopf sperren und es in der Statuszeile zeigen."""
        self._network_searching = searching
        self._net_button.setEnabled(not searching)
        self._sync_network_hint()

    def _sync_network_hint(self, found: int | None = None) -> None:
        """Statuszeile der Netzwerk-Seite: Suche, Ergebnis oder Hinweis."""
        if self._network_searching:
            text = tr("Suche läuft …")
        elif found == 0:
            text = tr("Keine Netzwerk-Drucker gefunden.")
        else:
            text = tr("Der Port {port} wird automatisch ergänzt.").format(
                port=NETWORK_PORT
            )
        self._net_hint.setText(text)

    def _rebuild_network_list(self) -> None:
        """Liste aus den zuletzt gefundenen Druckern neu aufbauen.

        Die aktuelle Adresse steht als „Handeingabe“ darin, solange sie nicht
        gefunden wurde - so bleibt sie sichtbar und auswaehlbar, egal ob sie
        getippt oder aus den Einstellungen geladen wurde.
        """
        current = self.address()
        self._net_combo.blockSignals(True)
        try:
            self._net_combo.clear()
            for printer in self._network_found:
                self._net_combo.addItem(printer.label(), printer.address)
                index = self._net_combo.count() - 1
                if printer.model_id:
                    self._net_combo.setItemData(index, printer.model_id, MODEL_ROLE)
                self._net_combo.setItemData(
                    index, printer.detail(), Qt.ItemDataRole.ToolTipRole
                )
            index = self._net_combo.findData(current) if current else -1
            if index < 0 and current:
                self._net_combo.addItem(tr("Handeingabe"), current)
                index = self._net_combo.count() - 1
            elif index < 0 and self._net_combo.count():
                index = 0
            self._net_combo.setCurrentIndex(index)
        finally:
            self._net_combo.blockSignals(False)

    def _apply_network_selection(self) -> None:
        """Gewaehlten Netzwerk-Drucker uebernehmen - Modell zieht nach."""
        address = self._net_combo.currentData() or ""
        model = self._net_combo.itemData(self._net_combo.currentIndex(), MODEL_ROLE)
        if address:
            self._adjusting = True
            try:
                self._host_edit.setText(network_host(address))
            finally:
                self._adjusting = False
        if model:
            self.set_model(model)
        self._sync_connection_rows()
        self.changed.emit()

    def _request_network_search(self) -> None:
        """Suche anfordern (das Hauptfenster sucht im Hintergrund)."""
        if self._network_searching:
            return
        self.network_search_requested.emit()

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
        """IP/Name getippt: Liste und Zeilen nachziehen, Aenderung melden."""
        if self._adjusting:
            return
        self._rebuild_network_list()
        self._sync_connection_rows()
        self.changed.emit()

    def _on_net_combo_changed(self) -> None:
        """Nutzer hat einen gefundenen Netzwerk-Drucker gewaehlt."""
        if self._adjusting:
            return
        self._apply_network_selection()

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
        else:
            # Netzwerk: im Hintergrund suchen (mDNS + SNMP). Das dauert rund
            # eine Sekunde und gehoert deshalb nicht in den Klickpfad.
            self._request_network_search()
        self._sync_connection_rows()
        self.changed.emit()

    def _sync_connection_rows(self) -> None:
        """Nur zeigen, was zum gewaehlten Anschluss gehoert."""
        usb = self.connection() == CONNECTION_USB
        # Beide Anschlussarten liegen im Stapel an derselben Stelle: der Wechsel
        # verschiebt weder Felder noch die Hoehe des Kastens (die IP-Zeile hat
        # darum bewusst einen Hinweis, damit die Netzwerk-Seite nicht leer wirkt).
        self._connection_stack.setCurrentIndex(1 if usb else 0)
        # Band-Erkennung braucht einen Rueckkanal: den gibt es nur ueber USB -
        # und nur, wenn wirklich ein Geraet gewaehlt ist.
        self._detect_button.setVisible(
            backend_supports_readback(backend_for_address(self.address()))
        )
        self._sync_access()

    def _sync_access(self) -> None:
        """Fehlende Rechte anzeigen - der haeufigste Grund, warum USB nicht druckt."""
        address = self.address()
        self.access_allowed = usb_access(address) if address else None
        needed = self.access_allowed is False
        self._usb_form.setRowVisible(self._row_access, needed)
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
