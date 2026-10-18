"""Hauptfenster der QLInux-Anwendung (PySide6).

Aufbau:

* links: :class:`~ql_editor.media_panel.MediaPanel` (Band, Laenge, Margins)
* mitte: :class:`~ql_editor.canvas.LabelCanvas` (feste Pixelgroesse, Lineale)
* rechts: Vorschau (monochrom) + Druckoptionen
* Toolbar: Items einfuegen, Reihenfolge, Loeschen, Zoom, Drucken
* Reiter: mehrere Etiketten in einem Fenster (Canvas, Band, Undo je Reiter)

Es gibt **keine klassische Menueleiste**. Alle Befehle liegen in einem
Hamburger-Menue (``main_menu_button``) links in der Toolbar - das wirkt
moderner und ist unter Linux/Wayland die uebliche Loesung (einen globalen
Menuebalken wie unter macOS gibt es hier nicht).

Die GUI haelt keine eigene Wahrheit ueber Bandmasse: alles kommt aus
:mod:`ql_editor.media`. Gerendert wird ueber :mod:`ql_editor.renderer`,
gedruckt ueber :mod:`ql_editor.printer` (in einem Worker-Thread).
"""

from __future__ import annotations

import math
import os
import sys
import threading
from datetime import datetime
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any, Iterable, Mapping

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
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QUndoGroup,
    QUndoStack,
)
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
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import access
from . import about
from . import document
from . import instance, lbx
from . import media
from . import resources
from . import templates
from .canvas import LabelCanvas
from .discovery import discover_network_printers
from .history import design_snapshot, push_if_changed
from .i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    language,
    language_name,
    set_language,
    tr,
)
from .icons import icon
from .jobs import PrintHistoryDialog, PrintJob
from .inspector import InspectorPanel
from .items import (
    BarcodeItem,
    ClipArtItem,
    DateTimeItem,
    ImageItem,
    LineItem,
    QRItem,
    RectItem,
    ShapeItem,
    TableItem,
    TextItem,
)
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
from .adaptive import AdaptivePages
from .sheet import ask_choice, ask_save, ask_text, choose_file, save_file, show_message, show_widget
from .symbols import SymbolPicker
from .widgets import FeedIndicator, SmoothScrollArea, install_wheel_guard_recursive

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
#: Entprellung der Druckvorschau (Millisekunden).
PREVIEW_REFRESH_MS = 150
#: Startgroesse des Fensters (Breite, Hoehe).
DEFAULT_WINDOW_SIZE = (1320, 860)
#: Abstand neuer Objekte vom linken/oberen Rand (Druckpunkte).
DEFAULT_ITEM_INSET_DOTS = 10
#: Schriftgroesse neuer Textfelder als Anteil der Designflaechen-Hoehe.
DEFAULT_FONT_HEIGHT_RATIO = 0.25
#: Mindestschriftgroesse neuer Textfelder (Druckpunkte).
DEFAULT_FONT_MIN_PX = 16


#: Worker ohne Elternteil. Ein noch laufender Thread darf das schliessende
#: Fenster nicht als Qt-Parent haben - sonst reisst der Abbau den Thread mit
#: ("QThread: Destroyed while thread is still running").
_orphan_workers: list[QThread] = []


def _forget_orphan(worker: QThread) -> None:
    try:
        _orphan_workers.remove(worker)
    except ValueError:
        return


class PrintWorker(QThread):
    """Rendert nichts, sondern konvertiert und sendet in einem Thread."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, image: Image.Image, label, config, options: dict):
        super().__init__(None)
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
        del parent  # absichtlich kein Qt-Parent, siehe _orphan_workers
        super().__init__(None)
        self._cancel = cancel

    def run(self) -> None:  # noqa: D401
        printers = []
        try:
            printers = discover_network_printers(cancel=self._cancel)
        except Exception as exc:  # pragma: no cover - defensiv
            logger.info("Netzwerksuche fehlgeschlagen: %s", exc)
        self.succeeded.emit(printers)


class DetectLabelWorker(QThread):
    """Fragt das eingelegte Band abseits der Oberflaeche ab (USB-Readback)."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, config, parent=None):
        del parent  # absichtlich kein Qt-Parent, siehe _orphan_workers
        super().__init__(None)
        self._config = config

    def run(self) -> None:  # noqa: D401
        try:
            label = detect_label(self._config)
        except Exception as exc:  # pragma: no cover - defensiv
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(label)


#: Das aktuelle Hauptfenster. Beim Sprachwechsel entsteht ein neues Fenster;
#: diese Referenz haelt es am Leben - ein Fenster ohne Elternteil wird sonst
#: vom Garbage Collector eingesammelt.
_current_window: MainWindow | None = None


def _remember_window(window: MainWindow) -> None:
    global _current_window
    _current_window = window


def _signed_dots(mm: float) -> float:
    """Millimeter -> Punkte, auch negativ (ein Rand kann auch kleiner werden)."""
    return math.copysign(media.mm_to_dots(abs(mm)), mm) if mm else 0.0


#: Mindesthoehe des Objekt-Bereichs, wenn Objekt und Drucken untereinander stehen.
INSPECTOR_MIN_PX = 240


