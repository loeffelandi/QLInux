"""Hauptfenster der QLInux-Anwendung (PySide6).

Aufbau:

* links: :class:`~ql_editor.media_panel.MediaPanel` (Band, Laenge, Margins)
* mitte: :class:`~ql_editor.canvas.LabelCanvas` (feste Pixelgroesse, Lineale)
* rechts: Vorschau (monochrom) + Druckoptionen
* Toolbar: Items einfuegen, Reihenfolge, Loeschen, Zoom, Drucken

Die GUI haelt keine eigene Wahrheit ueber Bandmasse: alles kommt aus
:mod:`ql_editor.media`. Gerendert wird ueber :mod:`ql_editor.renderer`,
gedruckt ueber :mod:`ql_editor.printer` (in einem Worker-Thread).
"""

from __future__ import annotations

import sys

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import media
from .canvas import LabelCanvas
from .icons import icon
from .inspector import InspectorPanel
from .items import BarcodeItem, ImageItem, LineItem, QRItem, RectItem, TextItem
from .media_panel import MediaPanel
from .preview import PreviewOptions, binarize, to_qimage
from .printer import (
    PrinterError,
    detect_label,
    print_image,
)
from .renderer import render_scene_to_image
from .settings import AppSettings
from .widgets import SmoothScrollArea, install_wheel_guard_recursive

