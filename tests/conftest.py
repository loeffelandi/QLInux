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
    """Der Start sucht Drucker. Tests sollen dafuer nicht ins Netz funken.

    Ein Test, der Treffer braucht, setzt ``discover_network_printers`` danach
    selbst. Laeuft am Ende noch eine Suche, wird sie abgebrochen, damit kein
    Thread ein schon verworfenes Fenster anspricht.
    """
    monkeypatch.setattr(
        "ql_editor.app.discover_network_printers", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        "ql_editor.media_panel.discover_network_printers", lambda *args, **kwargs: []
    )
    yield
    widgets = sys.modules.get("PySide6.QtWidgets")
    app = widgets.QApplication.instance() if widgets is not None else None
    if app is None:
        return
    for widget in app.topLevelWidgets():
        cancel = getattr(widget, "_network_cancel", None)
        worker = getattr(widget, "_network_worker", None)
        if cancel is not None:
            cancel.set()
        if worker is None:
            continue
        try:
            running = worker.isRunning()
        except RuntimeError:
            # close() trennt den Slot, der die Referenz leert; deleteLater
            # kann die Huelle danach schon abgebaut haben.
            continue
        if running:
            worker.wait(2000)
    app.processEvents()


@pytest.fixture(scope="session")
def qapp():
    """Eine QApplication-Instanz fuer alle Qt-Tests (offscreen)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _source_language():
    """Die Oberflaechensprache ist global - jeder Test startet auf Deutsch."""
    from ql_editor import i18n

    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
