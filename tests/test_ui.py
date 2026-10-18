"""UI-Tests: Panels, Inspector, Druckoptionen und Hauptfenster-Verhalten.

Bedient die echten Widgets (Checkboxen, Combos, Spinboxen, Aktionen) und
prueft die Folgen am Canvas und an den Items. Kein Drucker, kein Dateidialog.
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QToolButton

from ql_editor.items import ImageItem, TextItem
from ql_editor.printer import CUT_AT_END, CUT_EACH, CUT_MODES, resolution_options

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    from PySide6.QtCore import QSettings

    QSettings("QLInux", "QLInux").clear()
    yield
    QSettings("QLInux", "QLInux").clear()


@pytest.fixture
def window(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    QApplication.processEvents()


def _checkbox(parent, text: str) -> QCheckBox:
    matches = [c for c in parent.findChildren(QCheckBox) if c.text() == text]
    assert matches, f"Checkbox {text!r} nicht gefunden"
    return matches[0]


def _tool_button(parent, tooltip: str) -> QToolButton:
    matches = [b for b in parent.findChildren(QToolButton) if b.toolTip() == tooltip]
    assert matches, f"Symbol-Knopf {tooltip!r} nicht gefunden"
    return matches[0]


def _add_text(window) -> TextItem:
    window._act_add_text.trigger()
    QApplication.processEvents()
    return [i for i in window._canvas.ordered_items() if isinstance(i, TextItem)][-1]


# --------------------------------------------------------------------------- #
# Medien-Panel
# --------------------------------------------------------------------------- #


def test_band_wechsel_aendert_canvas_und_panel(window):
    panel = window._media_panel
    assert panel.select_label("62")
    QApplication.processEvents()

    assert panel.label_id() == "62"
    assert window._canvas.label.identifier == "62"


def test_ausrichtung_wechsel_aendert_canvas(window):
    panel = window._media_panel
    panel.set_orientation("across")
    QApplication.processEvents()
    across = window._canvas.orientation

    panel.set_orientation("along")
    QApplication.processEvents()
    along = window._canvas.orientation

    assert across != along


def test_automatische_laenge_und_feste_laenge(window):
    panel = window._media_panel
    auto = panel._auto_check
    auto.setChecked(True)
    QApplication.processEvents()
    assert panel.auto_length() is True

    auto.setChecked(False)
    panel._length_spin.setValue(120)
    QApplication.processEvents()
    assert panel.auto_length() is False
    assert panel.length_mm() == pytest.approx(120)


def test_panel_zustand_bleibt_nach_wiederherstellen_erhalten(window):
    panel = window._media_panel
    panel.select_label("62")
    QApplication.processEvents()
    saved = panel.state()

    panel.select_label("50")
    QApplication.processEvents()
    assert panel.label_id() == "50"

    panel.apply_state(saved)
    QApplication.processEvents()
    assert panel.label_id() == "62"


def test_panel_meldet_aenderungen(window):
    panel = window._media_panel
    seen: list[bool] = []
    panel.changed.connect(lambda: seen.append(True))

    panel.select_label("62")
    QApplication.processEvents()

    assert seen


def test_modellwechsel_laesst_gueltiges_band(window):
    panel = window._media_panel
    panel.set_model("QL-820NWB")
    QApplication.processEvents()

    assert panel.model_id() == "QL-820NWB"
    assert panel.label.identifier == panel.label_id()
    assert panel.label.restricted_to_models == () or "QL-820NWB" in panel.label.restricted_to_models


# --------------------------------------------------------------------------- #
# Inspector
# --------------------------------------------------------------------------- #


def test_inspector_formatting_buttons_have_tooltips(window):
    """Stil, Liste, Richtung und Farbmenue sind ueber Tooltips erreichbar."""
    text = _add_text(window)
    inspector = window._inspector
    inspector.set_item(text, allow_red=True)
    QApplication.processEvents()

    for tip in (
        "Unterstrichen (Strg+U)",
        "Durchgestrichen",
        "Keine",
        "Punkte",
        "Nummern",
        "Horizontal",
        "Vertikal",
        "Farbe",
    ):
        _tool_button(inspector, tip)

    color = _tool_button(inspector, "Farbe")
    assert color.text() == ""
    assert not color.icon().isNull()
    assert [action.text() for action in color.menu().actions()] == ["schwarz", "rot"]

    _tool_button(inspector, "Unterstrichen (Strg+U)").click()
    _tool_button(inspector, "Punkte").click()
    _tool_button(inspector, "Vertikal").click()
    color.menu().actions()[1].trigger()
    QApplication.processEvents()

    assert text.underline is True
    assert text.list_style == "bullet"
    assert text.vertical is True
    assert text.color == "red"
    assert color.text() == ""


def test_inspector_fett_und_kursiv_fuer_text(window):
    text = _add_text(window)
    inspector = window._inspector
    inspector.set_item(text)
    QApplication.processEvents()

    _tool_button(inspector, "Fett (Strg+B)").click()
    _tool_button(inspector, "Kursiv (Strg+I)").click()
    QApplication.processEvents()

    assert text.bold is True
    assert text.italic is True


def test_inspector_bild_hat_keine_textoptionen(window, tmp_path, monkeypatch):
    from PIL import Image

    from ql_editor import app as app_module

    path = tmp_path / "bild.png"
    Image.new("RGB", (80, 40), (0, 0, 0)).save(path)
    monkeypatch.setattr(
        app_module,
        "choose_file",
        lambda parent, *, on_selected, **_kw: on_selected(str(path)),
    )
    window._act_add_image.trigger()
    QApplication.processEvents()
    image = [i for i in window._canvas.ordered_items() if isinstance(i, ImageItem)][-1]

    window._inspector.set_item(image)
    QApplication.processEvents()

    assert not [c for c in window._inspector.findChildren(QCheckBox) if c.text() == "Fett"]


# --------------------------------------------------------------------------- #
# Druckoptionen
# --------------------------------------------------------------------------- #


def test_kopien_begrenzt_auf_gueltigen_bereich(window):
    spin = window._copies_spin
    spin.setValue(3)
    assert spin.value() == 3

    spin.setValue(10_000)
    assert spin.value() <= spin.maximum()
    assert spin.minimum() >= 1


def test_schnittmodus_auswahl(window):
    combo = window._cut_combo
    values = [combo.itemData(i) for i in range(combo.count())]
    assert set(values) == set(CUT_MODES)

    combo.setCurrentIndex(values.index(CUT_AT_END))
    assert combo.currentData() == CUT_AT_END

    combo.setCurrentIndex(values.index(CUT_EACH))
    assert combo.currentData() == CUT_EACH


def test_aufloesung_passt_zum_modell(window):
    panel = window._media_panel
    panel.set_model("QL-820NWB")
    QApplication.processEvents()

    expected = resolution_options(panel.model_id())
    assert window._resolution_combo.count() == len(expected)


# --------------------------------------------------------------------------- #
# Hauptfenster
# --------------------------------------------------------------------------- #


def test_undo_und_redo_fuer_text(window):
    text = _add_text(window)
    window._canvas.setFocus()
    text.start_editing()
    QTest.keyClicks(window._canvas.viewport(), "Undo")
    text.finish_editing()
    QApplication.processEvents()
    count = lambda: len([i for i in window._canvas.ordered_items() if isinstance(i, TextItem)])
    assert count() == 1

    window._act_undo.trigger()
    QApplication.processEvents()
    assert count() == 0

    window._act_redo.trigger()
    QApplication.processEvents()
    assert count() == 1


def test_zoom_aktionen_veraendern_den_massstab(window):
    canvas = window._canvas
    window._act_zoom_100.trigger()
    QApplication.processEvents()
    base = canvas.transform().m11()

    window._act_zoom_in.trigger()
    QApplication.processEvents()
    assert canvas.transform().m11() > base

    window._act_zoom_out.trigger()
    window._act_zoom_out.trigger()
    QApplication.processEvents()
    assert canvas.transform().m11() < base


def test_druckvorschau_umschalten(window):
    window._act_print_preview.trigger()
    QApplication.processEvents()
    assert window._canvas.print_preview is True
    assert window._act_print_preview.isChecked()

    window._act_print_preview.trigger()
    QApplication.processEvents()
    assert window._canvas.print_preview is False


def test_neuer_tab_hat_eigenen_zustand(window):
    first = window._canvas
    _add_text(window)
    window._create_tab()
    QApplication.processEvents()

    assert window._tab_bar.count() == 2
    assert window._canvas is not first
    assert len([i for i in window._canvas.ordered_items() if isinstance(i, TextItem)]) == 0


def test_dokument_speichern_enthaelt_den_text(window, tmp_path):
    import json

    _add_text(window).set_text_value("Speicherung")
    path = tmp_path / "design.qlx"

    assert window._save_document_to(str(path)) is True
    QApplication.processEvents()

    assert "Speicherung" in path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))