class LabelTab:
    """Ein offenes Etikett: eigener Canvas, Undo-Stapel und Dateizustand.

    Band und Ränder liegen im gemeinsamen Panel und werden beim Wechsel
    hierher geschrieben. Die Druckeradresse gehört nicht dazu.
    """

    def __init__(self, window: QWidget) -> None:
        self.canvas = LabelCanvas()
        self.canvas.setMinimumSize(240, 180)
        self.undo = QUndoStack(window)
        self.path = ""
        self.document_dirty = False
        self.media: dict[str, Any] = {}
        self.history_before: dict[str, Any] | None = None
        self.media_prev: dict[str, Any] | None = None
        self.margin_prev: dict[str, float] = {}
        self.margin_base: tuple[float, float] = (0.0, 0.0)
        self.preview_view: tuple[float, QPointF] | None = None

    def is_dirty(self) -> bool:
        """Inhalt geändert - unabhängig von der Druckeradresse."""
        try:
            stack_dirty = not self.undo.isClean()
        except RuntimeError:
            stack_dirty = False
        return self.document_dirty or stack_dirty


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None):
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle(tr("QLInux - P-touch Editor"))
        self._apply_window_icon()
        self.setWindowIcon(icon("label"))
        self._adjusting = False
        self._print_worker: PrintWorker | None = None
        self._print_jobs: list[PrintJob] = []
        self._pending_job: tuple[datetime, str, int, str] | None = None
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
        self._history_suppress = False
        #: Stern unabhängig vom Undo-Stapel (Druckeradresse gehört dem Rechner).
        self._address_dirty = False
        self._tab_ids: dict[int, LabelTab] = {}
        self._active: LabelTab | None = None
        self._undo_group = QUndoGroup(self)
        #: Sprachwechsel übernimmt das Etikett - dabei nicht nach dem Speichern fragen.
        self._accept_close = False
        self._close_prompt = False

        self._canvas_stack = QStackedWidget()
        self._canvas_stack.setMinimumSize(240, 180)
        self._host = PanelHost(self._canvas_stack, self)
        self._tab_chrome = self._build_tab_chrome()
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._tab_chrome)
        shell_layout.addWidget(self._host, 1)
        self.setCentralWidget(shell)

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
        self._refresh_timer.setInterval(PREVIEW_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh_now)
        self._detect_worker: DetectLabelWorker | None = None

        self._zoom_label = QLabel(tr("Zoom 100 %"))
        self._zoom_label.setToolTip(
            tr("Mausrad scrollt – Strg + Mausrad (oder Zoomgeste) zoomt")
        )
        self.statusBar().addPermanentWidget(self._zoom_label)
        self._hint_label = QLabel()
        self._hint_label.setVisible(False)
        hint_row = QWidget()
        hint_layout = QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.addStretch(1)
        hint_layout.addWidget(self._hint_label)
        hint_layout.addStretch(1)
        self.statusBar().addWidget(hint_row, 1)

        # Erstes Etikett, bevor Medien-Signale den Undo-Stapel anfassen.
        self._create_tab()

        self._media_panel.changed.connect(self._on_media_changed)
        self._media_panel.margins_reset.connect(self._sync_margin_base)
        self._margin_prev = {
            key: spin.value()
            for key, spin in self._media_panel._margin_spins.items()
        }
        for key, spin in self._media_panel._margin_spins.items():
            spin.valueChanged.connect(
                lambda value, k=key: self._on_margin_spin_changed(k, value)
            )
            spin.editingFinished.connect(
                lambda _=False: self._commit_history(tr("Ränder"))
            )
        self._media_panel.detect_requested.connect(self._on_detect_label)
        self._media_panel.usb_search_requested.connect(self._on_usb_search)
        self._media_panel.network_search_requested.connect(self._on_network_search)
        self._media_panel.usb_permission_requested.connect(self._on_usb_permission)
        self._inspector.changed.connect(self._on_inspector_changed)
        self._inspector.edit_begun.connect(self._capture_history)
        self._inspector.edit_committed.connect(
            lambda: self._commit_history(tr("Eigenschaften"))
        )
        self._inspector.rejected.connect(
            lambda message: self.statusBar().showMessage(message, 8000)
        )
        # Adresswechsel setzt den Stern unabhängig vom Undo-Stapel.
        self._media_panel.changed.connect(self._on_media_panel_dirty)

        # Rad-Ereignisse dürfen keine Werte in Feldern ändern (auch nicht in
        # den dynamisch erzeugten Inspector-Feldern - die sichern sich selbst).
        install_wheel_guard_recursive(self)

        # Gespeicherte Einstellungen anwenden.
        self._apply_saved_settings()
        self._on_media_changed()
        self._sync_margin_base()
        self._sync_media_prev()
        # Startzustand ist sauber - Medien-Sync oben zählt nicht als Bearbeitung.
        self._document_dirty = False
        self._address_dirty = False
        self._undo_stack.clear()
        self._undo_stack.setClean()
        self._stash_active()
        self._update_window_title()

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

    def _build_tab_chrome(self) -> QWidget:
        """Reiterleiste über dem Canvas, plus ein Knopf für ein neues Etikett."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 2, 6, 0)
        layout.setSpacing(2)
        self._tab_bar = QTabBar(bar)
        self._tab_bar.setObjectName("label_tab_bar")
        self._tab_bar.setDocumentMode(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self._tab_bar.setDrawBase(True)
        self._tab_bar.currentChanged.connect(self._on_tab_index_changed)
        self._tab_bar.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_plus = QToolButton(bar)
        self._tab_plus.setObjectName("tab_new_button")
        self._tab_plus.setIcon(icon("new"))
        self._tab_plus.setToolTip(tr("Neues Etikett (Strg+N)"))
        self._tab_plus.setAutoRaise(True)
        self._tab_plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tab_plus.clicked.connect(self._on_file_new)
        layout.addWidget(self._tab_bar)
        layout.addWidget(self._tab_plus)
        layout.addStretch(1)
        return bar

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

        # Objekt und Drucken untereinander, solange die Hoehe reicht. Wird es
        # knapp, wechseln sie in Reiter (siehe ql_editor.adaptive).
        print_area = self._scroll_wrap(self._build_print_panel())
        self._right_pages = AdaptivePages(
            [
                (
                    tr("Objekt"),
                    self._scroll_wrap(self._inspector),
                    lambda: INSPECTOR_MIN_PX,
                ),
                (
                    tr("Drucken"),
                    print_area,
                    lambda: print_area.widget().sizeHint().height(),
                ),
            ]
        )
        self._right_panel = OverlayPanel(
            tr("Eigenschaften & Druck"),
            self._right_pages,
            Qt.Edge.RightEdge,
            self,
        )
        self._host.add_panel(self._right_panel)

    def _build_print_panel(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        # Knapp bemessen: das Panel ist auf kleinen Bildschirmen nur ~170 px breit.
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Aufloesung: nur was das gewaehlte Modell kann (die Liste kommt aus den
        # Datenblaettern, siehe printer.resolution_options). Der High-Resolution-
        # Modus ist bewusst *nicht* voreingestellt - er druckt langsamer.
        resolution_label = QLabel(tr("Auflösung"))
        self._resolution_combo = QComboBox()
        self._resolution_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._resolution_combo.setMinimumContentsLength(8)
        resolution_label.setBuddy(self._resolution_combo)
        # Die Erklaerung zur gewaehlten Aufloesung steht im Tooltip des Feldes
        # (siehe _update_resolution_hint) - nicht dauerhaft im Panel.
        layout.addWidget(resolution_label)
        layout.addWidget(self._resolution_combo)

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
        self._cut_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._cut_combo.setMinimumContentsLength(8)
        self._cut_label.setBuddy(self._cut_combo)
        for mode, text in (
            (CUT_EACH, tr("Jede Kopie")),
            (CUT_AT_END, tr("Am Ende")),
            (CUT_NONE, tr("Aus")),
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
        self._print_button.clicked.connect(self._on_print)
        self._history_button = QToolButton()
        self._history_button.setIcon(icon("history"))
        self._history_button.setToolTip(tr("Druckverlauf dieser Sitzung anzeigen"))
        self._history_button.clicked.connect(self._show_print_history)
        self._history_button.setAutoRaise(False)
        # Gleiche Hoehe wie der Druckknopf: ein reiner Icon-Knopf ist sonst
        # niedriger und steht klein neben dem Text-Knopf.
        self._history_button.setFixedHeight(self._print_button.sizeHint().height())
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(6)
        button_row.addWidget(self._print_button, 16)
        button_row.addWidget(self._history_button, 3)

        # Feste Hoehe fuer zwei Zeilen: der Status springt nicht mehr beim Druck.
        self._last_job_label = QLabel(tr("Noch kein Auftrag"))
        self._last_job_label.setStyleSheet("color:#777;")
        status_height = 2 * self._last_job_label.fontMetrics().lineSpacing()
        self._feed_indicator = FeedIndicator()
        self._status_stack = QStackedWidget()
        self._status_stack.addWidget(self._last_job_label)
        self._status_stack.addWidget(self._feed_indicator)
        self._status_stack.setFixedHeight(status_height)

        layout.addWidget(self._dither_check)
        layout.addWidget(self._threshold_label)
        layout.addLayout(threshold_row)
        layout.addSpacing(8)
        layout.addLayout(copies_row)
        layout.addLayout(cut_row)
        layout.addStretch(1)
        layout.addWidget(self._status_stack)
        layout.addLayout(button_row)

        self._resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        self._threshold_spin.valueChanged.connect(self._schedule_refresh)
        self._dither_check.toggled.connect(self._on_dither_toggled)
        self._copies_spin.valueChanged.connect(self._sync_cut_options)
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
        self._resolution_combo.setToolTip(text)

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

        self._act_add_clipart = QAction(icon("clipart"), tr("Clip Art"), self)
        self._act_add_clipart.setToolTip(tr("Clip Art einfügen"))
        self._act_add_clipart.triggered.connect(self._add_clipart)

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

        self._act_add_table = QAction(icon("table"), tr("Tabelle"), self)
        self._act_add_table.setToolTip(tr("Tabelle einfügen"))
        self._act_add_table.triggered.connect(self._add_table)

        self._act_add_datetime = QAction(icon("datetime"), tr("Datum/Uhrzeit"), self)
        self._act_add_datetime.setToolTip(tr("Aktuelles Datum und aktuelle Uhrzeit einfügen"))
        self._act_add_datetime.triggered.connect(self._add_datetime)

        self._act_undo = self._undo_group.createUndoAction(self, tr("Rückgängig"))
        self._act_undo.setIcon(icon("undo"))
        self._act_undo.setToolTip(tr("Rückgängig (Strg+Z)"))
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_redo = self._undo_group.createRedoAction(self, tr("Wiederholen"))
        self._act_redo.setIcon(icon("redo"))
        self._act_redo.setToolTip(tr("Wiederholen (Strg+Umschalt+Z)"))
        self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)

        self._act_align_left = QAction(icon("align_left"), tr("Links ausrichten"), self)
        self._act_align_left.triggered.connect(lambda: self._align_selected("left"))
        self._act_align_hcenter = QAction(
            icon("align_hcenter"), tr("Horizontal zentrieren"), self
        )
        self._act_align_hcenter.triggered.connect(
            lambda: self._align_selected("hcenter")
        )
        self._act_align_right = QAction(
            icon("align_right"), tr("Rechts ausrichten"), self
        )
        self._act_align_right.triggered.connect(lambda: self._align_selected("right"))
        self._act_align_top = QAction(icon("align_top"), tr("Oben ausrichten"), self)
        self._act_align_top.triggered.connect(lambda: self._align_selected("top"))
        self._act_align_vcenter = QAction(
            icon("align_vcenter"), tr("Vertikal zentrieren"), self
        )
        self._act_align_vcenter.triggered.connect(
            lambda: self._align_selected("vcenter")
        )
        self._act_align_bottom = QAction(
            icon("align_bottom"), tr("Unten ausrichten"), self
        )
        self._act_align_bottom.triggered.connect(lambda: self._align_selected("bottom"))

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
        self._act_zoom_fit.triggered.connect(lambda: self._canvas.zoom_fit())

        self._act_zoom_in = QAction(icon("zoom_in"), tr("Vergrößern"), self)
        self._act_zoom_in.setToolTip(tr("Vergrößern (Strg ++)"))
        self._act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self._act_zoom_in.triggered.connect(lambda: self._canvas.zoom_in())

        self._act_zoom_out = QAction(icon("zoom_out"), tr("Verkleinern"), self)
        self._act_zoom_out.setToolTip(tr("Verkleinern (Strg +-)"))
        self._act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self._act_zoom_out.triggered.connect(lambda: self._canvas.zoom_out())

        self._act_zoom_100 = QAction(icon("zoom_100"), tr("1:1"), self)
        self._act_zoom_100.setToolTip(
            tr("Zoom 1:1 (Strg+1) - echte Druckpunkte,\n"
            "so wie der Drucker sie setzt")
        )
        self._act_zoom_100.setShortcut("Ctrl+1")
        self._act_zoom_100.triggered.connect(lambda: self._canvas.zoom_100())

        self._act_print = QAction(icon("print"), tr("Drucken"), self)
        self._act_print.setToolTip(tr("Drucken (Ctrl+P)"))
        self._act_print.setShortcut("Ctrl+P")
        self._act_print.triggered.connect(self._on_print)

        self._act_print_history = QAction(icon("history"), tr("Druckverlauf anzeigen"), self)
        self._act_print_history.setToolTip(tr("Druckverlauf dieser Sitzung anzeigen"))
        self._act_print_history.triggered.connect(self._show_print_history)


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
        self._act_file_new = QAction(icon("new"), tr("Neu"), self)
        self._act_file_new.setToolTip(tr("Neues Etikett (Strg+N)"))
        self._act_file_new.setShortcut(QKeySequence.StandardKey.New)
        self._act_file_new.triggered.connect(self._on_file_new)

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

        self._act_tab_close = QAction(icon("close"), tr("Reiter schließen"), self)
        self._act_tab_close.setToolTip(tr("Reiter schließen (Strg+W)"))
        self._act_tab_close.setShortcut(QKeySequence.StandardKey.Close)
        self._act_tab_close.triggered.connect(self._on_close_current_tab)

        self._act_tab_next = QAction(self)
        self._act_tab_next.setShortcut(QKeySequence.StandardKey.NextChild)
        self._act_tab_next.triggered.connect(self._on_next_tab)
        self._act_tab_prev = QAction(self)
        self._act_tab_prev.setShortcut(QKeySequence.StandardKey.PreviousChild)
        self._act_tab_prev.triggered.connect(self._on_previous_tab)
        self.addAction(self._act_tab_next)
        self.addAction(self._act_tab_prev)

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
        bar.addAction(self._act_file_new)
        bar.addAction(self._act_file_open)
        bar.addAction(self._act_file_save)
        bar.addWidget(self._build_template_button(bar))
        bar.addSeparator()

        bar.addAction(self._act_undo)
        bar.addAction(self._act_redo)
        bar.addSeparator()

        bar.addAction(self._act_add_text)
        bar.addAction(self._act_add_image)
        bar.addAction(self._act_add_clipart)
        bar.addAction(self._act_add_barcode)
        bar.addAction(self._act_add_qr)
        bar.addAction(self._act_add_table)
        bar.addAction(self._act_add_datetime)
        bar.addSeparator()
        bar.addWidget(self._build_shape_button(bar))
        bar.addWidget(self._build_align_button(bar))
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
        bar.addAction(self._act_print_history)

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

    def _build_shape_button(self, parent: QWidget) -> QToolButton:
        """Toolbar-Knopf "Formen": Klick oeffnet Linie, Rahmen, Pfeile und Formen."""
        button = QToolButton(parent)
        button.setObjectName("shape_button")
        button.setIcon(icon("shape"))
        button.setToolTip(tr("Formen einfügen"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        menu.addAction(icon("line"), tr("Linie"), self._add_line)
        menu.addAction(icon("rect"), tr("Rahmen"), self._add_rect)
        menu.addSeparator()
        for shape, label in (
            ("ellipse", tr("Ellipse")),
            ("triangle", tr("Dreieck")),
            ("star", tr("Stern")),
            ("arrow_right", tr("Pfeil rechts")),
            ("arrow_left", tr("Pfeil links")),
            ("arrow_double", tr("Doppelpfeil")),
        ):
            menu.addAction(icon(f"shape_{shape}"), label, lambda _=False, s=shape: self._add_shape(s))
        button.setMenu(menu)
        return button

    def _build_align_button(self, parent: QWidget) -> QToolButton:
        """Toolbar-Knopf "Ausrichten": Klick oeffnet die Ausrichtungen als Menue."""
        button = QToolButton(parent)
        button.setObjectName("align_button")
        button.setIcon(icon("align_left"))
        button.setToolTip(tr("Ausrichten"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for act in (
            self._act_align_left,
            self._act_align_hcenter,
            self._act_align_right,
            self._act_align_top,
            self._act_align_vcenter,
            self._act_align_bottom,
        ):
            menu.addAction(act)
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
            self._act_file_new,
            self._act_file_open,
            self._act_file_save,
            self._act_file_save_as,
            self._act_tab_close,
        ):
            menu.addAction(act)
        self._build_template_menu(menu)
        menu.addSection(tr("Einfügen"))
        for act in (
            self._act_add_text,
            self._act_add_image,
            self._act_add_clipart,
            self._act_add_barcode,
            self._act_add_qr,
            self._act_add_line,
            self._act_add_rect,
            self._act_add_table,
            self._act_add_datetime,
        ):
            menu.addAction(act)
        menu.addSection(tr("Bearbeiten"))
        for act in (
            self._act_undo,
            self._act_redo,
            self._act_align_left,
            self._act_align_hcenter,
            self._act_align_right,
            self._act_align_top,
            self._act_align_vcenter,
            self._act_align_bottom,
            self._act_front,
            self._act_back,
            self._act_delete,
        ):
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
        menu.addAction(self._act_print_history)
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

        Sonst würde „Speichern" das zuletzt geöffnete Etikett überschreiben.
        Liegt schon ein Etikett im Fenster, bekommt die Vorlage einen eigenen Reiter.
        """
        if not self._can_reuse_current():
            self._create_tab()
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

        Der Undo-Stapel geht dabei verloren (neues Fenster); der Stern im Titel
        bleibt ueber ``document_dirty`` / ``address_dirty`` erhalten. Der
        Druckverlauf der Sitzung wandert mit dem Zustand ins neue Fenster.
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
        # Das Etikett lebt im neuen Fenster weiter - nicht als ungespeichert nachfragen.
        self._accept_close = True
        self.close()

    def _state(self) -> dict[str, Any]:
        """Bedienzustand fuer einen Neuaufbau der Oberflaeche (Sprachwechsel)."""
        self._stash_active()
        tabs = [
            {
                "media": deepcopy(tab.media),
                "items": tab.canvas.items_serialized(),
                "path": tab.path,
                "document_dirty": tab.is_dirty(),
                "preview": tab.canvas.print_preview,
            }
            for tab in self._ordered_tabs()
        ]
        active = self._index_of(self._active) if self._active is not None else 0
        return {
            "media": self._media_panel.state(),
            "tabs": tabs,
            "active": active,
            "items": self._canvas.items_serialized(),
            "preview": self._act_print_preview.isChecked(),
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "hq": self._hq_check.isChecked(),
            "resolution": self._resolution().key,
            "copies": self._copies_spin.value(),
            "cut_mode": self._cut_combo.currentData(),
            "document_path": self._document_path,
            "document_dirty": self._is_document_dirty(),
            "address_dirty": self._address_dirty,
            "print_jobs": list(self._print_jobs),
        }

    def apply_state(self, state: Mapping[str, Any]) -> None:
        """Zustand aus :meth:`_state` uebernehmen (nach einem Neuaufbau)."""
        self._history_suppress = True
        try:
            self._media_panel.apply_state(state.get("media") or {})
        finally:
            self._history_suppress = False
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
        specs = state.get("tabs")
        if not specs:
            specs = [
                {
                    "media": dict(state.get("media") or {}),
                    "items": list(state.get("items") or []),
                    "path": str(state.get("document_path") or ""),
                    "document_dirty": bool(state.get("document_dirty")),
                    "preview": bool(state.get("preview")),
                }
            ]
        self._replace_tabs(list(specs), int(state.get("active") or 0))
        self._address_dirty = bool(state.get("address_dirty", False))
        self._print_jobs = list(state.get("print_jobs") or [])
        self._refresh_last_job_label()
        if self._canvas.print_preview and not self._act_print_preview.isChecked():
            self._act_print_preview.setChecked(True)
        else:
            self._sync_preview_action()
        self._update_window_title()
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
            self.resize(*DEFAULT_WINDOW_SIZE)
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
        # Das Band ist schon umgestellt. Eine offene Inspector-Aenderung
        # gehoert noch zum vorherigen Medium - sonst verschluckt sie der
        # Band-Befehl oder beide landen in einem Schritt.
        self._seal_open_inspector_edit()
        prev_media = self._media_prev
        self._media_prev = deepcopy(dict(self._media_panel.media_state()))
        self._recompute_canvas()
        self._settings.last_label = self._media_panel.label_id()
        self._settings.address = self._media_panel.address()
        self._settings.model = self._media_panel.model_id()
        # Ein anderes Modell hat andere Aufloesungen.
        self._sync_resolution_options()
        self._on_selection_changed()
        self._schedule_refresh()
        self._record_media_change(prev_media)

    def _record_media_change(self, prev_media: dict[str, Any] | None) -> None:
        """Band/Modell/Ausrichtung/Länge als eigenen Undo-Befehl ablegen.

        Ränder laufen über :meth:`_on_margin_spin_changed` (ein Befehl pro
        Feld, Commit bei ``editingFinished``) und werden hier uebersprungen,
        solange sich *nur* die Ränder geaendert haben. Ein Bandwechsel setzt
        die Ränder mit um - das gehoert dann in denselben Befehl.
        """
        if (
            prev_media is None
            or self._history_suppress
            or self._history_before is not None
        ):
            return
        now_media = self._media_prev or {}
        if prev_media == now_media:
            return
        only_margins = all(
            prev_media.get(key) == now_media.get(key)
            for key in set(prev_media) | set(now_media)
            if key != "margins"
        )
        if only_margins:
            return
        items = self._canvas.items_serialized()
        selection = self._selection_keys()
        before = design_snapshot(prev_media, items, selection)
        after = design_snapshot(now_media, items, selection)
        push_if_changed(
            self._undo_stack, before, after, self._restore_design, tr("Band")
        )

    def _sync_media_prev(self) -> None:
        """Bezug fuer den naechsten Band-Befehl auf den aktuellen Stand setzen."""
        self._media_prev = deepcopy(dict(self._media_panel.media_state()))

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
            margins = self._media_panel.margins()
            self._canvas.set_margins(
                margins.left, margins.right, margins.top, margins.bottom
            )
        finally:
            self._adjusting = False

    def _sync_margin_base(self) -> None:
        """Den Rand merken, auf den sich die Objekte beziehen (links, oben)."""
        margins = self._media_panel.margins()
        self._margin_base = (margins.left, margins.top)
        self._margin_prev = {
            key: spin.value()
            for key, spin in self._media_panel._margin_spins.items()
        }

    def _on_margin_spin_changed(self, key: str, value: float) -> None:
        """Randfeld geaendert: Undo merken, links/oben Objekte mitziehen."""
        if self._adjusting:
            self._margin_prev[key] = float(value)
            return
        self._seal_open_inspector_edit()
        if self._history_before is None:
            media = dict(self._media_panel.media_state())
            margins = dict(media.get("margins") or {})
            margins[key] = self._margin_prev.get(key, value)
            media["margins"] = margins
            self._history_before = design_snapshot(
                media, self._canvas.items_serialized(), self._selection_keys()
            )
        self._margin_prev[key] = float(value)
        if key in ("left", "top"):
            self._on_margin_edited()

    def _on_margin_edited(self) -> None:
        """Linker oder oberer Rand geaendert: die Objekte wandern mit.

        Der Rand ist der Abstand zur Bandkante - ändert er sich, verschiebt sich
        der Inhalt um dieselbe Strecke. Beim Laden und beim Bandwechsel passiert
        das nicht (dort wird der Bezug neu gesetzt, siehe _sync_margin_base).
        """
        if self._adjusting:
            return
        margins = self._media_panel.margins()
        base_left, base_top = self._margin_base
        dx = _signed_dots(margins.left - base_left)
        dy = _signed_dots(margins.top - base_top)
        self._sync_margin_base()
        if not dx and not dy:
            return
        # Klemme aus: die Laenge ist noch die alte und wuerde die Verschiebung
        # schlucken. Danach die Laenge aus der neuen Huelle.
        self._canvas.translate_items(dx, dy, clamp=False)
        self._recompute_canvas()
        self._schedule_refresh()

    # -------------------------------------------------------------- History --
    def _selection_keys(self) -> list[dict[str, Any]]:
        """Auswahl als Index in ``ordered_items`` - Position allein ist nicht eindeutig."""
        ordered = self._canvas.ordered_items()
        index_of = {id(item): index for index, item in enumerate(ordered)}
        return [
            {"index": index_of[id(item)]}
            for item in self._canvas.selected_items()
            if id(item) in index_of
        ]

    def _design_snapshot(self) -> dict[str, Any]:
        return design_snapshot(
            self._media_panel.media_state(),
            self._canvas.items_serialized(),
            self._selection_keys(),
        )

    def _capture_history(self) -> None:
        if self._adjusting or self._history_suppress or self._history_before is not None:
            return
        self._history_before = self._design_snapshot()

    def _commit_history(self, text: str = "") -> None:
        if self._adjusting or self._history_suppress:
            return
        before = self._history_before
        self._history_before = None
        after = self._design_snapshot()
        if push_if_changed(
            self._undo_stack, before, after, self._restore_design, text
        ):
            self._update_window_title()

    def _seal_open_inspector_edit(self) -> None:
        """Offene Inspector-Bearbeitung abschliessen, ohne das neue Medium mitzunehmen.

        ``changed`` vom Band-Panel kommt erst, wenn das Medium schon neu ist.
        Der Schnappschuss der Inspector-Aenderung behaelt deshalb das Medium
        aus ``before``; der Bandwechsel wird anschliessend ein eigener Schritt.
        """
        if not self._inspector.edit_open:
            return
        before = self._history_before
        self._history_before = None
        self._inspector.cancel_edit_tracking()
        if before is None:
            return
        after = design_snapshot(
            before.get("media") or {},
            self._canvas.items_serialized(),
            self._selection_keys(),
        )
        if push_if_changed(
            self._undo_stack, before, after, self._restore_design, tr("Eigenschaften")
        ):
            self._update_window_title()

    def _restore_design(self, snapshot: dict[str, Any]) -> None:
        """Medien und Objekte aus einem Undo-Schnappschuss setzen."""
        self._adjusting = True
        self._history_suppress = True
        try:
            self._media_panel.apply_media_state(snapshot.get("media") or {})
            loaded = self._canvas.load_items(list(snapshot.get("items") or []))
            self._sync_margin_base()
            keys = list(snapshot.get("selection") or [])
            self._canvas.scene().clearSelection()
            for key in keys:
                index = key.get("index")
                if isinstance(index, int) and 0 <= index < len(loaded):
                    loaded[index].setSelected(True)
                    continue
                # Aeltere Schnappschuesse: Position, wenn der Index fehlt.
                for item in loaded:
                    pos = item.pos()
                    if (
                        abs(pos.x() - float(key.get("x", 0))) < 0.5
                        and abs(pos.y() - float(key.get("y", 0))) < 0.5
                        and abs(item.zValue() - float(key.get("z", 0))) < 0.5
                    ):
                        item.setSelected(True)
                        break
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._wire_loaded_text_items()
        # Ueber den normalen Medien-Pfad: Aufloesungen, Einstellungen, Canvas.
        # ``_media_prev`` steht schon auf dem neuen Stand - kein neuer Befehl.
        self._sync_media_prev()
        self._on_media_changed()
        self._update_window_title()

    def _align_selected(self, mode: str) -> None:
        """Auswahl aneinander oder am Randrahmen ausrichten."""
        items = [
            item
            for item in self._canvas.selected_items()
            if hasattr(item, "to_dict")
        ]
        if not items:
            return
        self._capture_history()
        if len(items) == 1:
            ref = self._canvas.margin_rect()
        else:
            ref = items[0].sceneBoundingRect()
            for item in items[1:]:
                ref = ref.united(item.sceneBoundingRect())
        for item in items:
            box = item.sceneBoundingRect()
            dx = dy = 0.0
            if mode == "left":
                dx = ref.left() - box.left()
            elif mode == "hcenter":
                dx = ref.center().x() - box.center().x()
            elif mode == "right":
                dx = ref.right() - box.right()
            elif mode == "top":
                dy = ref.top() - box.top()
            elif mode == "vcenter":
                dy = ref.center().y() - box.center().y()
            elif mode == "bottom":
                dy = ref.bottom() - box.bottom()
            if dx or dy:
                item.moveBy(dx, dy)
        self._commit_history(tr("Ausrichten"))
        self._on_items_changed()

    def _on_media_panel_dirty(self) -> None:
        """Adresse/Anschluss: Stern ohne Undo-Eintrag."""
        if self._adjusting:
            return
        # Medien-Design laeuft ueber den Undo-Stapel (Ränder, Band, …).
        # Die Adresse gehoert dem Rechner - nur den Stern setzen.
        address = self._media_panel.address()
        if address != self._settings.address:
            self._address_dirty = True
            self._update_window_title()

    def _content_length_dots(self, orientation: media.Orientation) -> int:
        """Laenge des Inhalts in Bandrichtung (Dots), inkl. Rand an der Bandkante."""
        rect = self._canvas.scene().itemsBoundingRect()
        if rect.isNull():
            return 0
        margins = self._media_panel.margins()
        if orientation is media.Orientation.ALONG:
            edge = math.ceil(rect.right())
            return edge + media.mm_to_dots(margins.right)
        edge = math.ceil(rect.bottom())
        return edge + media.mm_to_dots(margins.bottom)

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
        inset = DEFAULT_ITEM_INSET_DOTS
        return QPointF(
            media.mm_to_dots(margins.left) + inset,
            media.mm_to_dots(margins.top) + inset,
        )

    def _default_font_size(self) -> int:
        return max(
            DEFAULT_FONT_MIN_PX,
            int(self._canvas.height_dots * DEFAULT_FONT_HEIGHT_RATIO)
            or DEFAULT_FONT_MIN_PX,
        )

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

    def _add_item(
        self, item, pos: QPointF | None = None, *, commit: bool = True, fit: bool = True
    ) -> None:
        """Objekt einfuegen - als ein Undo-Schritt.

        ``commit=False`` laesst den Schnappschuss offen: ein neues Textfeld
        wird erst mit dem Ende der Bearbeitung ein Schritt („Text"), und ein
        leer gebliebenes verschwindet ohne Spur auf dem Stapel.
        """
        self._seal_open_inspector_edit()
        self._capture_history()
        self._history_suppress = True
        try:
            if fit:
                self._fit_item_into_label(item)
            item.setPos(pos if pos is not None else self._default_item_pos())
            self._wire_text_item(item)
            self._wire_table_item(item)
            self._wire_datetime_item(item)
            self._canvas.add_item(item)
            self._canvas.setFocus()
            self._recompute_canvas()
            self._canvas.keep_inside_printable(item)
            self._schedule_refresh()
            self._on_selection_changed()
        finally:
            self._history_suppress = False
        if commit:
            self._commit_history(tr("Einfügen"))

    def _wire_text_item(self, item) -> None:
        """Textfeld an Undo und Aufraeumen haengen (Tippen, Bearbeitungsende)."""
        if not isinstance(item, TextItem):
            return
        # Schnappschuss beim Start der Bearbeitung - ``contentsChanged`` kommt
        # erst *nach* dem ersten Zeichen und waere als Bezug zu spaet.
        item.editing_started.connect(self._capture_history)
        item.document().contentsChanged.connect(self._on_text_edited)
        item.editing_finished.connect(self._on_text_editing_finished)

    def _wire_loaded_text_items(self) -> None:
        """Nach ``load_items`` (Öffnen, Undo, Sprachwechsel) neu verdrahten.

        ``item_from_dict`` erzeugt frische Objekte - ohne diesen Schritt
        würde ein später bearbeitetes Textfeld weder im Undo landen noch
        leer aufgeräumt.
        """
        self._wire_canvas_text(self._canvas)

    def _wire_canvas_text(self, canvas: LabelCanvas) -> None:
        for item in canvas.scene().items():
            self._wire_text_item(item)
            self._wire_table_item(item)
            self._wire_datetime_item(item)

    def _wire_table_item(self, item) -> None:
        """Tabelle an Undo haengen und den Inspector bei Zellenwechsel neu bauen."""
        if not isinstance(item, TableItem):
            return
        item.editing_started.connect(self._capture_history)
        item.content_changed.connect(self._on_text_edited)
        item.editing_finished.connect(self._on_table_editing_finished)
        item.cell_selection_changed.connect(self._defer_selection_refresh)
        item.structure_changed.connect(self._defer_selection_refresh)

    def _wire_datetime_item(self, item) -> None:
        """Stempel nachziehen, wenn die Uhr oder das Format den Text ändert.

        Der Text steht nicht im Undo: gespeichert werden Format und Versatz.
        Die Bandlänge und die Vorschau sollen der neuen Breite aber folgen.
        """
        if not isinstance(item, DateTimeItem):
            return
        item.display_changed.connect(self._on_datetime_displayed)

    def _on_datetime_displayed(self) -> None:
        # Sekunden-Ticks aendern oft nur den Text, nicht die Bounding-Breite.
        sender = self.sender()
        if isinstance(sender, DateTimeItem):
            width = sender.boundingRect().width()
            prev = getattr(sender, "_last_display_width", None)
            sender._last_display_width = width
            if prev is not None and abs(prev - width) < 0.5:
                self._schedule_refresh()
                return
        self._recompute_canvas()
        self._schedule_refresh()

    def _on_table_editing_finished(self) -> None:
        """Zellen-Text abschliessen, ausser der Inspector committet gerade selbst.

        Sonst wuerde das Schliessen des Editors den Schnappschuss verbrauchen,
        bevor Einfuegen oder Loeschen einer Zeile darin landet.
        """
        if self._inspector.edit_open:
            return
        self._commit_history(tr("Text"))

    def _defer_selection_refresh(self) -> None:
        """Inspector nach der laufenden Maus- oder Knopfaktion neu aufbauen.

        Ein Neuaufbau mitten im Klick wuerde das Feld wegwerfen, das das Signal
        gerade sendet. Danach den Zellen-Editor wieder fokussieren, falls die
        Tabelle noch in Bearbeitung ist.
        """
        QTimer.singleShot(0, self._refresh_selection_keep_focus)

    def _refresh_selection_keep_focus(self) -> None:
        editing = [
            it
            for it in self._canvas.scene().items()
            if isinstance(it, TableItem) and it.is_editing
        ]
        self._on_selection_changed()
        for item in editing:
            if item.scene() is not None and item.is_editing:
                item.focus_editor()

    def _new_text(self, pos: QPointF | None = None, text: str = "") -> TextItem:
        """Neues Textfeld anlegen und direkt bearbeiten.

        Bewusst **ohne Platzhaltertext**: der Doppelklick setzt nur den Cursor,
        getippt wird sofort der eigene Text. Bleibt das Feld leer, wird es beim
        Beenden der Bearbeitung wieder verworfen (siehe
        :meth:`_on_text_editing_finished`) - wie im P-touch Editor.
        """
        item = TextItem(text, font_pixel_size=self._default_font_size())
        # Einfuegen und Tippen sind *ein* Schritt; der Commit kommt mit dem
        # Ende der Bearbeitung (_on_text_editing_finished).
        self._add_item(item, pos, commit=False)
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
        if not isinstance(item, TextItem):
            return
        if str(item.toPlainText()).strip():
            self._commit_history(tr("Text"))
            return
        # Schnappschuss sofort freigeben: der Klick, der die Bearbeitung
        # beendet, startet oft im selben Atemzug die naechste Geste. Das
        # leere Feld zaehlt ab hier nicht mehr mit (``_pending_discard``),
        # der Undo-Schritt entsteht aber schon jetzt - nicht erst im Timer,
        # der sonst die Geste dazwischen in denselben Befehl ziehen wuerde.
        before = self._history_before
        self._history_before = None
        item._pending_discard = True
        pushed = push_if_changed(
            self._undo_stack,
            before,
            self._design_snapshot(),
            self._restore_design,
            tr("Löschen"),
        )
        if pushed:
            self._update_window_title()
        tab = self._active
        QTimer.singleShot(
            0, lambda: self._discard_text_if_empty(item, pushed, tab=tab)
        )

    def _discard_text_if_empty(
        self,
        item: TextItem,
        pushed: bool = False,
        *,
        tab: LabelTab | None = None,
    ) -> None:
        if item.scene() is None:
            return
        owner = tab if tab is not None else self._active
        if owner is None:
            return
        # Laeuft die Bearbeitung inzwischen wieder (z. B. nach einem Refresh,
        # der die Textmarke ausblendet), bleibt das Feld stehen - verworfen
        # wird nur, was wirklich nicht mehr in Bearbeitung ist.
        if item.is_editing or str(item.toPlainText()).strip():
            item._pending_discard = False
            if (
                pushed
                and owner.undo.undoText() == tr("Löschen")
                and owner.undo.index() == owner.undo.count()
            ):
                owner.undo.undo()
            return
        self._history_suppress = True
        try:
            owner.canvas.remove_item(item)
        finally:
            self._history_suppress = False
        if owner is self._active:
            self._on_items_changed()

    def _on_text_edited(self) -> None:
        self._capture_history()
        self._recompute_canvas()
        self._schedule_refresh()

    def _on_selection_changed(self) -> None:
        selection = self._canvas.selected_items()
        item = selection[0] if len(selection) == 1 else None
        allow_red = self._media_panel.model.two_color and self._media_panel.label.color.supports_red
        self._inspector.set_item(item, allow_red=allow_red)

    def _on_inspector_changed(self) -> None:
        self._canvas.viewport().update()
        self._recompute_canvas()
        self._schedule_refresh()

    def _delete_selected(self) -> None:
        """Objekte loeschen - und das Dokument als geaendert markieren."""
        if not self._canvas.selected_items():
            return
        self._capture_history()
        self._history_suppress = True
        try:
            self._canvas.delete_selected()
        finally:
            self._history_suppress = False
        self._commit_history(tr("Löschen"))
        self._on_items_changed()

    def _on_zoom_changed(self, percent: float) -> None:
        self._update_zoom_label(percent)

    def _on_canvas_hint(self, text: str) -> None:
        self._hint_label.setText(text)
        self._hint_label.setVisible(bool(text))

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
        if not self._history_suppress:
            text = tr("Bearbeiten")
            before = self._history_before
            if before is not None and len(self._canvas.items_serialized()) < len(
                before.get("items") or []
            ):
                text = tr("Löschen")  # Entf-Taste im Canvas
            self._commit_history(text)
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
        menu.addAction(self._act_add_clipart)
        menu.addAction(icon("barcode"), tr("Barcode…"), self._add_barcode)
        menu.addAction(icon("qr"), tr("QR-Code…"), self._add_qr)
        menu.addAction(icon("line"), tr("Linie"), self._add_line)
        menu.addAction(icon("rect"), tr("Rahmen"), self._add_rect)
        menu.addAction(self._act_add_table)
        menu.addAction(self._act_add_datetime)
        if self._canvas.selected_items():
            menu.addSeparator()
            for act in (
                self._act_align_left,
                self._act_align_hcenter,
                self._act_align_right,
                self._act_align_top,
                self._act_align_vcenter,
                self._act_align_bottom,
            ):
                menu.addAction(act)
            menu.addSeparator()
            menu.addAction(self._act_front)
            menu.addAction(self._act_back)
            menu.addAction(self._act_delete)
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
                "Bilder (*.png *.webp *.jpg *.jpeg *.bmp *.gif);;Alle Dateien (*)"
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

    def _add_shape(self, shape: str) -> None:
        width = self._canvas.printable_rect().width()
        size = max(40, int(self._canvas.height_dots * 0.4))
        if shape.startswith("arrow"):
            rect = QRectF(0, 0, int(width * 0.5), int(size * 0.6))
        else:
            rect = QRectF(0, 0, size, size)
        self._add_item(ShapeItem(rect, shape))

    def _add_datetime(self) -> None:
        self._add_item(DateTimeItem(font_pixel_size=self._default_font_size()))

    def _add_clipart(self) -> None:
        """Raster im Sheet. Ein Klick setzt das Symbol aufs Etikett."""
        picker = SymbolPicker()
        sheet = show_widget(
            self,
            title=tr("Clip Art"),
            content=picker,
            sizing="fill",
            max_size=QSize(560, 560),
            margins=20,
            close_on_outside=True,
        )

        def _picked(symbol_id: str) -> None:
            sheet.close_sheet()
            area = self._canvas.printable_rect()
            side = min(area.width(), area.height())
            item = ClipArtItem(symbol_id, max(48.0, side * 0.55))
            self._add_item(item)

        picker.chosen.connect(_picked)

    def _add_table(self) -> None:
        """2×3-Tabelle, fast so hoch wie das Band und etwa dreimal so lang.

        Das ist die Tabelle, die P-touch Editor mit einem Klick anlegt: sie
        fuellt die bedruckbare Breite und zieht bei automatischer Laenge das
        Etikett mit. ``fit=False``, weil die Laenge gerade erst entstehen soll
        und nicht auf das bisherige Minimum gekuerzt werden darf.
        """
        rect = self._canvas.margin_rect()
        if rect.width() < 40 or rect.height() < 40:
            rect = self._canvas.printable_rect()
        inset = 2.0
        rows, cols = 3, 2
        along = self._canvas.orientation is media.Orientation.ALONG
        if along:
            cross = max(40.0, rect.height() - 2 * inset)
            length = cross * 3.0
            if not self._media_panel.auto_length():
                length = min(length, max(40.0, rect.width() - 2 * inset))
            width, height = length, cross
        else:
            cross = max(40.0, rect.width() - 2 * inset)
            length = cross * 3.0
            if not self._media_panel.auto_length():
                length = min(length, max(40.0, rect.height() - 2 * inset))
            width, height = cross, length
        cell = min(width / cols, height / rows)
        item = TableItem(
            rows, cols, width, height, font_pixel_size=max(16, int(cell * 0.45))
        )
        self._add_item(
            item,
            QPointF(rect.left() + inset, rect.top() + inset),
            fit=False,
        )

    def _bump_z(self, direction: int) -> None:
        if not self._canvas.selected_items():
            return
        self._capture_history()
        for item in self._canvas.selected_items():
            item.setZValue(item.zValue() + direction)
        self._commit_history(tr("Reihenfolge"))
        self._canvas.viewport().update()

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
        self._pending_job = (datetime.now(), label.name, copies, config.model, config.address)
        self._print_button.setEnabled(False)
        self._status_stack.setCurrentWidget(self._feed_indicator)
        self._feed_indicator.start()
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
        self._print_worker.finished.connect(self._on_print_finished)
        self._print_worker.finished.connect(self._print_worker.deleteLater)
        self._print_worker.start()

    def _on_print_finished(self) -> None:
        self._print_worker = None
        self._print_button.setEnabled(True)
        self._feed_indicator.stop()
        self._status_stack.setCurrentWidget(self._last_job_label)

    def _on_print_succeeded(self, status: dict) -> None:
        self._record_print_job(status.get("outcome") or "sent")
        self.statusBar().showMessage(
            tr("Druckauftrag gesendet (outcome={outcome}).").format(
                outcome=status.get("outcome")
            ),
            8000,
        )

    def _on_print_failed(self, message: str) -> None:
        self._record_print_job("failed")
        self.statusBar().showMessage(tr("Druck fehlgeschlagen."), 8000)
        hint = access.failure_hint(message)
        if hint:
            message = f"{message}\n\n{hint}"
        show_message(self, "critical", tr("Druckfehler"), message, selectable=bool(hint))

    def _record_print_job(self, outcome: str) -> None:
        if self._pending_job is None:
            return
        started, label, copies, model, address = self._pending_job
        self._pending_job = None
        job = PrintJob(started, label, copies, model, address, outcome)
        self._print_jobs.append(job)
        self._refresh_last_job_label()

    def _refresh_last_job_label(self) -> None:
        """Statuszeile zum letzten Auftrag der Sitzung neu setzen."""
        if not self._print_jobs:
            self._last_job_label.setText(tr("Noch kein Auftrag"))
            self._last_job_label.setStyleSheet("color:#777;")
            return
        job = self._print_jobs[-1]
        self._last_job_label.setText(f"{job.started:%H:%M} · {job.model}\n{job.status_text()}")
        color = "#b00020" if job.is_error else "#777"
        self._last_job_label.setStyleSheet(f"color:{color};")

    def _show_print_history(self) -> None:
        PrintHistoryDialog(self._print_jobs, self).exec()

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
        self._network_worker = NetworkSearchWorker(self._network_cancel)
        self._network_worker.succeeded.connect(self._on_network_found)
        self._network_worker.finished.connect(self._on_network_search_done)
        self._network_worker.finished.connect(self._network_worker.deleteLater)
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
        self._network_worker = None
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
        if self._detect_worker is not None and self._detect_worker.isRunning():
            return
        config = self._media_panel.printer_config()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._detect_worker = DetectLabelWorker(config)
        self._detect_worker.succeeded.connect(self._on_detect_label_done)
        self._detect_worker.failed.connect(self._on_detect_label_failed)
        self._detect_worker.finished.connect(self._on_detect_label_finished)
        self._detect_worker.finished.connect(self._detect_worker.deleteLater)
        self._detect_worker.start()

    def _on_detect_label_finished(self) -> None:
        self._detect_worker = None
        QApplication.restoreOverrideCursor()

    def _on_detect_label_failed(self, message: str) -> None:
        show_message(
            self,
            "warning",
            tr("Band erkennen"),
            tr("Abfrage fehlgeschlagen:\n{error}").format(error=message),
        )

    def _on_detect_label_done(self, label) -> None:
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

    # --------------------------------------------------------------- Reiter --
    def _require_tab(self) -> LabelTab:
        tab = self._active
        if tab is None:
            raise RuntimeError("kein offenes Etikett")
        return tab

    @property
    def _canvas(self) -> LabelCanvas:
        return self._require_tab().canvas

    @property
    def _undo_stack(self) -> QUndoStack:
        return self._require_tab().undo

    @property
    def _document_path(self) -> str:
        return self._require_tab().path

    @_document_path.setter
    def _document_path(self, value: str) -> None:
        self._require_tab().path = value

    @property
    def _document_dirty(self) -> bool:
        return self._require_tab().document_dirty

    @_document_dirty.setter
    def _document_dirty(self, value: bool) -> None:
        self._require_tab().document_dirty = value

    @property
    def _history_before(self) -> dict[str, Any] | None:
        return self._require_tab().history_before

    @_history_before.setter
    def _history_before(self, value: dict[str, Any] | None) -> None:
        self._require_tab().history_before = value

    @property
    def _media_prev(self) -> dict[str, Any] | None:
        return self._require_tab().media_prev

    @_media_prev.setter
    def _media_prev(self, value: dict[str, Any] | None) -> None:
        self._require_tab().media_prev = value

    @property
    def _margin_prev(self) -> dict[str, float]:
        return self._require_tab().margin_prev

    @_margin_prev.setter
    def _margin_prev(self, value: dict[str, float]) -> None:
        self._require_tab().margin_prev = value

    @property
    def _margin_base(self) -> tuple[float, float]:
        return self._require_tab().margin_base

    @_margin_base.setter
    def _margin_base(self, value: tuple[float, float]) -> None:
        self._require_tab().margin_base = value

    @property
    def _preview_view(self) -> tuple[float, QPointF] | None:
        return self._require_tab().preview_view

    @_preview_view.setter
    def _preview_view(self, value: tuple[float, QPointF] | None) -> None:
        self._require_tab().preview_view = value

    def _ordered_tabs(self) -> list[LabelTab]:
        return [self._tab_at(index) for index in range(self._tab_bar.count())]

    def _tab_at(self, index: int) -> LabelTab:
        return self._tab_ids[int(self._tab_bar.tabData(index))]

    def _index_of(self, tab: LabelTab) -> int:
        for index in range(self._tab_bar.count()):
            if self._tab_at(index) is tab:
                return index
        return -1

    def _caption(self, tab: LabelTab) -> str:
        name = Path(tab.path).name if tab.path else tr("Unbenannt")
        return f"{name}*" if tab.is_dirty() else name

    def _refresh_tab_captions(self) -> None:
        if not hasattr(self, "_tab_bar"):
            return
        for index, tab in enumerate(self._ordered_tabs()):
            caption = self._caption(tab)
            if self._tab_bar.tabText(index) != caption:
                self._tab_bar.setTabText(index, caption)
            tip = tab.path or tr("Unbenannt")
            self._tab_bar.setTabToolTip(index, tip)

    def _bind_tab(self, tab: LabelTab) -> None:
        canvas = tab.canvas
        canvas.text_requested.connect(self._on_text_requested)
        canvas.item_double_clicked.connect(self._on_item_double_clicked)
        canvas.context_menu_requested.connect(self._show_context_menu)
        canvas.items_changed.connect(self._on_items_changed)
        canvas.gesture_begun.connect(self._capture_history)
        canvas.image_dropped.connect(self._on_image_dropped)
        canvas.text_dropped.connect(self._on_text_dropped)
        canvas.print_preview_exit_requested.connect(self._exit_print_preview)
        canvas.zoom_changed.connect(self._on_zoom_changed)
        canvas.hint_changed.connect(self._on_canvas_hint)
        canvas.scene().selectionChanged.connect(self._on_selection_changed)
        canvas.scene().changed.connect(self._on_scene_changed)
        tab.undo.cleanChanged.connect(self._on_undo_clean_changed)

    def _unbind_tab(self, tab: LabelTab) -> None:
        canvas = tab.canvas
        pairs = (
            (canvas.text_requested, self._on_text_requested),
            (canvas.item_double_clicked, self._on_item_double_clicked),
            (canvas.context_menu_requested, self._show_context_menu),
            (canvas.items_changed, self._on_items_changed),
            (canvas.gesture_begun, self._capture_history),
            (canvas.image_dropped, self._on_image_dropped),
            (canvas.text_dropped, self._on_text_dropped),
            (canvas.print_preview_exit_requested, self._exit_print_preview),
            (canvas.zoom_changed, self._on_zoom_changed),
            (canvas.hint_changed, self._on_canvas_hint),
            (canvas.scene().selectionChanged, self._on_selection_changed),
            (canvas.scene().changed, self._on_scene_changed),
            (tab.undo.cleanChanged, self._on_undo_clean_changed),
        )
        for signal, slot in pairs:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue

    def _stash_active(self) -> None:
        """Band des sichtbaren Etiketts merken, bevor ein anderes nach vorn kommt."""
        tab = self._active
        if tab is None:
            return
        tab.media = deepcopy(dict(self._media_panel.media_state()))

    def _create_tab(self, *, switch: bool = True) -> LabelTab:
        tab = LabelTab(self)
        self._canvas_stack.addWidget(tab.canvas)
        self._undo_group.addStack(tab.undo)
        self._tab_bar.blockSignals(True)
        index = self._tab_bar.addTab(self._caption(tab))
        self._tab_ids[id(tab)] = tab
        self._tab_bar.setTabData(index, id(tab))
        self._tab_bar.blockSignals(False)
        if switch:
            self._show_tab(tab)
        return tab

    def _show_tab(self, tab: LabelTab) -> None:
        index = self._index_of(tab)
        if index < 0:
            return
        if self._tab_bar.currentIndex() != index:
            self._tab_bar.setCurrentIndex(index)
        else:
            self._activate_tab(tab)

    def _on_tab_index_changed(self, index: int) -> None:
        if index < 0 or index >= self._tab_bar.count():
            return
        self._activate_tab(self._tab_at(index))

    def _activate_tab(self, tab: LabelTab) -> None:
        if tab is self._active:
            self._update_window_title()
            return
        previous = self._active
        if previous is not None:
            self._seal_open_inspector_edit()
            previous.canvas.cancel_editing()
            self._stash_active()
            self._unbind_tab(previous)
        self._active = tab
        self._undo_group.setActiveStack(tab.undo)
        self._canvas_stack.setCurrentWidget(tab.canvas)
        self._bind_tab(tab)
        self._adjusting = True
        self._history_suppress = True
        try:
            if tab.media:
                self._media_panel.apply_media_state(tab.media)
            self._sync_margin_base()
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._sync_media_prev()
        self._recompute_canvas()
        self._on_selection_changed()
        self._sync_preview_action()
        self._update_zoom_label()
        self._schedule_refresh()
        self._update_window_title()
        tab.canvas.setFocus()

    def _sync_preview_action(self) -> None:
        action = self._act_print_preview
        action.blockSignals(True)
        action.setChecked(self._canvas.print_preview)
        action.blockSignals(False)

    def _discard_tabs(self) -> None:
        if self._active is not None:
            self._unbind_tab(self._active)
            self._active = None
        self._tab_bar.blockSignals(True)
        while self._tab_bar.count():
            self._tab_bar.removeTab(0)
        self._tab_bar.blockSignals(False)
        for tab in list(self._tab_ids.values()):
            self._undo_group.removeStack(tab.undo)
            self._canvas_stack.removeWidget(tab.canvas)
            tab.canvas.hide()
            tab.canvas.deleteLater()
            tab.undo.deleteLater()
        self._tab_ids.clear()

    def _replace_tabs(self, specs: list[Mapping[str, Any]], active_index: int) -> None:
        """Alle Reiter aus einem gespeicherten Zustand neu aufbauen."""
        self._discard_tabs()
        created: list[tuple[LabelTab, Mapping[str, Any]]] = []
        for spec in specs:
            tab = self._create_tab(switch=False)
            tab.media = dict(spec.get("media") or {})
            tab.path = str(spec.get("path") or "")
            tab.canvas.load_items(list(spec.get("items") or []))
            self._wire_canvas_text(tab.canvas)
            if spec.get("preview"):
                tab.canvas.set_print_preview(True)
            created.append((tab, spec))
        if not created:
            self._create_tab()
            return
        index = min(max(0, active_index), len(created) - 1)
        self._show_tab(created[index][0])
        for tab, spec in created:
            if spec.get("document_dirty"):
                tab.document_dirty = True
                tab.undo.resetClean()
            else:
                tab.document_dirty = False
                tab.undo.setClean()
        self._update_window_title()

    def _can_reuse_current(self) -> bool:
        """Frisches Fenster: das leere Etikett nehmen statt einen zweiten Reiter."""
        tabs = self._ordered_tabs()
        if len(tabs) != 1 or self._active is None:
            return False
        tab = self._active
        return not tab.path and not tab.is_dirty() and not tab.canvas.items_serialized()

    def _tab_with_path(self, path: str) -> LabelTab | None:
        try:
            wanted = str(Path(path).resolve())
        except OSError:
            wanted = path
        for tab in self._ordered_tabs():
            if not tab.path:
                continue
            try:
                current = str(Path(tab.path).resolve())
            except OSError:
                current = tab.path
            if current == wanted:
                return tab
        return None

    def _on_next_tab(self) -> None:
        count = self._tab_bar.count()
        if count < 2:
            return
        self._tab_bar.setCurrentIndex((self._tab_bar.currentIndex() + 1) % count)

    def _on_previous_tab(self) -> None:
        count = self._tab_bar.count()
        if count < 2:
            return
        self._tab_bar.setCurrentIndex((self._tab_bar.currentIndex() - 1) % count)

    def _on_close_current_tab(self) -> None:
        if self._active is not None:
            self._request_close_tab(self._active)

    def _on_tab_close_requested(self, index: int) -> None:
        if 0 <= index < self._tab_bar.count():
            self._request_close_tab(self._tab_at(index))

    def _request_close_tab(self, tab: LabelTab) -> None:
        if not tab.is_dirty():
            self._remove_tab(tab)
            return
        self._show_tab(tab)

        def _saved() -> None:
            self._remove_tab(tab)

        self._ask_about_tab(tab, on_save=_saved, on_discard=_saved, on_cancel=lambda: None)

    def _ask_about_tab(self, tab: LabelTab, *, on_save, on_discard, on_cancel) -> None:
        name = Path(tab.path).name if tab.path else tr("Unbenannt")

        def _chosen(choice: str) -> None:
            if choice == "save":
                self._show_tab(tab)
                self._on_file_save(on_saved=on_save, on_cancel=on_cancel)
            elif choice == "discard":
                on_discard()
            else:
                on_cancel()

        ask_save(
            self,
            title=tr("Etikett schließen"),
            text=tr("Änderungen an „{name}“ speichern?").format(name=name),
            on_choice=_chosen,
        )

    def _remove_tab(self, tab: LabelTab) -> None:
        ordered = self._ordered_tabs()
        if len(ordered) <= 1:
            self._blank_tab(tab)
            return
        index = self._index_of(tab)
        was_active = tab is self._active
        neighbor = None
        if was_active:
            neighbor = ordered[index - 1] if index > 0 else ordered[index + 1]
            self._unbind_tab(tab)
            self._active = None
        self._tab_bar.blockSignals(True)
        self._tab_bar.removeTab(index)
        self._tab_bar.blockSignals(False)
        self._tab_ids.pop(id(tab), None)
        self._undo_group.removeStack(tab.undo)
        self._canvas_stack.removeWidget(tab.canvas)
        tab.canvas.hide()
        tab.canvas.deleteLater()
        tab.undo.deleteLater()
        if was_active and neighbor is not None:
            self._show_tab(neighbor)
        else:
            self._update_window_title()

    def _blank_tab(self, tab: LabelTab) -> None:
        """Letzten Reiter leeren, statt das Fenster zu schließen."""
        self._show_tab(tab)
        self._adjusting = True
        self._history_suppress = True
        try:
            if tab.canvas.print_preview:
                tab.canvas.set_print_preview(False)
                tab.canvas.set_print_image(None)
            tab.canvas.load_items([])
            tab.path = ""
            tab.document_dirty = False
            tab.history_before = None
            tab.preview_view = None
            tab.undo.clear()
            tab.undo.setClean()
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._wire_loaded_text_items()
        self._sync_margin_base()
        self._sync_media_prev()
        self._stash_active()
        self._recompute_canvas()
        self._on_selection_changed()
        self._sync_preview_action()
        self._update_window_title()
        self._schedule_refresh()
        tab.canvas.setFocus()

    def _prompt_close(self, tabs: list[LabelTab]) -> None:
        pending = [tab for tab in tabs if tab.is_dirty()]
        if not pending:
            self._close_prompt = False
            self._accept_close = True
            self.close()
            return
        tab = pending[0]

        def _cancel() -> None:
            self._close_prompt = False

        def _continue() -> None:
            self._prompt_close(pending[1:])

        self._show_tab(tab)
        self._ask_about_tab(tab, on_save=_continue, on_discard=_continue, on_cancel=_cancel)

    # ------------------------------------------------------------- Dateien --
    def _document_data(self) -> dict:
        """Aktuelles Design als Dokumentdaten (Band/Design + Objekte)."""
        return document.build(
            self._media_panel.media_state(), self._canvas.items_serialized()
        )

    def _apply_document(self, data: dict) -> None:
        """Dokumentdaten uebernehmen - Adresse und Anschluss bleiben stehen."""
        self._adjusting = True
        self._history_suppress = True
        try:
            self._media_panel.apply_media_state(data.get("media") or {})
            self._canvas.load_items(list(data.get("items") or []))
            self._sync_margin_base()
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._wire_loaded_text_items()
        self._sync_media_prev()
        self._undo_stack.clear()
        self._undo_stack.setClean()
        self._document_dirty = False
        self._address_dirty = False
        self._history_before = None
        self._recompute_canvas()
        self._schedule_refresh()
        self._stash_active()
        self._update_window_title()

    def _set_document_path(self, path: str) -> None:
        self._document_path = path
        self._document_dirty = False
        self._address_dirty = False
        self._undo_stack.setClean()
        self._update_window_title()

    def _on_undo_clean_changed(self, _clean: bool = False) -> None:
        """Titel nach Undo-Stapel-Clean-Flag aktualisieren."""
        self._update_window_title()

    def _is_document_dirty(self) -> bool:
        """Stern: Undo-Stapel unsauber, Vorlage angewendet oder Adresswechsel."""
        try:
            stack_dirty = not self._undo_stack.isClean()
        except RuntimeError:
            stack_dirty = False
        return self._document_dirty or self._address_dirty or stack_dirty

    def _update_window_title(self) -> None:
        try:
            self._refresh_tab_captions()
            base = tr("QLInux - P-touch Editor")
            dirty = self._is_document_dirty()
            if not self._document_path and not dirty:
                self.setWindowTitle(base)
                return
            name = (
                Path(self._document_path).name
                if self._document_path
                else tr("Unbenannt")
            )
            star = "*" if dirty else ""
            self.setWindowTitle(f"{name}{star} – {base}")
        except RuntimeError:
            # Fenster oder Undo-Stapel schon freigegeben (Teardown).
            return

    def _on_file_new(self, _checked: bool = False) -> None:
        """Leeres Etikett im neuen Reiter. Das Band des aktuellen Etiketts bleibt."""
        media = deepcopy(dict(self._media_panel.media_state()))
        tab = self._create_tab(switch=False)
        tab.media = media
        self._show_tab(tab)
        tab.undo.clear()
        tab.undo.setClean()
        tab.document_dirty = False
        tab.history_before = None
        self._update_window_title()
        self._canvas.setFocus()

    def _on_file_open(self) -> None:
        """„Öffnen…": Datei waehlen und laden."""
        choose_file(
            self,
            caption=tr("Etikett öffnen"),
            name_filter=tr(
                "QLInux-Etiketten (*{suffix});;"
                "Brother P-touch (*{lbx});;"
                "Alle Etiketten (*{suffix} *{lbx})"
            ).format(suffix=document.DOCUMENT_SUFFIX, lbx=lbx.LBX_SUFFIX),
            start_dir=self._settings.document_dir or "",
            on_selected=self._open_document_chosen,
        )

    def open_path(self, path: str) -> None:
        """Datei von außen öffnen (Kommandozeile, Dateimanager) - immer in einem neuen Reiter.

        Ein frisches, leeres Etikett im Fenster fliegt danach wieder raus.
        """
        placeholder = self._active if self._can_reuse_current() else None
        self._open_document_chosen(path, new_tab=True)
        if placeholder is not None and placeholder is not self._active:
            self._remove_tab(placeholder)

    def _open_document_chosen(self, path: str | None, new_tab: bool = False) -> None:
        if not path:
            return
        imported = path.lower().endswith(lbx.LBX_SUFFIX)
        try:
            data = lbx.load(path) if imported else document.load(path)
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Etikett öffnen"), str(exc))
            return
        name = Path(path).name
        if not imported:
            existing = self._tab_with_path(path)
            if existing is not None:
                self._show_tab(existing)
                self.statusBar().showMessage(
                    tr("Etikett bereits geöffnet: {name}").format(name=name), 8000
                )
                return
        if new_tab or not self._can_reuse_current():
            self._create_tab()
        self._apply_document(data)
        if imported:
            # Nicht als .lbx-Pfad merken: „Speichern" würde JSON hineinschreiben.
            # Der Reiter bleibt „Unbenannt*", der nächste Speicherdialog fragt
            # nach einer .qlx.
            self._document_path = ""
            self._document_dirty = True
            self._update_window_title()
            self.statusBar().showMessage(
                tr("Importiert: {name}").format(name=name), 8000
            )
            warnings = [str(entry) for entry in data.get("warnings") or [] if entry]
            if warnings:
                show_message(
                    self,
                    "info",
                    tr("Brother P-touch"),
                    "\n".join(warnings),
                )
            return
        self._set_document_path(path)
        self.statusBar().showMessage(
            tr("Etikett geöffnet: {name}").format(name=name), 8000
        )

    def _on_file_save(
        self,
        on_saved: Any = None,
        on_cancel: Any = None,
    ) -> None:
        """„Speichern": ohne Dateinamen erst nach ihm fragen."""
        if not callable(on_saved):
            on_saved = None
        if not callable(on_cancel):
            on_cancel = None
        if not self._document_path:
            self._on_file_save_as(on_saved=on_saved, on_cancel=on_cancel)
            return
        if self._save_document_to(self._document_path):
            if on_saved is not None:
                on_saved()
        elif on_cancel is not None:
            on_cancel()

    def _on_file_save_as(
        self,
        on_saved: Any = None,
        on_cancel: Any = None,
    ) -> None:
        if not callable(on_saved):
            on_saved = None
        if not callable(on_cancel):
            on_cancel = None

        def _chosen(path: str | None) -> None:
            if not path:
                if on_cancel is not None:
                    on_cancel()
                return
            if not path.endswith(document.DOCUMENT_SUFFIX):
                path += document.DOCUMENT_SUFFIX
            if self._save_document_to(path):
                if on_saved is not None:
                    on_saved()
            elif on_cancel is not None:
                on_cancel()

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
            on_selected=_chosen,
        )

    def _save_document_chosen(self, path: str | None) -> None:
        if not path:
            return
        if not path.endswith(document.DOCUMENT_SUFFIX):
            path += document.DOCUMENT_SUFFIX
        self._save_document_to(path)

    def _save_document_to(self, path: str) -> bool:
        """Design schreiben - ohne Dialog (auch fuer Tests und „Speichern")."""
        try:
            document.save(path, self._document_data())
        except document.DocumentError as exc:
            show_message(self, "critical", tr("Etikett speichern"), str(exc))
            return False
        self._settings.document_dir = str(Path(path).parent)
        self._set_document_path(path)
        self.statusBar().showMessage(
            tr("Etikett gespeichert: {name}").format(name=Path(path).name), 8000
        )
        return True

    # -------------------------------------------------------------- Close ---
    def _disconnect_worker(self, worker: QThread | None, slots: list[tuple]) -> None:
        """Ergebnis-Signale loesen, warten, und einen haengenden Thread behalten.

        Ohne Qt-Parent ueberlebt der Thread das Fenster. Die Slots duerfen das
        geschlossene Fenster nicht mehr ansprechen; ``deleteLater`` bleibt.
        """
        if worker is None or not hasattr(worker, "isRunning"):
            return
        for signal, slot in slots:
            try:
                signal.disconnect(slot)
            except RuntimeError:
                continue
        if not worker.isRunning():
            return
        worker.wait(NETWORK_CANCEL_WAIT_MS)
        if worker.isRunning():
            _orphan_workers.append(worker)
            worker.finished.connect(lambda worker=worker: _forget_orphan(worker))

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._accept_close and self.isVisible():
            dirty = [tab for tab in self._ordered_tabs() if tab.is_dirty()]
            if dirty:
                event.ignore()
                if not self._close_prompt:
                    self._close_prompt = True
                    self._prompt_close(dirty)
                return
        self._finish_close(event)

    def _finish_close(self, event) -> None:
        # Laufende Suche abbrechen, damit kein Thread das geschlossene
        # Fenster anspricht.
        self._network_cancel.set()
        if self._detect_worker is not None and self._detect_worker.isRunning():
            QApplication.restoreOverrideCursor()
        network = self._network_worker
        self._disconnect_worker(
            network,
            [
                (network.succeeded, self._on_network_found),
                (network.finished, self._on_network_search_done),
            ]
            if network is not None
            else [],
        )
        detect = self._detect_worker
        self._disconnect_worker(
            detect,
            [
                (detect.succeeded, self._on_detect_label_done),
                (detect.failed, self._on_detect_label_failed),
                (detect.finished, self._on_detect_label_finished),
            ]
            if detect is not None
            else [],
        )
        printing = self._print_worker
        self._disconnect_worker(
            printing,
            [
                (printing.succeeded, self._on_print_succeeded),
                (printing.failed, self._on_print_failed),
                (printing.finished, self._on_print_finished),
            ]
            if printing is not None
            else [],
        )
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


