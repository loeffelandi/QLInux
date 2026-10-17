"""Hauptfenster der QLInux-Anwendung (PySide6).

Aufbau:

* links: :class:`~ql_editor.media_panel.MediaPanel` (Band, Laenge, Margins)
* mitte: :class:`~ql_editor.canvas.LabelCanvas` (feste Pixelgroesse, Lineale)
* rechts: Vorschau (monochrom) + Druckoptionen
* Toolbar: Items einfuegen, Reihenfolge, Loeschen, Zoom, Drucken

Es gibt **keine klassische Menueleiste**. Alle Befehle liegen in einem
Hamburger-Menue (``main_menu_button``) links in der Toolbar - das wirkt
moderner und ist unter Linux/Wayland die uebliche Loesung (einen globalen
Menuebalken wie unter macOS gibt es hier nicht).

Die GUI haelt keine eigene Wahrheit ueber Bandmasse: alles kommt aus
:mod:`ql_editor.media`. Gerendert wird ueber :mod:`ql_editor.renderer`,
gedruckt ueber :mod:`ql_editor.printer` (in einem Worker-Thread).
"""

from __future__ import annotations

import sys
import threading
from functools import partial
from pathlib import Path
from typing import Any, Mapping

from PIL import Image
from PySide6.QtCore import (
    QLocale,
    QPointF,
    QProcess,
    QRectF,
    QSize,
    QThread,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QActionGroup, QFontMetrics, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import access
from . import about
from . import document
from . import media
from . import resources
from . import templates
from .canvas import LabelCanvas
from .discovery import discover_network_printers
from .i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    language,
    language_name,
    set_language,
    tr,
)
from .icons import icon
from .inspector import InspectorPanel
from .items import BarcodeItem, ImageItem, LineItem, QRItem, RectItem, TextItem
from .media_panel import MediaPanel
from .panels import OverlayPanel, PanelHost
from .preview import (
    DEFAULT_THRESHOLD,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
    PreviewOptions,
    binarize,
    ink_ratio,
    reduce_for_display,
    to_qimage,
)
from .printer import (
    COPIES_MAX,
    CUT_AT_END,
    CUT_EACH,
    CUT_NONE,
    PrintResolution,
    PrinterError,
    RESOLUTION_HIGH,
    RESOLUTION_STANDARD,
    detect_label,
    maximum_resolution,
    print_image,
    resolution_by_key,
    resolution_options,
)
from .settings import AppSettings
from .sheet import ask_choice, ask_text, choose_file, save_file, show_message
from .widgets import SmoothScrollArea, install_wheel_guard_recursive

BARCODE_SYMBOLOGIES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"]

#: Wie lange auf den Passwort-Dialog gewartet wird, bevor der Einzeiler kommt.
PERMISSION_TIMEOUT_MS = 90_000
#: Nach dem Einrichten der Regel greift udev erst kurz verzoegert: so lange
#: (in Schritten von ACCESS_RETRY_MS) werden die Rechte nachgefasst.
ACCESS_RETRY_MS = 400
ACCESS_RETRY_COUNT = 8
#: So lange darf eine abgebrochene Netzwerksuche beim Schliessen nachlaufen.
NETWORK_CANCEL_WAIT_MS = 1000
#: Zugabe auf die reine Textbreite der Beschriftungsspalte in den
#: Druckoptionen (Kopien / Zuschnitt) - sonst schneidet die Schrift ab.
ROW_LABEL_EXTRA_PX = 8


