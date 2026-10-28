"""Allgemeine Test-Fixtures.

* stellt das Repo-Root in ``sys.path`` (``import ql_editor``)
* erzwingt das Qt-Offscreen-Backend (headless, kein Display noetig)
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# QSettings("QLInux", "QLInux") landet unter $XDG_CONFIG_HOME. Zeigt der
# Testlauf auf ein frisches temporaeres Verzeichnis, kann kein Test die echten
# Einstellungen lesen oder loeschen - vorher tat er genau das: die Fixture
# unten raeumt "QLInux/QLInux" auf, und damit war die Datei des Nutzers weg.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="qlinux-test-config-")

# Muss *vor* dem ersten Qt-Import gesetzt sein. Absichtlich hart gesetzt:
# laeuft pytest in einer Desktop-Sitzung, waere QT_QPA_PLATFORM dort schon
# gesetzt (z. B. "wayland;xcb") und ginge fuer jeden Test ein echtes Fenster
# auf. Wer wirklich auf dem Bildschirm testen will, setzt QLINUX_TEST_PLATFORM.
os.environ["QT_QPA_PLATFORM"] = os.environ.get("QLINUX_TEST_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _quiet_network_discovery(monkeypatch):
    """Der Start sucht Drucker, das aktive Fenster fragt den Netzwerkdrucker
    ab. Tests sollen dafuer nicht ins Netz funken.

    Ein Test, der Treffer braucht, setzt ``discover_network_printers`` bzw.
    ``network_printer_status`` danach selbst. Laeuft am Ende noch eine Suche
    oder Abfrage, wird darauf gewartet, damit kein Thread ein schon
    verworfenes Fenster anspricht.
    """
    monkeypatch.setattr(
        "ql_editor.app.discover_network_printers", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        "ql_editor.media_panel.discover_network_printers", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        "ql_editor.app.network_printer_status", lambda *args, **kwargs: None
    )
    yield
    widgets = sys.modules.get("PySide6.QtWidgets")
    app = widgets.QApplication.instance() if widgets is not None else None
    if app is None:
        return
    _release_qt_windows(app)


def _release_qt_windows(app) -> None:
    """Fenster wegwerfen, die ein Test offen gelassen hat.

    Jedes Hauptfenster haelt Menues und Combo-Popups als weitere
    Top-Level-Widgets. Bleiben die stehen, laeuft am Ende jedes Tests
    ``topLevelWidgets`` plus ``getattr`` ueber die ganze Liste - das wurde
    mit jedem weiteren Fenster teurer. Ein offenes Sheet laesst ausserdem
    den Tastaturfilter auf der QApplication, der dann jedes Qt-Ereignis
    durch Python schickt.
    """
    import shiboken6
    from PySide6.QtCore import QEvent
    from ql_editor.app import MainWindow
    from ql_editor.sheet import _shortcut_filter

    for widget in app.topLevelWidgets():
        if not shiboken6.isValid(widget) or not isinstance(widget, MainWindow):
            continue
        widget._network_cancel.set()
        for worker in (widget._network_worker, widget._net_poll_worker):
            if worker is None or not shiboken6.isValid(worker):
                continue
            try:
                running = worker.isRunning()
            except RuntimeError:
                # close() trennt den Slot, der die Referenz leert; deleteLater
                # kann die Huelle danach schon abgebaut haben.
                continue
            if running:
                worker.wait(2000)

    for widget in list(app.topLevelWidgets()):
        if not shiboken6.isValid(widget) or widget.parent() is not None:
            continue
        # close() wuerde Einstellungen schreiben. Zerstoeren reicht.
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    guard = _shortcut_filter
    if guard is not None and shiboken6.isValid(guard):
        guard._sheets.clear()
        guard._remove()


@pytest.fixture(scope="session")
def qapp():
    """Eine QApplication-Instanz fuer alle Qt-Tests (offscreen)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _instant_smooth_scroll(monkeypatch):
    """Rad-Scrollen im Test sofort ausfuehren.

    Die Animation dauert 160 ms. Tests, die danach den Scrollwert pruefen,
    haben bisher den Event-Loop mit ``sleep`` bedient.
    """
    from ql_editor.widgets import SmoothScroller

    original = SmoothScroller.__init__

    def _init(self, parent, bar, duration=0):
        original(self, parent, bar, 0)

    monkeypatch.setattr(SmoothScroller, "__init__", _init)


@pytest.fixture(autouse=True)
def _source_language():
    """Die Oberflaechensprache ist global - jeder Test startet auf Deutsch."""
    from ql_editor import i18n

    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
