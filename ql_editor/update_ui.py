"""Oberflaeche des Selbst-Updates: Suche im Hintergrund, Sheets, Installation.

``updater`` erledigt die Arbeit ohne Qt; hier laufen Suche und Installation
als ``QThread`` ohne Qt-Parent (siehe ``app._orphan_workers``) und melden sich
per Signal im GUI-Thread zurueck.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, updater
from .i18n import tr
from .sheet import SheetLike, ask_restart, ask_update, show_message, show_widget

if TYPE_CHECKING:
    from .app import MainWindow

logger = logging.getLogger(__name__)


class CheckWorker(QThread):
    """Fragt GitHub nach der neuesten Release, abseits der Oberflaeche."""

    answered = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__(None)

    def run(self) -> None:
        try:
            result = updater.check()
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensiv
            logger.info("Update-Suche fehlgeschlagen: %s", exc)
            self.failed.emit(
                tr("Die Suche ist fehlgeschlagen: {error}").format(error=exc)
            )
        else:
            self.answered.emit(result)


class InstallWorker(QThread):
    """Laedt das Update, prueft es und ersetzt das laufende Programm."""

    progress = Signal(int, int)
    installing = Signal()
    succeeded = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        update: updater.Update,
        kind: str,
        target: Path,
        cancel: threading.Event,
    ) -> None:
        super().__init__(None)
        self._update = update
        self._kind = kind
        self._target = target
        self._cancel = cancel

    def run(self) -> None:
        try:
            self._install()
        except updater.UpdateCancelled:
            self.cancelled.emit()
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensiv
            logger.warning("Update fehlgeschlagen: %s", exc)
            self.failed.emit(
                tr("Das Update ist fehlgeschlagen: {error}").format(error=exc)
            )
        else:
            self.succeeded.emit()

    def _download(self, target: Path) -> None:
        updater.download(
            self._update.url,
            target,
            self._update.sha256,
            progress=self.progress.emit,
            cancel=self._cancel,
        )

    def _install(self) -> None:
        updater.ensure_writable(self._target)
        if self._kind == updater.KIND_APPIMAGE:
            part = updater.staging_path(self._target)
            self._download(part)
            self.installing.emit()
            updater.install_appimage(part, self._target)
            return
        folder = Path(tempfile.mkdtemp(prefix="qlinux-update-"))
        try:
            dmg = folder / self._update.name
            self._download(dmg)
            self.installing.emit()
            updater.install_app(dmg, self._target, self._update.version)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class UpdateProgress(QWidget):
    """Fortschritt des Downloads; waehrend des Ersetzens nicht abbrechbar."""

    cancel_requested = Signal()

    def __init__(self, version: str) -> None:
        super().__init__()
        self._label = QLabel(
            tr("QLInux {version} wird geladen …").format(version=version)
        )
        self._label.setWordWrap(True)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self.cancel_button = QPushButton(tr("Abbrechen"))
        self.cancel_button.clicked.connect(self.cancel_requested)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        layout.addWidget(self._bar)
        layout.addLayout(buttons)
        self.setMinimumWidth(360)

    def set_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self._bar.setRange(0, 0)
            return
        self._bar.setRange(0, total)
        self._bar.setValue(min(done, total))

    def set_installing(self) -> None:
        self._label.setText(tr("Update wird installiert …"))
        self._bar.setRange(0, 0)
        self.cancel_button.setEnabled(False)


class UpdateController(QObject):
    """Verbindet Suche, Sheets und Installation mit dem Hauptfenster."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._check_worker: CheckWorker | None = None
        self._install_worker: InstallWorker | None = None
        self._cancel = threading.Event()
        self._manual = False
        self._progress_sheet: SheetLike | None = None
        self._progress: UpdateProgress | None = None
        self._kind = ""
        self._target = Path()

    @property
    def _settings(self):
        return self._window._settings

    def busy(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._check_worker, self._install_worker)
        )

    # ----------------------------------------------------------- Suche ----
    def check_on_start(self) -> None:
        """Nach dem Zeigen des Fensters: hoechstens einmal am Tag, ohne Meldung."""
        if updater.check_due(self._settings):
            self._start_check(manual=False)

    def check_now(self) -> None:
        """Menueeintrag: sofort, ohne Sperre, mit Rueckmeldung."""
        self._start_check(manual=True)

    def _start_check(self, *, manual: bool) -> None:
        if self.busy():
            return
        self._manual = manual
        worker = CheckWorker()
        worker.answered.connect(self._on_answered)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._check_finished)
        worker.finished.connect(worker.deleteLater)
        self._check_worker = worker
        worker.start()

    def _on_answered(self, result: updater.CheckResult) -> None:
        update = result.update
        if not result.pending:
            self._settings.update_last_check = time.time()
        if update is not None:
            skipped = update.version == self._settings.update_skipped_version
            if self._manual or not skipped:
                self._offer(update)
            return
        if not self._manual:
            return
        if result.pending:
            show_message(
                self._window,
                "info",
                tr("Nach Updates suchen"),
                tr(
                    "Eine neue Version wird gerade veröffentlicht. "
                    "Bitte in ein paar Minuten noch einmal suchen."
                ),
            )
        else:
            show_message(
                self._window,
                "info",
                tr("Nach Updates suchen"),
                tr("QLInux ist aktuell (Version {version}).").format(
                    version=__version__
                ),
            )

    def _on_failed(self, text: str) -> None:
        logger.info("Update-Suche: %s", text)
        if self._manual:
            show_message(self._window, "warning", tr("Nach Updates suchen"), text)

    # ------------------------------------------------------- Angebot ------
    def _offer(self, update: updater.Update) -> None:
        def chosen(choice: str) -> None:
            if choice == "update":
                self._install(update)
            elif choice == "skip":
                self._settings.update_skipped_version = update.version

        ask_update(
            self._window,
            title=tr("Update verfügbar"),
            text=tr(
                "QLInux {new} ist erschienen. Installiert ist Version {current}.\n\n"
                "Jetzt herunterladen und installieren?"
            ).format(new=update.version, current=__version__),
            on_choice=chosen,
        )

    # ---------------------------------------------------- Installation ----
    def _install(self, update: updater.Update) -> None:
        kind = updater.install_kind()
        if kind is None or self.busy():
            return
        self._kind = kind
        self._target = updater.install_path(kind)
        self._cancel = threading.Event()
        progress = UpdateProgress(update.version)
        progress.cancel_requested.connect(self._cancel.set)
        worker = InstallWorker(update, kind, self._target, self._cancel)
        worker.progress.connect(progress.set_progress)
        worker.installing.connect(progress.set_installing)
        worker.succeeded.connect(self._on_installed)
        worker.failed.connect(self._on_install_failed)
        worker.cancelled.connect(self._close_progress)
        worker.finished.connect(self._install_finished)
        worker.finished.connect(worker.deleteLater)
        self._progress = progress
        self._progress_sheet = show_widget(
            self._window,
            title=tr("Update wird geladen"),
            content=progress,
            sizing="hint",
        )
        self._progress_sheet.closed.connect(self._on_progress_closed)
        self._install_worker = worker
        worker.start()

    def _on_progress_closed(self) -> None:
        # Das Sheet schliessen heisst waehrend des Downloads: abbrechen.
        if self._progress is not None and self._progress.cancel_button.isEnabled():
            self._cancel.set()

    def _close_progress(self) -> None:
        sheet = self._progress_sheet
        self._progress_sheet = None
        self._progress = None
        if sheet is not None:
            try:
                sheet.closed.disconnect(self._on_progress_closed)
            except (RuntimeError, TypeError):
                pass
            sheet.close_sheet()

    def _on_install_failed(self, text: str) -> None:
        self._close_progress()
        show_message(self._window, "warning", tr("Update fehlgeschlagen"), text)

    def _on_installed(self) -> None:
        self._close_progress()
        ask_restart(
            self._window,
            title=tr("Update installiert"),
            text=tr(
                "QLInux wurde aktualisiert. Jetzt neu starten, um die neue "
                "Version zu benutzen?"
            ),
            on_choice=self._restart_chosen,
        )

    def _restart_chosen(self, choice: str) -> None:
        if choice == "restart":
            self._window.request_restart(self._kind, self._target)

    def _check_finished(self) -> None:
        self._check_worker = None

    def _install_finished(self) -> None:
        self._install_worker = None

    # ------------------------------------------------------- Schliessen ---
    def shutdown(self) -> None:
        """Fenster schliesst: Download abbrechen, Threads abhaengen."""
        self._cancel.set()
        check = self._check_worker
        if check is not None:
            self._window._disconnect_worker(
                check,
                [
                    (check.answered, self._on_answered),
                    (check.failed, self._on_failed),
                    (check.finished, self._check_finished),
                ],
            )
        install = self._install_worker
        if install is not None:
            self._window._disconnect_worker(
                install,
                [
                    (install.succeeded, self._on_installed),
                    (install.failed, self._on_install_failed),
                    (install.cancelled, self._close_progress),
                    (install.finished, self._install_finished),
                ],
            )
        self._check_worker = None
        self._install_worker = None


__all__ = ["UpdateController"]
