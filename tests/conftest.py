"""Allgemeine Test-Fixtures.

* stellt das Repo-Root in ``sys.path`` (``import ql_editor``)
* erzwingt das Qt-Offscreen-Backend (headless, kein Display noetig)
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Muss *vor* dem ersten Qt-Import gesetzt sein. Absichtlich hart gesetzt:
# laeuft pytest in einer Desktop-Sitzung, waere QT_QPA_PLATFORM dort schon
# gesetzt (z. B. "wayland;xcb") und ginge fuer jeden Test ein echtes Fenster
# auf. Wer wirklich auf dem Bildschirm testen will, setzt QLINUX_TEST_PLATFORM.
os.environ["QT_QPA_PLATFORM"] = os.environ.get("QLINUX_TEST_PLATFORM", "offscreen")


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
