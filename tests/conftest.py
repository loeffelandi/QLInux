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

# Muss *vor* dem ersten Qt-Import gesetzt sein.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