def _label_paths(paths: Iterable[str]) -> list[str]:
    """Nur Etikettendateien (``.qlx``, ``.lbx``) - alles andere fällt weg."""
    suffixes = (document.DOCUMENT_SUFFIX, lbx.LBX_SUFFIX)
    return [
        os.path.abspath(path)
        for path in paths
        if not path.startswith("-") and path.lower().endswith(suffixes)
    ]


def _document_args(argv: list[str]) -> list[str]:
    """Etikettendateien aus der Kommandozeile (Doppelklick im Dateimanager).

    Optionen (``-...``) und Qt-eigene Argumente ohne passende Endung fallen weg.
    """
    return _label_paths(argv[1:])


def _open_from_outside(window: MainWindow, paths: list[str]) -> None:
    """Dateien, die ein zweiter Start geschickt hat: als Reiter, Fenster nach vorn."""
    for path in _label_paths(paths):
        window.open_path(path)
    window.raise_()
    window.activateWindow()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("QLInux")
    files = _document_args(argv)
    # Läuft schon eine Instanz, öffnet sie die Dateien als Reiter - dieser Start endet.
    if files and instance.forward(files):
        return 0
    settings = AppSettings()
    set_language(settings.language or _system_language())
    # Zahlen (Dezimaltrennzeichen) folgen der Sprache - auch in Spinboxen.
    QLocale.setDefault(QLocale(language()))
    window = MainWindow(settings)
    _remember_window(window)
    # Der Server bleibt in ``server`` am Leben, solange die Schleife läuft.
    # Kein removeServer bei belegtem Namen: nur die Owner-Instanz hält den Socket.
    server = instance.listen(partial(_open_from_outside, window))
    # TOCTOU: zwei Starts mit Dateien — Verlierer reicht nach listen() nach.
    if server is None and files and instance.forward(files, attempts=5, retry_ms=50):
        return 0
    window.show()
    for path in files:
        window.open_path(path)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
