"""Hauptfenster der QLInux-Anwendung (PySide6).

Aufbau:

* links: :class:`~ql_editor.media_panel.MediaPanel` (Band, Laenge, Margins)
* mitte: :class:`~ql_editor.canvas.LabelCanvas` (feste Pixelgroesse, Lineale)
* rechts: Objekteigenschaften; der Knopf unten oeffnet Drucken als Sheet
* Toolbar: Datei (Speichern mit Pfeil fuer Speichern unter), Items einfuegen,
  Ausrichten, Ebenen, Loeschen, Datenbank, Drucken
* Statusleiste: Zoom-Knoepfe und Zoomstufe
* Reiter: mehrere Etiketten in einem Fenster (Canvas, Band, Undo je Reiter)

Es gibt **keine klassische Menueleiste**. Haeufige Befehle liegen in der
Toolbar. Das Hamburger-Menue behaelt nur, was keinen eigenen Schalter hat:
Sprache, Erscheinungsbild, Hilfe, Ueber und Beenden.
Strg+K listet alle Befehle.

Die GUI haelt keine eigene Wahrheit ueber Bandmasse: alles kommt aus
:mod:`ql_editor.media`. Gerendert wird ueber :mod:`ql_editor.renderer`,
gedruckt ueber :mod:`ql_editor.printer` (in einem Worker-Thread).
"""

from __future__ import annotations

import json
import logging
import math
import sys
import threading
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QLocale,
    QMimeData,
    QPointF,
    QProcess,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
    QStandardItemModel,
    QUndoGroup,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import (
    about,
    access,
    csv_source,
    document,
    instance,
    lbx,
    media,
    resources,
    stationery,
    templates,
)
from . import help as app_help
from . import merge as merge_engine
from .canvas import DUPLICATE_OFFSET_DOTS, LabelCanvas
from .command_palette import CommandPalette, PaletteEntry
from .csv_source import CsvTable
from .database_panel import DatabasePanel
from .discovery import (
    NETWORK_PROBE_ATTEMPTS,
    NetworkStatus,
    confirm_network_job,
    discover_network_printers,
    network_printer_status,
)
from .history import design_snapshot, push_if_changed
from .i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    language,
    language_name,
    paste_hint,
    paste_label,
    set_language,
    tr,
)
from .icons import icon
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
    item_from_dict,
)
from .jobs import PrintJob, fill_history_table, make_history_table
from .media_panel import CONNECTION_USB, MediaPanel
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
    RESOLUTION_HIGH,
    RESOLUTION_STANDARD,
    PrinterError,
    PrintResolution,
    backend_for_address,
    detect_label,
    maximum_resolution,
    print_image,
    print_images,
    resolution_by_key,
    resolution_options,
)
from .settings import AppSettings
from .sheet import (
    Sheet,
    ask_choice,
    ask_label_printer,
    ask_loaded_tape,
    ask_print_anyway,
    ask_save,
    ask_text,
    choose_file,
    save_file,
    show_message,
    show_widget,
)
from .sheet_output import print_sheets, render_page_image, system_printers, write_pdf
from .sheet_picker import SheetStartPicker
from .symbols import SymbolPicker
from .theme import apply_theme, scheme_for
from .widgets import (
    SmoothScrollArea,
    add_toolbar_separator,
    install_wheel_guard_recursive,
    title_box,
)

logger = logging.getLogger(__name__)

BARCODE_SYMBOLOGIES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"]

#: Wie lange auf den Passwort-Dialog gewartet wird, bevor der Einzeiler kommt.
PERMISSION_TIMEOUT_MS = 90_000
#: Nach dem Einrichten der Regel greift udev erst kurz verzoegert: so lange
#: (in Schritten von ACCESS_RETRY_MS) werden die Rechte nachgefasst.
ACCESS_RETRY_MS = 400
ACCESS_RETRY_COUNT = 8
#: So lange darf eine abgebrochene Netzwerksuche beim Schliessen nachlaufen.
NETWORK_CANCEL_WAIT_MS = 1000
#: So lange wartet das Programmende hoechstens auf abgehaengte Worker.
ORPHAN_EXIT_WAIT_MS = 5000
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


def _wait_for_orphans(timeout_ms: int = ORPHAN_EXIT_WAIT_MS) -> None:
    """Vor dem Programmende: abgehaengte Worker auslaufen lassen.

    Wird ein noch laufender ``QThread`` beim Beenden abgebaut, bricht Qt das
    ganze Programm ab. ``timeout_ms`` gilt fuer alle zusammen.
    """
    deadline = monotonic() + timeout_ms / 1000
    for worker in _orphan_workers:
        remaining = max(0, int((deadline - monotonic()) * 1000))
        try:
            worker.wait(remaining)
        except RuntimeError:
            # deleteLater war schneller als _forget_orphan: der Thread ist fertig.
            continue


#: Abstand der Hintergrundabfrage des Netzwerkdruckers (Millisekunden).
NETWORK_POLL_MS = 5000
#: Wie alt ein Abfrageergebnis hoechstens sein darf, um den Druck zu bestimmen.
SNMP_CACHE_MAX_AGE = 15.0


class PrintWorker(QThread):
    """Rendert nichts, sondern konvertiert und sendet in einem Thread."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        image,
        label,
        config,
        options: dict,
        snmp_answered: bool | None = None,
        cancel: threading.Event | None = None,
    ):
        super().__init__(None)
        if isinstance(image, Image.Image):
            self._images = [image]
        else:
            self._images = list(image)
        self._label = label
        self._config = config
        self._options = options
        self._snmp_answered = snmp_answered
        self._cancel = cancel

    def run(self) -> None:
        snmp_answered = self._snmp_answered
        if snmp_answered is None and self._config.backend == "network":
            snmp_answered = (
                network_printer_status(
                    self._config.address, attempts=NETWORK_PROBE_ATTEMPTS
                )
                is not None
            )
        try:
            if len(self._images) == 1:
                status = print_image(
                    self._images[0], self._label, self._config, **self._options
                )
            else:
                status = print_images(
                    self._images, self._label, self._config, **self._options
                )
        except PrinterError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensiv
            self.failed.emit(tr("Unerwarteter Fehler: {error}").format(error=exc))
        else:
            try:
                status = confirm_network_job(
                    self._config,
                    status,
                    snmp_answered=bool(snmp_answered),
                    cancel=self._cancel,
                )
            except Exception:  # pragma: no cover - defensiv
                logger.exception("SNMP-Pruefung nach dem Senden fehlgeschlagen")
            self.succeeded.emit(status)


class SheetOutputWorker(QThread):
    """Schreibt das PDF oder gibt den Bogen an CUPS, abseits der Oberfläche."""

    succeeded = Signal()
    failed = Signal(str)

    def __init__(
        self,
        *,
        kind: str,
        template: stationery.SheetTemplate,
        images: list[Image.Image],
        placements: list[stationery.Placement],
        offset_x: float,
        offset_y: float,
        printer_name: str = "",
        path: str = "",
    ) -> None:
        super().__init__(None)
        self._kind = kind
        self._template = template
        self._images = list(images)
        self._placements = list(placements)
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._printer_name = printer_name
        self._path = path

    def run(self) -> None:
        try:
            if self._kind == "pdf":
                write_pdf(
                    self._path,
                    self._template,
                    self._images,
                    self._placements,
                    offset_x_mm=self._offset_x,
                    offset_y_mm=self._offset_y,
                )
            else:
                print_sheets(
                    self._printer_name,
                    self._template,
                    self._images,
                    self._placements,
                    offset_x_mm=self._offset_x,
                    offset_y_mm=self._offset_y,
                )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit()


class NetworkStatusWorker(QThread):
    """Fragt den Netzwerkdrucker im Hintergrund per SNMP nach seinem Status.

    ``polled`` liefert ``{"address": ..., "status": NetworkStatus | None}``.
    """

    polled = Signal(object)

    def __init__(self, address: str):
        super().__init__(None)
        self._address = address

    def run(self) -> None:
        # Ein verlorenes Paket hiesse "kein SNMP" - dann entfiele die Pruefung
        # nach dem naechsten Druck. Die Wiederholung kostet nur diesen Thread.
        status = network_printer_status(self._address, attempts=NETWORK_PROBE_ATTEMPTS)
        self.polled.emit({"address": self._address, "status": status})


class NetworkSearchWorker(QThread):
    """Sucht Drucker im Netzwerk (mDNS + SNMP) abseits der Oberflaeche."""

    succeeded = Signal(list)

    def __init__(self, cancel: threading.Event, parent=None):
        del parent  # absichtlich kein Qt-Parent, siehe _orphan_workers
        super().__init__(None)
        self._cancel = cancel

    def run(self) -> None:
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

    def run(self) -> None:
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


#: Zwischenablage fuer Objekte. Text im Feld bleibt ``text/plain``.
_CLIPBOARD_MIME = "application/x-qlinux-items"


def _items_on_clipboard() -> list[dict[str, Any]] | None:
    """Objekt-Kopien aus der Zwischenablage, sonst ``None``."""
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasFormat(_CLIPBOARD_MIME):
        return None
    try:
        payload = json.loads(bytes(mime.data(_CLIPBOARD_MIME).data()).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(entry, dict) and entry.get("type") for entry in payload):
        return None
    return payload


def _put_items_on_clipboard(items) -> None:
    mime = QMimeData()
    payload = [item.to_dict() for item in items]
    mime.setData(_CLIPBOARD_MIME, json.dumps(payload).encode("utf-8"))
    QApplication.clipboard().setMimeData(mime)


class _PrintIconButton(QPushButton):
    """Drucker-Knopf oben rechts. Während des Auftrags dreht sich ein Bogen.

    Ein Toolbutton mit ``autoRaise`` sieht nur beim Hover nach Knopf aus.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("print_icon_button")
        self.setIcon(icon("print"))
        self.setIconSize(QSize(22, 22))
        # Breiter als hoch, damit links und rechts vom Icon Luft bleibt.
        self.setFixedSize(72, 36)
        self.setToolTip(tr("Drucken"))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._angle = 0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def is_busy(self) -> bool:
        return self._busy

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        self._busy = busy
        self.setEnabled(not busy)
        if busy:
            if not self._timer.isActive():
                self._timer.start()
            self._tick()
            return
        self._timer.stop()
        self._angle = 0
        self.setIcon(icon("print"))

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        size = 22
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(size / 2, size / 2)
        painter.rotate(self._angle)
        pen = QPen(self.palette().color(QPalette.ColorRole.WindowText))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(-6, -6, 12, 12), 40 * 16, 280 * 16)
        painter.end()
        self.setIcon(QIcon(pixmap))