BARCODE_SYMBOLOGIES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"]


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
            self.failed.emit(f"Unerwarteter Fehler: {exc}")
        else:
            self.succeeded.emit(status)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None):
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle("QLInux - P-touch Editor")
        self.setWindowIcon(icon("label"))
        self._adjusting = False
        self._print_worker: PrintWorker | None = None

        self._canvas = LabelCanvas(self)
        self._canvas.setMinimumSize(240, 180)
        self.setCentralWidget(self._canvas)

        self._media_panel = MediaPanel(self)
        self._media_panel.setMinimumWidth(220)
        self._inspector = InspectorPanel(self)
        self._inspector.setMinimumWidth(240)

        # Gesamtfenster darf klein werden, ohne dass etwas unbedienbar wird.
        self.setMinimumSize(640, 460)

        self._build_docks()
        self._build_actions()
        self._build_toolbar()
        self._build_menu()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_now)

        self._media_panel.changed.connect(self._on_media_changed)
        self._media_panel.detect_requested.connect(self._on_detect_label)
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

        # Rad-Ereignisse duerfen keine Werte in Feldern aendern (auch nicht in
        # den dynamisch erzeugten Inspector-Feldern - die sichern sich selbst).
        install_wheel_guard_recursive(self)

        self._zoom_label = QLabel("Zoom 100 %")
        self._zoom_label.setToolTip("Mausrad über dem Canvas zoomt bzw. scrollt")
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

    def _build_docks(self) -> None:
        left = QDockWidget("Band & Drucker", self)
        left.setWidget(self._scroll_wrap(self._media_panel))
        left.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        left.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)
        self._left_dock = left

        right = QDockWidget("Eigenschaften & Druck", self)
        right.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        right.setMinimumWidth(260)
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._scroll_wrap(self._inspector))
        splitter.addWidget(self._scroll_wrap(self._build_print_panel()))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([380, 220])
        right.setWidget(splitter)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)
        self._right_dock = right

        # Grosszuegige Standardbreiten der Seitenpanels.
        self.resizeDocks([left, right], [300, 380], Qt.Orientation.Horizontal)

    def _build_print_panel(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Druckoptionen")
        title.setStyleSheet("color:#555; font-weight:600;")
        layout.addWidget(title)

        hint = QLabel(
            "Druckvorschau über das Auge-Symbol in der Toolbar "
            "(zeigt die echte 1-bit-Ausgabe)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777;")
        layout.addWidget(hint)

        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 100)
        self._threshold_spin.setValue(70)
        self._threshold_spin.setToolTip("Höher = mehr Pixel werden zu Tinte")
        self._dither_check = QCheckBox("Dithering (Floyd-Steinberg)")
        self._cut_check = QCheckBox("Nach dem Druck schneiden")
        self._cut_check.setChecked(True)
        self._print_button = QPushButton(icon("print"), "Drucken")

        layout.addWidget(QLabel("Threshold"))
        layout.addWidget(self._threshold_spin)
        layout.addWidget(self._dither_check)
        layout.addWidget(self._cut_check)
        layout.addStretch(1)
        layout.addWidget(self._print_button)

        self._threshold_spin.valueChanged.connect(self._schedule_refresh)
        self._dither_check.toggled.connect(self._schedule_refresh)
        self._print_button.clicked.connect(self._on_print)
        return widget

    def _build_actions(self) -> None:
        self._act_add_text = QAction(icon("text"), "Text", self)
        self._act_add_text.setToolTip("Text einfügen (Doppelklick auf den Canvas)")
        self._act_add_text.triggered.connect(self._add_text)

        self._act_add_image = QAction(icon("image"), "Bild…", self)
        self._act_add_image.setToolTip("Bild einfügen")
        self._act_add_image.triggered.connect(self._add_image)

        self._act_add_barcode = QAction(icon("barcode"), "Barcode…", self)
        self._act_add_barcode.setToolTip("Barcode einfügen")
        self._act_add_barcode.triggered.connect(self._add_barcode)

        self._act_add_qr = QAction(icon("qr"), "QR-Code…", self)
        self._act_add_qr.setToolTip("QR-Code einfügen")
        self._act_add_qr.triggered.connect(self._add_qr)

        self._act_add_line = QAction(icon("line"), "Linie", self)
        self._act_add_line.setToolTip("Linie einfügen")
        self._act_add_line.triggered.connect(self._add_line)

        self._act_add_rect = QAction(icon("rect"), "Rahmen", self)
        self._act_add_rect.setToolTip("Rahmen einfügen")
        self._act_add_rect.triggered.connect(self._add_rect)

        self._act_front = QAction(icon("front"), "In den Vordergrund", self)
        self._act_front.setToolTip("In den Vordergrund")
        self._act_front.triggered.connect(lambda: self._bump_z(+1))

        self._act_back = QAction(icon("back"), "In den Hintergrund", self)
        self._act_back.setToolTip("In den Hintergrund")
        self._act_back.triggered.connect(lambda: self._bump_z(-1))

        self._act_delete = QAction(icon("delete"), "Löschen", self)
        self._act_delete.setToolTip("Löschen (Entf)")
        self._act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self._act_delete.triggered.connect(self._canvas.delete_selected)

        self._act_zoom_fit = QAction(icon("zoom_fit"), "Einpassen", self)
        self._act_zoom_fit.setToolTip("Zoom: Einpassen (Ctrl+0)")
        self._act_zoom_fit.setShortcut("Ctrl+0")
        self._act_zoom_fit.triggered.connect(self._canvas.zoom_fit)

        self._act_zoom_in = QAction(icon("zoom_in"), "Vergrößern", self)
        self._act_zoom_in.setToolTip("Vergrößern (Strg ++)")
        self._act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self._act_zoom_in.triggered.connect(self._canvas.zoom_in)

        self._act_zoom_out = QAction(icon("zoom_out"), "Verkleinern", self)
        self._act_zoom_out.setToolTip("Verkleinern (Strg +-)")
        self._act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self._act_zoom_out.triggered.connect(self._canvas.zoom_out)

        self._act_print = QAction(icon("print"), "Drucken", self)
        self._act_print.setToolTip("Drucken (Ctrl+P)")
        self._act_print.setShortcut("Ctrl+P")
        self._act_print.triggered.connect(self._on_print)

        self._act_print_preview = QAction(icon("preview"), "Druckvorschau", self)
        self._act_print_preview.setCheckable(True)
        self._act_print_preview.setToolTip("Druckvorschau: echte 1-bit-Ausgabe (Ctrl+Shift+P)")
        self._act_print_preview.setShortcut("Ctrl+Shift+P")
        self._act_print_preview.toggled.connect(self._on_toggle_print_preview)

        self._act_quit = QAction(icon("quit"), "Beenden", self)
        self._act_quit.setToolTip("Beenden (Strg+Q)")
        self._act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_quit.triggered.connect(self.close)

        self._act_about = QAction(icon("about"), "Über QLInux", self)
        self._act_about.setToolTip("Über QLInux")
        self._act_about.triggered.connect(self._show_about)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Werkzeuge")
        bar.setObjectName("main_toolbar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        bar.setIconSize(QSize(22, 22))
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
        bar.addSeparator()
        bar.addAction(self._act_print_preview)
        bar.addAction(self._act_print)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu(icon("file"), "&Datei")
        file_menu.addAction(self._act_print)
        file_menu.addSeparator()
        file_menu.addAction(self._act_quit)
        edit_menu = self.menuBar().addMenu(icon("edit"), "&Bearbeiten")
        edit_menu.addAction(self._act_delete)
        edit_menu.addAction(self._act_front)
        edit_menu.addAction(self._act_back)
        view_menu = self.menuBar().addMenu(icon("view"), "&Ansicht")
        view_menu.addAction(self._act_print_preview)
        view_menu.addSeparator()
        view_menu.addAction(self._act_zoom_out)
        view_menu.addAction(self._act_zoom_fit)
        view_menu.addAction(self._act_zoom_in)
        help_menu = self.menuBar().addMenu(icon("help"), "&Hilfe")
        help_menu.addAction(self._act_about)

    # ------------------------------------------------------------- Settings --
    def _apply_saved_settings(self) -> None:
        geometry = self._settings.restore_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1320, 860)
        model = self._settings.model
        index = self._media_panel._model_combo.findData(model)
        if index >= 0:
            self._media_panel._model_combo.setCurrentIndex(index)
        self._media_panel._address_edit.setText(self._settings.address)
        last_label = self._settings.last_label
        if last_label:
            self._media_panel.select_label(last_label)

    # ---------------------------------------------------------- Media-Sync --
    def _on_media_changed(self) -> None:
        if self._adjusting:
            return
        self._recompute_canvas()
        self._settings.last_label = self._media_panel.label_id()
        self._settings.address = self._media_panel.address()
        self._settings.model = self._media_panel.model_id()
        self._on_selection_changed()
        self._schedule_refresh()

    def _recompute_canvas(self) -> None:
        self._adjusting = True
        try:
            label = self._media_panel.label
            model = self._media_panel.model
            if self._media_panel.auto_length():
                content = self._content_height_dots()
                _, height = media.canvas_size_dots(
                    label, model, auto_length=True, content_length_dots=content
                )
            else:
                _, height = self._media_panel.canvas_size()
            self._canvas.set_label(label, height)
        finally:
            self._adjusting = False

    def _content_height_dots(self) -> int:
        rect = self._canvas.scene().itemsBoundingRect()
        if rect.isNull():
            return 0
        margins = self._media_panel.margins()
        return int(rect.bottom()) + media.mm_to_dots(margins.bottom)

    # ----------------------------------------------------------- Rendering --
    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def _current_render(self) -> Image.Image:
        rect = self._canvas.sceneRect()
        return render_scene_to_image(self._canvas.scene(), int(rect.width()), int(rect.height()))

    def _refresh_now(self) -> None:
        """Aktualisiere die Canvas-Druckvorschau (nur im Vorschau-Modus)."""
        if not self._canvas.print_preview:
            return
        try:
            image = self._current_render()
        except Exception as exc:  # pragma: no cover - defensiv
            self.statusBar().showMessage(f"Renderfehler: {exc}")
            return
        self._canvas.set_print_image(to_qimage(binarize(image, self._preview_options())))

    def _preview_options(self) -> PreviewOptions:
        return PreviewOptions(
            threshold=self._threshold_spin.value(),
            dither=self._dither_check.isChecked(),
        )

    def _on_toggle_print_preview(self, enabled: bool) -> None:
        self._canvas.set_print_preview(enabled)
        if enabled:
            self._refresh_now()
            self.statusBar().showMessage(
                "Druckvorschau aktiv - echte 1-bit-Ausgabe (Esc beendet)", 4000
            )
        else:
            self._canvas.set_print_image(None)
            self.statusBar().showMessage("Druckvorschau aus", 2000)

    def _exit_print_preview(self) -> None:
        self._act_print_preview.setChecked(False)

    # ------------------------------------------------------------- Items ----
    def _default_item_pos(self) -> QPointF:
        margins = self._media_panel.margins()
        return QPointF(media.mm_to_dots(margins.left) + 10, media.mm_to_dots(margins.top) + 10)

    def _default_font_size(self) -> int:
        return max(16, int(self._canvas.height_dots * 0.25) or 40)

    def _add_item(self, item, pos: QPointF | None = None) -> None:
        item.setPos(pos if pos is not None else self._default_item_pos())
        if isinstance(item, TextItem):
            item.document().contentsChanged.connect(self._on_text_edited)
        self._canvas.add_item(item)
        self._canvas.setFocus()
        self._recompute_canvas()
        self._schedule_refresh()
        self._on_selection_changed()

    def _new_text(self, pos: QPointF | None = None, text: str = "Text") -> TextItem:
        item = TextItem(text, font_pixel_size=self._default_font_size())
        self._add_item(item, pos)
        item.start_editing()
        return item

    def _add_text(self) -> None:
        self._new_text()

    def _on_text_requested(self, scene_pos: QPointF) -> None:
        self._new_text(scene_pos)

    def _on_text_edited(self) -> None:
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

    def _on_zoom_changed(self, percent: float) -> None:
        self._zoom_label.setText(f"Zoom {percent:.0f} %")

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
            QMessageBox.warning(self, "Bild", str(exc))
            return
        rect = item.boundingRect()
        pos = QPointF(scene_pos.x() - rect.width() / 2, scene_pos.y() - rect.height() / 2)
        self._add_item(item, pos)

    def _on_text_dropped(self, text: str, scene_pos: QPointF) -> None:
        text = text.strip()
        if not text:
            return
        self._add_item(TextItem(text, font_pixel_size=self._default_font_size()), scene_pos)

    def _build_context_menu(self, scene_pos: QPointF) -> QMenu:
        menu = QMenu(self)
        menu.addAction(icon("text"), "Text einfügen", lambda: self._on_text_requested(scene_pos))
        menu.addAction(icon("image"), "Bild…", self._add_image)
        menu.addAction(icon("barcode"), "Barcode…", self._add_barcode)
        menu.addAction(icon("qr"), "QR-Code…", self._add_qr)
        menu.addAction(icon("line"), "Linie", self._add_line)
        menu.addAction(icon("rect"), "Rahmen", self._add_rect)
        if self._canvas.selected_items():
            menu.addSeparator()
            menu.addAction(icon("front"), "In den Vordergrund", lambda: self._bump_z(+1))
            menu.addAction(icon("back"), "In den Hintergrund", lambda: self._bump_z(-1))
            menu.addAction(icon("delete"), "Löschen", self._canvas.delete_selected)
        return menu

    def _show_context_menu(self, global_pos, scene_pos: QPointF) -> None:
        self._build_context_menu(scene_pos).exec(global_pos)

    def _add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Bild wählen", "", "Bilder (*.png *.jpg *.jpeg *.bmp *.gif);;Alle Dateien (*)"
        )
        if not path:
            return
        try:
            item = ImageItem.from_file(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Bild", str(exc))
            return
        self._add_item(item)

    def _add_barcode(self) -> None:
        symbology, ok = QInputDialog.getItem(self, "Barcode", "Symbologie", BARCODE_SYMBOLOGIES, 0, False)
        if not ok:
            return
        value, ok = QInputDialog.getText(self, "Barcode", "Inhalt")
        if not ok or not value:
            return
        try:
            item = BarcodeItem(value, symbology, height_dots=max(60, int(self._canvas.height_dots * 0.4)))
        except ValueError as exc:
            QMessageBox.warning(self, "Barcode", str(exc))
            return
        self._add_item(item)

    def _add_qr(self) -> None:
        value, ok = QInputDialog.getText(self, "QR-Code", "Inhalt", text="https://")
        if not ok or not value:
            return
        item = QRItem(value, size_dots=max(60, int(self._canvas.height_dots * 0.5)))
        self._add_item(item)

    def _add_line(self) -> None:
        width = self._canvas.sceneRect().width()
        item = LineItem(0, 0, int(width * 0.6), 0, width_px=3)
        self._add_item(item)

    def _add_rect(self) -> None:
        height = self._canvas.height_dots
        item = RectItem(QRectF(0, 0, int(self._canvas.sceneRect().width() * 0.6), int(max(40, height * 0.4))))
        self._add_item(item)

    def _bump_z(self, direction: int) -> None:
        for item in self._canvas.selected_items():
            item.setZValue(item.zValue() + direction)

    # -------------------------------------------------------------- Print ---
    def _on_print(self) -> None:
        if self._print_worker is not None and self._print_worker.isRunning():
            return
        try:
            image = self._current_render()
        except Exception as exc:
            QMessageBox.critical(self, "Rendern", f"Etikett konnte nicht gerendert werden:\n{exc}")
            return
        label = self._media_panel.label
        config = self._media_panel.printer_config()
        options = {
            "threshold": self._threshold_spin.value(),
            "dither": self._dither_check.isChecked(),
            "red": self._media_panel.use_red(),
            "cut": self._cut_check.isChecked(),
        }
        self._print_button.setEnabled(False)
        self.statusBar().showMessage(f"Sende an {config.address}…")
        self._print_worker = PrintWorker(image, label, config, options)
        self._print_worker.succeeded.connect(self._on_print_succeeded)
        self._print_worker.failed.connect(self._on_print_failed)
        self._print_worker.finished.connect(lambda: self._print_button.setEnabled(True))
        self._print_worker.start()

    def _on_print_succeeded(self, status: dict) -> None:
        self.statusBar().showMessage(f"Druckauftrag gesendet (outcome={status.get('outcome')}).", 8000)

    def _on_print_failed(self, message: str) -> None:
        self.statusBar().showMessage("Druck fehlgeschlagen.", 8000)
        QMessageBox.critical(self, "Druckfehler", message)

    # ------------------------------------------------------------- Detect ---
    def _on_detect_label(self) -> None:
        config = self._media_panel.printer_config()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            label = detect_label(config)
        except Exception as exc:  # pragma: no cover - defensiv
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Band erkennen", f"Abfrage fehlgeschlagen:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if label is None:
            QMessageBox.information(
                self,
                "Band erkennen",
                "Der Drucker hat kein Band gemeldet (kein Status-Readback über TCP).\n"
                "Bitte das Band manuell auswählen.",
            )
            return
        if self._media_panel.select_label(label.identifier):
            self.statusBar().showMessage(f"Band erkannt: {label.display_name}", 8000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "Über QLInux",
            "QLInux - P-touch-Editor-Klon für Brother QL-820NWB\n\n"
            f"Band- und Modellmaße: {len(media.all_labels())} Bänder / "
            f"{len(media.all_models())} Modelle (dynamisch aus brother_ql)\n"
            f"Auflösung: {media.DPI} dpi",
        )

    # -------------------------------------------------------------- Close ---
    def closeEvent(self, event) -> None:  # noqa: N802
        self._settings.save_geometry(self.saveGeometry())
        self._settings.address = self._media_panel.address()
        self._settings.model = self._media_panel.model_id()
        self._settings.last_label = self._media_panel.label_id()
        self._settings.sync()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("QLInux")
    window = MainWindow()
    window.resize(1080, 700)
    window.show()
    window.resizeDocks(
        [window._right_dock],
        [320],
        Qt.Orientation.Horizontal,
    )
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