class PrintWorker(QThread):
    """Rendert nichts, sondern konvertiert und sendet in einem Thread."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, image: Image.Image, label, config, options: dict):
        super().__init__()
        self._image = image
        self._label = label
        self._config = config
        self._options = options

    def run(self) -> None:  # noqa: D401
        try:
            status = print_image(self._image, self._label, self._config, **self._options)
        except PrinterError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensiv
            self.failed.emit(
                tr("Unerwarteter Fehler: {error}").format(error=exc)
            )
        else:
            self.succeeded.emit(status)


class NetworkSearchWorker(QThread):
    """Sucht Drucker im Netzwerk (mDNS + SNMP) abseits der Oberflaeche."""

    succeeded = Signal(list)

    def __init__(self, cancel: threading.Event, parent=None):
        super().__init__(parent)
        self._cancel = cancel

    def run(self) -> None:  # noqa: D401
        printers = []
        try:
            printers = discover_network_printers(cancel=self._cancel)
        except Exception as exc:  # pragma: no cover - defensiv
            logger.info("Netzwerksuche fehlgeschlagen: %s", exc)
        self.succeeded.emit(printers)


#: Das aktuelle Hauptfenster. Beim Sprachwechsel entsteht ein neues Fenster;
#: diese Referenz haelt es am Leben - ein Fenster ohne Elternteil wird sonst
#: vom Garbage Collector eingesammelt.
_current_window: MainWindow | None = None


def _remember_window(window: MainWindow) -> None:
    global _current_window
    _current_window = window


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None):
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle(tr("QLInux - P-touch Editor"))
        self._apply_window_icon()
        self.setWindowIcon(icon("label"))
        self._adjusting = False
        self._print_worker: PrintWorker | None = None
        # Netzwerksuche im Hintergrund (mDNS + SNMP); ``_network_cancel``
        # bricht sie beim Schliessen des Fensters ab.
        self._network_worker: NetworkSearchWorker | None = None
        self._network_cancel = threading.Event()
        # Passwort-Dialog des Systems (pkexec + Helfer), siehe _on_usb_permission.
        self._permission_process = QProcess(self)
        self._permission_process.finished.connect(self._on_permission_finished)
        self._permission_timer = QTimer(self)
        self._permission_timer.setSingleShot(True)
        self._permission_timer.setInterval(PERMISSION_TIMEOUT_MS)
        self._permission_timer.timeout.connect(self._on_permission_timeout)
        # Rechte nachfassen, bis udev die neue Regel angewendet hat.
        self._access_attempts = 0
        self._access_retry = QTimer(self)
        self._access_retry.setInterval(ACCESS_RETRY_MS)
        self._access_retry.timeout.connect(self._check_usb_access)
        #: Ansicht (Zoom + Mittelpunkt) vor dem Einschalten der Druckvorschau.
        self._preview_view: tuple[float, QPointF] | None = None

        self._canvas = LabelCanvas(self)
        self._canvas.setMinimumSize(240, 180)
        self._host = PanelHost(self._canvas, self)
        self.setCentralWidget(self._host)

        self._media_panel = MediaPanel(self)
        self._media_panel.setMinimumWidth(220)
        self._inspector = InspectorPanel(self)
        self._inspector.setMinimumWidth(240)

        # Gesamtfenster darf klein werden, ohne dass etwas unbedienbar wird.
        self.setMinimumSize(640, 460)

        self._build_panels()
        self._build_actions()
        self._build_toolbar()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_now)

        self._media_panel.changed.connect(self._on_media_changed)
        self._media_panel.detect_requested.connect(self._on_detect_label)
        self._media_panel.usb_search_requested.connect(self._on_usb_search)
        self._media_panel.network_search_requested.connect(self._on_network_search)
        self._media_panel.usb_permission_requested.connect(self._on_usb_permission)
        self._canvas.text_requested.connect(self._on_text_requested)
        self._canvas.item_double_clicked.connect(self._on_item_double_clicked)
        self._canvas.context_menu_requested.connect(self._show_context_menu)
        self._canvas.items_changed.connect(self._on_items_changed)
        self._canvas.image_dropped.connect(self._on_image_dropped)
        self._canvas.text_dropped.connect(self._on_text_dropped)
        self._canvas.print_preview_exit_requested.connect(self._exit_print_preview)
        self._canvas.scene().selectionChanged.connect(self._on_selection_changed)
        # Direkte Canvas-Aenderungen (Ziehen, Groesse, Drehen) aktualisieren die
        # Vorschau live; die Bandgroesse wird erst am Ende der Geste neu berechnet.
        self._canvas.scene().changed.connect(self._on_scene_changed)
        self._inspector.changed.connect(self._on_inspector_changed)
        # Aenderungen am Band/Design markieren das Dokument als geaendert
        # (die Adresse zaehlt mit - ein falscher Stern ist harmloser als
        # ein fehlender).
        self._media_panel.changed.connect(self._mark_document_dirty)

        # Rad-Ereignisse duerfen keine Werte in Feldern aendern (auch nicht in
        # den dynamisch erzeugten Inspector-Feldern - die sichern sich selbst).
        install_wheel_guard_recursive(self)

        self._zoom_label = QLabel(tr("Zoom 100 %"))
        self._zoom_label.setToolTip(
            tr("Mausrad scrollt – Strg + Mausrad (oder Zoomgeste) zoomt")
        )
        self.statusBar().addPermanentWidget(self._zoom_label)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)

        # Gespeicherte Einstellungen anwenden.
        self._apply_saved_settings()
        self._on_media_changed()

        # Fokus auf dem Canvas: kein Formularfeld ist anfangs "aktiv", damit das
        # Mausrad über den Panels scrollt statt Werte zu veraendern.
        self._canvas.setFocus()

    # --------------------------------------------------------------- Aufbau --
    @staticmethod
    def _scroll_wrap(widget: QWidget) -> QScrollArea:
        """Widget responsiv machen: bei Platzmangel scrollen statt zu blockieren.

        Verwendet :class:`SmoothScrollArea` fuer weiches Mausrad-Scrollen.
        """
        area = SmoothScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setWidget(widget)
        return area

    def _build_panels(self) -> None:
        """Seitenpanels als einklappbare Overlays ueber dem Canvas.

        Der Pfeil sitzt *im* Panel (siehe :mod:`ql_editor.panels`); die
        Panel-Breiten orientieren sich an den Formularzeilen (siehe
        ``PANEL_WIDTH``), damit "Symbologie"/"Höhe (Dots)" einzeilig bleiben.
        """
        self._left_panel = OverlayPanel(
            tr("Band & Drucker"),
            self._scroll_wrap(self._media_panel),
            Qt.Edge.LeftEdge,
            self,
        )
        self._host.add_panel(self._left_panel)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._scroll_wrap(self._inspector))
        print_area = self._scroll_wrap(self._build_print_panel())
        # Die Druckoptionen sind eine feste Formularhoehe - sie muessen immer
        # ganz sichtbar bleiben (der Drucken-Knopf darf nie hinter dem
        # Scrollbalken verschwinden). Der Inspector darueber gibt dafuer nach;
        # er scrollt selbst.
        print_area.setMinimumHeight(print_area.sizeHint().height())
        splitter.addWidget(print_area)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([300, print_area.minimumHeight()])
        self._right_panel = OverlayPanel(
            tr("Eigenschaften & Druck"),
            splitter,
            Qt.Edge.RightEdge,
            self,
        )
        self._host.add_panel(self._right_panel)

    def _build_print_panel(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel(tr("Druckoptionen"))
        title.setStyleSheet("color:#555; font-weight:600;")
        layout.addWidget(title)

        hint = QLabel(
            tr("Die Druckvorschau (Strg+Umschalt+P) zeigt die gewählte Auflösung in "
            "echten Druckpunkten.")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777;")
        layout.addWidget(hint)

        # Aufloesung: nur was das gewaehlte Modell kann (die Liste kommt aus den
        # Datenblaettern, siehe printer.resolution_options). Der High-Resolution-
        # Modus ist bewusst *nicht* voreingestellt - er druckt langsamer.
        resolution_label = QLabel(tr("Auflösung"))
        self._resolution_combo = QComboBox()
        resolution_label.setBuddy(self._resolution_combo)
        self._resolution_hint = QLabel()
        self._resolution_hint.setWordWrap(True)
        self._resolution_hint.setStyleSheet("color:#777;")
        layout.addWidget(resolution_label)
        layout.addWidget(self._resolution_combo)
        layout.addWidget(self._resolution_hint)

        # Eigener Schalter: "Qualitaet vor Tempo" (brother_ql ``pquality``/hq).
        # Das ist *keine* Aufloesung - deshalb getrennt vom Feld darueber.
        self._hq_check = QCheckBox(tr("Hohe Druckqualität (HQ)"))
        self._hq_check.setChecked(True)
        self._hq_check.setToolTip(
            tr("Der Drucker arbeitet dann mit Vorrang für Qualität statt Tempo "
            "(das pquality-Flag aus der Brother-Rasterreferenz).\n"
            "Die Auflösung ändert das nicht - die steht im Feld darüber.")
        )
        layout.addWidget(self._hq_check)

        self._dither_check = QCheckBox(tr("Graustufen (Dithering)"))
        self._dither_check.setToolTip(
            tr("Graustufen werden gepunktet statt hart geschwellt - für Fotos.\n"
            "Ohne Dithering entscheidet die Tintenmenge unten, welche Helligkeit "
            "Tinte wird.")
        )

        # Tintenmenge = brother_ql-Schwelle ("-t"). Sie wirkt nur ohne
        # Dithering (convert() nutzt sie dann nicht) - deshalb wird sie dann
        # ausgegraut, statt still wirkungslos zu sein. Die Extremwerte (alles
        # schwarz / nur reines Schwarz) sind nicht waehlbar.
        self._threshold_label = QLabel(tr("Tintenmenge"))
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(THRESHOLD_MIN, THRESHOLD_MAX)
        self._threshold_spin.setValue(DEFAULT_THRESHOLD)
        self._threshold_spin.setSuffix(" %")
        self._threshold_label.setBuddy(self._threshold_spin)
        self._threshold_spin.setToolTip(self._threshold_tooltip())
        self._threshold_label.setToolTip(self._threshold_spin.toolTip())
        self._ink_label = QLabel(tr("Tinte: –"))
        self._ink_label.setStyleSheet("color:#777;")
        self._ink_label.setToolTip(
            tr("Anteil der bedruckten Fläche - sofort sichtbar, was Tintenmenge "
            "und Dithering bewirken.")
        )
        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.addWidget(self._threshold_spin)
        threshold_row.addWidget(self._ink_label, 1)

        # Kopien und Zuschnitt in je einer Zeile (Beschriftung links): die
        # Druckoptionen haben eine feste Formularhoehe, und zwei Zeilen sparen
        # zwei Reihen gegenueber "Beschriftung ueber Feld".
        self._copies_label = QLabel(tr("Kopien"))
        self._copies_spin = QSpinBox()
        self._copies_spin.setRange(1, COPIES_MAX)
        self._copies_spin.setValue(1)
        self._copies_label.setBuddy(self._copies_spin)
        self._copies_spin.setToolTip(
            tr("Wie oft dieses Etikett gedruckt wird - als ein Auftrag.")
        )
        self._copies_label.setToolTip(self._copies_spin.toolTip())

        self._cut_label = QLabel(tr("Zuschnitt"))
        self._cut_combo = QComboBox()
        self._cut_label.setBuddy(self._cut_combo)
        for mode, text in (
            (CUT_EACH, tr("Nach jeder Kopie")),
            (CUT_AT_END, tr("Nur am Ende")),
            (CUT_NONE, tr("Nicht schneiden")),
        ):
            self._cut_combo.addItem(text, mode)
        self._cut_combo.setCurrentIndex(self._cut_combo.findData(CUT_EACH))
        self._cut_combo.setToolTip(
            tr("Nach jeder Kopie: einzelne Etiketten.\n"
               "Nur am Ende: die Kopien hängen zusammen und werden zuletzt "
               "getrennt - nur bei mehreren Kopien.\n"
               "Nicht schneiden: der Streifen bleibt am Band.")
        )
        self._cut_label.setToolTip(self._cut_combo.toolTip())

        # Gemeinsame Beschriftungsspalte, damit beide Felder gleich anfangen.
        metrics = QFontMetrics(self.font())
        label_width = max(
            metrics.horizontalAdvance(self._copies_label.text()),
            metrics.horizontalAdvance(self._cut_label.text()),
        ) + ROW_LABEL_EXTRA_PX
        for label in (self._copies_label, self._cut_label):
            label.setFixedWidth(label_width)

        copies_row = QHBoxLayout()
        copies_row.setContentsMargins(0, 0, 0, 0)
        copies_row.addWidget(self._copies_label)
        copies_row.addWidget(self._copies_spin, 1)

        cut_row = QHBoxLayout()
        cut_row.setContentsMargins(0, 0, 0, 0)
        cut_row.addWidget(self._cut_label)
        cut_row.addWidget(self._cut_combo, 1)

        self._print_button = QPushButton(icon("print"), tr("Drucken"))

        layout.addWidget(self._dither_check)
        layout.addWidget(self._threshold_label)
        layout.addLayout(threshold_row)
        layout.addLayout(copies_row)
        layout.addLayout(cut_row)
        layout.addStretch(1)
        layout.addWidget(self._print_button)

        self._resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        self._threshold_spin.valueChanged.connect(self._schedule_refresh)
        self._dither_check.toggled.connect(self._on_dither_toggled)
        self._copies_spin.valueChanged.connect(self._sync_cut_options)
        self._print_button.clicked.connect(self._on_print)
        self._hq_check.toggled.connect(self._on_hq_toggled)
        self._sync_resolution_options()
        self._sync_cut_options()
        return widget

    def _sync_cut_options(self) -> None:
        """„Nur am Ende" gibt es nur bei mehreren Kopien.

        Bei einer Kopie ist der Schnitt am Ende der Schnitt nach der Kopie -
        die Wahl waere eine Scheinoption. Der Eintrag wird deshalb ausgegraut
        statt versteckt: die Zeile bleibt stehen und das Panel springt nicht,
        aber man sieht, dass er mehr als eine Kopie braucht.
        """
        several = self._copies_spin.value() > 1
        item = self._cut_combo.model().item(self._cut_combo.findData(CUT_AT_END))
        if item is not None:
            item.setEnabled(several)
        if not several and self._cut_combo.currentData() == CUT_AT_END:
            # Gleiche Wirkung wie „Nach jeder Kopie": die Auswahl aufraeumen,
            # damit in den Einstellungen steht, was wirklich passiert.
            self._cut_combo.setCurrentIndex(self._cut_combo.findData(CUT_EACH))

    def _on_resolution_changed(self) -> None:
        """Aufloesung gewechselt: Hinweis aktualisieren und neu rendern.

        Der High-Resolution-Modus aendert den Renderfaktor - Vorschau und
        Tintenanteil muessen also neu berechnet werden.
        """
        self._update_resolution_hint()
        self._schedule_refresh()

    def _on_hq_toggled(self) -> None:
        """HQ aendert nur ein Druckerflag - die Vorschau bleibt gleich."""
        self._update_resolution_hint()

    def _threshold_tooltip(self) -> str:
        return tr(
            "Wie viel Tinte der Drucker setzt.\n"
            "\n"
            "Der Drucker kennt nur Schwarz oder Weiß: jede weiche Kante und "
            "jeder Grauton\n"
            "im Design muss zu einem von beidem werden. Die Tintenmenge ist der "
            "Schnitt:\n"
            "70 % (Standard) = alles ab etwa 30 % Schwärze wird Tinte - gut für "
            "Text.\n"
            "höher = mehr Tinte: auch hellgraue Ränder werden schwarz, die "
            "Schrift wird\n"
            "kräftiger und etwas breiter.\n"
            "niedriger = weniger Tinte: nur dunkle Punkte werden schwarz, feiner "
            "- dünne\n"
            "Striche können ausfransen.\n"
            "Einstellbar von {low} % (fein) bis {high} % (kräftig).\n"
            "Wirkt nur ohne Dithering."
        ).format(low=THRESHOLD_MIN, high=THRESHOLD_MAX)

    def _on_dither_toggled(self) -> None:
        self._sync_threshold_enabled()
        self._schedule_refresh()

    def _sync_threshold_enabled(self) -> None:
        """Tintenmenge nur anbieten, wenn sie wirkt (ohne Dithering)."""
        active = not self._dither_check.isChecked()
        self._threshold_spin.setEnabled(active)
        self._threshold_label.setEnabled(active)
        self._threshold_label.setText(
            tr("Tintenmenge") if active else tr("Tintenmenge (ohne Wirkung)")
        )

    def _sync_resolution_options(self, prefer: str | None = None) -> None:
        """Aufloesungsliste an das gewaehlte Modell anpassen.

        Die Auswahl bleibt erhalten, solange das Modell sie kann; sonst faellt
        sie auf das zurueck, was das Modell hergibt. Es werden **nur** die
        Aufloesungen angeboten, die der Druckkopf wirklich kann (Quelle:
        Datenblaetter, siehe :func:`ql_editor.printer.resolution_options`).

        ``prefer`` ueberschreibt die Auswahl (beim Laden der Einstellungen).
        """
        model_id = self._media_panel.model_id()
        options = resolution_options(model_id)
        wanted = prefer or self._resolution_combo.currentData() or self._settings.print_resolution

        self._resolution_combo.blockSignals(True)
        self._resolution_combo.clear()
        for option in options:
            self._resolution_combo.addItem(option.label, option.key)
        index = self._resolution_combo.findData(wanted)
        if index < 0:
            index = self._resolution_combo.findData(RESOLUTION_STANDARD.key)
        self._resolution_combo.setCurrentIndex(max(0, index))
        self._resolution_combo.blockSignals(False)

        chosen = self._resolution()
        self._resolution_combo.setToolTip(
            tr("{label}: {detail}.").format(
                label=chosen.label, detail=chosen.detail
            )
        )
        self._update_resolution_hint()
        self._sync_threshold_enabled()

    def _update_resolution_hint(self) -> None:
        """Untertitel zur Aufloesung: was dieses Modell kann."""
        model_id = self._media_panel.model_id()
        best = maximum_resolution(model_id)
        chosen = self._resolution()
        if chosen.key == RESOLUTION_HIGH.key:
            text = tr("600 dpi nur in Bandlaufrichtung; quer bleiben es 300 dpi.")
        elif best.key == RESOLUTION_HIGH.key:
            text = tr("Auch möglich: 300 × 600 dpi (feiner längs, druckt langsamer).")
        else:
            text = tr(
                "{model}: 300 × 300 dpi - mehr kann dieser Druckkopf nicht."
            ).format(model=model_id)
        if not self._hq_check.isChecked():
            text += " " + tr("Ohne HQ druckt der Drucker schneller.")
        self._resolution_hint.setText(text)

    def _resolution(self) -> PrintResolution:
        """Die gewaehlte Aufloesung - auf die Faehigkeiten des Modells begrenzt."""
        return resolution_by_key(
            self._media_panel.model_id(), self._resolution_combo.currentData()
        )

    def _hq(self) -> bool:
        """Qualitaet vor Tempo (brother_ql ``pquality``/``hq``)."""
        return self._hq_check.isChecked()

    def _build_actions(self) -> None:
        self._act_add_text = QAction(icon("text"), tr("Text"), self)
        self._act_add_text.setToolTip(tr("Text einfügen (Doppelklick auf den Canvas)"))
        self._act_add_text.triggered.connect(self._add_text)

        self._act_add_image = QAction(icon("image"), tr("Bild…"), self)
        self._act_add_image.setToolTip(tr("Bild einfügen"))
        self._act_add_image.triggered.connect(self._add_image)

        self._act_add_barcode = QAction(icon("barcode"), tr("Barcode…"), self)
        self._act_add_barcode.setToolTip(tr("Barcode einfügen"))
        self._act_add_barcode.triggered.connect(self._add_barcode)

        self._act_add_qr = QAction(icon("qr"), tr("QR-Code…"), self)
        self._act_add_qr.setToolTip(tr("QR-Code einfügen"))
        self._act_add_qr.triggered.connect(self._add_qr)

        self._act_add_line = QAction(icon("line"), tr("Linie"), self)
        self._act_add_line.setToolTip(tr("Linie einfügen"))
        self._act_add_line.triggered.connect(self._add_line)

        self._act_add_rect = QAction(icon("rect"), tr("Rahmen"), self)
        self._act_add_rect.setToolTip(tr("Rahmen einfügen"))
        self._act_add_rect.triggered.connect(self._add_rect)

        self._act_front = QAction(icon("front"), tr("In den Vordergrund"), self)
        self._act_front.setToolTip(tr("In den Vordergrund"))
        self._act_front.triggered.connect(lambda: self._bump_z(+1))

        self._act_back = QAction(icon("back"), tr("In den Hintergrund"), self)
        self._act_back.setToolTip(tr("In den Hintergrund"))
        self._act_back.triggered.connect(lambda: self._bump_z(-1))

        self._act_delete = QAction(icon("delete"), tr("Löschen"), self)
        self._act_delete.setToolTip(tr("Löschen (Entf)"))
        self._act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self._act_delete.triggered.connect(self._delete_selected)

        self._act_zoom_fit = QAction(icon("zoom_fit"), tr("Einpassen"), self)
        self._act_zoom_fit.setToolTip(tr("Zoom: Einpassen (Ctrl+0)"))
        self._act_zoom_fit.setShortcut("Ctrl+0")
        self._act_zoom_fit.triggered.connect(self._canvas.zoom_fit)

        self._act_zoom_in = QAction(icon("zoom_in"), tr("Vergrößern"), self)
        self._act_zoom_in.setToolTip(tr("Vergrößern (Strg ++)"))
        self._act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self._act_zoom_in.triggered.connect(self._canvas.zoom_in)

        self._act_zoom_out = QAction(icon("zoom_out"), tr("Verkleinern"), self)
        self._act_zoom_out.setToolTip(tr("Verkleinern (Strg +-)"))
        self._act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self._act_zoom_out.triggered.connect(self._canvas.zoom_out)

        self._act_zoom_100 = QAction(icon("zoom_100"), tr("1:1"), self)
        self._act_zoom_100.setToolTip(
            tr("Zoom 1:1 (Strg+1) - echte Druckpunkte,\n"
            "so wie der Drucker sie setzt")
        )
        self._act_zoom_100.setShortcut("Ctrl+1")
        self._act_zoom_100.triggered.connect(self._canvas.zoom_100)

        self._act_print = QAction(icon("print"), tr("Drucken"), self)
        self._act_print.setToolTip(tr("Drucken (Ctrl+P)"))
        self._act_print.setShortcut("Ctrl+P")
        self._act_print.triggered.connect(self._on_print)

        self._act_print_preview = QAction(icon("preview"), tr("Druckvorschau"), self)
        self._act_print_preview.setCheckable(True)
        self._act_print_preview.setToolTip(tr("Druckvorschau: echte 1-bit-Ausgabe (Ctrl+Shift+P)"))
        self._act_print_preview.setShortcut("Ctrl+Shift+P")
        self._act_print_preview.toggled.connect(self._on_toggle_print_preview)

        # Seitenpanels ein-/ausblenden (kleine Bildschirme). Beide Aktionen sind
        # immer erreichbar (Toolbar + Menue) - so laesst sich ein versehentlich
        # verstecktes Panel jederzeit zurueckholen.
        self._act_panel_left = QAction(icon("panel_left"), tr("Panel links"), self)
        self._act_panel_left.setCheckable(True)
        self._act_panel_left.setChecked(True)
        self._act_panel_left.setToolTip(
            tr("Panel links ein-/ausklappen (Strg+B)\n"
            "Eingeklappt bleibt ein Streifen mit Pfeil; er klappt beim "
            "Überfahren über dem Canvas auf")
        )
        self._act_panel_left.setShortcut("Ctrl+B")
        self._act_panel_left.toggled.connect(self._left_panel.set_docked)

        self._act_panel_right = QAction(icon("panel_right"), tr("Panel rechts"), self)
        self._act_panel_right.setCheckable(True)
        self._act_panel_right.setChecked(True)
        self._act_panel_right.setToolTip(
            tr("Panel rechts ein-/ausklappen (Strg+Shift+B)\nEigenschaften und Druckoptionen")
        )
        self._act_panel_right.setShortcut("Ctrl+Shift+B")
        self._act_panel_right.toggled.connect(self._right_panel.set_docked)

        # Pfeil im Panel und Menue-Haekchen synchron halten (der Pfeil ist der
        # primaere Weg, das Menue der Shortcut).
        self._left_panel.docked_changed.connect(self._act_panel_left.setChecked)
        self._right_panel.docked_changed.connect(self._act_panel_right.setChecked)

        self._act_quit = QAction(icon("quit"), tr("Beenden"), self)
        self._act_quit.setToolTip(tr("Beenden (Strg+Q)"))
        self._act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_quit.triggered.connect(self.close)

        self._act_about = QAction(icon("about"), tr("Über QLInux"), self)
        self._act_about.setToolTip(tr("Über QLInux"))
        self._act_about.triggered.connect(self._show_about)

        # Datei: ein Etikett ist eine Datei (JSON, .qlx) - nicht nur ein Fenster.
        self._act_file_open = QAction(icon("open"), tr("Öffnen…"), self)
        self._act_file_open.setToolTip(tr("Etikett öffnen (Strg+O)"))
        self._act_file_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_file_open.triggered.connect(self._on_file_open)

        self._act_file_save = QAction(icon("save"), tr("Speichern"), self)
        self._act_file_save.setToolTip(tr("Etikett speichern (Strg+S)"))
        self._act_file_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_file_save.triggered.connect(self._on_file_save)

        self._act_file_save_as = QAction(icon("save_as"), tr("Speichern unter…"), self)
        self._act_file_save_as.setToolTip(tr("Etikett unter neuem Namen speichern (Strg+Umschalt+S)"))
        self._act_file_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._act_file_save_as.triggered.connect(self._on_file_save_as)

        # Der Dateiname steht im Fenstertitel; ein Stern markiert Aenderungen.
        self._document_path = ""
        self._document_dirty = False
        self._canvas.items_changed.connect(self._mark_document_dirty)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Werkzeuge")
        bar.setObjectName("main_toolbar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        bar.setIconSize(QSize(22, 22))

        # Moderner "App-Menue"-Knopf (Hamburger) statt klassischer Menueleiste.
        self._menu_button = QToolButton(bar)
        self._menu_button.setObjectName("main_menu_button")
        self._menu_button.setIcon(icon("menu"))
        self._menu_button.setToolTip(tr("Menü"))
        self._menu_button.setAutoRaise(True)
        self._menu_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_button.setMenu(self._build_main_menu())
        # Das kleine "Aufklapp"-Dreieck passt nicht zu einem modernen Hamburger.
        self._menu_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; }"
        )
        bar.addWidget(self._menu_button)
        bar.addSeparator()

        # Datei-Gruppe direkt nach dem Burger: Öffnen, Speichern, Vorlage laden.
        bar.addAction(self._act_file_open)
        bar.addAction(self._act_file_save)
        bar.addWidget(self._build_template_button(bar))
        bar.addSeparator()

        bar.addAction(self._act_add_text)
        bar.addAction(self._act_add_image)
        bar.addAction(self._act_add_barcode)
        bar.addAction(self._act_add_qr)
        bar.addAction(self._act_add_line)
        bar.addAction(self._act_add_rect)
        bar.addSeparator()
        bar.addAction(self._act_front)
        bar.addAction(self._act_back)
        bar.addAction(self._act_delete)
        bar.addSeparator()
        bar.addAction(self._act_zoom_out)
        bar.addAction(self._act_zoom_fit)
        bar.addAction(self._act_zoom_in)
        bar.addAction(self._act_zoom_100)
        bar.addSeparator()
        bar.addAction(self._act_print_preview)
        bar.addAction(self._act_print)

    def _build_template_button(self, parent: QWidget) -> QToolButton:
        """Toolbar-Knopf "Vorlage laden": Klick oeffnet die Vorlagenliste."""
        button = QToolButton(parent)
        button.setObjectName("template_button")
        button.setIcon(icon("label"))
        button.setToolTip(tr("Vorlage laden"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda: self._fill_templates_into(menu))
        button.setMenu(menu)
        return button

    def _build_main_menu(self) -> QMenu:
        """Alle Befehle in einem einzigen Menue (Hamburger-Menue).

        Die Befehle liegen bereits als :class:`QAction` vor und werden mit der
        Toolbar geteilt - so bleiben Icons, Shortcuts und der Aktivierungs-
        zustand automatisch synchron.
        """
        menu = QMenu(self)
        menu.addSection(tr("Datei"))
        for act in (
            self._act_file_open,
            self._act_file_save,
            self._act_file_save_as,
        ):
            menu.addAction(act)
        self._build_template_menu(menu)
        menu.addSection(tr("Einfügen"))
        for act in (
            self._act_add_text,
            self._act_add_image,
            self._act_add_barcode,
            self._act_add_qr,
            self._act_add_line,
            self._act_add_rect,
        ):
            menu.addAction(act)
        menu.addSection(tr("Bearbeiten"))
        for act in (self._act_front, self._act_back, self._act_delete):
            menu.addAction(act)
        menu.addSection(tr("Etikett"))
        for act in self._media_panel.orientation_actions():
            menu.addAction(act)
        menu.addSection(tr("Ansicht"))
        for act in (
            self._act_print_preview,
            self._act_panel_left,
            self._act_panel_right,
            self._act_zoom_out,
            self._act_zoom_fit,
            self._act_zoom_in,
            self._act_zoom_100,
        ):
            menu.addAction(act)
        menu.addSection(tr("Drucken"))
        menu.addAction(self._act_print)
        menu.addSeparator()
        self._build_language_menu(menu)
        menu.addAction(self._act_about)
        menu.addAction(self._act_quit)
        return menu

    def _build_template_menu(self, menu: QMenu) -> None:
        """„Vorlagen": eingebaute und eigene Etiketten als Untermenue."""
        submenu = menu.addMenu(icon("label"), tr("Vorlagen"))
        submenu.aboutToShow.connect(self._fill_template_menu)
        self._template_menu = submenu
        self._fill_template_menu()

    def _fill_template_menu(self) -> None:
        """Vorlagenliste im Menue fuellen (siehe :meth:`_fill_templates_into`)."""
        self._fill_templates_into(self._template_menu)

    def _fill_templates_into(self, submenu: QMenu) -> None:
        """Vorlagenliste fuellen - auch die eigenen, die gerade dazukamen.

        Dieselbe Liste speist das Menue und den Toolbar-Knopf "Vorlage laden".
        """
        submenu.clear()
        for name, data in templates.builtins():
            action = submenu.addAction(icon("label"), name)
            action.setToolTip(tr("Vorlage anlegen: {name}").format(name=name))
            action.triggered.connect(partial(self._on_template_builtin, name))
        own = templates.list_user()
        if own:
            submenu.addSeparator()
            for path in own:
                action = submenu.addAction(icon("open"), path.stem)
                action.setToolTip(tr("Eigene Vorlage öffnen"))
                action.triggered.connect(partial(self._on_template_open, str(path)))
        submenu.addSeparator()
        action = submenu.addAction(icon("save"), tr("Als Vorlage speichern…"))
        action.setToolTip(tr("Das aktuelle Etikett als Vorlage ablegen"))
        action.triggered.connect(self._on_template_save)

    def _on_template_builtin(self, name: str) -> None:
        """Eingebaute Vorlage anlegen: ein neues, ungespeichertes Etikett."""
        data = templates.find_builtin(name)
        if data is None:
            return
        self._apply_template(data, tr("Vorlage angelegt: {name}").format(name=name))

    def _on_template_open(self, path: str) -> None:
        """Eigene Vorlage oeffnen - gleiche Datei wie ein gespeichertes Etikett."""
        try:
            data = document.load(path)
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Vorlagen"), str(exc))
            return
        self._apply_template(
            data, tr("Vorlage geöffnet: {name}").format(name=Path(path).name)
        )

    def _apply_template(self, data: dict, message: str) -> None:
        """Vorlage anwenden - bewusst als *neues* Etikett ohne Dateinamen.

        Sonst wuerde „Speichern" das zuletzt geoeffnete Etikett ueberschreiben.
        """
        self._apply_document(data)
        self._document_path = ""
        self._document_dirty = True
        self._update_window_title()
        self.statusBar().showMessage(message, 8000)

    def _on_template_save(self) -> None:
        """Aktuelles Etikett als eigene Vorlage ablegen."""
        ask_text(
            self,
            title=tr("Als Vorlage speichern"),
            label=tr("Name der Vorlage:"),
            default=(
                Path(self._document_path).stem if self._document_path else ""
            ),
            on_ok=self._save_template_named,
        )

    def _save_template_named(self, name: str) -> None:
        if not name.strip():
            return
        try:
            path = templates.save_user(name, self._document_data())
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Als Vorlage speichern"), str(exc))
            return
        self.statusBar().showMessage(
            tr("Vorlage gespeichert: {name}").format(name=path.stem), 8000
        )

    def _build_language_menu(self, menu: QMenu) -> None:
        """Sprachwahl als Untermenue ("Deutsch"/"English")."""
        submenu = menu.addMenu(icon("language"), tr("Sprache"))
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        for code in LANGUAGES:
            action = QAction(language_name(code), self)
            action.setCheckable(True)
            action.setChecked(code == language())
            action.triggered.connect(
                lambda _checked=False, value=code: self.switch_language(value)
            )
            self._language_group.addAction(action)
            submenu.addAction(action)

    # ------------------------------------------------------------ Sprache --
    def switch_language(self, code: str) -> None:
        """Sprache umstellen - die Oberflaeche wird dafuer neu aufgebaut.

        Ein kompletter Neuaufbau statt einzelner Texte sorgt dafuer, dass auch
        jede Formularbeschriftung, jeder Tooltip und jede Liste mitkommt. Der
        Inhalt des Etiketts und alle Einstellungen werden uebernommen.

        Das neue Fenster wird **vor** dem Schliessen des alten gezeigt: sonst
        gilt das letzte Fenster als geschlossen und Qt beendet das Programm.
        """
        if code not in LANGUAGES or code == language():
            return
        state = self._state()
        set_language(code)
        QLocale.setDefault(QLocale(code))
        self._settings.language = code
        self._settings.sync()

        window = MainWindow(self._settings)
        window.apply_state(state)
        window.setGeometry(self.geometry())
        window.setWindowState(self.windowState())
        window.show()
        _remember_window(window)
        self.close()

    def _state(self) -> dict[str, Any]:
        """Bedienzustand fuer einen Neuaufbau der Oberflaeche (Sprachwechsel)."""
        return {
            "media": self._media_panel.state(),
            "items": self._canvas.items_serialized(),
            "preview": self._act_print_preview.isChecked(),
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "hq": self._hq_check.isChecked(),
            "resolution": self._resolution().key,
            "copies": self._copies_spin.value(),
            "cut_mode": self._cut_combo.currentData(),
        }

    def apply_state(self, state: Mapping[str, Any]) -> None:
        """Zustand aus :meth:`_state` uebernehmen (nach einem Neuaufbau)."""
        self._media_panel.apply_state(state.get("media") or {})
        self._threshold_spin.setValue(int(state.get("threshold", DEFAULT_THRESHOLD)))
        self._dither_check.setChecked(bool(state.get("dither", False)))
        self._hq_check.setChecked(bool(state.get("hq", False)))
        self._sync_resolution_options(prefer=str(state.get("resolution") or ""))
        self._copies_spin.setValue(int(state.get("copies", 1)))
        cut_mode = self._cut_combo.findData(str(state.get("cut_mode") or CUT_EACH))
        if cut_mode >= 0:
            self._cut_combo.setCurrentIndex(cut_mode)
        # Erst wenn beide Werte stehen: „Nur am Ende" haengt an der Kopienzahl.
        self._sync_cut_options()
        self._canvas.load_items(list(state.get("items") or []))
        self._recompute_canvas()
        self._schedule_refresh()
        if state.get("preview"):
            self._act_print_preview.setChecked(True)
        self._canvas.setFocus()

    # ------------------------------------------------------------- Settings --
    def _apply_saved_settings(self) -> None:
        """Einstellungen uebernehmen - erst alle lesen, dann setzen.

        Die Werte muessen *vor* dem Setzen gelesen werden: das Setzen loest
        ``changed`` aus, und dieser Slot schreibt den gerade gueltigen Zustand
        zurueck in die Einstellungen. Wird zwischendurch gelesen, steht dort
        schon der Standarddrucker - die gespeicherte USB-Adresse war damit beim
        naechsten Start verloren.
        """
        geometry = self._settings.restore_geometry()
        address = self._settings.address
        model = self._settings.model
        last_label = self._settings.last_label
        panel_left = self._settings.panel_left_visible
        panel_right = self._settings.panel_right_visible
        threshold = self._settings.threshold
        dither = self._settings.dither
        hq = self._settings.hq
        resolution = self._settings.print_resolution
        copies = self._settings.copies
        cut_mode = self._settings.cut_mode

        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1320, 860)
        index = self._media_panel._model_combo.findData(model)
        if index >= 0:
            self._media_panel._model_combo.setCurrentIndex(index)
        self._media_panel.set_address(address)
        if last_label:
            self._media_panel.select_label(last_label)
        # Zuletzt gewaehlte Panel-Sichtbarkeit wiederherstellen (kleine Screens).
        self._act_panel_left.setChecked(panel_left)
        self._act_panel_right.setChecked(panel_right)
        # Druckoptionen wiederherstellen (Tintenmenge, Dithering, Aufloesung,
        # HQ, Kopien, Zuschnitt). Die Aufloesung erst *nach* dem Modell - ihre
        # Liste haengt am Drucker.
        self._threshold_spin.setValue(threshold)
        self._dither_check.setChecked(dither)
        self._hq_check.setChecked(hq)
        self._sync_resolution_options(prefer=resolution)
        self._copies_spin.setValue(copies)
        index = self._cut_combo.findData(cut_mode)
        if index >= 0:
            self._cut_combo.setCurrentIndex(index)
        self._sync_cut_options()
        self._schedule_refresh()

    # ---------------------------------------------------------- Media-Sync --
    def _on_media_changed(self) -> None:
        if self._adjusting:
            return
        self._recompute_canvas()
        self._settings.last_label = self._media_panel.label_id()
        self._settings.address = self._media_panel.address()
        self._settings.model = self._media_panel.model_id()
        # Ein anderes Modell hat andere Aufloesungen.
        self._sync_resolution_options()
        self._on_selection_changed()
        self._schedule_refresh()

    def _recompute_canvas(self) -> None:
        self._adjusting = True
        try:
            orientation = self._media_panel.orientation()
            content = (
                self._content_length_dots(orientation)
                if self._media_panel.auto_length()
                else 0
            )
            length = self._media_panel.label_length_dots(content)
            self._media_panel.set_content_dots(content)
            self._canvas.set_label(
                self._media_panel.label, length, orientation=orientation
            )
        finally:
            self._adjusting = False

    def _content_length_dots(self, orientation: media.Orientation) -> int:
        """Laenge des Inhalts in Bandrichtung (Dots), inkl. Rand an der Bandkante."""
        rect = self._canvas.scene().itemsBoundingRect()
        if rect.isNull():
            return 0
        margins = self._media_panel.margins()
        if orientation is media.Orientation.ALONG:
            return int(rect.right()) + media.mm_to_dots(margins.right)
        return int(rect.bottom()) + media.mm_to_dots(margins.bottom)

    # ----------------------------------------------------------- Rendering --
    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def _current_render(self, *, rotate: bool = False, scale: int = 1) -> Image.Image:
        """Rendere die Designflaeche.

        ``rotate=True`` (Druckpfad, Ausrichtung ``ALONG``) dreht das Ergebnis in
        die Bandorientierung; ohne Drehung passt es 1:1 auf den Canvas - genau
        das braucht die Druckvorschau als Overlay.

        ``scale=2`` rendert feiner (600-dpi-Modus, siehe
        :meth:`LabelCanvas.render_printable`).

        Die Textmarke blendet :meth:`LabelCanvas.render_printable` aus: sonst
        landet die blinkende Einfuegemarke als duenne Linie in Vorschau und
        Etikett.
        """
        return self._canvas.render_printable(rotate=rotate, scale=scale)

    def _print_scale(self) -> int:
        """Renderfaktor fuer den Druck (1 = 300 dpi, 2 = 600-dpi-Modus).

        Die Vorschau rendert mit demselben Faktor - sie zeigt also genau das,
        was in der gewaehlten Aufloesung an den Drucker geht.
        """
        return self._resolution().scale

    def _for_print(self) -> Image.Image:
        """Bild fuer den Drucker: immer exakt ``dots_printable[0]`` breit.

        Im 600-dpi-Modus ist es ``DPI_600_SCALE`` mal so gross - genau das
        erwartet ``convert()`` dann (``dots_expected``); die Laenge bleibt, weil
        der Drucker die Zeilen mit halbem Abstand setzt.
        """
        rotate = self._media_panel.orientation().rotates_for_print
        return self._current_render(rotate=rotate, scale=self._print_scale())

    def _refresh_now(self) -> None:
        """Druckvorschau und Tintenanteil aktualisieren (entprellt).

        Gerendert wird mit dem Faktor des **Druckpfads**: die Vorschau zeigt
        damit immer die echten Druckdaten. Im 600-dpi-Modus wird das 1-bit-Bild
        fuer das Overlay auf Canvas-Groesse heruntergerechnet (Box-Filter),
        waehrend der Tintenanteil auf den vollen Daten beruht.

        Der Tintenanteil wird immer berechnet - er zeigt sofort, was Tintenmenge
        und Dithering bewirken, auch wenn die Vorschau aus ist.
        """
        scale = self._print_scale()
        try:
            image = self._current_render(scale=scale)
        except Exception as exc:  # pragma: no cover - defensiv
            self.statusBar().showMessage(
                tr("Renderfehler: {error}").format(error=exc)
            )
            return
        options = self._preview_options()
        if self._canvas.print_preview:
            printable = binarize(image, options)
            self._canvas.set_print_image(
                to_qimage(reduce_for_display(printable, scale))
            )
        ratio = ink_ratio(image, options)
        self._ink_label.setText(
            tr("Tinte: {value} %").format(
                value=QLocale().toString(ratio * 100, "f", 1)
            )
        )

    def _preview_options(self) -> PreviewOptions:
        return PreviewOptions(
            threshold=self._threshold_spin.value(),
            dither=self._dither_check.isChecked(),
        )

    def _on_toggle_print_preview(self, enabled: bool) -> None:
        if enabled:
            # Die vorherige Ansicht merken, um sie beim Verlassen
            # wiederherzustellen.
            self._preview_view = (
                self._canvas.transform().m11(),
                self._canvas.mapToScene(self._canvas.viewport().rect().center()),
            )
            # 1:1 zeigt die echten Druckpunkte. Nur beim *Verkleinern* verliert
            # das 1-bit-Bild feine Linien - wer schon vergroessert hat, bleibt
            # so stehen.
            if self._canvas.transform().m11() < 1.0:
                self._canvas.zoom_100()
        self._canvas.set_print_preview(enabled)
        if enabled:
            self._refresh_now()
            self.statusBar().showMessage(
                tr("Druckvorschau aktiv - echte 1-bit-Ausgabe bei 1:1 (Esc beendet)"),
                4000,
            )
        else:
            self._canvas.set_print_image(None)
            self._restore_preview_view()
            self.statusBar().showMessage(tr("Druckvorschau aus"), 2000)
        self._update_zoom_label()

    def _restore_preview_view(self) -> None:
        """Nach dem Verlassen der Vorschau zurueck zur vorherigen Ansicht."""
        if self._preview_view is None:
            return
        scale, centre = self._preview_view
        self._preview_view = None
        self._canvas.zoom_by(scale / max(1e-6, self._canvas.transform().m11()))
        self._canvas.centerOn(centre)
        self._update_zoom_label()

    def _exit_print_preview(self) -> None:
        self._act_print_preview.setChecked(False)

    # ------------------------------------------------------------- Items ----
    def _default_item_pos(self) -> QPointF:
        margins = self._media_panel.margins()
        return QPointF(media.mm_to_dots(margins.left) + 10, media.mm_to_dots(margins.top) + 10)

    def _default_font_size(self) -> int:
        return max(16, int(self._canvas.height_dots * 0.25) or 40)

    def _fit_item_into_label(self, item) -> bool:
        """Zu grosse Objekte auf die bedruckbare Flaeche verkleinern.

        Beim Einfuegen eines Fotos ist das der Normalfall: ein 2400 px breites
        Bild auf ein 50-mm-Band wuerde sonst stillschweigend am Bandrand
        abgeschnitten. Verkleinert wird nur, nie vergroessert, und immer im
        Seitenverhaeltnis. Die Hoehe ist nur bei fester Etikettenlaenge eine
        harte Grenze - bei "Auto Length (Inhalt)" waechst das Etikett mit dem
        Inhalt, dann begrenzt allein die Bandbreite.

        :returns: ``True``, wenn das Objekt verkleinert wurde.
        """
        area = self._canvas.printable_rect()
        width, height = self._canvas.item_scene_size(item)
        if width <= 0 or height <= 0:
            return False
        limit_w = area.width()
        limit_h = area.height() if not self._media_panel.auto_length() else None
        factor = limit_w / width
        if limit_h is not None:
            factor = min(factor, limit_h / height)
        if factor >= 1.0:
            return False
        item.apply_resize(width * factor, height * factor)
        return True

    def _add_item(self, item, pos: QPointF | None = None) -> None:
        self._fit_item_into_label(item)
        item.setPos(pos if pos is not None else self._default_item_pos())
        if isinstance(item, TextItem):
            item.document().contentsChanged.connect(self._on_text_edited)
            item.editing_finished.connect(self._on_text_editing_finished)
        self._canvas.add_item(item)
        self._canvas.setFocus()
        self._mark_document_dirty()
        self._recompute_canvas()
        self._schedule_refresh()
        self._on_selection_changed()

    def _new_text(self, pos: QPointF | None = None, text: str = "") -> TextItem:
        """Neues Textfeld anlegen und direkt bearbeiten.

        Bewusst **ohne Platzhaltertext**: der Doppelklick setzt nur den Cursor,
        getippt wird sofort der eigene Text. Bleibt das Feld leer, wird es beim
        Beenden der Bearbeitung wieder verworfen (siehe
        :meth:`_on_text_editing_finished`) - wie im P-touch Editor.
        """
        item = TextItem(text, font_pixel_size=self._default_font_size())
        self._add_item(item, pos)
        item.start_editing()
        return item

    def _add_text(self) -> None:
        self._new_text()

    def _on_text_requested(self, scene_pos: QPointF) -> None:
        self._new_text(scene_pos)

    def _on_text_editing_finished(self) -> None:
        """Leer gebliebene Textfelder verwerfen.

        Ein Doppelklick legt ein leeres Feld an; tippt man nichts und klickt
        daneben, soll kein unsichtbares Objekt im Etikett zurueckbleiben.
        Das Entfernen wird verzoegert, weil das Signal aus dem Fokus-Event des
        Items kommt - dort darf es sich nicht selbst aus der Szene nehmen.
        """
        item = self.sender()
        if not isinstance(item, TextItem) or str(item.toPlainText()).strip():
            return
        QTimer.singleShot(0, lambda: self._discard_text_if_empty(item))

    def _discard_text_if_empty(self, item: TextItem) -> None:
        if item.scene() is None or str(item.toPlainText()).strip():
            return
        # Laeuft die Bearbeitung inzwischen wieder (z. B. nach einem Refresh,
        # der die Textmarke ausblendet), bleibt das Feld stehen - verworfen
        # wird nur, was wirklich nicht mehr in Bearbeitung ist.
        if item.is_editing:
            return
        self._canvas.remove_item(item)
        self._on_items_changed()

    def _on_text_edited(self) -> None:
        self._recompute_canvas()
        self._schedule_refresh()

    def _on_selection_changed(self) -> None:
        selection = self._canvas.selected_items()
        item = selection[0] if len(selection) == 1 else None
        allow_red = self._media_panel.model.two_color and self._media_panel.label.color.supports_red
        self._inspector.set_item(item, allow_red=allow_red)

    def _on_inspector_changed(self) -> None:
        self._mark_document_dirty()
        self._canvas.viewport().update()
        self._recompute_canvas()
        self._schedule_refresh()

    def _delete_selected(self) -> None:
        """Objekte loeschen - und das Dokument als geaendert markieren."""
        self._mark_document_dirty()
        self._canvas.delete_selected()

    def _on_zoom_changed(self, percent: float) -> None:
        self._update_zoom_label(percent)

    def _update_zoom_label(self, percent: float | None = None) -> None:
        """Zoomanzeige - mit Hinweis, wenn die Vorschau nicht 1:1 ist.

        Die Vorschau zeigt die echten Druckpunkte nur ab 1:1; darunter
        verschwinden feine Linien im 1-bit-Bild.
        """
        if percent is None:
            percent = self._canvas.transform().m11() * 100.0
        text = tr("Zoom {percent} %").format(percent=f"{percent:.0f}")
        if self._canvas.print_preview and percent < 99.5:
            text += " " + tr("· Vorschau: 1:1 für Details (Strg+1)")
        self._zoom_label.setText(text)

    def _on_item_double_clicked(self, item) -> None:
        self._on_selection_changed()

    def _on_scene_changed(self, *args) -> None:
        """Live-Vorschau waehrend direkter Manipulation (entprellt)."""
        if not self._adjusting:
            self._schedule_refresh()

    def _on_items_changed(self) -> None:
        """Nach Abschluss einer Geste: Bandgroesse + Inspector aktualisieren."""
        self._canvas.viewport().update()
        self._recompute_canvas()
        self._schedule_refresh()
        self._on_selection_changed()

    def _on_image_dropped(self, path: str, scene_pos: QPointF) -> None:
        try:
            item = ImageItem.from_file(path)
        except ValueError as exc:
            show_message(self, "warning", tr("Bild"), str(exc))
            return
        self._fit_item_into_label(item)
        width, height = self._canvas.item_scene_size(item)
        pos = QPointF(scene_pos.x() - width / 2, scene_pos.y() - height / 2)
        self._add_item(item, pos)

    def _on_text_dropped(self, text: str, scene_pos: QPointF) -> None:
        text = text.strip()
        if not text:
            return
        self._add_item(TextItem(text, font_pixel_size=self._default_font_size()), scene_pos)

    def _build_context_menu(self, scene_pos: QPointF) -> QMenu:
        menu = QMenu(self)
        menu.addAction(
            icon("text"),
            tr("Text einfügen"),
            lambda: self._on_text_requested(scene_pos),
        )
        menu.addAction(icon("image"), tr("Bild…"), self._add_image)
        menu.addAction(icon("barcode"), tr("Barcode…"), self._add_barcode)
        menu.addAction(icon("qr"), tr("QR-Code…"), self._add_qr)
        menu.addAction(icon("line"), tr("Linie"), self._add_line)
        menu.addAction(icon("rect"), tr("Rahmen"), self._add_rect)
        if self._canvas.selected_items():
            menu.addSeparator()
            menu.addAction(
                icon("front"), tr("In den Vordergrund"), lambda: self._bump_z(+1)
            )
            menu.addAction(
                icon("back"), tr("In den Hintergrund"), lambda: self._bump_z(-1)
            )
            menu.addAction(icon("delete"), tr("Löschen"), self._delete_selected)
        return menu

    def _show_context_menu(self, global_pos, scene_pos: QPointF) -> None:
        self._build_context_menu(scene_pos).exec(global_pos)

    def _add_image(self) -> None:
        def _selected(path: str | None) -> None:
            if not path:
                return
            self._settings.image_dir = str(Path(path).parent)
            try:
                item = ImageItem.from_file(path)
            except ValueError as exc:
                show_message(self, "warning", tr("Bild"), str(exc))
                return
            self._add_item(item)

        choose_file(
            self,
            caption=tr("Bild wählen"),
            name_filter=tr(
                "Bilder (*.png *.jpg *.jpeg *.bmp *.gif);;Alle Dateien (*)"
            ),
            on_selected=_selected,
            start_dir=self._settings.image_dir,
        )

    def _add_barcode(self) -> None:
        def _with_symbology(symbology: str) -> None:
            def _with_value(value: str) -> None:
                if not value:
                    return
                try:
                    item = BarcodeItem(
                        value,
                        symbology,
                        height_dots=max(60, int(self._canvas.height_dots * 0.4)),
                    )
                except ValueError as exc:
                    show_message(self, "warning", tr("Barcode"), str(exc))
                    return
                self._add_item(item)

            ask_text(self, title=tr("Barcode"), label=tr("Inhalt"), on_ok=_with_value)

        ask_choice(
            self,
            title=tr("Barcode"),
            label=tr("Symbologie"),
            items=BARCODE_SYMBOLOGIES,
            on_ok=_with_symbology,
        )

    def _add_qr(self) -> None:
        def _with_value(value: str) -> None:
            if not value:
                return
            item = QRItem(value, size_dots=max(60, int(self._canvas.height_dots * 0.5)))
            self._add_item(item)

        ask_text(
            self,
            title=tr("QR-Code"),
            label=tr("Inhalt"),
            default="https://",
            on_ok=_with_value,
        )

    def _add_line(self) -> None:
        width = self._canvas.printable_rect().width()
        item = LineItem(0, 0, int(width * 0.6), 0, width_px=3)
        self._add_item(item)

    def _add_rect(self) -> None:
        height = self._canvas.height_dots
        item = RectItem(
            QRectF(0, 0, int(self._canvas.printable_rect().width() * 0.6), int(max(40, height * 0.4)))
        )
        self._add_item(item)

    def _bump_z(self, direction: int) -> None:
        for item in self._canvas.selected_items():
            item.setZValue(item.zValue() + direction)

    # -------------------------------------------------------------- Print ---
    def _on_print(self) -> None:
        if self._print_worker is not None and self._print_worker.isRunning():
            return
        config = self._media_panel.printer_config()
        if not config.address:
            show_message(
                self,
                "warning",
                tr("Keine Druckeradresse"),
                tr("Im Panel unter „Drucker“ Anschluss und Adresse wählen."),
            )
            return
        try:
            image = self._for_print()
        except Exception as exc:
            show_message(
                self,
                "critical",
                tr("Rendern"),
                tr("Etikett konnte nicht gerendert werden:\n{error}").format(
                    error=exc
                ),
            )
            return
        label = self._media_panel.label
        copies = self._copies_spin.value()
        options = {
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "hq": self._hq(),
            "dpi_600": self._resolution().dpi_600,
            "red": self._media_panel.use_red(),
            "copies": copies,
            "cut_mode": self._cut_combo.currentData(),
        }
        self._print_button.setEnabled(False)
        message = (
            tr("Sende {count} Kopien an {address}…")
            if copies > 1
            else tr("Sende an {address}…")
        )
        self.statusBar().showMessage(
            message.format(count=copies, address=config.address)
        )
        self._print_worker = PrintWorker(image, label, config, options)
        self._print_worker.succeeded.connect(self._on_print_succeeded)
        self._print_worker.failed.connect(self._on_print_failed)
        self._print_worker.finished.connect(lambda: self._print_button.setEnabled(True))
        self._print_worker.start()

    def _on_print_succeeded(self, status: dict) -> None:
        self.statusBar().showMessage(
            tr("Druckauftrag gesendet (outcome={outcome}).").format(
                outcome=status.get("outcome")
            ),
            8000,
        )

    def _on_print_failed(self, message: str) -> None:
        self.statusBar().showMessage(tr("Druck fehlgeschlagen."), 8000)
        hint = access.failure_hint(message)
        if hint:
            message = f"{message}\n\n{hint}"
        show_message(self, "critical", tr("Druckfehler"), message, selectable=bool(hint))
    # --------------------------------------------------------- USB-Zugriff --
    def _on_usb_permission(self) -> None:
        """udev-Regel einrichten: das System fragt dabei nach dem Passwort.

        Der Befehl laeuft als eigener Prozess (``pkexec`` + Helfer), damit die
        Oberflaeche waehrend des Passwort-Dialogs bedienbar bleibt.
        """
        command = access.install_command()
        if command is None:
            self._show_manual_permission()
            return
        self._permission_process.start(command[0], command[1:])
        # Sicherheitsnetz: ein Agent, der den Dialog nicht zeigt, darf die
        # Anzeige nicht ewig auf "Passwort-Dialog" stehen lassen.
        self._permission_timer.start()
        self.statusBar().showMessage(tr("Zugriff einrichten: Passwort-Dialog …"))

    def _on_permission_timeout(self) -> None:
        self._permission_process.kill()
        self.statusBar().showMessage(tr("Kein Passwort-Dialog erschienen."), 8000)
        self._show_manual_permission()

    def _on_permission_finished(self, code: int, _status=None) -> None:
        self._permission_timer.stop()
        stderr = bytes(self._permission_process.readAllStandardError()).decode(
            "utf-8", "replace"
        )
        if code == 0:
            # Die Regel ist geschrieben, aber udev wendet sie erst kurz danach
            # an - sofortiges Nachsehen meldete sonst "keine Rechte" und man
            # klickt ein zweites Mal.
            self._access_attempts = ACCESS_RETRY_COUNT
            self._check_usb_access()
            return
        text = access.describe_failure(code, stderr)
        if access.rule_installed():
            text += "\n\n" + tr(
                "Regel ist schon eingerichtet – Drucker kurz ab- und anstecken."
            )
        show_message(self, "warning", tr("USB-Zugriff"), text, selectable=True)

    def _check_usb_access(self) -> None:
        """Rechte am Drucker nachsehen - und nachfassen, solange sie fehlen."""
        allowed = self._media_panel.refresh_access()
        if allowed is False and self._access_attempts > 0:
            self._access_attempts -= 1
            self._access_retry.start()
            self.statusBar().showMessage(tr("Zugriff einrichten: Rechte werden geprüft …"))
            return
        self._access_retry.stop()
        if allowed is False:
            self.statusBar().showMessage(
                tr("Rechte noch nicht aktiv – Drucker kurz ab- und anstecken."), 10_000
            )
            return
        self.statusBar().showMessage(
            tr("USB-Zugriff eingerichtet – der Drucker ist freigegeben."), 8000
        )

    def _show_manual_permission(self) -> None:
        """Ohne Passwort-Dialog bleibt der Einzeiler fuer das Terminal."""
        show_message(
            self,
            "info",
            tr("USB-Zugriff"),
            tr(
                "{reason}\n\nEinmalig im Terminal ausführen:\n\n    {command}"
            ).format(
                reason=access.reason_no_prompt(), command=access.manual_command()
            ),
            selectable=True,
        )

    # ------------------------------------------------------------- Detect ---
    def _on_network_search(self) -> None:
        """Netzwerk nach Druckern durchsuchen (im Hintergrund)."""
        if self._network_worker is not None and self._network_worker.isRunning():
            return
        self._network_cancel.clear()
        self._media_panel.set_network_searching(True)
        self.statusBar().showMessage(tr("Netzwerk wird durchsucht …"), 4000)
        self._network_worker = NetworkSearchWorker(self._network_cancel, self)
        self._network_worker.succeeded.connect(self._on_network_found)
        self._network_worker.finished.connect(self._on_network_search_done)
        self._network_worker.start()

    def _on_network_found(self, printers: list) -> None:
        """Gefundene Drucker in die Liste uebernehmen und kurz melden."""
        found = self._media_panel.refresh_network_devices(printers)
        if not found:
            self.statusBar().showMessage(
                tr("Keine Netzwerk-Drucker gefunden."), 8000
            )
            return
        if len(found) == 1:
            self.statusBar().showMessage(
                tr("Netzwerk-Drucker gefunden: {device}").format(
                    device=found[0].host
                ),
                8000,
            )
            return
        self.statusBar().showMessage(
            tr("{count} Netzwerk-Drucker gefunden").format(count=len(found))
            + " – "
            + tr("bitte in der Liste wählen."),
            8000,
        )

    def _on_network_search_done(self) -> None:
        self._media_panel.set_network_searching(False)

    def _on_usb_search(self) -> None:
        """Angeschlossene USB-Drucker suchen und in die Auswahl eintragen."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            devices = self._media_panel.refresh_usb_devices()
        finally:
            QApplication.restoreOverrideCursor()

        if not devices:
            show_message(
                self,
                "info",
                tr("USB suchen"),
                tr("Kein USB-Drucker gefunden. Kabel und Strom prüfen."),
            )
            return
        if len(devices) == 1:
            # Bei einem einzigen Geraet ist die Wahl klar - gleich uebernehmen.
            self._media_panel.select_usb_device(devices[0])
            self.statusBar().showMessage(
                tr("USB-Drucker übernommen: {device}").format(device=devices[0]),
                8000,
            )
            return
        self.statusBar().showMessage(
            tr("{count} USB-Drucker gefunden").format(count=len(devices))
            + " – "
            + tr("bitte in der Liste wählen."),
            8000,
        )

    def _on_detect_label(self) -> None:
        config = self._media_panel.printer_config()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            label = detect_label(config)
        except Exception as exc:  # pragma: no cover - defensiv
            QApplication.restoreOverrideCursor()
            show_message(
                self,
                "warning",
                tr("Band erkennen"),
                tr("Abfrage fehlgeschlagen:\n{error}").format(error=exc),
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        if label is None:
            # Der Knopf steht nur dort, wo es einen Rueckkanal gibt - hier ist
            # also nur noch die Frage, ob die Rechte fehlen oder das Band
            # nicht gemeldet wurde.
            if self._media_panel.access_allowed is False:
                reason = tr(
                    "Kein Zugriff auf den USB-Drucker.\n"
                    "Im Panel unter „Drucker“: „Zugriff einrichten“."
                )
            else:
                reason = tr("Kein Band gemeldet. Bitte von Hand wählen.")
            show_message(self, "info", tr("Band erkennen"), reason)
            return
        if self._media_panel.select_label(label.identifier):
            self.statusBar().showMessage(
                tr("Band erkannt: {name}").format(name=label.display_name), 8000
            )

    def _show_about(self) -> None:
        """„Über QLInux": Modellliste, Lizenz, Danksagung (siehe about.py)."""
        about.show_about(self)

    def _apply_window_icon(self) -> None:
        """App-Symbol aus ``assets/`` (fehlt es, bleibt das Qt-Standardsymbol)."""
        path = resources.asset(resources.APP_ICON)
        if path.exists():
            self.setWindowIcon(QIcon(str(path)))

    # ------------------------------------------------------------- Dateien --
    def _document_data(self) -> dict:
        """Aktuelles Design als Dokumentdaten (Band/Design + Objekte)."""
        return document.build(
            self._media_panel.media_state(), self._canvas.items_serialized()
        )

    def _apply_document(self, data: dict) -> None:
        """Dokumentdaten uebernehmen - Adresse und Anschluss bleiben stehen."""
        self._adjusting = True
        try:
            self._media_panel.apply_media_state(data.get("media") or {})
            self._canvas.load_items(list(data.get("items") or []))
        finally:
            self._adjusting = False
        self._recompute_canvas()
        self._schedule_refresh()

    def _set_document_path(self, path: str) -> None:
        self._document_path = path
        self._document_dirty = False
        self._update_window_title()

    def _mark_document_dirty(self) -> None:
        """Etwas am Etikett geaendert - Stern im Titel."""
        if self._adjusting or self._document_dirty:
            return
        self._document_dirty = True
        self._update_window_title()

    def _update_window_title(self) -> None:
        base = tr("QLInux - P-touch Editor")
        if not self._document_path and not self._document_dirty:
            self.setWindowTitle(base)
            return
        name = (
            Path(self._document_path).name
            if self._document_path
            else tr("Unbenannt")
        )
        star = "*" if self._document_dirty else ""
        self.setWindowTitle(f"{name}{star} – {base}")

    def _on_file_open(self) -> None:
        """„Öffnen…": Datei waehlen und laden."""
        choose_file(
            self,
            caption=tr("Etikett öffnen"),
            name_filter=tr("QLInux-Etiketten (*{suffix})").format(
                suffix=document.DOCUMENT_SUFFIX
            ),
            start_dir=self._settings.document_dir or "",
            on_selected=self._open_document_chosen,
        )

    def _open_document_chosen(self, path: str | None) -> None:
        if not path:
            return
        try:
            data = document.load(path)
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Etikett öffnen"), str(exc))
            return
        self._apply_document(data)
        self._set_document_path(path)
        self.statusBar().showMessage(
            tr("Etikett geöffnet: {name}").format(name=Path(path).name), 8000
        )

    def _on_file_save(self) -> None:
        """„Speichern": ohne Dateinamen erst nach ihm fragen."""
        if not self._document_path:
            self._on_file_save_as()
            return
        self._save_document_to(self._document_path)

    def _on_file_save_as(self) -> None:
        save_file(
            self,
            caption=tr("Etikett speichern"),
            name_filter=tr("QLInux-Etiketten (*{suffix})").format(
                suffix=document.DOCUMENT_SUFFIX
            ),
            start_dir=self._settings.document_dir or "",
            default_name=(
                Path(self._document_path).name
                if self._document_path
                else f"{tr('Unbenannt')}{document.DOCUMENT_SUFFIX}"
            ),
            on_selected=self._save_document_chosen,
        )

    def _save_document_chosen(self, path: str | None) -> None:
        if not path:
            return
        if not path.endswith(document.DOCUMENT_SUFFIX):
            path += document.DOCUMENT_SUFFIX
        self._save_document_to(path)

    def _save_document_to(self, path: str) -> None:
        """Design schreiben - ohne Dialog (auch fuer Tests und „Speichern")."""
        try:
            document.save(path, self._document_data())
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Etikett speichern"), str(exc))
            return
        self._settings.document_dir = str(Path(path).parent)
        self._set_document_path(path)
        self.statusBar().showMessage(
            tr("Etikett gespeichert: {name}").format(name=Path(path).name), 8000
        )

    # -------------------------------------------------------------- Close ---
    def closeEvent(self, event) -> None:  # noqa: N802
        # Laufende Netzwerksuche abbrechen, damit kein Thread das geschlossene
        # Fenster anspricht.
        self._network_cancel.set()
        if self._network_worker is not None and self._network_worker.isRunning():
            self._network_worker.wait(NETWORK_CANCEL_WAIT_MS)
        self._settings.save_geometry(self.saveGeometry())
        self._settings.address = self._media_panel.address()
        self._settings.model = self._media_panel.model_id()
        self._settings.last_label = self._media_panel.label_id()
        self._settings.panel_left_visible = self._act_panel_left.isChecked()
        self._settings.panel_right_visible = self._act_panel_right.isChecked()
        self._settings.threshold = self._threshold_spin.value()
        self._settings.dither = self._dither_check.isChecked()
        self._settings.print_resolution = self._resolution().key
        self._settings.hq = self._hq()
        self._settings.copies = self._copies_spin.value()
        self._settings.cut_mode = self._cut_combo.currentData()
        self._settings.sync()
        super().closeEvent(event)


def _system_language() -> str:
    """Erststart: die Systemsprache, wenn wir sie anbieten - sonst Deutsch."""
    code = QLocale.system().name().split("_")[0].lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("QLInux")
    settings = AppSettings()
    set_language(settings.language or _system_language())
    # Zahlen (Dezimaltrennzeichen) folgen der Sprache - auch in Spinboxen.
    QLocale.setDefault(QLocale(language()))
    window = MainWindow(settings)
    _remember_window(window)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