class _PrintPreview(QLabel):
    """1-bit-Bild im Druck-Sheet, skaliert in den vorhandenen Platz.

    Die Groesse kommt vom Layout, nicht vom Bild: sonst waechst das Sheet mit
    jedem neuen Pixmap und die Skalierung schaukelt sich auf.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._rescaling = False
        self.setObjectName("print_preview_image")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:  # noqa: N802
        # Stylesheet wuerde die Farbe beim Wechsel einfrieren.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid)))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        painter.end()
        super().paintEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, 240)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, 160)

    def set_image(self, image: QImage | None) -> None:
        self._image = None if image is None or image.isNull() else image
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._rescaling:
            return
        self._rescaling = True
        try:
            if self._image is None:
                self.clear()
                return
            box = self.contentsRect().size()
            if box.width() < 4 or box.height() < 4:
                return
            pixmap = QPixmap.fromImage(self._image).scaled(
                box,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self.setPixmap(pixmap)
        finally:
            self._rescaling = False


class LabelTab:
    """Ein offenes Etikett: eigener Canvas, Undo-Stapel und Dateizustand.

    Band, Ränder und das Ziel (Brother oder Zweckform-Vorlage) liegen im
    gemeinsamen Panel und werden beim Wechsel hierher geschrieben. Die
    Druckeradresse, der Versatz und das erste Feld gehören nicht dazu.
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
        #: Geladene CSV (nicht in ``.qlx`` eingebettet, D1).
        self.csv_table: CsvTable | None = None
        #: Persistenter ``data_source``-Block (Pfad, Hash, current_record).
        self.data_source: dict[str, Any] | None = None
        #: Serienparameter (Format 2); Vorschau nutzt Index 0 (D10).
        self.serial: dict[str, Any] = document.merge_serial()
        self.current_record: int = 0
        #: Mehrfachauswahl im Datenbank-Grid (nicht persistiert).
        self.selected_records: list[int] = []
        #: Ziel dieses Reiters. Versatz und Drucker bleiben am Fenster.
        self.sheet_output = False
        self.sheet_part = stationery.DEFAULT_PART
        #: Pfad-/Hash-Hinweis fuer das Datenbank-Banner (nicht persistiert).
        self.database_notice: str | None = None

    def is_dirty(self) -> bool:
        """Inhalt geändert - unabhängig von der Druckeradresse."""
        try:
            stack_dirty = not self.undo.isClean()
        except RuntimeError:
            stack_dirty = False
        return self.document_dirty or stack_dirty

    def clear_database(self) -> None:
        """CSV und Merge-Zustand dieses Reiters verwerfen."""
        self.csv_table = None
        self.data_source = None
        self.current_record = 0
        self.selected_records = []
        self.database_notice = None
        self.serial = document.merge_serial()


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None, *, discover: bool = True):
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle(tr("QLInux - P-touch Editor"))
        self._apply_window_icon()
        self.setWindowIcon(icon("label"))
        self._adjusting = False
        self._print_worker: PrintWorker | None = None
        self._sheet_worker: SheetOutputWorker | None = None
        #: True, solange der Bogen aufgebaut wird und der Dialog zu bleibt.
        self._sheet_preparing = False
        self._sheet_return_on_error = False
        self._sheet_meta: tuple[str, str, int, int, str, str] | None = None
        self._print_jobs: list[PrintJob] = []
        # Start, Etikettname, Kopien, Modell, Adresse, Bandkennung.
        self._pending_job: tuple[datetime, str, int, str, str, str] | None = None
        self._pending_sheet: tuple[Any, Any, Any, int] | None = None
        # Netzwerksuche im Hintergrund (mDNS + SNMP); ``_network_cancel``
        # bricht sie beim Schliessen des Fensters ab.
        self._network_worker: NetworkSearchWorker | None = None
        self._network_cancel = threading.Event()
        # Bricht die SNMP-Pruefung nach dem Senden ab, wenn das Fenster schliesst.
        self._print_cancel = threading.Event()
        # True, solange die Startsuche laeuft: ihr Ergebnis stellt den letzten
        # Drucker wieder her und zaehlt nicht als Bearbeitung.
        self._startup_discovery = False
        # Anschluss und Adresse beim Start der Suche. Weicht der Stand beim
        # Ergebnis davon ab, hat der Nutzer schon selbst gewaehlt.
        self._startup_connection = ""
        self._startup_address = ""
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
        #: Sheet der Fenster-Rückfrage. Hilfe und andere Sheets zählen nicht.
        self._close_sheet: Sheet | None = None
        #: CSV-/Hash-Status nach Open zuletzt anzeigen (nicht von „geöffnet“ überdecken).
        self._pending_database_status: str | None = None
        # Von/Bis, wie der Nutzer sie gesetzt hat. Eine kürzere CSV klemmt nur
        # die Anzeige; die gemerkten Grenzen bleiben für die nächste Datei.
        self._range_request_from = 1
        self._range_request_to = 1
        self._syncing_print_range = False

        self._canvas_stack = QStackedWidget()
        self._canvas_stack.setMinimumSize(240, 180)
        self._host = PanelHost(self._canvas_stack, self)
        # Reiter über der Werkzeugleiste: das Menü-Widget sitzt ganz oben,
        # addToolBar darunter.
        self._tab_chrome = self._build_tab_chrome()
        self.setMenuWidget(self._tab_chrome)
        self._database_panel = DatabasePanel(self)
        self._database_panel.record_selected.connect(self._on_database_record_selected)
        self._database_panel.connect_requested.connect(self._choose_csv)
        self._database_panel.replace_requested.connect(self._choose_csv)
        self._database_panel.disconnect_requested.connect(self.disconnect_csv)
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._host, 1)
        shell_layout.addWidget(self._database_panel)
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

        self._net_poll: dict | None = None
        self._net_poll_worker: NetworkStatusWorker | None = None
        # Zuletzt in der Statusleiste gemeldeter Zustand (Adresse, Status).
        self._net_shown: tuple[str, NetworkStatus] | None = None
        # Laeuft nur, solange das Fenster aktiv ist (siehe changeEvent).
        self._net_poll_timer = QTimer(self)
        self._net_poll_timer.setInterval(NETWORK_POLL_MS)
        self._net_poll_timer.timeout.connect(self._poll_network_printer)

        self._zoom_label = QLabel(tr("Zoom 100 %"))
        self._zoom_label.setToolTip(
            tr("Mausrad scrollt – Strg + Mausrad (oder Zoomgeste) zoomt")
        )
        zoom_row = QWidget()
        zoom_layout = QHBoxLayout(zoom_row)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(2)
        for act in (
            self._act_zoom_out,
            self._act_zoom_fit,
            self._act_zoom_in,
            self._act_zoom_100,
        ):
            button = QToolButton(zoom_row)
            button.setDefaultAction(act)
            button.setAutoRaise(True)
            button.setIconSize(QSize(16, 16))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            zoom_layout.addWidget(button)
        zoom_layout.addSpacing(6)
        zoom_layout.addWidget(self._zoom_label)
        self.statusBar().addPermanentWidget(zoom_row)
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
            key: spin.value() for key, spin in self._media_panel._margin_spins.items()
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
        self._media_panel.forget_loaded_requested.connect(self._forget_loaded_tape)
        self._media_panel.changed.connect(self._sync_loaded_tape)
        self._inspector.changed.connect(self._on_inspector_changed)
        self._inspector.edit_begun.connect(self._capture_history)
        self._inspector.edit_committed.connect(self._on_inspector_edit_committed)
        self._inspector.database_binding_changed.connect(
            self._on_database_binding_changed
        )
        self._inspector.serial_spec_changed.connect(self._on_serial_spec_changed)
        self._inspector.serial_toggle_requested.connect(
            self._on_serial_toggle_requested
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
        self._sync_loaded_tape()
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
        # Sprachwechsel baut das Fenster neu und uebergibt den Zustand selbst -
        # dort nicht noch einmal suchen und die laufende Auswahl ersetzen.
        if discover:
            self._discover_startup_printer()

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
        """Reiterleiste über der Werkzeugleiste, plus ein Knopf für ein neues Etikett."""
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
        Rechts bleibt der Inspector; Drucken oeffnet das Sheet.
        """
        # Ziel und Zweckform gehören zur Medienwahl, nicht in den Druckdialog.
        self._media_panel.insert_header(self._build_target_box())
        self._sheet_box = self._build_sheet_box()
        self._sheet_box.setVisible(False)
        self._media_panel.insert_header(self._sheet_box)
        self._left_panel = OverlayPanel(
            tr("Band & Drucker"),
            self._scroll_wrap(self._media_panel),
            Qt.Edge.LeftEdge,
            self,
        )
        self._host.add_panel(self._left_panel)

        self._print_sheet: Sheet | None = None
        self._print_panel = self._build_print_panel()
        self._print_panel.hide()

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll_wrap(self._inspector), 1)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(6, 6, 6, 6)
        self._open_print_button = QPushButton(icon("print"), "")
        self._open_print_button.setObjectName("open_print_button")
        self._open_print_button.setIconSize(QSize(28, 28))
        self._open_print_button.setMinimumHeight(48)
        self._open_print_button.setToolTip(
            tr("Druckvorschau, Einstellungen und Verlauf")
        )
        self._open_print_button.clicked.connect(self._show_print_sheet)
        footer_layout.addWidget(self._open_print_button)
        layout.addWidget(footer)

        self._right_panel = OverlayPanel(
            tr("Eigenschaften & Druck"),
            body,
            Qt.Edge.RightEdge,
            self,
        )
        self._host.add_panel(self._right_panel)

    def _build_print_panel(self) -> QWidget:
        """Inhalt des Druck-Sheets: Vorschau, Optionen, Knopf, Verlauf.

        Das Widget lebt am Fenster und wird nur ins Sheet gehaengt, solange
        es offen ist. So bleiben die Felder (und ihre Werte) erhalten.
        """
        widget = QWidget(self)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        preview_box = title_box(tr("Druckvorschau"))
        preview_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        preview_layout = QVBoxLayout(preview_box)
        self._print_preview = _PrintPreview()
        preview_layout.addWidget(self._print_preview)
        self._sheet_preview_page = QLabel()
        self._sheet_preview_page.setObjectName("sheet_preview_page")
        self._sheet_preview_page.hide()
        preview_layout.addWidget(self._sheet_preview_page)
        layout.addWidget(preview_box, 1)

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

        # Eigener Schalter: "Qualitaet vor Tempo" (brother_ql ``pquality``/hq).
        # Das ist *keine* Aufloesung - deshalb getrennt vom Feld darueber.
        self._hq_check = QCheckBox(tr("Hohe Druckqualität (HQ)"))
        self._hq_check.setChecked(True)
        self._hq_check.setToolTip(
            tr(
                "Der Drucker arbeitet dann mit Vorrang für Qualität statt Tempo "
                "(das pquality-Flag aus der Brother-Rasterreferenz).\n"
                "Die Auflösung ändert das nicht - die steht im Feld darüber."
            )
        )

        self._dither_check = QCheckBox(tr("Graustufen (Dithering)"))
        self._dither_check.setToolTip(
            tr(
                "Graustufen werden gepunktet statt hart geschwellt - für Fotos.\n"
                "Ohne Dithering entscheidet die Tintenmenge unten, welche Helligkeit "
                "Tinte wird."
            )
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
        self._ink_label.setToolTip(
            tr(
                "Anteil der bedruckten Fläche - sofort sichtbar, was Tintenmenge "
                "und Dithering bewirken."
            )
        )
        threshold_holder = QWidget()
        threshold_row = QHBoxLayout(threshold_holder)
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
            tr(
                "Wie oft jedes Etikett gedruckt wird - identische Kopien "
                "in einem Auftrag."
            )
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
            tr(
                "Nach jeder Kopie: einzelne Etiketten.\n"
                "Nur am Ende: die Etiketten hängen zusammen und werden zuletzt "
                "getrennt - nur bei mehreren Etiketten.\n"
                "Nicht schneiden: der Streifen bleibt am Band."
            )
        )
        self._cut_label.setToolTip(self._cut_combo.toolTip())

        # Datenbank-Druckbereich (D16). Serie liegt im Inspector und ist
        # nur sichtbar, solange eine CSV geladen ist.
        # Eigener Kasten: ohne CSV ausgeblendet, damit der Druckreiter auf
        # kleinen Bildschirmen ohne Scrollen auskommt.
        self._scope_selected = QRadioButton(tr("Ausgewählte Datensätze"))
        self._scope_selected.setObjectName("print_scope_selected")
        self._scope_selected.setToolTip(
            tr("Die in der Tabelle gewählten Zeilen (Strg/Umschalt für mehrere).")
        )
        self._scope_all = QRadioButton(tr("Alle Datensätze"))
        self._scope_all.setObjectName("print_scope_all")
        self._scope_all.setToolTip(tr("Jede Zeile der verbundenen CSV."))
        self._scope_range = QRadioButton(tr("Datensatzbereich"))
        self._scope_range.setObjectName("print_scope_range")
        self._scope_range.setToolTip(
            tr("Von–bis, 1 ist die erste Zeile, beide Grenzen zählen.")
        )
        self._scope_selected.setChecked(True)

        self._range_from_label = QLabel(tr("Von"))
        self._range_from = QSpinBox()
        self._range_from.setObjectName("print_record_from")
        self._range_from.setRange(1, 1)
        self._range_from.setValue(1)
        self._range_from_label.setBuddy(self._range_from)
        self._range_from.setToolTip(tr("Erster Datensatz, 1 ist die erste Zeile."))
        self._range_from_label.setToolTip(self._range_from.toolTip())
        self._range_to_label = QLabel(tr("Bis"))
        self._range_to = QSpinBox()
        self._range_to.setObjectName("print_record_to")
        self._range_to.setRange(1, 1)
        self._range_to.setValue(1)
        self._range_to_label.setBuddy(self._range_to)
        self._range_to.setToolTip(tr("Letzter Datensatz, einschließlich."))
        self._range_to_label.setToolTip(self._range_to.toolTip())
        self._range_row = QWidget()
        range_row = QHBoxLayout(self._range_row)
        range_row.setContentsMargins(0, 0, 0, 0)
        range_row.addWidget(self._range_from_label)
        range_row.addWidget(self._range_from, 1)
        range_row.addWidget(self._range_to_label)
        range_row.addWidget(self._range_to, 1)

        self._db_print_box = title_box(tr("Datenbank"))
        self._db_print_box.setToolTip(
            tr(
                "Welche Datensätze gedruckt werden: die gewählte Zeile, "
                "alle oder ein Bereich. Ohne CSV bleibt es ein Etikett."
            )
        )
        db_layout = QVBoxLayout(self._db_print_box)
        db_layout.addWidget(self._scope_selected)
        db_layout.addWidget(self._scope_all)
        db_layout.addWidget(self._scope_range)
        db_layout.addWidget(self._range_row)

        self._print_button = _PrintIconButton(widget)
        self._print_button.clicked.connect(self._on_print)
        # Fensterweit: nach dem Oeffnen hat das Sheet den Fokus, und der
        # Druck-Knopf sitzt im Sheet-Kopf - beide liegen ausserhalb von
        # ``widget``. Ohne Sheet ist das Panel versteckt, der Shortcut aus.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), widget)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(self._on_print_key)

        quality = title_box(tr("Qualität"))
        self._quality_box = quality
        quality_form = self._panel_form(quality)
        quality_form.addRow(resolution_label, self._resolution_combo)
        quality_form.addRow(self._hq_check)
        quality_form.addRow(self._dither_check)
        quality_form.addRow(self._threshold_label, threshold_holder)

        self._sheet_hint = QLabel()
        self._sheet_hint.setObjectName("sheet_fill")
        self._sheet_hint.setWordWrap(True)
        self._sheet_pdf_button = QPushButton(tr("PDF speichern…"))
        self._sheet_pdf_button.setObjectName("sheet_pdf")
        self._sheet_pdf_button.clicked.connect(self._on_sheet_pdf)

        output = title_box(tr("Ausgabe"))
        self._output_form = self._panel_form(output)
        self._output_form.addRow(self._copies_label, self._copies_spin)
        self._output_form.addRow(self._cut_label, self._cut_combo)
        self._output_form.addRow(tr("Belegt"), self._sheet_hint)
        self._output_form.addRow(self._sheet_pdf_button)

        history = title_box(tr("Druckverlauf"))
        history_layout = QVBoxLayout(history)
        self._history_table = make_history_table()
        self._history_table.setObjectName("print_history_table")
        # Eigener Scrollbereich: die Hoehe bleibt, der Balken nur bei Bedarf.
        # Sonst waechst das Sheet mit jedem weiteren Auftrag.
        self._history_table.setFixedHeight(120)
        self._history_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._history_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        history_layout.addWidget(self._history_table)

        options = QWidget()
        options_row = QHBoxLayout(options)
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(6)
        options_row.addWidget(quality, 1)
        options_row.addWidget(output, 1)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)
        form_layout.addWidget(options)
        form_layout.addWidget(self._db_print_box)
        form_layout.addWidget(history)

        options_scroll = self._scroll_wrap(form)
        options_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(options_scroll)

        self._resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        self._threshold_spin.valueChanged.connect(self._schedule_refresh)
        self._dither_check.toggled.connect(self._on_dither_toggled)
        self._copies_spin.valueChanged.connect(self._sync_cut_options)
        self._copies_spin.valueChanged.connect(self._schedule_refresh)
        self._output_combo.currentIndexChanged.connect(self._on_output_target_changed)
        self._hq_check.toggled.connect(self._on_hq_toggled)
        for radio in (self._scope_selected, self._scope_all, self._scope_range):
            radio.toggled.connect(self._on_print_scope_toggled)
        self._range_from.valueChanged.connect(self._on_print_range_from_edited)
        self._range_to.valueChanged.connect(self._on_print_range_to_edited)
        self._sync_resolution_options()
        self._sync_print_scope_ui()
        # Brother ist der Start. Der Bogen blendet das nach den Einstellungen ein.
        self._output_form.setRowVisible(self._sheet_hint, False)
        self._output_form.setRowVisible(self._sheet_pdf_button, False)
        return widget

    @staticmethod
    def _panel_form(box: QGroupBox) -> QFormLayout:
        """Formular im Kasten, gleiche Zeilenregeln wie im linken Panel."""
        form = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def _build_target_box(self) -> QGroupBox:
        """Brother-Band oder Etikettenbogen. Steht über der Medienwahl."""
        box = title_box(tr("Ziel"))
        self._output_label = QLabel(tr("Ziel"))
        self._output_combo = QComboBox()
        self._output_combo.setObjectName("print_output")
        self._output_combo.addItem(tr("Brother QL"), stationery.OUTPUT_BROTHER)
        self._output_combo.addItem(tr("Etikettenbogen"), stationery.OUTPUT_SHEET)
        self._output_label.setBuddy(self._output_combo)
        self._output_combo.setToolTip(
            tr(
                "Brother QL druckt das Band. Etikettenbogen legt dieselben "
                "Datensätze auf einen Avery-Zweckform-Bogen."
            )
        )
        self._output_label.setToolTip(self._output_combo.toolTip())
        form = self._panel_form(box)
        form.addRow(self._output_label, self._output_combo)
        return box

    def _build_sheet_box(self) -> QGroupBox:
        """Avery-Zweckform: Vorlage, erstes Feld, Versatz, Systemdrucker."""
        box = title_box(tr("Avery Zweckform"))
        box.setObjectName("sheet_box")
        box.setToolTip(
            tr(
                "Jeder Datensatz füllt ein Etikett, von links nach rechts. "
                "Kopien wiederholen denselben Datensatz. Das erste Etikett "
                "lässt schon benutzte Felder auf dem Bogen frei."
            )
        )
        form = self._panel_form(box)

        self._sheet_part_combo = QComboBox()
        self._sheet_part_combo.setObjectName("sheet_part")
        self._sheet_part_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._sheet_part_combo.setMinimumContentsLength(18)
        locale = QLocale()
        for template in stationery.templates():
            text = tr("{part} · {width} × {height} mm · {count} pro Bogen").format(
                part=template.part,
                width=locale.toString(template.label_width_mm, "f", 1),
                height=locale.toString(template.label_height_mm, "f", 1),
                count=template.per_sheet,
            )
            self._sheet_part_combo.addItem(text, template.part)
            self._sheet_part_combo.setItemData(
                self._sheet_part_combo.count() - 1,
                stationery.description_text(template.description),
                Qt.ItemDataRole.ToolTipRole,
            )
        index = self._sheet_part_combo.findData(stationery.DEFAULT_PART)
        if index >= 0:
            self._sheet_part_combo.setCurrentIndex(index)

        self._sheet_start = QSpinBox()
        self._sheet_start.setObjectName("sheet_start")
        self._sheet_start.setRange(1, 1)
        self._sheet_start.setValue(1)
        self._sheet_start.setToolTip(
            tr("Feld 1 ist links oben. Höhere Zahlen überspringen benutzte Felder.")
        )

        self._sheet_offset_x = self._offset_spin()
        self._sheet_offset_x.setObjectName("sheet_offset_x")
        self._sheet_offset_x.setToolTip(
            tr("Schiebt den ganzen Bogen nach rechts, in Millimetern.")
        )
        self._sheet_offset_y = self._offset_spin()
        self._sheet_offset_y.setObjectName("sheet_offset_y")
        self._sheet_offset_y.setToolTip(
            tr("Schiebt den ganzen Bogen nach unten, in Millimetern.")
        )

        self._sheet_printer_combo = QComboBox()
        self._sheet_printer_combo.setObjectName("sheet_printer")
        self._sheet_printer_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._sheet_printer_combo.setMinimumContentsLength(12)

        self._sheet_picker = SheetStartPicker()
        self._sheet_picker.setToolTip(
            tr("Klick auf das erste Feld, das noch frei ist.")
        )

        form.addRow(tr("Vorlage"), self._sheet_part_combo)
        form.addRow(tr("Erstes Etikett"), self._sheet_start)
        form.addRow(self._sheet_picker)
        form.addRow(tr("Versatz rechts"), self._sheet_offset_x)
        form.addRow(tr("Versatz unten"), self._sheet_offset_y)
        form.addRow(tr("Systemdrucker"), self._sheet_printer_combo)

        self._sheet_part_combo.currentIndexChanged.connect(self._on_sheet_part_changed)
        self._sheet_start.valueChanged.connect(self._update_sheet_hint)
        self._sheet_start.valueChanged.connect(self._schedule_refresh)
        self._sheet_start.valueChanged.connect(self._sheet_picker.set_start)
        self._sheet_picker.start_picked.connect(self._on_sheet_start_picked)
        self._sheet_offset_x.valueChanged.connect(self._schedule_refresh)
        self._sheet_offset_y.valueChanged.connect(self._schedule_refresh)
        return box

    @staticmethod
    def _offset_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-stationery.OFFSET_MM_MAX, stationery.OFFSET_MM_MAX)
        spin.setDecimals(1)
        spin.setSingleStep(0.1)
        spin.setSuffix(" mm")
        return spin

    def _on_print_scope_toggled(self, checked: bool) -> None:
        if checked:
            self._sync_print_scope_ui()

    def _remember_print_range(self, start: int, end: int) -> None:
        """Nutzergrenzen merken (1-basiert), unabhängig von der aktuellen CSV."""
        self._range_request_from = max(1, int(start))
        self._range_request_to = max(1, int(end))

    def _on_print_range_from_edited(self, value: int) -> None:
        if self._syncing_print_range:
            return
        self._range_request_from = max(1, int(value))
        self._sync_cut_options()

    def _on_print_range_to_edited(self, value: int) -> None:
        if self._syncing_print_range:
            return
        self._range_request_to = max(1, int(value))
        self._sync_cut_options()

    def _print_scope(self) -> str:
        """Gewaehlter Datenbank-Druckbereich (D16)."""
        if self._scope_all.isChecked():
            return merge_engine.PRINT_ALL
        if self._scope_range.isChecked():
            return merge_engine.PRINT_RANGE
        return merge_engine.PRINT_SELECTED

    def _set_print_scope(self, scope: str) -> None:
        if scope == merge_engine.PRINT_ALL:
            self._scope_all.setChecked(True)
        elif scope == merge_engine.PRINT_RANGE:
            self._scope_range.setChecked(True)
        else:
            self._scope_selected.setChecked(True)
        self._sync_print_scope_ui()

    def _active_print_records(self):
        """Records der verbundenen CSV, oder ``None`` ohne druckbare Zeilen."""
        tab = self._active
        if tab is None or tab.csv_table is None or not tab.csv_table.records:
            return None
        return tab.csv_table.records

    def _selected_print_records(self) -> list[int]:
        """Alle in der Tabelle gewählten Zeilen, sonst der aktuelle Record."""
        rows = self._database_panel.selected_records()
        if rows:
            return rows
        return [self._active.current_record] if self._active is not None else [0]

    def _print_variants(self) -> list[merge_engine.PrintVariant]:
        records = self._active_print_records()
        if records is None:
            return merge_engine.plan_print_variants(None)
        return merge_engine.plan_print_variants(
            records,
            scope=self._print_scope(),
            selected=self._selected_print_records(),
            range_from=self._range_from.value(),
            range_to=self._range_to.value(),
        )

    def _planned_labels(self) -> list[merge_engine.PlannedLabel]:
        """Druckliste: Records (oder ein virtueller) × Serie (D5)."""
        self._normalize_serial_limits()
        self._reconcile_serial_enabled()
        tab = self._active
        serial = tab.serial if tab is not None else None
        return merge_engine.plan_serial_labels(self._print_variants(), serial)

    def _planned_page_count(self) -> int:
        """Seiten, die der naechste Auftrag haette (Varianten × Kopien)."""
        copies = self._copies_spin.value()
        try:
            labels = self._planned_labels()
        except merge_engine.MergeError:
            return copies
        return len(labels) * copies

    def _sync_print_scope_ui(self) -> None:
        """Radios und Von/Bis an die CSV haengen; ohne Zeilen ausgrauen."""
        count = 0
        records = self._active_print_records()
        if records is not None:
            count = len(records)
        enabled = count > 0
        self._db_print_box.setVisible(enabled)
        self._db_print_box.setEnabled(enabled)
        # Das Grid kann zugeklappt sein: die Zahl zeigt, wie viele Zeilen gemeint sind.
        selected = len(self._database_panel.selected_records()) if enabled else 0
        if selected > 1:
            self._scope_selected.setText(
                tr("Ausgewählte Datensätze ({count})").format(count=selected)
            )
        else:
            self._scope_selected.setText(tr("Ausgewählte Datensätze"))
        if count > 0:
            maximum = count
            shown_from = min(self._range_request_from, maximum)
            shown_to = min(self._range_request_to, maximum)
        else:
            # Ohne CSV die gemerkten Grenzen behalten (nicht auf 1 klemmen).
            maximum = max(1, self._range_request_from, self._range_request_to)
            shown_from = self._range_request_from
            shown_to = self._range_request_to
        self._syncing_print_range = True
        try:
            for spin, value in (
                (self._range_from, shown_from),
                (self._range_to, shown_to),
            ):
                spin.blockSignals(True)
                spin.setMaximum(maximum)
                spin.setValue(min(value, maximum))
                spin.blockSignals(False)
        finally:
            self._syncing_print_range = False
        range_on = enabled and self._scope_range.isChecked()
        self._range_row.setVisible(range_on)
        self._range_from.setEnabled(range_on)
        self._range_to.setEnabled(range_on)
        self._range_from_label.setEnabled(range_on)
        self._range_to_label.setEnabled(range_on)
        self._sync_cut_options()

    def _sync_cut_options(self) -> None:
        """„Nur am Ende" gibt es nur bei mehreren Etiketten im Auftrag.

        Eine einzelne Seite am Ende zu schneiden ist der Schnitt nach dem
        Etikett - die Wahl waere eine Scheinoption. Der Eintrag wird deshalb
        ausgegraut statt versteckt: die Zeile bleibt stehen und das Panel
        springt nicht. Mehrere Datensaetze zaehlen mit, nicht nur Kopien.
        """
        several = self._planned_page_count() > 1
        model = self._cut_combo.model()
        item = (
            model.item(self._cut_combo.findData(CUT_AT_END))
            if isinstance(model, QStandardItemModel)
            else None
        )
        if item is not None:
            item.setEnabled(several)
        if not several and self._cut_combo.currentData() == CUT_AT_END:
            # Gleiche Wirkung wie „Nach jeder Kopie": die Auswahl aufraeumen,
            # damit in den Einstellungen steht, was wirklich passiert.
            self._cut_combo.setCurrentIndex(self._cut_combo.findData(CUT_EACH))
        if self._sheet_output():
            self._update_sheet_hint()

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
        wanted = (
            prefer
            or self._resolution_combo.currentData()
            or self._settings.print_resolution
        )

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
            tr("{label}: {detail}.").format(label=chosen.label, detail=chosen.detail)
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

        self._act_add_shapes = []
        for shape, label in (
            ("ellipse", tr("Ellipse")),
            ("triangle", tr("Dreieck")),
            ("star", tr("Stern")),
            ("arrow_right", tr("Pfeil rechts")),
            ("arrow_left", tr("Pfeil links")),
            ("arrow_double", tr("Doppelpfeil")),
        ):
            act = QAction(icon(f"shape_{shape}"), label, self)
            act.setToolTip(label)
            act.triggered.connect(lambda _=False, s=shape: self._add_shape(s))
            self._act_add_shapes.append(act)

        self._act_add_table = QAction(icon("table"), tr("Tabelle"), self)
        self._act_add_table.setToolTip(tr("Tabelle einfügen"))
        self._act_add_table.triggered.connect(self._add_table)

        self._act_add_datetime = QAction(icon("datetime"), tr("Datum/Uhrzeit"), self)
        self._act_add_datetime.setToolTip(
            tr("Aktuelles Datum und aktuelle Uhrzeit einfügen")
        )
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

        self._act_bold = QAction(icon("bold"), tr("Fett"), self)
        self._act_bold.setCheckable(True)
        self._act_bold.setEnabled(False)
        self._act_bold.setToolTip(tr("Fett (Strg+B)"))
        self._act_bold.setShortcut("Ctrl+B")
        self._act_bold.triggered.connect(
            lambda _checked=False: self._toggle_text_style("bold")
        )

        self._act_italic = QAction(icon("italic"), tr("Kursiv"), self)
        self._act_italic.setCheckable(True)
        self._act_italic.setEnabled(False)
        self._act_italic.setToolTip(tr("Kursiv (Strg+I)"))
        self._act_italic.setShortcut("Ctrl+I")
        self._act_italic.triggered.connect(
            lambda _checked=False: self._toggle_text_style("italic")
        )

        self._act_underline = QAction(icon("underline"), tr("Unterstrichen"), self)
        self._act_underline.setCheckable(True)
        self._act_underline.setEnabled(False)
        self._act_underline.setToolTip(tr("Unterstrichen (Strg+U)"))
        self._act_underline.setShortcut("Ctrl+U")
        self._act_underline.triggered.connect(
            lambda _checked=False: self._toggle_text_style("underline")
        )
        # Nicht im Burger: die Kuerzel haengen am Fenster und erscheinen unter Strg+K.
        self.addAction(self._act_bold)
        self.addAction(self._act_italic)
        self.addAction(self._act_underline)

        self._act_forward = QAction(icon("forward"), tr("Eine Ebene nach vorn"), self)
        self._act_forward.setToolTip(tr("Eine Ebene nach vorn"))
        self._act_forward.triggered.connect(lambda: self._step_stack(+1))

        self._act_backward = QAction(
            icon("backward"), tr("Eine Ebene nach hinten"), self
        )
        self._act_backward.setToolTip(tr("Eine Ebene nach hinten"))
        self._act_backward.triggered.connect(lambda: self._step_stack(-1))

        self._act_front = QAction(icon("front"), tr("In den Vordergrund"), self)
        self._act_front.setToolTip(tr("In den Vordergrund"))
        self._act_front.triggered.connect(lambda: self._stack_extreme(front=True))

        self._act_back = QAction(icon("back"), tr("In den Hintergrund"), self)
        self._act_back.setToolTip(tr("In den Hintergrund"))
        self._act_back.triggered.connect(lambda: self._stack_extreme(front=False))

        self._act_snap_guides = QAction(
            icon("align_left"), tr("An Hilfslinien ausrichten"), self
        )
        self._act_snap_guides.setToolTip(tr("An Hilfslinien ausrichten"))
        self._act_snap_guides.triggered.connect(self._snap_selection_to_guides)
        for act in (
            self._act_forward,
            self._act_backward,
            self._act_front,
            self._act_back,
            self._act_snap_guides,
        ):
            act.setEnabled(False)

        self._act_delete = QAction(icon("delete"), tr("Löschen"), self)
        self._act_delete.setToolTip(tr("Löschen (Entf)"))
        self._act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self._act_delete.triggered.connect(self._delete_selected)

        # Nicht im Burger. Strg+K und das Kontextmenue. Auf dem Mac werden
        # Copy/Cut/Paste zu Cmd, wie die anderen Standard-Kuerzel.
        # „Einfügen" ist schon die Gruppe (Englisch: Insert), deshalb paste_label.
        self._act_copy = QAction(icon("copy"), tr("Kopieren"), self)
        self._act_copy.setToolTip(tr("Kopieren (Strg+C)"))
        self._act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self._act_copy.triggered.connect(self._copy_selected)
        self._act_cut = QAction(icon("cut"), tr("Ausschneiden"), self)
        self._act_cut.setToolTip(tr("Ausschneiden (Strg+X)"))
        self._act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        self._act_cut.triggered.connect(self._cut_selected)
        self._act_paste = QAction(icon("paste"), paste_label(), self)
        self._act_paste.setToolTip(paste_hint())
        self._act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self._act_paste.triggered.connect(self._paste_clipboard)
        self._act_duplicate = QAction(icon("duplicate"), tr("Duplizieren"), self)
        self._act_duplicate.setToolTip(tr("Duplizieren (Strg+D)"))
        self._act_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self._act_duplicate.triggered.connect(self._duplicate_selected)
        for act in (
            self._act_copy,
            self._act_cut,
            self._act_paste,
            self._act_duplicate,
        ):
            act.setEnabled(False)
            self.addAction(act)
        self._paste_generation = 0
        QApplication.clipboard().dataChanged.connect(self._sync_clipboard_actions)

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
            tr("Zoom 1:1 (Strg+1) - echte Druckpunkte,\nso wie der Drucker sie setzt")
        )
        self._act_zoom_100.setShortcut("Ctrl+1")
        self._act_zoom_100.triggered.connect(lambda: self._canvas.zoom_100())

        self._act_print = QAction(icon("print"), tr("Drucken"), self)
        self._act_print.setToolTip(tr("Druckdialog (Ctrl+P)"))
        self._act_print.setShortcut("Ctrl+P")
        self._act_print.triggered.connect(self._show_print_sheet)

        self._act_print_history = QAction(
            icon("history"), tr("Druckverlauf anzeigen"), self
        )
        self._act_print_history.setToolTip(tr("Druckverlauf dieser Sitzung anzeigen"))
        self._act_print_history.triggered.connect(self._show_print_sheet)

        self._act_forget_tape = QAction(
            icon("delete"), tr("Gemerktes Band vergessen"), self
        )
        self._act_forget_tape.setToolTip(
            tr("Gemerktes Band löschen, z. B. nach einem Bandwechsel am Drucker.")
        )
        self._act_forget_tape.setEnabled(False)
        self._act_forget_tape.triggered.connect(self._forget_loaded_tape)

        self._act_print_preview = QAction(icon("preview"), tr("Druckvorschau"), self)
        self._act_print_preview.setCheckable(True)
        self._act_print_preview.setToolTip(
            tr("Druckvorschau: echte 1-bit-Ausgabe (Ctrl+Shift+P)")
        )
        self._act_print_preview.setShortcut("Ctrl+Shift+P")
        self._act_print_preview.toggled.connect(self._on_toggle_print_preview)

        # Seitenpanels ein-/ausblenden (kleine Bildschirme). Der Pfeil im
        # Panel und Strg+K bleiben der Weg zurueck; das Kuerzel haengt am Fenster.
        self._act_panel_left = QAction(icon("panel_left"), tr("Panel links"), self)
        self._act_panel_left.setCheckable(True)
        self._act_panel_left.setChecked(True)
        self._act_panel_left.setToolTip(
            tr(
                "Panel links ein-/ausklappen (F9)\n"
                "Eingeklappt bleibt ein Streifen mit Pfeil; er klappt beim "
                "Überfahren über dem Canvas auf"
            )
        )
        self._act_panel_left.setShortcut("F9")
        self._act_panel_left.toggled.connect(self._left_panel.set_docked)
        self.addAction(self._act_panel_left)

        self._act_panel_right = QAction(icon("panel_right"), tr("Panel rechts"), self)
        self._act_panel_right.setCheckable(True)
        self._act_panel_right.setChecked(True)
        self._act_panel_right.setToolTip(
            tr(
                "Panel rechts ein-/ausklappen (Umschalt+F9)\nEigenschaften und Druckoptionen"
            )
        )
        self._act_panel_right.setShortcut("Shift+F9")
        self._act_panel_right.toggled.connect(self._right_panel.set_docked)
        self.addAction(self._act_panel_right)

        # Pfeil im Panel und Menue-Haekchen synchron halten (der Pfeil ist der
        # primaere Weg, das Menue der Shortcut).
        self._left_panel.docked_changed.connect(self._act_panel_left.setChecked)
        self._right_panel.docked_changed.connect(self._act_panel_right.setChecked)

        self._act_connect_csv = QAction(icon("database"), tr("CSV verbinden…"), self)
        self._act_connect_csv.setToolTip(tr("CSV-Datei mit dem Etikett verbinden"))
        self._act_connect_csv.triggered.connect(self._choose_csv)

        # Erst sichtbar, wenn eine CSV haengt. Klick klappt das untere Grid auf.
        self._act_database = QAction(icon("database_view"), tr("Datenbank"), self)
        self._act_database.setObjectName("database_toolbar")
        self._act_database.setCheckable(True)
        self._act_database.setChecked(False)
        self._act_database.setVisible(False)
        self._act_database.setToolTip(tr("Datenbank ein- oder ausblenden"))
        self._act_database.toggled.connect(self._on_database_toolbar_toggled)

        self._act_commands = QAction(icon("menu"), tr("Befehle…"), self)
        self._act_commands.setToolTip(tr("Befehle (Strg+K)"))
        self._act_commands.setShortcut("Ctrl+K")
        self._act_commands.triggered.connect(self._open_command_palette)
        # Nicht im Burger: das Kuerzel bleibt am Fenster haengen.
        self.addAction(self._act_commands)

        self._act_quit = QAction(icon("quit"), tr("Beenden"), self)
        self._act_quit.setToolTip(tr("Beenden (Strg+Q)"))
        self._act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_quit.triggered.connect(self.close)

        self._act_help = QAction(icon("help"), tr("Hilfe"), self)
        self._act_help.setToolTip(tr("Hilfe"))
        self._act_help.triggered.connect(self._show_help)

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
        self._act_file_save.setToolTip(
            tr("Etikett speichern (Strg+S)\nPfeil: Speichern unter… (Strg+Umschalt+S)")
        )
        self._act_file_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_file_save.triggered.connect(self._on_file_save)

        self._act_file_save_as = QAction(icon("save_as"), tr("Speichern unter…"), self)
        self._act_file_save_as.setToolTip(
            tr("Etikett unter neuem Namen speichern (Strg+Umschalt+S)")
        )
        self._act_file_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._act_file_save_as.triggered.connect(self._on_file_save_as)
        self.addAction(self._act_file_save_as)

        self._act_tab_close = QAction(icon("close"), tr("Reiter schließen"), self)
        self._act_tab_close.setToolTip(tr("Reiter schließen (Strg+W)"))
        self._act_tab_close.setShortcut(QKeySequence.StandardKey.Close)
        self._act_tab_close.triggered.connect(self._on_close_current_tab)
        self.addAction(self._act_tab_close)

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
        add_toolbar_separator(bar)

        # Datei-Gruppe direkt nach dem Burger: Öffnen, Speichern, Vorlage laden.
        bar.addAction(self._act_file_new)
        bar.addAction(self._act_file_open)
        bar.addWidget(self._build_save_button(bar))
        bar.addWidget(self._build_template_button(bar))
        add_toolbar_separator(bar)

        bar.addAction(self._act_undo)
        bar.addAction(self._act_redo)
        add_toolbar_separator(bar)

        bar.addAction(self._act_add_text)
        bar.addAction(self._act_add_image)
        bar.addWidget(self._build_shape_button(bar))
        bar.addAction(self._act_add_clipart)
        bar.addWidget(self._build_code_button(bar))
        bar.addAction(self._act_add_table)
        bar.addAction(self._act_add_datetime)
        add_toolbar_separator(bar)
        bar.addWidget(self._build_align_button(bar))
        bar.addWidget(self._build_layer_button(bar))
        bar.addAction(self._act_delete)
        # Datenbank vor dem Drucken: CSV bleibt sichtbar, das Raster erst mit Datei.
        add_toolbar_separator(bar)
        bar.addAction(self._act_connect_csv)
        bar.addAction(self._act_database)
        add_toolbar_separator(bar)
        bar.addAction(self._act_print)

    def _build_save_button(self, parent: QWidget) -> QToolButton:
        """Speichern mit Klick; der kleine Pfeil öffnet „Speichern unter…“."""
        button = QToolButton(parent)
        button.setObjectName("save_button")
        button.setDefaultAction(self._act_file_save)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(button)
        menu.addAction(self._act_file_save_as)
        button.setMenu(menu)
        return button

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
        self._add_shape_actions(menu)
        button.setMenu(menu)
        return button

    def _build_code_button(self, parent: QWidget) -> QToolButton:
        """Ein Knopf fuer Barcode und QR-Code."""
        button = QToolButton(parent)
        button.setObjectName("code_button")
        button.setIcon(icon("barcode"))
        button.setToolTip(tr("Barcode oder QR-Code einfügen"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        menu.addAction(self._act_add_barcode)
        menu.addAction(self._act_add_qr)
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

    def _build_layer_button(self, parent: QWidget) -> QToolButton:
        """Toolbar-Knopf "Ebenen": Klick oeffnet vor, zurueck, Vorder- und Hintergrund."""
        button = QToolButton(parent)
        button.setObjectName("layer_button")
        button.setIcon(icon("front"))
        button.setToolTip(tr("Ebenen"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for act in (
            self._act_front,
            self._act_forward,
            self._act_backward,
            self._act_back,
        ):
            menu.addAction(act)
        button.setMenu(menu)
        return button

    def _build_main_menu(self) -> QMenu:
        """Primaeres Menue: nur was keinen eigenen Schalter hat.

        Sprache, Erscheinungsbild, Hilfe, Ueber und Beenden.
        Alles andere liegt in der Toolbar, im Kontextmenue oder unter Strg+K.
        """
        menu = QMenu(self)
        self._ensure_template_menu()
        self._build_language_menu(menu)
        self._build_appearance_menu(menu)
        menu.addAction(self._act_help)
        menu.addAction(self._act_about)
        menu.addAction(self._act_quit)
        return menu

    def _add_codes_menu(self, menu: QMenu) -> QMenu:
        """Barcode und QR-Code als ein Eintrag."""
        submenu = menu.addMenu(icon("barcode"), tr("Barcode und QR-Code"))
        submenu.addAction(self._act_add_barcode)
        submenu.addAction(self._act_add_qr)
        return submenu

    def _add_shapes_menu(self, menu: QMenu) -> QMenu:
        """Linie, Rahmen und die uebrigen Formen in einem Eintrag."""
        submenu = menu.addMenu(icon("shape"), tr("Formen"))
        self._add_shape_actions(submenu)
        return submenu

    def _add_align_menu(self, menu: QMenu) -> QMenu:
        submenu = menu.addMenu(icon("align_left"), tr("Ausrichten"))
        for act in (
            self._act_align_left,
            self._act_align_hcenter,
            self._act_align_right,
            self._act_align_top,
            self._act_align_vcenter,
            self._act_align_bottom,
        ):
            submenu.addAction(act)
        return submenu

    def _add_layout_menu(self, menu: QMenu) -> QMenu:
        """Ebenen inkl. Vordergrund und Hintergrund (nur Kontextmenue)."""
        submenu = menu.addMenu(icon("forward"), tr("Layout"))
        for act in (
            self._act_forward,
            self._act_front,
            self._act_backward,
            self._act_back,
            self._act_snap_guides,
        ):
            submenu.addAction(act)
        return submenu

    def _open_command_palette(self) -> None:
        """Strg+K: Gruppen, darin die Befehle. Unabhaengig vom Burger."""
        show_widget(
            self,
            title=tr("Befehle"),
            content=CommandPalette(self._palette_entries()),
            sizing="hint",
            max_size=QSize(440, 480),
            close_on_outside=True,
        )

    def _palette_entries(self) -> list[PaletteEntry]:
        """Volle Befehlsliste. Oben nur die Gruppen, Befehle eine Ebene tiefer."""
        self._fill_template_menu()
        templates_here = [
            self._palette_leaf(action)
            for action in self._template_menu.actions()
            if not action.isSeparator() and action.text() and action.menu() is None
        ]
        return [
            self._palette_group(
                tr("Datei"),
                "open",
                [
                    self._act_file_new,
                    self._act_file_open,
                    self._act_file_save,
                    self._act_file_save_as,
                    self._act_tab_close,
                ],
            ),
            PaletteEntry(tr("Vorlagen"), icon=icon("label"), children=templates_here),
            self._palette_group(
                tr("Einfügen"),
                "text",
                [
                    self._act_add_text,
                    self._act_add_image,
                    self._act_add_clipart,
                    PaletteEntry(
                        tr("Barcode und QR-Code"),
                        icon=icon("barcode"),
                        children=[
                            self._palette_leaf(self._act_add_barcode),
                            self._palette_leaf(self._act_add_qr),
                        ],
                    ),
                    PaletteEntry(
                        tr("Formen"),
                        icon=icon("shape"),
                        children=[
                            self._palette_leaf(self._act_add_line),
                            self._palette_leaf(self._act_add_rect),
                            *(self._palette_leaf(act) for act in self._act_add_shapes),
                        ],
                    ),
                    self._act_add_table,
                    self._act_add_datetime,
                ],
            ),
            self._palette_group(
                tr("Bearbeiten"),
                "undo",
                [
                    self._act_undo,
                    self._act_redo,
                    self._act_copy,
                    self._act_cut,
                    self._act_paste,
                    self._act_duplicate,
                    self._act_bold,
                    self._act_italic,
                    self._act_underline,
                    PaletteEntry(
                        tr("Ausrichten"),
                        icon=icon("align_left"),
                        children=[
                            self._palette_leaf(self._act_align_left),
                            self._palette_leaf(self._act_align_hcenter),
                            self._palette_leaf(self._act_align_right),
                            self._palette_leaf(self._act_align_top),
                            self._palette_leaf(self._act_align_vcenter),
                            self._palette_leaf(self._act_align_bottom),
                        ],
                    ),
                    self._act_delete,
                ],
            ),
            self._palette_group(
                tr("Layout"),
                "forward",
                [
                    self._act_forward,
                    self._act_front,
                    self._act_backward,
                    self._act_back,
                    self._act_snap_guides,
                ],
            ),
            self._palette_group(
                tr("Etikett"),
                "orient_across",
                list(self._media_panel.orientation_actions()),
            ),
            self._palette_group(
                tr("Datenbank"),
                "database",
                [self._act_connect_csv, self._act_database],
            ),
            self._palette_group(
                tr("Ansicht"),
                "zoom_fit",
                [
                    self._act_print_preview,
                    self._act_panel_left,
                    self._act_panel_right,
                    self._act_zoom_out,
                    self._act_zoom_fit,
                    self._act_zoom_in,
                    self._act_zoom_100,
                ],
            ),
            self._palette_group(
                tr("Drucken"),
                "print",
                [self._act_print, self._act_print_history, self._act_forget_tape],
            ),
            self._palette_group(
                tr("Sprache"),
                "language",
                list(self._language_group.actions()),
            ),
            self._palette_group(
                tr("Erscheinungsbild"),
                "appearance",
                list(self._appearance_group.actions()),
            ),
            self._palette_leaf(self._act_help),
            self._palette_leaf(self._act_about),
            self._palette_leaf(self._act_quit),
        ]

    def _palette_leaf(self, action: QAction) -> PaletteEntry:
        return PaletteEntry(action.text(), action=action)

    def _palette_group(
        self, title: str, icon_name: str, children: list
    ) -> PaletteEntry:
        nodes: list[PaletteEntry] = []
        for child in children:
            if isinstance(child, PaletteEntry):
                nodes.append(child)
            else:
                nodes.append(self._palette_leaf(child))
        return PaletteEntry(title, icon=icon(icon_name), children=nodes)

    def _ensure_template_menu(self) -> QMenu:
        """Vorlagenliste fuer Strg+K und den Toolbar-Knopf, nicht fuer den Burger."""
        menu = getattr(self, "_template_menu", None)
        if menu is not None:
            return menu
        menu = QMenu(self)
        menu.setTitle(tr("Vorlagen"))
        menu.setIcon(icon("label"))
        menu.aboutToShow.connect(self._fill_template_menu)
        self._template_menu = menu
        self._fill_template_menu()
        return menu

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
            default=(Path(self._document_path).stem if self._document_path else ""),
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
            action = QAction(icon(f"flag_{code}"), language_name(code), self)
            action.setCheckable(True)
            action.setChecked(code == language())
            action.triggered.connect(
                lambda _checked=False, value=code: self.switch_language(value)
            )
            self._language_group.addAction(action)
            submenu.addAction(action)

    def _build_appearance_menu(self, menu: QMenu) -> None:
        """Hell, dunkel oder das Farbschema der Arbeitsumgebung."""
        submenu = menu.addMenu(icon("appearance"), tr("Erscheinungsbild"))
        self._appearance_group = QActionGroup(self)
        self._appearance_group.setExclusive(True)
        current = self._settings.appearance
        for key, label, glyph in (
            ("system", tr("Wie das System"), "appearance_system"),
            ("light", tr("Hell"), "appearance_light"),
            ("dark", tr("Dunkel"), "appearance_dark"),
        ):
            action = QAction(icon(glyph), label, self)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(
                lambda _checked=False, value=key: self._set_appearance(value)
            )
            self._appearance_group.addAction(action)
            submenu.addAction(action)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # Der Systemwechsel ruft ``_set_appearance`` nicht. Fehlerrot in den
        # Verlaufszellen haengt sonst am alten Grund.
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self._refresh_history_table()
        elif event.type() == QEvent.Type.ActivationChange:
            # Im Hintergrund oder ueber Nacht bleibt der Drucker in Ruhe.
            if self.isActiveWindow():
                self._poll_network_printer()
                self._net_poll_timer.start()
            else:
                self._net_poll_timer.stop()

    def _set_appearance(self, value: str) -> None:
        """Palette umschalten. ``system`` bleibt die Vorgabe."""
        if value == self._settings.appearance:
            return
        self._settings.appearance = value
        self._settings.sync()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, scheme_for(value))
        self._refresh_history_table()

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

        window = MainWindow(self._settings, discover=False)
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
                "guides": tab.canvas.guides(),
                "path": tab.path,
                "document_dirty": tab.is_dirty(),
                "preview": tab.canvas.print_preview,
                "data_source": deepcopy(tab.data_source),
                "serial": deepcopy(tab.serial),
                "current_record": tab.current_record,
                "selected_records": list(tab.selected_records),
                "sheet_output": tab.sheet_output,
                "sheet_part": tab.sheet_part,
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
            "database_open": self._act_database.isChecked(),
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "hq": self._hq_check.isChecked(),
            "resolution": self._resolution().key,
            "copies": self._copies_spin.value(),
            "cut_mode": self._cut_combo.currentData(),
            "print_scope": self._print_scope(),
            "record_from": self._range_request_from,
            "record_to": self._range_request_to,
            "sheet_output": self._sheet_output(),
            "sheet_part": self._sheet_part_combo.currentData(),
            "sheet_start": self._sheet_start.value(),
            "sheet_offset_x": self._sheet_offset_x.value(),
            "sheet_offset_y": self._sheet_offset_y.value(),
            "sheet_printer": self._sheet_printer_combo.currentData() or "",
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
        self._remember_print_range(
            int(state.get("record_from", 1) or 1),
            int(state.get("record_to", 1) or 1),
        )
        self._set_print_scope(str(state.get("print_scope") or ""))
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
        if state.get("database_open") and self._database_is_linked():
            self._act_database.setChecked(True)
        self._address_dirty = bool(state.get("address_dirty", False))
        self._print_jobs = list(state.get("print_jobs") or [])
        self._refresh_history_table()
        if self._canvas.print_preview and not self._act_print_preview.isChecked():
            self._act_print_preview.setChecked(True)
        else:
            self._sync_preview_action()
        self._update_window_title()
        self._sync_print_scope_ui()
        self._apply_sheet_controls(
            enabled=bool(state.get("sheet_output")),
            part=str(state.get("sheet_part") or stationery.DEFAULT_PART),
            start=int(state.get("sheet_start") or 1),
            offset_x=float(state.get("sheet_offset_x") or 0),
            offset_y=float(state.get("sheet_offset_y") or 0),
            printer=str(state.get("sheet_printer") or ""),
        )
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
        connection = self._settings.connection
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
        print_scope = self._settings.print_scope
        record_from = self._settings.record_from
        record_to = self._settings.record_to
        sheet_output = self._settings.sheet_output
        sheet_part = self._settings.sheet_part
        sheet_start = self._settings.sheet_start
        sheet_offset_x = self._settings.sheet_offset_x
        sheet_offset_y = self._settings.sheet_offset_y
        sheet_printer = self._settings.sheet_printer

        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(*DEFAULT_WINDOW_SIZE)
        index = self._media_panel._model_combo.findData(model)
        if index >= 0:
            self._media_panel._model_combo.setCurrentIndex(index)
        # Erst der Anschluss, dann die Adresse - aber nur, wenn sie zu diesem
        # Anschluss gehoert. Eine leere Adresse laesst das Netzwerkfeld leer.
        self._media_panel.set_connection(connection)
        if address and _address_matches_connection(address, connection):
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
        self._remember_print_range(record_from, record_to)
        self._set_print_scope(print_scope)
        self._sync_print_scope_ui()
        self._apply_sheet_controls(
            enabled=sheet_output,
            part=sheet_part,
            start=sheet_start,
            offset_x=sheet_offset_x,
            offset_y=sheet_offset_y,
            printer=sheet_printer,
        )
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
        self._settings.connection = self._media_panel.connection()
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
        guides = self._canvas.guides()
        before = design_snapshot(prev_media, items, selection, guides=guides)
        after = design_snapshot(now_media, items, selection, guides=guides)
        push_if_changed(
            self._undo_stack, before, after, self._restore_design, tr("Band")
        )

    def _sync_media_prev(self) -> None:
        """Bezug fuer den naechsten Band-Befehl auf den aktuellen Stand setzen."""
        self._media_prev = deepcopy(dict(self._media_panel.media_state()))

    def _recompute_canvas(self) -> None:
        self._adjusting = True
        try:
            if self._sheet_output():
                spec = stationery.as_label_spec(self._sheet_template())
                self._canvas.set_label(
                    spec,
                    spec.height_dots,
                    orientation=media.Orientation.ACROSS,
                )
                margins = self._media_panel.margins()
                self._canvas.set_margins(
                    margins.left, margins.right, margins.top, margins.bottom
                )
                return
            orientation = self._media_panel.orientation()
            content = (
                self._content_length_dots(orientation)
                if self._media_panel.auto_length()
                else 0
            )
            length = self._media_panel.label_length_dots(content)
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
            key: spin.value() for key, spin in self._media_panel._margin_spins.items()
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
                media,
                self._canvas.items_serialized(),
                self._selection_keys(),
                guides=self._canvas.guides(),
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
        tab = self._active
        return design_snapshot(
            self._media_panel.media_state(),
            self._canvas.items_serialized(),
            self._selection_keys(),
            serial=tab.serial if tab is not None else None,
            guides=self._canvas.guides(),
        )

    def _capture_history(self) -> None:
        if (
            self._adjusting
            or self._history_suppress
            or self._history_before is not None
        ):
            return
        self._history_before = self._design_snapshot()

    def _commit_history(self, text: str = "") -> None:
        if self._adjusting or self._history_suppress:
            return
        before = self._history_before
        self._history_before = None
        after = self._design_snapshot()
        if push_if_changed(self._undo_stack, before, after, self._restore_design, text):
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
        tab = self._active
        after = design_snapshot(
            before.get("media") or {},
            self._canvas.items_serialized(),
            self._selection_keys(),
            serial=tab.serial if tab is not None else before.get("serial"),
            guides=self._canvas.guides(),
        )
        if push_if_changed(
            self._undo_stack, before, after, self._restore_design, tr("Eigenschaften")
        ):
            self._update_window_title()

    def _seal_pending_edits(self) -> None:
        """Offene Eingabe in den Undo-Stapel legen, bevor Dirty geprüft wird.

        Text, Tabelle, Inspector und angefangenes Randfeld halten den
        Schnappschuss oft noch offen. Ohne diesen Schritt wäre der Stapel
        beim Schließen noch sauber - und die Rückfrage fiele aus.
        """
        self._seal_open_inspector_edit()
        if self._active is not None:
            self._active.canvas.cancel_editing()
        if self._history_before is not None:
            # Restpfad: Randfeld ohne editingFinished. Text/Tabelle/Inspector
            # sind oben schon mit eigenem Text commitet.
            self._commit_history(tr("Ränder"))

    def _restore_design(self, snapshot: dict[str, Any]) -> None:
        """Medien und Objekte aus einem Undo-Schnappschuss setzen."""
        self._adjusting = True
        self._history_suppress = True
        try:
            if "serial" in snapshot and self._active is not None:
                raw_serial = snapshot.get("serial")
                self._active.serial = document.merge_serial(
                    raw_serial if isinstance(raw_serial, Mapping) else None
                )
            self._media_panel.apply_media_state(snapshot.get("media") or {})
            loaded = self._canvas.load_items(list(snapshot.get("items") or []))
            self._canvas.set_guides(list(snapshot.get("guides") or []))
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
        self._sync_cut_options()
        self._update_window_title()

    def _align_selected(self, mode: str) -> None:
        """Auswahl aneinander oder am Randrahmen ausrichten."""
        items = [
            item for item in self._canvas.selected_items() if hasattr(item, "to_dict")
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

        Ein Etikettenbogen zeigt das Raster statt des 1-bit-Bildes.
        """
        if self._sheet_output():
            self._refresh_sheet_preview()
            return
        scale = self._print_scale()
        try:
            image = self._current_render(scale=scale)
        except Exception as exc:  # pragma: no cover - defensiv
            self.statusBar().showMessage(tr("Renderfehler: {error}").format(error=exc))
            return
        options = self._preview_options()
        if self._canvas.print_preview or self._print_sheet_open():
            display = to_qimage(reduce_for_display(binarize(image, options), scale))
            if self._canvas.print_preview:
                self._canvas.set_print_image(display)
            if self._print_sheet_open():
                self._print_preview.set_image(display)
        ratio = ink_ratio(image, options)
        self._ink_label.setText(
            tr("Tinte: {value} %").format(value=QLocale().toString(ratio * 100, "f", 1))
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
        wird erst mit dem Ende der Bearbeitung ein Schritt („Text"), auch
        wenn es leer geblieben ist.
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
        item.editing_started.connect(self._sync_clipboard_actions)
        item.document().contentsChanged.connect(self._on_text_edited)
        item.editing_finished.connect(self._on_text_editing_finished)
        item.editing_finished.connect(self._sync_clipboard_actions)

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
        item.editing_started.connect(self._sync_clipboard_actions)
        item.content_changed.connect(self._on_text_edited)
        item.editing_finished.connect(self._on_table_editing_finished)
        item.editing_finished.connect(self._sync_clipboard_actions)
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
        getippt wird sofort der eigene Text. Ein leer gebliebenes Feld bleibt
        selektiert, damit Schriftgroesse oder Datenbankfeld danach gesetzt
        werden koennen.
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
        """Bearbeitung beenden, ohne ein leeres Textfeld zu loeschen.

        Wegklicken schliesst nur die Eingabe. Das Objekt bleibt, und solange
        nichts anderes gewaehlt ist, bleibt es selektiert - Schriftgroesse
        und Datenbankfeld lassen sich danach setzen. Die Auswahl kommt erst
        nach dem Mausklick, weil die Szene sie im selben Druck noch loescht.
        Esc setzt ``_skip_reselect`` und laesst die Auswahl aus. Der
        Undo-Schritt entsteht sofort, damit die naechste Geste nicht in
        denselben Befehl rutscht.
        """
        item = self.sender()
        if not isinstance(item, TextItem):
            return
        skip = bool(getattr(item, "_skip_reselect", False))
        item._skip_reselect = False
        keep = (
            not skip
            and item.scene() is not None
            and not str(item.toPlainText()).strip()
            and not any(it is not item for it in self._canvas.selected_items())
        )
        if keep:
            item.setSelected(True)
        self._commit_history(tr("Text"))
        if keep:
            QTimer.singleShot(0, lambda item=item: self._reselect_empty_text(item))

    def _reselect_empty_text(self, item: TextItem) -> None:
        """Leeres Feld nach dem Mausklick wieder waehlen, falls noch nichts anderes gilt."""
        if item.scene() is None or item.scene() is not self._canvas.scene():
            return
        if str(item.toPlainText()).strip():
            return
        if any(it is not item for it in self._canvas.selected_items()):
            return
        item.setSelected(True)

    def _on_text_edited(self) -> None:
        self._capture_history()
        self._recompute_canvas()
        self._schedule_refresh()

    def _on_selection_changed(self) -> None:
        selection = self._canvas.selected_items()
        item = selection[0] if len(selection) == 1 else None
        allow_red = (
            self._media_panel.model.two_color
            and self._media_panel.label.color.supports_red
        )
        fields: list[str] = []
        tab = self._active
        if tab is not None and tab.csv_table is not None:
            fields = list(tab.csv_table.fields)
        self._normalize_serial_limits()
        self._inspector.set_database_fields(fields)
        self._inspector.set_serial_context(
            tab.serial if tab is not None else None,
            csv_connected=tab is not None and tab.csv_table is not None,
        )
        self._inspector.set_item(item, allow_red=allow_red)
        self._sync_arrange_actions()
        self._sync_text_style_actions()
        self._sync_clipboard_actions()

    def _on_inspector_edit_committed(self) -> None:
        """Undo-Schritt schliessen; Database Field baut den Inspector neu."""
        self._commit_history(tr("Eigenschaften"))
        if self._inspector.take_binding_refresh():
            self._on_selection_changed()

    def _on_database_binding_changed(self) -> None:
        """Neues Feld sofort in den Snapshot schreiben (D11), ohne den Aufbau."""
        self._reconcile_serial_enabled()
        self._apply_merge_to_canvas(refresh_inspector=False)
        self._sync_cut_options()

    def _serial_target_item(self):
        """Einzeln ausgewaehltes Text-, Barcode- oder QR-Objekt, sonst ``None``."""
        selected = self._canvas.selected_items()
        if len(selected) != 1:
            return None
        item = selected[0]
        if getattr(item, "kind", None) not in ("text", "qr", "barcode"):
            return None
        if not hasattr(item, "set_binding"):
            return None
        return item

    def _any_serial_binding(self) -> bool:
        for item in self._canvas.ordered_items():
            binding = getattr(item, "binding", None)
            if isinstance(binding, Mapping) and binding.get("source") == "serial":
                return True
        return False

    def _reconcile_serial_enabled(self) -> None:
        """Ohne Serien-Objekt ist die Serie aus (D4/D5)."""
        tab = self._active
        if tab is None or self._any_serial_binding() or not tab.serial.get("enabled"):
            return
        spec = dict(tab.serial)
        spec["enabled"] = False
        tab.serial = document.merge_serial(spec)

    def _normalize_serial_limits(self) -> None:
        """Anzahl auf 1…99 und Schritt weg von 0, passend zum Inspector."""
        tab = self._active
        if tab is None:
            return
        spec = dict(tab.serial)
        changed = False
        count = spec.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            spec["count"] = 1
            changed = True
        elif count > 99:
            spec["count"] = 99
            changed = True
        step = spec.get("step", 1)
        if isinstance(step, bool) or not isinstance(step, int) or step == 0:
            spec["step"] = 1
            changed = True
        if not changed:
            return
        tab.serial = document.merge_serial(spec)
        if not self._history_suppress and not self._adjusting:
            self._document_dirty = True

    def _on_serial_spec_changed(self, spec) -> None:
        """Start/Anzahl/Schritt/Prefix aus dem Inspector, ohne ``enabled`` zu drehen."""
        if self._adjusting or self._history_suppress:
            return
        tab = self._require_tab()
        merged = document.merge_serial(spec if isinstance(spec, Mapping) else None)
        step = merged.get("step", 1)
        if isinstance(step, bool) or not isinstance(step, int) or step == 0:
            return
        count = merged.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int):
            count = 1
        merged["count"] = max(1, min(99, int(count)))
        # Gebundene Objekte drucken die Serie; ein reiner Parameter-Edit
        # schaltet sie ein, ohne das Binding anzufassen.
        merged["enabled"] = (
            bool(tab.serial.get("enabled")) or self._any_serial_binding()
        )
        if merged == tab.serial:
            return
        tab.serial = merged
        self._apply_merge_to_canvas(refresh_inspector=False)
        self._sync_cut_options()

    def _on_serial_toggle_requested(self, checked: bool) -> None:
        """Serie an das ausgewaehlte Objekt binden oder loesen (D4)."""
        if self._adjusting or self._history_suppress:
            return
        tab = self._require_tab()
        item = self._serial_target_item()
        source = (item.binding or {}).get("source") if item is not None else None
        if checked:
            if item is None or source == "database":
                return
            item.set_binding({"source": "serial"})
            spec = dict(tab.serial)
            spec["enabled"] = True
            tab.serial = document.merge_serial(spec)
        else:
            if item is not None and source == "serial":
                item.clear_binding()
            if not self._any_serial_binding():
                spec = dict(tab.serial)
                spec["enabled"] = False
                tab.serial = document.merge_serial(spec)
        self._apply_merge_to_canvas(refresh_inspector=False)
        self._sync_cut_options()

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
        self._reconcile_serial_enabled()
        self._commit_history(tr("Löschen"))
        self._on_items_changed()

    def _selected_serializable(self) -> list:
        return [
            item for item in self._canvas.selected_items() if hasattr(item, "to_dict")
        ]

    def _sync_clipboard_actions(self) -> None:
        """Kopieren nur bei Auswahl ausserhalb der Inline-Bearbeitung."""
        if self._active is None or not hasattr(self, "_act_copy"):
            return
        editing = self._canvas.inline_editing()
        can_copy = bool(self._selected_serializable()) and not editing
        self._act_copy.setEnabled(can_copy)
        self._act_cut.setEnabled(can_copy)
        self._act_duplicate.setEnabled(can_copy)
        self._act_paste.setEnabled(not editing and _items_on_clipboard() is not None)

    def _on_copies_spawned(self, copies) -> None:
        for item in copies:
            self._wire_text_item(item)
            self._wire_table_item(item)
            self._wire_datetime_item(item)

    def _copy_selected(self) -> None:
        if self._active is None or self._canvas.inline_editing():
            return
        items = self._selected_serializable()
        if not items:
            return
        _put_items_on_clipboard(items)
        self._paste_generation = 0

    def _cut_selected(self) -> None:
        if self._active is None or self._canvas.inline_editing():
            return
        items = self._selected_serializable()
        if not items:
            return
        _put_items_on_clipboard(items)
        self._paste_generation = 0
        self._capture_history()
        self._history_suppress = True
        try:
            self._canvas.delete_selected()
        finally:
            self._history_suppress = False
        self._reconcile_serial_enabled()
        self._commit_history(tr("Ausschneiden"))
        self._on_items_changed()

    def _paste_clipboard(self) -> None:
        if self._active is None or self._canvas.inline_editing():
            return
        payload = _items_on_clipboard()
        if not payload:
            return
        self._paste_generation += 1
        delta = DUPLICATE_OFFSET_DOTS * self._paste_generation
        self._spawn_copies(payload, delta, delta, paste_label())

    def _duplicate_selected(self) -> None:
        if self._active is None or self._canvas.inline_editing():
            return
        items = self._selected_serializable()
        if not items:
            return
        self._spawn_copies(
            [item.to_dict() for item in items],
            DUPLICATE_OFFSET_DOTS,
            DUPLICATE_OFFSET_DOTS,
            tr("Duplizieren"),
        )

    def _spawn_copies(
        self, payload: list[dict[str, Any]], dx: float, dy: float, undo_text: str
    ) -> None:
        """Kopien einsetzen. Ein Undo-Schritt, wie beim Einfuegen eines Objekts."""
        self._seal_open_inspector_edit()
        self._capture_history()
        self._history_suppress = True
        try:
            created = []
            for raw in payload:
                item = item_from_dict(dict(raw))
                item.moveBy(dx, dy)
                self._wire_text_item(item)
                self._wire_table_item(item)
                self._wire_datetime_item(item)
                created.append(item)
            self._canvas.add_copies(created)
            self._recompute_canvas()
            for item in created:
                self._canvas.keep_inside_printable(item)
            self._schedule_refresh()
        finally:
            self._history_suppress = False
        self._commit_history(undo_text)
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
        duplicated = self._canvas.take_gesture_duplicate()
        if not self._history_suppress:
            self._reconcile_serial_enabled()
            text = tr("Bearbeiten")
            before = self._history_before
            if duplicated:
                text = tr("Duplizieren")
            elif before is not None and len(self._canvas.items_serialized()) < len(
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
        self._add_item(
            TextItem(text, font_pixel_size=self._default_font_size()), scene_pos
        )

    def _build_context_menu(self, scene_pos: QPointF) -> QMenu:
        menu = QMenu(self)
        menu.addAction(
            icon("text"),
            tr("Text einfügen"),
            lambda: self._on_text_requested(scene_pos),
        )
        menu.addAction(self._act_add_image)
        menu.addAction(self._act_add_clipart)
        self._add_codes_menu(menu)
        self._add_shapes_menu(menu)
        menu.addAction(self._act_add_table)
        menu.addAction(self._act_add_datetime)
        menu.addSeparator()
        menu.addAction(self._act_copy)
        menu.addAction(self._act_cut)
        menu.addAction(self._act_paste)
        menu.addAction(self._act_duplicate)
        if self._canvas.selected_items():
            menu.addSeparator()
            self._add_align_menu(menu)
            self._add_layout_menu(menu)
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
            QRectF(
                0,
                0,
                int(self._canvas.printable_rect().width() * 0.6),
                int(max(40, height * 0.4)),
            )
        )
        self._add_item(item)

    def _add_shape_actions(self, menu: QMenu) -> None:
        """Dieselben Formen wie der Toolbar-Knopf und das Kontextmenue."""
        menu.addAction(self._act_add_line)
        menu.addAction(self._act_add_rect)
        menu.addSeparator()
        for act in self._act_add_shapes:
            menu.addAction(act)

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
        """Kleine 1×2-Tabelle. Weitere Zeilen und Spalten kommen im Inspector."""
        rect = self._canvas.margin_rect()
        if rect.width() < 40 or rect.height() < 40:
            rect = self._canvas.printable_rect()
        inset = 2.0
        rows, cols = 1, 2
        cell_w = media.mm_to_dots(22)
        cell_h = media.mm_to_dots(8)
        width = min(cell_w * cols, max(40.0, rect.width() - 2 * inset))
        height = min(cell_h * rows, max(40.0, rect.height() - 2 * inset))
        item = TableItem(
            rows,
            cols,
            width,
            height,
            font_pixel_size=max(16, int(height * 0.45)),
        )
        self._add_item(
            item,
            QPointF(rect.left() + inset, rect.top() + inset),
            fit=False,
        )

    def _text_style_targets(self) -> list:
        """Ausgewaehlte Objekte, die Fett, Kursiv und Unterstrichen tragen."""
        targets = []
        for item in self._canvas.selected_items():
            if getattr(item, "kind", None) == "table" or all(
                hasattr(item, f"set_{name}") for name in ("bold", "italic", "underline")
            ):
                targets.append(item)
        return targets

    def _text_style_value(self, item, name: str) -> bool:
        if getattr(item, "kind", None) == "table":
            same, value = item.selected_uniform(name)
            return bool(value) if same else False
        return bool(getattr(item, name))

    def _apply_text_style(self, item, name: str, value: bool) -> None:
        if getattr(item, "kind", None) == "table":
            item.set_selected(name, value)
            return
        getattr(item, f"set_{name}")(value)

    def _toggle_text_style(self, name: str) -> None:
        """Stil an der Auswahl umschalten - dieselben Setter wie der Inspector.

        Waehrend der Eingabe ist schon ein Schnappschuss offen. Der wird zuerst
        als „Text" geschlossen, der Stil folgt als eigener Schritt, und weiteres
        Tippen bekommt wieder einen neuen Schnappschuss.
        """
        targets = self._text_style_targets()
        if not targets:
            return
        turn_on = not all(self._text_style_value(item, name) for item in targets)
        labels = {
            "bold": tr("Fett"),
            "italic": tr("Kursiv"),
            "underline": tr("Unterstrichen"),
        }
        typing = (
            self._canvas._focused_editor() is not None and not self._inspector.edit_open
        )
        if typing:
            self._commit_history(tr("Text"))
        own_step = self._history_before is None
        if own_step:
            self._capture_history()
        for item in targets:
            self._apply_text_style(item, name, turn_on)
        if own_step:
            self._commit_history(labels[name])
        self._canvas.viewport().update()
        self._recompute_canvas()
        self._schedule_refresh()
        self._on_selection_changed()
        if typing and self._canvas._focused_editor() is not None:
            self._capture_history()

    def _sync_text_style_actions(self) -> None:
        targets = self._text_style_targets()
        actions = (
            ("bold", self._act_bold),
            ("italic", self._act_italic),
            ("underline", self._act_underline),
        )
        for name, action in actions:
            action.blockSignals(True)
            action.setEnabled(bool(targets))
            checked = bool(targets) and all(
                self._text_style_value(item, name) for item in targets
            )
            action.setChecked(checked)
            action.blockSignals(False)

    def _sync_arrange_actions(self) -> None:
        """Stapel-Befehle nur mit Auswahl und weiteren Objekten; Snap mit Auswahl."""
        selected = [
            item for item in self._canvas.selected_items() if hasattr(item, "to_dict")
        ]
        others = [item for item in self._canvas.ordered_items() if item not in selected]
        can_stack = bool(selected and others)
        for act in (
            self._act_forward,
            self._act_backward,
            self._act_front,
            self._act_back,
        ):
            act.setEnabled(can_stack)
        self._act_snap_guides.setEnabled(bool(selected))

    def _stack_bottom_to_top(self) -> list:
        """Sichtbare Stapelreihenfolge, unten zuerst.

        ``scene.items()`` ist oben zuerst und kennt z zusammen mit der
        Einfuegereihenfolge. Nur nach z zu sortieren dreht den Gleichstand um.
        """
        items = [
            item
            for item in self._canvas.scene().items()
            if hasattr(item, "to_dict") and not getattr(item, "_pending_discard", False)
        ]
        items.reverse()
        return items

    def _apply_stack(self, order: list) -> None:
        current = [id(item) for item in self._stack_bottom_to_top()]
        if current == [id(item) for item in order]:
            return
        self._capture_history()
        for index, item in enumerate(order):
            item.setZValue(float(index))
        self._commit_history(tr("Reihenfolge"))
        self._canvas.viewport().update()

    def _step_stack(self, direction: int) -> None:
        """Eine sichtbare Stufe, an den nicht ausgewaehlten Nachbarn vorbei."""
        selected = {
            id(item)
            for item in self._canvas.selected_items()
            if hasattr(item, "to_dict")
        }
        order = self._stack_bottom_to_top()
        if not selected or len(order) < 2:
            return
        if direction > 0:
            index = len(order) - 1
            while index >= 0:
                if (
                    id(order[index]) in selected
                    and index + 1 < len(order)
                    and id(order[index + 1]) not in selected
                ):
                    order[index], order[index + 1] = order[index + 1], order[index]
                index -= 1
        else:
            index = 0
            while index < len(order):
                if (
                    id(order[index]) in selected
                    and index > 0
                    and id(order[index - 1]) not in selected
                ):
                    order[index], order[index - 1] = order[index - 1], order[index]
                index += 1
        self._apply_stack(order)

    def _stack_extreme(self, *, front: bool) -> None:
        """Auswahl in einem Schritt ganz nach vorn oder ganz nach hinten."""
        selected = {
            id(item)
            for item in self._canvas.selected_items()
            if hasattr(item, "to_dict")
        }
        order = self._stack_bottom_to_top()
        picked = [item for item in order if id(item) in selected]
        others = [item for item in order if id(item) not in selected]
        if not picked or not others:
            return
        self._apply_stack(others + picked if front else picked + others)

    def _snap_selection_to_guides(self) -> None:
        """Einmal einrasten: Hilfslinien, Bandkanten und andere Objekte."""
        items = [
            item for item in self._canvas.selected_items() if hasattr(item, "to_dict")
        ]
        if not items:
            return
        bbox = QRectF()
        for item in items:
            box = item.sceneBoundingRect()
            bbox = box if bbox.isNull() else bbox.united(box)
        dx, dy, guides = self._canvas._snap_move(bbox, 0.0, 0.0, exclude=items)
        if not dx and not dy:
            return
        self._capture_history()
        for item in items:
            item.moveBy(dx, dy)
        self._canvas._guides = guides
        self._commit_history(tr("An Hilfslinien ausrichten"))
        self._on_items_changed()

    # -------------------------------------------------------------- Print ---
    def _sheet_output(self) -> bool:
        combo = getattr(self, "_output_combo", None)
        return combo is not None and combo.currentData() == stationery.OUTPUT_SHEET

    def _sheet_template(self) -> stationery.SheetTemplate:
        part = self._sheet_part_combo.currentData() or stationery.DEFAULT_PART
        return stationery.get_template(str(part))

    def _on_output_target_changed(self) -> None:
        self._sync_output_target()

    def _on_sheet_part_changed(self) -> None:
        self._sync_sheet_start_range()
        self._stash_sheet_target()
        self._update_sheet_hint()
        self._recompute_canvas()
        self._schedule_refresh()

    def _stash_sheet_target(self) -> None:
        """Ziel des sichtbaren Reiters merken. Die anderen bleiben, wie sie sind."""
        tab = self._active
        if tab is None or not hasattr(self, "_output_combo"):
            return
        tab.sheet_output = self._sheet_output()
        tab.sheet_part = str(
            self._sheet_part_combo.currentData() or stationery.DEFAULT_PART
        )

    def _apply_tab_sheet_target(self, tab: LabelTab) -> None:
        """Combo auf das Ziel dieses Reiters stellen, bevor die Fläche folgt."""
        if not hasattr(self, "_output_combo"):
            return
        widgets = (self._output_combo, self._sheet_part_combo)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            output = (
                stationery.OUTPUT_SHEET
                if tab.sheet_output
                else stationery.OUTPUT_BROTHER
            )
            index = self._output_combo.findData(output)
            if index >= 0:
                self._output_combo.setCurrentIndex(index)
            part = tab.sheet_part or stationery.DEFAULT_PART
            index = self._sheet_part_combo.findData(part)
            if index < 0:
                part = stationery.DEFAULT_PART
                index = self._sheet_part_combo.findData(part)
                tab.sheet_part = part
            if index >= 0:
                self._sheet_part_combo.setCurrentIndex(index)
            self._sync_sheet_start_range()
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self._sync_output_target()

    def _sync_output_target(self) -> None:
        """Brother-Felder oder den Bogen zeigen, die Fläche folgt dem Ziel."""
        sheet = self._sheet_output()
        self._print_button.setToolTip(
            tr("Bogen an den Systemdrucker senden") if sheet else tr("Drucken")
        )
        self._quality_box.setVisible(not sheet)
        self._output_form.setRowVisible(self._cut_combo, not sheet)
        self._output_form.setRowVisible(self._sheet_hint, sheet)
        self._output_form.setRowVisible(self._sheet_pdf_button, sheet)
        self._sheet_box.setVisible(sheet)
        self._media_panel.set_tape_controls_visible(not sheet)
        self._left_panel.set_title(
            tr("Etikettenbogen") if sheet else tr("Band & Drucker")
        )
        self._stash_sheet_target()
        if not sheet:
            self._set_sheet_preview_caption(0)
        if sheet:
            self._reload_system_printers()
            self._sync_sheet_start_range()
            self._update_sheet_hint()
        self._recompute_canvas()
        self._schedule_refresh()

    def _on_sheet_start_picked(self, number: int) -> None:
        if self._sheet_start.value() != number:
            self._sheet_start.setValue(number)

    def _sync_sheet_start_range(self) -> None:
        template = self._sheet_template()
        self._sheet_picker.set_template(template)
        self._sheet_start.setMaximum(template.per_sheet)
        self._sheet_picker.set_start(self._sheet_start.value())

    def _reload_system_printers(self) -> None:
        current = self._sheet_printer_combo.currentData()
        preferred = current or self._settings.sheet_printer
        self._sheet_printer_combo.blockSignals(True)
        self._sheet_printer_combo.clear()
        names = system_printers()
        if names:
            for name in names:
                self._sheet_printer_combo.addItem(name, name)
            index = self._sheet_printer_combo.findData(preferred)
            if index >= 0:
                self._sheet_printer_combo.setCurrentIndex(index)
        else:
            self._sheet_printer_combo.addItem(tr("Kein Drucker gefunden"), None)
        self._sheet_printer_combo.blockSignals(False)

    def _sheet_offsets(self) -> tuple[float, float]:
        return self._sheet_offset_x.value(), self._sheet_offset_y.value()

    def _sheet_job(self):
        """Gerenderte Etiketten und ihre Felder auf dem Bogen."""
        template = self._sheet_template()
        labels = self._planned_labels()
        placements = stationery.plan_sheet(
            template,
            len(labels),
            start=self._sheet_start.value(),
            copies=self._copies_spin.value(),
        )
        images = self._render_print_images(for_sheet=True)
        return template, images, placements

    def _update_sheet_hint(self) -> None:
        try:
            count = len(self._planned_labels())
            placements = stationery.plan_sheet(
                self._sheet_template(),
                count,
                start=self._sheet_start.value(),
                copies=self._copies_spin.value(),
            )
        except (merge_engine.MergeError, stationery.SheetError) as exc:
            self._sheet_hint.setText(str(exc))
            return
        self._sheet_hint.setText(
            stationery.fill_caption(
                stationery.filled_per_page(placements),
                self._sheet_template().per_sheet,
            )
        )

    def _refresh_sheet_preview(self) -> None:
        """Vorschau von Bogen 1 mit den echten Datensätzen, nicht dem aktuellen Bild."""
        self._canvas.set_print_image(None)
        self._update_sheet_hint()
        if not self._print_sheet_open():
            self._set_sheet_preview_caption(0)
            return
        try:
            template = self._sheet_template()
            count = len(self._planned_labels())
            placements = stationery.plan_sheet(
                template,
                count,
                start=self._sheet_start.value(),
                copies=self._copies_spin.value(),
            )
            page0 = [place for place in placements if place.page == 0]
            indexes = sorted({place.image_index for place in page0})
            rendered = self._render_print_images(for_sheet=True, only_indexes=indexes)
            remap = {old: new for new, old in enumerate(indexes)}
            preview_places = [
                stationery.Placement(
                    0, place.slot, remap[place.image_index], place.x_mm, place.y_mm
                )
                for place in page0
            ]
            offset_x, offset_y = self._sheet_offsets()
            self._print_preview.set_image(
                render_page_image(
                    template,
                    rendered,
                    preview_places,
                    offset_x_mm=offset_x,
                    offset_y_mm=offset_y,
                )
            )
            self._set_sheet_preview_caption(stationery.page_count(placements))
        except (merge_engine.MergeError, stationery.SheetError):
            self._print_preview.set_image(None)
            self._set_sheet_preview_caption(0)
        except Exception as exc:  # pragma: no cover - defensiv
            self._set_sheet_preview_caption(0)
            self.statusBar().showMessage(tr("Renderfehler: {error}").format(error=exc))

    def _set_sheet_preview_caption(self, pages: int) -> None:
        """Nur bei mehreren Bögen: die Vorschau ist die erste Seite."""
        label = getattr(self, "_sheet_preview_page", None)
        if label is None:
            return
        if self._sheet_output() and pages > 1 and self._print_sheet_open():
            label.setText(
                tr("Vorschau: Bogen {page} von {count}").format(page=1, count=pages)
            )
            label.show()
            return
        label.hide()
        label.clear()

    def _remember_sheet_job(
        self,
        address: str,
        cell_count: int,
        outcome: str,
        *,
        copies: int,
        part: str,
    ) -> None:
        if cell_count == 1:
            label = tr("Zweckform {part} · {count} Etikett").format(
                part=part, count=cell_count
            )
        else:
            label = tr("Zweckform {part} · {count} Etiketten").format(
                part=part, count=cell_count
            )
        self._pending_job = (
            datetime.now(),
            label,
            copies,
            "Zweckform",
            address,
            part,
        )
        self._record_print_job(outcome)

    def _sheet_busy(self) -> bool:
        worker = self._sheet_worker
        return self._sheet_preparing or (worker is not None and worker.isRunning())

    def _on_sheet_print(self) -> None:
        if self._sheet_busy():
            return
        if self._print_worker is not None and self._print_worker.isRunning():
            return
        self._inspector.flush_edit()
        name = self._sheet_printer_combo.currentData()
        if not name:
            self._show_print_message(
                "warning",
                tr("Etikettenbogen"),
                tr(
                    "Kein Systemdrucker. PDF speichern und das mit "
                    "Originalgröße drucken."
                ),
            )
            return
        from_sheet = self._print_sheet_open()
        self._arm_sheet_job(from_sheet)
        QTimer.singleShot(0, lambda: self._begin_sheet_print(str(name), from_sheet))

    def _on_sheet_pdf(self) -> None:
        if self._sheet_busy():
            return
        if self._print_worker is not None and self._print_worker.isRunning():
            return
        self._inspector.flush_edit()
        from_sheet = self._print_sheet_open()
        self._arm_sheet_job(from_sheet)
        QTimer.singleShot(0, lambda: self._begin_sheet_pdf(from_sheet))

    def _arm_sheet_job(self, from_sheet: bool) -> None:
        """Dialog zu, Knopf dreht, die Statuszeile kann sich noch zeichnen."""
        self._sheet_preparing = True
        self._sheet_return_on_error = from_sheet
        self._print_button.set_busy(True)
        self.statusBar().showMessage(tr("Bogen wird aufgebaut…"))
        if from_sheet:
            self._close_print_sheet()

    def _begin_sheet_print(self, name: str, from_sheet: bool) -> None:
        try:
            template, images, placements = self._sheet_job()
        except (merge_engine.MergeError, stationery.SheetError) as exc:
            self._abort_sheet_job(from_sheet, "warning", str(exc))
            return
        except Exception as exc:
            self._abort_sheet_job(
                from_sheet,
                "critical",
                tr("Bogen konnte nicht gedruckt werden:\n{error}").format(error=exc),
            )
            return
        offset_x, offset_y = self._sheet_offsets()
        self._start_sheet_worker(
            "print",
            template=template,
            images=images,
            placements=placements,
            offset_x=offset_x,
            offset_y=offset_y,
            printer_name=name,
            copies=self._copies_spin.value(),
        )

    def _begin_sheet_pdf(self, from_sheet: bool) -> None:
        try:
            template, images, placements = self._sheet_job()
        except (merge_engine.MergeError, stationery.SheetError) as exc:
            self._abort_sheet_job(from_sheet, "warning", str(exc))
            return
        except Exception as exc:
            self._abort_sheet_job(
                from_sheet,
                "critical",
                tr("Bogen konnte nicht gedruckt werden:\n{error}").format(error=exc),
            )
            return
        self._pending_sheet = (template, images, placements, self._copies_spin.value())

        def _chosen(path: str | None) -> None:
            job = self._pending_sheet
            self._pending_sheet = None
            if not path or job is None:
                self._finish_sheet_prepare(from_sheet)
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            saved_template, saved_images, saved_placements, copies = job
            offset_x, offset_y = self._sheet_offsets()
            self._settings.document_dir = str(Path(path).parent)
            self._start_sheet_worker(
                "pdf",
                template=saved_template,
                images=saved_images,
                placements=saved_placements,
                offset_x=offset_x,
                offset_y=offset_y,
                path=path,
                copies=copies,
            )

        save_file(
            self,
            caption=tr("Bogen speichern"),
            name_filter=tr("PDF (*.pdf)"),
            on_selected=_chosen,
            start_dir=self._settings.document_dir or "",
            default_name=f"Zweckform-{template.part}.pdf",
        )

    def _start_sheet_worker(
        self,
        kind: str,
        *,
        template: stationery.SheetTemplate,
        images: list[Image.Image],
        placements: list[stationery.Placement],
        offset_x: float,
        offset_y: float,
        copies: int,
        printer_name: str = "",
        path: str = "",
    ) -> None:
        self._sheet_meta = (
            kind,
            printer_name or "PDF",
            len(placements),
            copies,
            path,
            template.part,
        )
        worker = SheetOutputWorker(
            kind=kind,
            template=template,
            images=images,
            placements=placements,
            offset_x=offset_x,
            offset_y=offset_y,
            printer_name=printer_name,
            path=path,
        )
        worker.succeeded.connect(self._on_sheet_output_succeeded)
        worker.failed.connect(self._on_sheet_output_failed)
        worker.finished.connect(self._on_sheet_output_finished)
        worker.finished.connect(worker.deleteLater)
        self._sheet_worker = worker
        worker.start()

    def _finish_sheet_prepare(self, reopen: bool) -> None:
        """Dateidialog abgebrochen: Knopf los, Druckdialog wieder auf."""
        self._sheet_preparing = False
        self._sheet_return_on_error = False
        self._print_button.set_busy(False)
        if reopen:
            QTimer.singleShot(0, self._return_to_print_sheet)

    def _abort_sheet_job(self, reopen: bool, kind: str, text: str) -> None:
        """Aufbau gescheitert. Die Meldung geht vor, der Druckdialog folgt ihr."""
        self._sheet_preparing = False
        self._sheet_return_on_error = False
        self._print_button.set_busy(False)
        sheet = show_message(self, kind, tr("Etikettenbogen"), text)
        if reopen:
            sheet.closed.connect(
                lambda: QTimer.singleShot(0, self._return_to_print_sheet)
            )

    def _on_sheet_output_succeeded(self) -> None:
        meta = getattr(self, "_sheet_meta", None)
        self._sheet_meta = None
        reopen = self._sheet_return_on_error
        self._sheet_return_on_error = False
        if meta is None:
            return
        kind, address, cells, copies, path, part = meta
        outcome = "saved" if kind == "pdf" else "sent"
        self._remember_sheet_job(address, cells, outcome, copies=copies, part=part)
        if kind == "pdf":
            self.statusBar().showMessage(
                tr("PDF gespeichert: {path}").format(path=path),
                8000,
            )
            if reopen:
                QTimer.singleShot(0, self._return_to_print_sheet)
            return
        self.statusBar().showMessage(
            tr("{count} Etiketten an {printer} gesendet.").format(
                count=cells, printer=address
            ),
            8000,
        )

    def _on_sheet_output_failed(self, message: str) -> None:
        self._sheet_meta = None
        reopen = self._sheet_return_on_error
        self._sheet_return_on_error = False
        self.statusBar().showMessage(tr("Druck fehlgeschlagen."), 8000)
        # Der Dialog war schon zu. Erst die Meldung, danach wieder der Druck.
        sheet = show_message(self, "critical", tr("Etikettenbogen"), message)
        if reopen:
            sheet.closed.connect(
                lambda: QTimer.singleShot(0, self._return_to_print_sheet)
            )

    def _on_sheet_output_finished(self) -> None:
        self._sheet_worker = None
        self._sheet_preparing = False
        self._print_button.set_busy(False)

    def _apply_sheet_controls(
        self,
        *,
        enabled: bool,
        part: str,
        start: int,
        offset_x: float,
        offset_y: float,
        printer: str,
    ) -> None:
        widgets = (
            self._output_combo,
            self._sheet_part_combo,
            self._sheet_start,
            self._sheet_offset_x,
            self._sheet_offset_y,
            self._sheet_printer_combo,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            output = stationery.OUTPUT_SHEET if enabled else stationery.OUTPUT_BROTHER
            index = self._output_combo.findData(output)
            if index >= 0:
                self._output_combo.setCurrentIndex(index)
            index = self._sheet_part_combo.findData(part)
            if index >= 0:
                self._sheet_part_combo.setCurrentIndex(index)
            self._sync_sheet_start_range()
            self._sheet_start.setValue(min(max(1, start), self._sheet_start.maximum()))
            self._sheet_offset_x.setValue(offset_x)
            self._sheet_offset_y.setValue(offset_y)
            self._settings.sheet_printer = printer
            self._reload_system_printers()
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self._sync_output_target()

    def _on_print_key(self) -> None:
        """Enter im Druck-Sheet: wie ein Klick auf den Druck-Knopf.

        Hat ein anderer Knopf den Fokus, bekommt er den Klick.
        """
        focus = QApplication.focusWidget()
        if (
            isinstance(focus, (QPushButton, QToolButton))
            and focus is not self._print_button
        ):
            focus.click()
            return
        if self._print_button.isEnabled():
            self._on_print()

    def _on_print(self) -> None:
        if self._sheet_output():
            self._on_sheet_print()
            return
        if self._sheet_busy():
            return
        if self._print_worker is not None and self._print_worker.isRunning():
            return
        self._inspector.flush_edit()
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
            images = self._render_print_images()
        except merge_engine.MergeError as exc:
            # Bereich oder Kopien stehen im Druck-Sheet: dorthin zurueck.
            self._show_print_message("warning", tr("Drucken"), str(exc))
            return
        except Exception as exc:
            show_message(
                self,
                "critical",
                tr("Rendern"),
                tr("Etikett konnte nicht gerendert werden:\n{error}").format(error=exc),
            )
            return
        label = self._media_panel.label
        # Eine Rueckfrage verdraengt das Druck-Sheet; danach kommt es wieder.
        from_sheet = self._print_sheet_open()
        fault = self._known_fault(config)
        if fault:
            ask_print_anyway(
                self,
                title=tr("Drucker prüfen"),
                text=tr(
                    "Der Drucker meldet: {errors}\n\n"
                    "Erst beheben, sonst druckt der Drucker den Auftrag wahrscheinlich nicht."
                ).format(errors=", ".join(fault)),
                on_choice=partial(
                    self._on_fault_choice, config, images, label, from_sheet
                ),
            )
            return
        self._check_loaded_tape(config, images, label, from_sheet)

    def _known_fault(self, config) -> tuple[str, ...]:
        """Stoerung laut letzter Abfrage (z. B. Klappe offen), sonst leer."""
        if config.backend != "network":
            return ()
        poll = self._fresh_poll(config.address)
        status = poll["status"] if poll is not None else None
        if status is None or not status.fault:
            return ()
        return status.texts

    def _on_fault_choice(
        self, config, images, label, from_sheet: bool, choice: str
    ) -> None:
        if choice == "print":
            self._check_loaded_tape(config, images, label, from_sheet)
        elif from_sheet:
            QTimer.singleShot(0, self._return_to_print_sheet)

    def _return_to_print_sheet(self) -> None:
        """Nach einer Rueckfrage wieder ins Druck-Sheet.

        Hat ein anderes Sheet die Rueckfrage verdraengt (z. B. die Frage beim
        Schliessen), bleibt es vorn. Darum kommt "Abbrechen" erst verzoegert
        hier an: dann ist das andere Sheet schon sichtbar.
        """
        if not self.isVisible():
            return
        if any(sheet.isVisible() for sheet in self.findChildren(Sheet)):
            return
        self._show_print_sheet()

    def _show_print_message(self, kind: str, title: str, text: str, **kwargs) -> None:
        """Meldung zum Druck; danach wieder ins Druck-Sheet, wenn es offen war."""
        from_sheet = self._print_sheet_open()
        sheet = show_message(self, kind, title, text, **kwargs)
        if from_sheet:
            sheet.closed.connect(
                lambda: QTimer.singleShot(0, self._return_to_print_sheet)
            )

    def _check_loaded_tape(self, config, images, label, from_sheet: bool) -> None:
        loaded = self._settings.loaded_label(config.address)
        if (
            config.backend == "network"
            and loaded
            and not self._fits_loaded(label, loaded)
        ):
            ask_loaded_tape(
                self,
                title=tr("Band prüfen"),
                text=tr(
                    "Gewählt: {selected}\nLaut QLInux eingelegt: {loaded}\n\n"
                    "Stimmt das nicht, bricht der Drucker mit einem Fehler ab."
                ).format(
                    selected=self._band_name(label.identifier),
                    loaded=self._band_name(loaded),
                ),
                on_choice=partial(
                    self._on_loaded_tape_choice, config, images, label, from_sheet
                ),
            )
            return
        if from_sheet:
            self._return_to_print_sheet()
        self._start_print(config, images, label)

    def _band_name(self, identifier: str) -> str:
        try:
            return media.get_label(identifier).display_name
        except KeyError:
            return identifier

    @staticmethod
    def _fits_loaded(label: media.LabelSpec, loaded: str) -> bool:
        try:
            return label.prints_on(media.get_label(loaded))
        except KeyError:
            return False

    def _remember_printed_tape(self, address: str, identifier: str) -> None:
        """Nach sauberer SNMP-Antwort liegt das gedruckte Band ein.

        Ein gemerktes Band, auf das der Auftrag schon passte (z. B. schwarz/rot
        fuer einen schwarzen Druck), bleibt stehen.
        """
        loaded = self._settings.loaded_label(address)
        if loaded and self._fits_loaded(media.get_label(identifier), loaded):
            return
        self._settings.set_loaded_label(address, identifier)
        self._settings.sync()
        self._sync_loaded_tape()

    def _sync_loaded_tape(self) -> None:
        """Gemerktes Band des gewaehlten Netzwerkdruckers im Panel zeigen."""
        config = self._media_panel.printer_config()
        loaded = (
            self._settings.loaded_label(config.address)
            if config.backend == "network" and config.address
            else None
        )
        self._media_panel.set_loaded_tape(self._band_name(loaded) if loaded else "")
        self._act_forget_tape.setEnabled(bool(loaded))

    def _forget_loaded_tape(self) -> None:
        config = self._media_panel.printer_config()
        if config.backend != "network" or not config.address:
            return
        self._settings.forget_loaded_label(config.address)
        self._settings.sync()
        self._sync_loaded_tape()

    def _on_loaded_tape_choice(
        self, config, images, label, from_sheet: bool, choice: str
    ) -> None:
        if choice == "cancel":
            if from_sheet:
                QTimer.singleShot(0, self._return_to_print_sheet)
            return
        if from_sheet:
            self._return_to_print_sheet()
        if choice == "remember":
            self._settings.set_loaded_label(config.address, label.identifier)
            self._settings.sync()
            self._sync_loaded_tape()
        self._start_print(config, images, label)

    def _start_print(self, config, images, label) -> None:
        copies = self._copies_spin.value()
        pages = len(images) * copies
        options = {
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "hq": self._hq(),
            "dpi_600": self._resolution().dpi_600,
            "red": self._media_panel.use_red(),
            "copies": copies,
            "cut_mode": self._cut_combo.currentData(),
        }
        self._pending_job = (
            datetime.now(),
            label.name,
            copies,
            config.model,
            config.address,
            label.identifier,
        )
        self._print_button.set_busy(True)
        if len(images) > 1:
            message = tr("Sende {count} Etiketten an {address}…")
            count = pages
        elif copies > 1:
            message = tr("Sende {count} Kopien an {address}…")
            count = copies
        else:
            message = tr("Sende an {address}…")
            count = 1
        self.statusBar().showMessage(
            message.format(count=count, address=config.address)
        )
        snmp_answered = (
            self._cached_snmp_answer(config.address)
            if config.backend == "network"
            else None
        )
        self._print_worker = PrintWorker(
            images,
            label,
            config,
            options,
            snmp_answered=snmp_answered,
            cancel=self._print_cancel,
        )
        self._print_worker.succeeded.connect(self._on_print_succeeded)
        self._print_worker.failed.connect(self._on_print_failed)
        self._print_worker.finished.connect(self._on_print_finished)
        self._print_worker.finished.connect(self._print_worker.deleteLater)
        self._print_worker.start()

    def _render_print_images(
        self,
        *,
        for_sheet: bool = False,
        only_indexes: Sequence[int] | None = None,
    ) -> list[Image.Image]:
        """Varianten vor dem Worker rendern (D5/D8/D10/D16).

        Pro gewaehltem Record laeuft die Serie einmal, dann ``+step``.
        Die automatische Laenge wird pro Etikett neu gerechnet, auch fuer
        jeden Serien-Schritt, sonst behielten alle die Laenge der Vorschau.
        ``copies`` wiederholt jedes Bild erst im Drucker, identisch.
        Auf einem Bogen wiederholt ``plan_sheet`` die Bilder in aufeinander
        folgenden Feldern; hier bleibt es bei einem Bild pro Datensatz.
        ``only_indexes`` rendert nur diese Positionen, in dieser Reihenfolge
        (die Vorschau braucht nur Bogen 1).
        Danach steht wieder der aktuelle Record und Serien-Index 0
        auf dem Canvas.
        """
        labels = self._planned_labels()
        if not for_sheet:
            merge_engine.job_page_count(len(labels), self._copies_spin.value())
        current = self._active.current_record if self._active is not None else 0
        wanted = (
            list(range(len(labels))) if only_indexes is None else list(only_indexes)
        )

        def _image() -> Image.Image:
            return self._for_sheet() if for_sheet else self._for_print()

        def _is_current(label: merge_engine.PlannedLabel) -> bool:
            return label.serial_index == 0 and (
                label.variant.record is None or label.variant.index == current
            )

        if len(wanted) == 1 and wanted[0] == 0 and labels and _is_current(labels[0]):
            return [_image()]
        tab = self._require_tab()
        images: list[Image.Image] = []
        self._history_suppress = True
        try:
            for index in wanted:
                label = labels[index]
                merge_engine.apply_record(
                    self._canvas.ordered_items(),
                    record=label.variant.record,
                    serial=tab.serial,
                    serial_index=label.serial_index,
                    strict=True,
                )
                self._recompute_canvas()
                images.append(_image())
            return images
        finally:
            try:
                self._apply_merge_to_canvas()
            finally:
                self._history_suppress = False

    def _for_sheet(self) -> Image.Image:
        """Etikett in der Größe der Vorlage, ohne Brother-Drehung."""
        return self._current_render(rotate=False, scale=1)

    def _poll_network_printer(self) -> None:
        config = self._media_panel.printer_config()
        if config.backend != "network" or not config.address:
            self._net_poll = None
            return
        # Erst nach ``finished``: sonst verwirft dessen Slot den naechsten,
        # noch laufenden Thread, und Qt bricht das Programm ab.
        if self._net_poll_worker is not None:
            return
        worker = NetworkStatusWorker(config.address)
        worker.polled.connect(self._on_network_polled)
        worker.finished.connect(self._on_network_poll_finished)
        worker.finished.connect(worker.deleteLater)
        self._net_poll_worker = worker
        worker.start()

    def _on_network_poll_finished(self) -> None:
        self._net_poll_worker = None

    def _on_network_polled(self, result: dict) -> None:
        address, status = result["address"], result["status"]
        self._net_poll = {"address": address, "at": monotonic(), "status": status}
        if status is None:
            # Keine Antwort (auch ein verlorenes Paket): die letzte Meldung gilt.
            return
        config = self._media_panel.printer_config()
        if config.backend != "network" or config.address != address:
            # Antwort fuer einen eben abgewaehlten Drucker.
            return
        shown = self._net_shown
        before = shown[1] if shown is not None and shown[0] == address else None
        self._net_shown = (address, status)
        if before is not None and before.texts == status.texts:
            return
        if status.texts:
            message = (
                tr("Drucker meldet: {errors}")
                if status.fault
                else tr("Hinweis vom Drucker: {texts}")
            )
            texts = ", ".join(status.texts)
            self.statusBar().showMessage(
                message.format(errors=texts, texts=texts), 10000
            )
        elif before is not None and before.fault:
            self.statusBar().showMessage(tr("Drucker wieder bereit"), 5000)

    def _fresh_poll(self, address: str) -> dict | None:
        """Letzte Abfrage dieses Druckers, ``None`` wenn sie fehlt oder veraltet ist."""
        poll = self._net_poll
        if poll is None or poll["address"] != address:
            return None
        if monotonic() - poll["at"] > SNMP_CACHE_MAX_AGE:
            return None
        return poll

    def _cached_snmp_answer(self, address: str) -> bool | None:
        """Hat der Drucker zuletzt per SNMP geantwortet? ``None``: unbekannt."""
        poll = self._fresh_poll(address)
        return None if poll is None else poll["status"] is not None

    def _on_print_finished(self) -> None:
        self._print_worker = None
        self._print_button.set_busy(False)

    def _on_print_succeeded(self, status: dict) -> None:
        outcome = status.get("outcome") or "sent"
        pending = self._pending_job
        self._record_print_job(outcome)
        if status.get("snmp_ok") and pending is not None:
            self._remember_printed_tape(pending[4], pending[5])
        self.statusBar().showMessage(
            tr("Druckauftrag gesendet (outcome={outcome}).").format(outcome=outcome),
            8000,
        )
        warnings = status.get("warnings") or ()
        if outcome == "unconfirmed":
            self.statusBar().showMessage(
                tr(
                    "Drucker hat nach dem Senden nicht geantwortet. "
                    "Etikett prüfen, bevor du neu druckst."
                ),
                10000,
            )
        elif warnings:
            self.statusBar().showMessage(
                tr("Hinweis vom Drucker: {texts}").format(texts=", ".join(warnings)),
                10000,
            )
        # USB-Fehler bringen keine Texte mit: dort genuegt die rote Verlaufszeile.
        if outcome == "error" and status.get("errors"):
            errors = "\n".join(f"• {text}" for text in status["errors"])
            self._show_print_message(
                "warning",
                tr("Drucker meldet einen Fehler"),
                tr(
                    "Der Drucker meldet:\n{errors}\n\n"
                    "Band, Klappe und Papier prüfen und danach erneut drucken."
                ).format(errors=errors),
            )
        # USB meldet "printed", das Netzwerk "sent", sobald der Auftrag weg ist.
        # Ohne Statusantwort bleibt das Sheet offen: erst pruefen, dann neu drucken.
        if outcome not in ("error", "failed", "unconfirmed"):
            self._close_print_sheet()

    def _on_print_failed(self, message: str) -> None:
        self._record_print_job("failed")
        self.statusBar().showMessage(tr("Druck fehlgeschlagen."), 8000)
        hint = access.failure_hint(message)
        if hint:
            message = f"{message}\n\n{hint}"
        self._show_print_message(
            "critical", tr("Druckfehler"), message, selectable=bool(hint)
        )

    def _record_print_job(self, outcome: str) -> None:
        if self._pending_job is None:
            return
        started, label, copies, model, address, _tape = self._pending_job
        self._pending_job = None
        job = PrintJob(started, label, copies, model, address, outcome)
        self._print_jobs.append(job)
        self._refresh_history_table()

    def _refresh_history_table(self) -> None:
        table = getattr(self, "_history_table", None)
        if table is None:
            return
        fill_history_table(table, self._print_jobs)

    def _print_sheet_open(self) -> bool:
        sheet = self._print_sheet
        return sheet is not None and sheet.isVisible()

    def _show_print_sheet(self) -> None:
        """Druckvorschau, Optionen und Verlauf im Sheet."""
        # Erst hier: jeder Grid-Klick davor wuerde „Am Ende" bei einer
        # einzelnen Zeile dauerhaft auf „Jede Kopie" stellen.
        self._sync_print_scope_ui()
        if self._sheet_output():
            self._reload_system_printers()
        sheet = self._print_sheet
        if sheet is not None and sheet.isVisible():
            sheet.raise_()
            self._refresh_history_table()
            self._refresh_now()
            return
        sheet = show_widget(
            self,
            title=tr("Drucken"),
            content=self._print_panel,
            sizing="fill",
            max_size=QSize(760, 900),
            close_on_outside=True,
            corner=self._print_button,
        )
        self._print_sheet = sheet
        # hide() am Fenster bleibt sonst stehen: ein Layout zeigt das Widget
        # nicht von selbst wieder.
        self._print_panel.show()
        sheet.closed.connect(self._on_print_sheet_closed)
        self._refresh_history_table()
        self._refresh_now()

    def _close_print_sheet(self) -> None:
        sheet = self._print_sheet
        if sheet is not None and sheet.isVisible():
            sheet.close_sheet()

    def _on_print_sheet_closed(self) -> None:
        """Sheet gibt den Inhalt zurueck, sonst loescht deleteLater die Felder."""
        panel = getattr(self, "_print_panel", None)
        button = getattr(self, "_print_button", None)
        self._print_sheet = None
        if panel is None:
            return
        try:
            if button is not None:
                button.setParent(panel)
                if not self._sheet_preparing and not self._sheet_busy():
                    button.set_busy(False)
            panel.setParent(self)
            panel.hide()
        except RuntimeError:
            return

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
        raw = self._permission_process.readAllStandardError()
        # Der Prozess liefert ein QByteArray; Tests setzen ein bytes-Objekt ein.
        stderr = (raw if isinstance(raw, bytes) else bytes(raw.data())).decode(
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
            self.statusBar().showMessage(
                tr("Zugriff einrichten: Rechte werden geprüft …")
            )
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
            tr("{reason}\n\nEinmalig im Terminal ausführen:\n\n    {command}").format(
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
        # Die Startsuche soll keine spaetere Statusmeldung ueberschreiben
        # (z. B. den Hinweis nach dem Oeffnen einer Datei).
        if not self._startup_discovery:
            self.statusBar().showMessage(tr("Netzwerk wird durchsucht …"), 4000)
        self._network_worker = NetworkSearchWorker(self._network_cancel)
        self._network_worker.succeeded.connect(self._on_network_found)
        self._network_worker.finished.connect(self._on_network_search_done)
        self._network_worker.finished.connect(self._network_worker.deleteLater)
        self._network_worker.start()

    def _discover_startup_printer(self) -> None:
        """Gespeicherten Anschluss suchen und den letzten Drucker waehlen.

        Steht er in den Treffern, wird er ausgewaehlt, sonst der erste Treffer.
        Findet die Suche nichts, bleibt eine gespeicherte Adresse stehen; eine
        fehlende Einstellung laesst das Feld leer.
        """
        self._history_suppress = True
        try:
            if self._media_panel.connection() == CONNECTION_USB:
                self._media_panel.refresh_usb_devices(select_fallback=True)
            else:
                self._startup_connection = self._media_panel.connection()
                self._startup_address = self._media_panel.address()
                self._startup_discovery = True
                self._on_network_search()
        finally:
            self._history_suppress = False
        # Die Startauswahl ist der Ausgangszustand, keine Bearbeitung.
        self._sync_media_prev()
        self._address_dirty = False
        self._undo_stack.clear()
        self._undo_stack.setClean()
        self._update_window_title()

    def _startup_search_is_stale(self) -> bool:
        """Nutzer hat Anschluss oder Adresse geaendert, waehrend gesucht wurde."""
        return (
            self._media_panel.connection() != self._startup_connection
            or self._media_panel.address() != self._startup_address
        )

    def _label_loaded(self) -> bool:
        """Ein Etikett ist offen oder schon bearbeitet.

        Ohne Datei und ohne Aenderung bleibt der Startabgleich still: ein
        leeres Fenster hat noch nichts, das die Suche bewahren muesste.
        """
        return (
            bool(self._document_path)
            or self._document_dirty
            or not self._undo_stack.isClean()
        )

    def _finish_startup_discovery(self, *, clear_address_dirty: bool) -> None:
        self._history_suppress = False
        self._startup_discovery = False
        self._sync_media_prev()
        if (
            clear_address_dirty
            and self._undo_stack.isClean()
            and not self._document_dirty
        ):
            self._address_dirty = False
            self._update_window_title()

    def _offer_label_adaption(self) -> None:
        """Fragen, bevor das gefundene Modell Band und Raender umbaut."""
        discovered = self._media_panel.network_model_id()
        current = self._media_panel.model_id()
        if not discovered or discovered == current:
            return
        ask_label_printer(
            self,
            title=tr("Drucker gefunden"),
            text=tr(
                "Das Etikett ist für {label_model} ausgelegt, gefunden wurde "
                "{printer_model}. Band und Ränder bleiben, wenn du das "
                "Etikett behältst."
            ).format(label_model=current, printer_model=discovered),
            on_choice=self._on_label_printer_choice,
        )

    def _on_label_printer_choice(self, choice: str) -> None:
        """„Anpassen" zieht das Modell nach und wird ein Undo-Schritt."""
        if choice != "adapt":
            return
        self._media_panel._apply_network_model()

    def _on_network_found(self, printers: list) -> None:
        """Gefundene Drucker in die Liste uebernehmen und kurz melden."""
        startup = self._startup_discovery
        if startup and self._startup_search_is_stale():
            self._history_suppress = True
            try:
                self._media_panel.remember_network_printers(printers)
            finally:
                # Die Zwischenwahl des Nutzers bleibt eine Aenderung.
                self._finish_startup_discovery(clear_address_dirty=False)
            return
        defer_model = startup and self._label_loaded()
        if startup:
            self._history_suppress = True
        try:
            found = self._media_panel.refresh_network_devices(
                printers,
                select_fallback=startup,
                apply_model=not defer_model,
            )
        finally:
            if startup:
                self._finish_startup_discovery(clear_address_dirty=True)
        if startup and defer_model:
            self._offer_label_adaption()
            return
        if startup:
            return
        if not found:
            self.statusBar().showMessage(tr("Keine Netzwerk-Drucker gefunden."), 8000)
            return
        if len(found) == 1:
            self.statusBar().showMessage(
                tr("Netzwerk-Drucker gefunden: {device}").format(device=found[0].host),
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

    def _show_help(self) -> None:
        """Hilfe: kurzer Text und die Tasten, die der Code bindet."""
        app_help.show_help(self)

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
        canvas.copies_spawned.connect(self._on_copies_spawned)
        canvas.image_dropped.connect(self._on_image_dropped)
        canvas.text_dropped.connect(self._on_text_dropped)
        canvas.database_field_dropped.connect(self._on_database_field_dropped)
        canvas.print_preview_exit_requested.connect(self._exit_print_preview)
        canvas.zoom_changed.connect(self._on_zoom_changed)
        canvas.hint_changed.connect(self._on_canvas_hint)
        canvas.scene().selectionChanged.connect(self._on_selection_changed)
        canvas.scene().changed.connect(self._on_scene_changed)
        tab.undo.cleanChanged.connect(self._on_undo_clean_changed)

    def _unbind_tab(self, tab: LabelTab) -> None:
        # Der Hinweis gehoert zum Reiter. Sonst bleibt er stehen, weil nur
        # das Signal getrennt wird und der Canvas ihn nicht neu setzt.
        tab.canvas._set_hint("")
        self._on_canvas_hint("")
        canvas = tab.canvas
        pairs = (
            (canvas.text_requested, self._on_text_requested),
            (canvas.item_double_clicked, self._on_item_double_clicked),
            (canvas.context_menu_requested, self._show_context_menu),
            (canvas.items_changed, self._on_items_changed),
            (canvas.gesture_begun, self._capture_history),
            (canvas.copies_spawned, self._on_copies_spawned),
            (canvas.image_dropped, self._on_image_dropped),
            (canvas.text_dropped, self._on_text_dropped),
            (canvas.database_field_dropped, self._on_database_field_dropped),
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
        """Band und Ziel des sichtbaren Etiketts merken, bevor ein anderes nach vorn kommt."""
        tab = self._active
        if tab is None:
            return
        tab.media = deepcopy(dict(self._media_panel.media_state()))
        self._stash_sheet_target()

    def _create_tab(self, *, switch: bool = True) -> LabelTab:
        self._stash_sheet_target()
        source = self._active
        tab = LabelTab(self)
        if source is not None:
            tab.sheet_output = source.sheet_output
            tab.sheet_part = source.sheet_part
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
            self._seal_pending_edits()
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
        self._apply_tab_sheet_target(tab)
        self._sync_database_panel()
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
            tab.canvas.set_guides(list(spec.get("guides") or []))
            self._wire_canvas_text(tab.canvas)
            if spec.get("preview"):
                tab.canvas.set_print_preview(True)
            self._restore_tab_database(tab, spec)
            tab.sheet_output = bool(spec.get("sheet_output", False))
            tab.sheet_part = str(spec.get("sheet_part") or stationery.DEFAULT_PART)
            tab.selected_records = [
                int(row) for row in spec.get("selected_records") or []
            ]
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
        self._sync_database_panel()
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
        """Letzter Reiter beendet die App, sonst fällt nur dieser Reiter weg."""
        # Anderen Reiter schließen: Tippen im aktiven lassen.
        if tab is self._active or len(self._ordered_tabs()) <= 1:
            self._seal_pending_edits()
        if len(self._ordered_tabs()) <= 1:
            self.close()
            return
        if not tab.is_dirty():
            self._remove_tab(tab)
            return
        self._show_tab(tab)

        def _saved() -> None:
            self._remove_tab(tab)

        self._ask_about_tab(
            tab, on_save=_saved, on_discard=_saved, on_cancel=lambda: None
        )

    def _ask_about_tab(self, tab: LabelTab, *, on_save, on_discard, on_cancel) -> Sheet:
        name = Path(tab.path).name if tab.path else tr("Unbenannt")

        def _chosen(choice: str) -> None:
            if choice == "save":
                self._show_tab(tab)
                self._on_file_save(on_saved=on_save, on_cancel=on_cancel)
            elif choice == "discard":
                on_discard()
            else:
                on_cancel()

        return ask_save(
            self,
            title=tr("Etikett schließen"),
            text=tr("Änderungen an „{name}“ speichern?").format(name=name),
            on_choice=_chosen,
        )

    def _remove_tab(self, tab: LabelTab) -> None:
        ordered = self._ordered_tabs()
        if len(ordered) <= 1:
            # Weg damit ist schon entschieden (sauber, gespeichert, verworfen).
            self._close_prompt = False
            self._close_sheet = None
            self._accept_close = True
            self.close()
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
        """Reiter leeren, ohne ihn zu entfernen und ohne das Fenster zu schließen."""
        self._show_tab(tab)
        self._adjusting = True
        self._history_suppress = True
        try:
            if tab.canvas.print_preview:
                tab.canvas.set_print_preview(False)
                tab.canvas.set_print_image(None)
            tab.canvas.load_items([])
            tab.canvas.set_guides([])
            tab.path = ""
            tab.document_dirty = False
            tab.history_before = None
            tab.preview_view = None
            tab.clear_database()
            tab.undo.clear()
            tab.undo.setClean()
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._wire_loaded_text_items()
        self._sync_margin_base()
        self._sync_media_prev()
        self._stash_active()
        self._sync_database_panel()
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
            self._close_sheet = None
            self._accept_close = True
            self.close()
            return
        tab = pending[0]

        def _cancel() -> None:
            self._close_prompt = False
            self._close_sheet = None

        def _continue() -> None:
            self._prompt_close(pending[1:])

        self._show_tab(tab)
        self._close_sheet = self._ask_about_tab(
            tab, on_save=_continue, on_discard=_continue, on_cancel=_cancel
        )

    # ------------------------------------------------------------- Dateien --
    def _document_data(self, *, relative_to: str | None = None) -> dict:
        """Aktuelles Design als Dokumentdaten (Band/Design + Objekte + Merge)."""
        tab = self._require_tab()
        data_source = self._data_source_for_save(tab, relative_to=relative_to)
        return document.build(
            self._media_panel.media_state(),
            self._canvas.items_serialized(),
            data_source=data_source,
            serial=tab.serial,
            guides=self._canvas.guides(),
        )

    def _data_source_for_save(
        self, tab: LabelTab, *, relative_to: str | None = None
    ) -> dict[str, Any] | None:
        """``data_source`` fuer Speichern: Pfad relativ zur ``.qlx`` (D3).

        ``relative_to`` ist das Ziel der ``.qlx``, auch wenn der Reiter noch
        keinen Pfad hat (erster Speichervorgang nach einem LBX-Import).
        """
        base = relative_to if relative_to is not None else (tab.path or None)
        if tab.csv_table is not None:
            csv_path = tab.csv_table.path
            if csv_path is None and tab.data_source:
                raw = tab.data_source.get("path")
                csv_path = Path(raw) if raw else None
            if csv_path is None:
                return None
            try:
                stored = csv_source.data_source_dict(
                    tab.csv_table,
                    path=csv_path,
                    current_record=tab.current_record,
                    relative_to=base,
                )
            except csv_source.CsvSourceError:
                pass
            else:
                if tab.data_source and "containsFieldName" in tab.data_source:
                    stored["containsFieldName"] = tab.data_source.get(
                        "containsFieldName"
                    )
                return stored
        if tab.data_source is None:
            return None
        stored = dict(tab.data_source)
        stored["current_record"] = int(tab.current_record)
        return stored

    def _queue_database_status(self, message: str) -> None:
        """CSV-/Hash-Hinweis merken und anzeigen (Open darf spaeter erneut setzen)."""
        self._pending_database_status = message
        self.statusBar().showMessage(message, 8000)

    def _flush_database_status(self) -> None:
        """Ausstehenden Database-Status nachrangig nach „Etikett geöffnet“ setzen."""
        message = self._pending_database_status
        self._pending_database_status = None
        if message:
            self.statusBar().showMessage(message, 8000)

    def _load_document_database(
        self,
        data: Mapping[str, Any],
        *,
        document_path: str | None = None,
    ) -> None:
        """``data_source``/``serial`` aus dem Dokument in den aktiven Reiter laden."""
        tab = self._require_tab()
        self._pending_database_status = None
        tab.selected_records = []
        raw_serial = data.get("serial")
        tab.serial = document.merge_serial(
            raw_serial if isinstance(raw_serial, Mapping) else None
        )
        raw_source = data.get("data_source")
        if not isinstance(raw_source, Mapping) or raw_source.get("type") != "csv":
            tab.csv_table = None
            tab.data_source = None
            tab.current_record = 0
            tab.database_notice = None
            return
        tab.data_source = dict(raw_source)
        stored_path = str(raw_source.get("path") or "")
        current = int(raw_source.get("current_record") or 0)
        tab.current_record = current
        if not stored_path:
            tab.csv_table = None
            tab.database_notice = tr("CSV-Pfad fehlt.")
            self._queue_database_status(tab.database_notice)
            return
        base = document_path if document_path is not None else (tab.path or None)
        csv_path = merge_engine.resolve_csv_path(stored_path, document_path=base)
        try:
            table = csv_source.load(
                csv_path,
                delimiter=raw_source.get("delimiter"),
            )
        except csv_source.CsvSourceError as exc:
            tab.csv_table = None
            tab.database_notice = tr("CSV nicht geladen: {error}").format(error=exc)
            self._queue_database_status(tab.database_notice)
            return
        tab.database_notice = None
        stored_sha = str(raw_source.get("content_sha256") or "")
        if stored_sha and stored_sha != table.content_sha256:
            tab.database_notice = tr("CSV-Inhalt hat sich geändert (Hash weicht ab).")
            self._queue_database_status(tab.database_notice)
        tab.csv_table = table
        tab.current_record = merge_engine.clamp_record_index(
            current, len(table.records)
        )
        # SHA/Meta aus der geladenen Datei aktualisieren, Pfad beibehalten.
        tab.data_source = csv_source.data_source_dict(
            table,
            path=stored_path,
            current_record=tab.current_record,
        )
        if "containsFieldName" in raw_source:
            tab.data_source["containsFieldName"] = raw_source.get("containsFieldName")

    def _restore_tab_database(self, tab: LabelTab, spec: Mapping[str, Any]) -> None:
        """Merge-Zustand eines Reiters aus ``_state``/``apply_state`` wiederherstellen."""
        raw_serial = spec.get("serial")
        tab.serial = document.merge_serial(
            raw_serial if isinstance(raw_serial, Mapping) else None
        )
        raw_source = spec.get("data_source")
        tab.current_record = int(spec.get("current_record") or 0)
        if not isinstance(raw_source, Mapping):
            tab.csv_table = None
            tab.data_source = None
            tab.database_notice = None
            return
        previous = self._active
        self._active = tab
        try:
            self._load_document_database(
                {"data_source": raw_source, "serial": tab.serial},
                document_path=tab.path or None,
            )
        finally:
            self._active = previous

    def _database_is_linked(self) -> bool:
        """True, wenn der aktive Reiter eine CSV geladen oder einen Pfad hat."""
        tab = self._active
        if tab is None:
            return False
        if tab.csv_table is not None:
            return True
        source = tab.data_source
        if not isinstance(source, Mapping):
            return False
        return bool(str(source.get("path") or "").strip())

    def _on_database_toolbar_toggled(self, checked: bool) -> None:
        """Toolbar-Icon zeigt das Grid nur bei bestehender Verbindung."""
        if checked and self._database_is_linked():
            self._database_panel.set_expanded(True)
            self._database_panel.show()
            return
        self._database_panel.hide()

    def _apply_database_visibility(self) -> None:
        """Ohne CSV weder Icon noch Panel; mit CSV nur das Icon, bis es geklickt wird."""
        linked = self._database_is_linked()
        self._act_database.setVisible(linked)
        if not linked:
            self._act_database.blockSignals(True)
            self._act_database.setChecked(False)
            self._act_database.blockSignals(False)
            self._database_panel.hide()
            return
        self._database_panel.setVisible(self._act_database.isChecked())

    def _sync_database_panel(self) -> None:
        """Unteres Grid an den aktiven Reiter anbinden."""
        tab = self._active
        if tab is None:
            self._database_panel.clear()
            self._apply_database_visibility()
            self._sync_print_scope_ui()
            return
        notice = tab.database_notice
        if tab.csv_table is None:
            path = ""
            if tab.data_source:
                path = str(tab.data_source.get("path") or "")
            if path:
                self._database_panel.show_unloaded(Path(path).name, notice)
            else:
                self._database_panel.clear(notice=notice)
            self._apply_database_visibility()
            self._sync_print_scope_ui()
            self._on_selection_changed()
            return
        name = None
        if tab.data_source and tab.data_source.get("path"):
            name = Path(str(tab.data_source["path"])).name
        self._database_panel.set_table(
            tab.csv_table,
            current_record=tab.current_record,
            display_name=name,
            notice=notice,
        )
        # Die Vorschau muss in der Auswahl liegen, sonst druckt "Ausgewählte"
        # andere Zeilen als der Canvas zeigt.
        if tab.current_record in tab.selected_records:
            self._database_panel.set_selected_records(tab.selected_records)
        else:
            tab.selected_records = self._database_panel.selected_records()
        self._apply_database_visibility()
        self._sync_print_scope_ui()
        self._on_selection_changed()

    def _on_database_record_selected(self, index: int) -> None:
        """Tabellenzeile → ``current_record`` + Live-Merge (D15, ohne Undo)."""
        self.set_current_record(index, mark_dirty=True)

    def set_current_record(self, index: int, *, mark_dirty: bool = False) -> None:
        """Record wechseln und gebundene Canvas-Objekte aktualisieren (D10/D15)."""
        tab = self._require_tab()
        count = len(tab.csv_table.records) if tab.csv_table is not None else 0
        index = merge_engine.clamp_record_index(index, count)
        changed = tab.current_record != index
        tab.current_record = index
        if tab.data_source is not None:
            tab.data_source = dict(tab.data_source)
            tab.data_source["current_record"] = index
        self._apply_merge_to_canvas()
        self._database_panel.set_current_record(index)
        tab.selected_records = self._database_panel.selected_records()
        if mark_dirty and changed:
            self._document_dirty = True
            self._update_window_title()

    def _apply_merge_to_canvas(self, *, refresh_inspector: bool = True) -> None:
        """Snapshots aus aktuellem Record (+ Serie Index 0) auf den Canvas."""
        tab = self._require_tab()
        record: Mapping[str, str] | None = None
        if tab.csv_table is not None and tab.csv_table.records:
            index = merge_engine.clamp_record_index(
                tab.current_record, len(tab.csv_table.records)
            )
            record = tab.csv_table.record(index)
        self._history_suppress = True
        self._adjusting = True
        try:
            merge_engine.apply_record(
                self._canvas.ordered_items(),
                record=record,
                serial=tab.serial,
                serial_index=0,
            )
        finally:
            self._adjusting = False
            self._history_suppress = False
        self._recompute_canvas()
        self._schedule_refresh()
        if refresh_inspector:
            self._on_selection_changed()

    def bind_csv_table(
        self,
        table: CsvTable,
        *,
        current_record: int = 0,
        relative_path: str | None = None,
    ) -> None:
        """CSV an den aktiven Reiter binden und Live-Merge anwenden (Tests/API)."""
        tab = self._require_tab()
        tab.csv_table = table
        tab.selected_records = []
        path = relative_path
        if path is None and table.path is not None:
            path = str(table.path)
        if path is None:
            raise csv_source.CsvSourceError(tr("CSV-Pfad fehlt."))
        tab.current_record = merge_engine.clamp_record_index(
            current_record, len(table.records)
        )
        tab.data_source = csv_source.data_source_dict(
            table,
            path=path,
            current_record=tab.current_record,
            relative_to=tab.path or None,
        )
        self._apply_merge_to_canvas()
        self._sync_database_panel()
        self._document_dirty = True
        self._update_window_title()

    def connect_csv_path(self, path: str) -> bool:
        """CSV verbinden oder ersetzen und sofort mergen (D13)."""
        tab = self._require_tab()
        try:
            table = csv_source.load(path)
        except csv_source.CsvSourceError as exc:
            tab.database_notice = str(exc)
            self._sync_database_panel()
            self.statusBar().showMessage(tab.database_notice, 8000)
            return False
        tab.database_notice = None
        self.bind_csv_table(table)
        return True

    def disconnect_csv(self) -> None:
        """Datenbankverbindung loesen. Snapshots und Serie bleiben (D11)."""
        tab = self._require_tab()
        if tab.csv_table is None and not tab.data_source:
            return
        tab.csv_table = None
        tab.data_source = None
        tab.current_record = 0
        tab.selected_records = []
        tab.database_notice = None
        self._sync_database_panel()
        self._on_selection_changed()
        self._document_dirty = True
        self._update_window_title()

    def _choose_csv(self) -> None:
        """Datei-Dialog fuer Verbinden / Andere."""
        tab = self._active
        start = ""
        if tab is not None and tab.csv_table is not None and tab.csv_table.path:
            start = str(tab.csv_table.path.parent)
        elif tab is not None and tab.path:
            start = str(Path(tab.path).parent)
        elif self._settings.document_dir:
            start = self._settings.document_dir
        choose_file(
            self,
            caption=tr("CSV verbinden"),
            name_filter=tr("CSV-Dateien (*.csv);;Alle Dateien (*)"),
            on_selected=self._on_csv_file_chosen,
            start_dir=start,
        )

    def _on_csv_file_chosen(self, path: str | None) -> None:
        if path:
            self.connect_csv_path(path)

    def bind_database_field(self, item, field: str) -> None:
        """Spalte an Text/Barcode/QR binden. Ersetzt eine Serie am Objekt (D4)."""
        if getattr(item, "kind", None) not in ("text", "qr", "barcode"):
            return
        if not hasattr(item, "set_binding"):
            return
        self._seal_open_inspector_edit()
        self._capture_history()
        item.set_binding({"source": "database", "field": field})
        self._apply_merge_to_canvas(refresh_inspector=False)
        self._commit_history(tr("Datenbankfeld"))
        self._canvas.scene().clearSelection()
        item.setSelected(True)
        self._on_selection_changed()

    def _on_database_field_dropped(self, field: str, scene_pos: QPointF) -> None:
        """Drop auf Text/Barcode/QR bindet; sonst neues Textfeld mit Binding (D14)."""
        item = self._canvas.serializable_item_at_scene(scene_pos)
        if item is not None and getattr(item, "kind", None) in (
            "text",
            "qr",
            "barcode",
        ):
            self.bind_database_field(item, field)
            return
        text = TextItem(
            self._database_snapshot(field),
            font_pixel_size=self._default_font_size(),
        )
        text.set_binding({"source": "database", "field": field})
        self._add_item(text, scene_pos)

    def _database_snapshot(self, field: str) -> str:
        """Aktueller Zellenwert, oder leer wenn keine CSV geladen ist."""
        tab = self._require_tab()
        table = tab.csv_table
        if table is None or not table.records:
            return ""
        index = merge_engine.clamp_record_index(tab.current_record, len(table.records))
        return str(table.record(index).get(field, ""))

    def _apply_document(self, data: dict, *, document_path: str | None = None) -> None:
        """Dokumentdaten uebernehmen - Adresse und Anschluss bleiben stehen.

        ``document_path`` erlaubt die relative CSV-Aufloesung schon beim Laden,
        bevor der Reiter-Pfad gesetzt ist.
        """
        self._adjusting = True
        self._history_suppress = True
        try:
            self._media_panel.apply_media_state(data.get("media") or {})
            self._canvas.load_items(list(data.get("items") or []))
            self._canvas.set_guides(list(data.get("guides") or []))
            self._sync_margin_base()
            self._load_document_database(data, document_path=document_path)
            self._reconcile_serial_enabled()
            self._normalize_serial_limits()
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
        self._apply_merge_to_canvas()
        self._sync_database_panel()
        # Auch bei fehlender CSV: das Banner mit „Andere…" steht im Grid.
        if self._database_is_linked():
            self._act_database.setChecked(True)
            self._database_panel.set_expanded(True)
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
                "Alle Etiketten (*{suffix} *{lbx});;"
                "QLInux-Etiketten (*{suffix});;"
                "Brother P-touch (*{lbx})"
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
        # Auch beim LBX-Import: relative CSV neben der Datei aufloesen.
        # Der Pfad wird danach nicht als Speicherziel gemerkt.
        self._apply_document(data, document_path=path)
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
        # CSV-Warnung/Hash-Drift nachrangig, sonst verschwindet sie sofort.
        self._flush_database_status()

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
            document.save(path, self._document_data(relative_to=path))
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
    def _disconnect_worker(
        self,
        worker: QThread | None,
        slots: list[tuple],
        wait_ms: int = NETWORK_CANCEL_WAIT_MS,
    ) -> None:
        """Ergebnis-Signale loesen, warten, und einen haengenden Thread behalten.

        Ohne Qt-Parent ueberlebt der Thread das Fenster. Die Slots duerfen das
        geschlossene Fenster nicht mehr ansprechen; ``deleteLater`` bleibt.
        ``wait_ms=0`` behaelt ihn sofort (auf ihn wartet dann nur das
        Programmende, siehe :func:`_wait_for_orphans`).
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
        if wait_ms:
            worker.wait(wait_ms)
        if worker.isRunning():
            _orphan_workers.append(worker)
            worker.finished.connect(lambda worker=worker: _forget_orphan(worker))

    def _close_sheet_open(self) -> bool:
        """True, solange die Speicher-Rückfrage dieses Schließens sichtbar ist."""
        sheet = self._close_sheet
        if sheet is None:
            return False
        try:
            return sheet.isVisible()
        except RuntimeError:
            return False

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._accept_close and self.isVisible():
            self._seal_pending_edits()
            dirty = [tab for tab in self._ordered_tabs() if tab.is_dirty()]
            if dirty:
                event.ignore()
                # Hängendes Flag ohne diese Rückfrage würde „Schließen“
                # schlucken. Sichtbare Rückfrage: nicht noch einmal fragen.
                if self._close_prompt and self._close_sheet_open():
                    return
                self._close_prompt = True
                self._prompt_close(dirty)
                return
        self._finish_close(event)

    def _finish_close(self, event) -> None:
        # Laufende Suche abbrechen, damit kein Thread das geschlossene
        # Fenster anspricht.
        self._network_cancel.set()
        self._print_cancel.set()
        self._net_poll_timer.stop()
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
        # Der finished-Slot, der die Referenz leert, ist jetzt getrennt.
        # Sonst zeigt das Fenster nach deleteLater auf einen toten Thread.
        self._network_worker = None
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
        self._detect_worker = None
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
        self._print_worker = None
        sheet_job = self._sheet_worker
        self._disconnect_worker(
            sheet_job,
            [
                (sheet_job.succeeded, self._on_sheet_output_succeeded),
                (sheet_job.failed, self._on_sheet_output_failed),
                (sheet_job.finished, self._on_sheet_output_finished),
            ]
            if sheet_job is not None
            else [],
        )
        self._sheet_worker = None
        self._sheet_preparing = False
        polling = self._net_poll_worker
        # Die kurze Abfrage nicht abwarten - das tut erst das Programmende.
        self._disconnect_worker(
            polling,
            [
                (polling.polled, self._on_network_polled),
                (polling.finished, self._on_network_poll_finished),
            ]
            if polling is not None
            else [],
            wait_ms=0,
        )
        self._net_poll_worker = None
        self._settings.save_geometry(self.saveGeometry())
        self._settings.connection = self._media_panel.connection()
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
        self._settings.print_scope = self._print_scope()
        self._settings.record_from = self._range_request_from
        self._settings.record_to = self._range_request_to
        self._settings.sheet_output = self._sheet_output()
        self._settings.sheet_part = str(
            self._sheet_part_combo.currentData() or stationery.DEFAULT_PART
        )
        self._settings.sheet_start = self._sheet_start.value()
        self._settings.sheet_offset_x = self._sheet_offset_x.value()
        self._settings.sheet_offset_y = self._sheet_offset_y.value()
        self._settings.sheet_printer = str(
            self._sheet_printer_combo.currentData() or ""
        )
        self._settings.sync()
        super().closeEvent(event)


def _address_matches_connection(address: str, connection: str) -> bool:
    """Gehoert ``address`` zum Anschluss ``network`` oder ``usb``?"""
    kind = "network" if backend_for_address(address) == "network" else CONNECTION_USB
    return kind == connection


def _system_language() -> str:
    """Erststart: die Systemsprache, wenn wir sie anbieten - sonst Deutsch."""
    code = QLocale.system().name().split("_")[0].lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def _canonical_path(path: str) -> str:
    """Wie ``_tab_with_path``: Symlinks aufloesen, bei OSError den Pfad lassen."""
    try:
        return str(Path(path).resolve())
    except OSError:
        return path


def _label_paths(paths: Iterable[str]) -> list[str]:
    """Nur Etikettendateien (``.qlx``, ``.lbx``) - alles andere fällt weg."""
    suffixes = (document.DOCUMENT_SUFFIX, lbx.LBX_SUFFIX)
    return [
        _canonical_path(path)
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
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(argv)
    app.setApplicationName("QLInux")
    files = _document_args(argv)
    # Läuft schon eine Instanz, öffnet sie die Dateien als Reiter bzw. holt das
    # Fenster nach vorn - auch ohne Datei. Dieser Start endet dann.
    if instance.forward(files):
        return 0
    settings = AppSettings()
    # Vorgabe ist das Farbschema der Arbeitsumgebung. Hell/dunkel nur, wenn
    # der Nutzer das im Menue so gespeichert hat.
    apply_theme(app, scheme_for(settings.appearance))
    set_language(settings.language or _system_language())
    # Zahlen (Dezimaltrennzeichen) folgen der Sprache - auch in Spinboxen.
    QLocale.setDefault(QLocale(language()))
    window = MainWindow(settings)
    _remember_window(window)
    # Der Server bleibt in ``server`` am Leben, solange die Schleife läuft.
    # Kein removeServer bei belegtem Namen: nur die Owner-Instanz hält den Socket.
    server = instance.listen(partial(_open_from_outside, window))
    # TOCTOU: zwei Starts mit Dateien — Verlierer reicht nach listen() nach.
    if server is None and instance.forward(files, attempts=5, retry_ms=50):
        return 0
    window.show()
    for path in files:
        window.open_path(path)
    code = app.exec()
    _wait_for_orphans()
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
