"""GUI-Tests (PySide6, headless via Offscreen-Plattform).

Prueft die Verschaltung von Media-Panel, Canvas und Vorschau sowie die
Randbegrenzung. Es wird kein Drucker benoetigt.
"""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QSettings, Qt

from ql_editor import media
from ql_editor.canvas import ROTATE_OFFSET_PX, LabelCanvas
from ql_editor.items import BarcodeItem, QRItem, TextItem, item_from_dict
from ql_editor.media import get_label
from ql_editor.printer import RESOLUTION_HIGH, RESOLUTION_STANDARD

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clean_settings():
    QSettings("QLInux", "QLInux").clear()
    yield
    QSettings("QLInux", "QLInux").clear()


# --------------------------------------------------------------------------- #
# MediaPanel
# --------------------------------------------------------------------------- #
def test_media_panel_defaults(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert panel.model_id() == media.DEFAULT_MODEL
    assert panel.label_id() == media.DEFAULT_LABEL
    assert panel.auto_length() is True
    # Auto-Laenge: minimaler Canvas = Modell-Minimum.
    width, height = panel.canvas_size()
    assert width == 554
    assert height == panel.model.min_max_length_dots[0]


def test_media_panel_shows_band_erkennen_only_where_it_works(qapp):
    """Der Knopf „Band erkennen" braucht einen Rueckkanal - den gibt es nur ueber USB.

    Deshalb steht er im Netzwerk gar nicht erst da (statt ausgegraut).
    """
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert panel.printer_config().backend == "network"
    assert not panel._detect_button.isVisibleTo(panel)

    panel.set_address("usb://0x04f9:0x209b")
    assert panel.printer_config().backend == "pyusb"
    assert panel._detect_button.isVisibleTo(panel)

    panel.set_address("/dev/usb/lp1")
    assert panel.printer_config().backend == "linux_kernel"
    assert panel._detect_button.isVisibleTo(panel)

    panel.set_address("tcp://192.168.178.62:9100")
    assert not panel._detect_button.isVisibleTo(panel)


def test_media_panel_emits_a_usb_search(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[bool] = []
    panel.usb_search_requested.connect(lambda: seen.append(True))
    panel._usb_button.click()
    assert seen == [True]


def test_usb_search_applies_the_only_printer_found(qapp, tmp_path, monkeypatch):
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(
        media_panel_module, "usb_printers", lambda: ["usb://0x04f9:0x209b"]
    )

    win._on_usb_search()

    assert win._media_panel.address() == "usb://0x04f9:0x209b"
    assert win._media_panel.printer_config().backend == "pyusb"


def test_usb_search_switches_the_model_from_the_usb_id(qapp, tmp_path, monkeypatch):
    """Am USB haengt ein anderes Modell - die Kennung zieht das Modell nach."""
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_model("QL-820NWB")
    monkeypatch.setattr(
        media_panel_module, "usb_printers", lambda: ["usb://0x04f9:0x2042"]
    )

    win._on_usb_search()

    assert win._media_panel.address() == "usb://0x04f9:0x2042"
    assert win._media_panel.model_id() == "QL-700"
    assert win._media_panel.printer_config().model == "QL-700"


def test_usb_search_keeps_the_model_when_it_is_unknown(qapp, tmp_path, monkeypatch):
    from ql_editor import media_panel as media_panel_module

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_model("QL-820NWB")
    monkeypatch.setattr(
        media_panel_module, "usb_printers", lambda: ["usb://0x04f9:0x9999"]
    )

    win._on_usb_search()

    assert win._media_panel.model_id() == "QL-820NWB"


# --------------------------------------------------------------------------- #
# Druckerauswahl: Anschluss waehlen statt Adresse auswendig lernen
# --------------------------------------------------------------------------- #
def test_media_panel_asks_only_for_the_ip(qapp):
    """Netzwerk: nur die IP eintragen - Praefix und Port ergaenzt die App."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.set_network_host("192.168.178.77")

    assert panel.address() == "tcp://192.168.178.77:9100"
    assert panel.printer_config().backend == "network"


def test_media_panel_switches_between_network_and_usb_rows(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_NETWORK, CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    panel = MediaPanel()
    assert panel.connection() == CONNECTION_NETWORK
    assert panel._net_combo.isVisibleTo(panel)
    assert not panel._usb_combo.isVisibleTo(panel)

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.connection() == CONNECTION_USB
    assert not panel._net_combo.isVisibleTo(panel)
    assert panel._usb_combo.isVisibleTo(panel)
    # Ohne Geraet gibt es keine Adresse - und der Druckdialog sagt das dann.
    assert panel.address() == ""


def test_connection_tabs_keep_the_layout_stable(qapp, monkeypatch):
    """Netzwerk/USB umschalten verschiebt weder Felder noch Nachbarkaesten.

    Beide Anschlussarten liegen in einem Stapel an derselben Stelle; die
    Beschriftungsspalte ist fest breit.
    """
    from PySide6.QtCore import QPoint

    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_NETWORK, CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "usb_access", lambda address: True)
    panel = MediaPanel()
    panel.resize(280, 720)
    panel.show()
    qapp.processEvents()

    box = panel._printer_form.parentWidget()
    groups = [w for w in panel.findChildren(type(box))]

    def snapshot():
        qapp.processEvents()
        return (
            box.height(),
            [g.y() for g in groups],
            (
                panel._model_combo.pos(),
                panel._conn_buttons[CONNECTION_NETWORK].size(),
                panel._conn_buttons[CONNECTION_USB].size(),
            ),
        )

    def field_x(widget) -> int:
        return widget.mapTo(panel, QPoint(0, 0)).x()

    network = snapshot()
    assert field_x(panel._net_combo) == field_x(panel._model_combo)

    panel._conn_buttons[CONNECTION_USB].setChecked(True)
    usb = snapshot()
    assert field_x(panel._usb_combo) == field_x(panel._model_combo)

    panel._conn_buttons[CONNECTION_NETWORK].setChecked(True)
    back = snapshot()

    assert usb == network
    assert back == network


def test_network_address_is_asked_for_by_the_list_entry(qapp):
    """Die IP-Eingabe liegt hinter dem letzten Listeneintrag - nicht im Panel.

    Das Panel selbst zeigt nur Liste und Suchsymbol; wer die Adresse von Hand
    braucht, findet sie genau dort, wo die anderen Drucker stehen.
    """
    from ql_editor.media_panel import NET_ADD_ENTRY, MediaPanel
    from ql_editor.sheet import Sheet

    panel = MediaPanel()
    panel.resize(280, 720)
    panel.show()
    qapp.processEvents()

    last = panel._net_combo.count() - 1
    assert panel._net_combo.itemText(last) == "Per IP-Adresse hinzufügen…"
    assert panel._net_combo.itemData(last) == NET_ADD_ENTRY
    # Der Befehlseintrag ist nie die aktuelle Auswahl - sonst wuerde ein Klick
    # darauf keine Aenderung melden.
    assert panel._net_combo.currentData() != NET_ADD_ENTRY
    # Nur eine Zeile fuer Liste + Suche: das Panel bleibt kurz.
    assert panel._net_button.text() == ""
    assert panel._net_button.isVisibleTo(panel)

    panel._net_combo.setCurrentIndex(last)  # oeffnet die IP-Abfrage
    qapp.processEvents()
    sheet = panel.findChild(Sheet)
    assert sheet is not None
    # ... und nimmt die Auswahl gleich wieder zurueck (Befehl, keine Adresse).
    assert panel._net_combo.currentData() != NET_ADD_ENTRY
    sheet.close_sheet()
    qapp.processEvents()


def test_network_address_is_taken_over_from_the_sheet(qapp, monkeypatch):
    """Der Befehlseintrag fuehrt zur Handeingabe - inklusive Liste."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    panel = MediaPanel()

    panel.set_network_host("192.168.178.99")

    assert panel.address() == "tcp://192.168.178.99:9100"
    assert panel._net_combo.currentText() == "192.168.178.99 – manuell"
    assert panel._net_combo.currentData() == "tcp://192.168.178.99:9100"
    # Kein Wildwuchs: erneut eintragen erweitert die Liste nicht (nur die
    # Handeingabe und der Befehlseintrag stehen darin).
    panel.set_network_host("192.168.178.98")
    assert panel._net_combo.count() == 2
    assert panel._net_combo.currentData() == "tcp://192.168.178.98:9100"


def test_media_panel_fills_the_network_list_from_a_search(qapp):
    """Gefundene Drucker stehen in der Liste; die Adresse bleibt unberuehrt."""
    from ql_editor import discovery
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.62:9100")

    found = panel.refresh_network_devices(
        [discovery.NetworkPrinter(host="192.168.178.62", model_id="QL-820NWB")]
    )

    assert [printer.host for printer in found] == ["192.168.178.62"]
    assert panel.address() == "tcp://192.168.178.62:9100"
    assert panel._net_combo.currentText() == "192.168.178.62 (QL-820NWB)"
    # Der Eintrag kennt sein Modell - das wird beim Waehlen uebernommen.
    assert panel._net_combo.currentData() == "tcp://192.168.178.62:9100"


def test_media_panel_takes_the_only_found_printer_without_an_address(qapp):
    """Ohne Adresse und mit genau einem Treffer ist die Wahl klar."""
    from ql_editor import discovery
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.apply_state({"connection": "network", "host": ""})
    assert panel.address() == ""

    changed = []
    panel.changed.connect(lambda: changed.append(True))
    panel.refresh_network_devices(
        [discovery.NetworkPrinter(host="192.168.178.77", model_id="QL-800")]
    )

    assert panel.address() == "tcp://192.168.178.77:9100"
    assert panel.model_id() == "QL-800"
    assert panel._net_combo.currentText() == "192.168.178.77 (QL-800)"
    assert changed  # das Hauptfenster muss davon erfahren


def test_picking_a_found_printer_sets_address_and_model(qapp):
    """Auswahl aus der Liste setzt IP und - wenn gemeldet - das Modell."""
    from ql_editor import discovery
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.refresh_network_devices(
        [
            discovery.NetworkPrinter(host="192.168.178.62", model_id="QL-820NWB"),
            discovery.NetworkPrinter(host="192.168.178.70", model_id="QL-700"),
        ]
    )

    panel._net_combo.setCurrentIndex(1)

    assert panel.address() == "tcp://192.168.178.70:9100"
    assert panel.model_id() == "QL-700"


def test_network_search_pulls_the_model_for_the_current_printer(qapp):
    """Auch ohne neue Auswahl zieht das Modell nach, wenn es gemeldet wird.

    Stand in den Einstellungen ein anderes Modell als das, was am gefundenen
    Geraet wirklich haengt, wuerde sonst mit falscher Aufloesung gedruckt.
    """
    from ql_editor import discovery
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.62:9100")
    panel.set_model("QL-800")
    assert panel.address() == "tcp://192.168.178.62:9100"

    panel.refresh_network_devices(
        [discovery.NetworkPrinter(host="192.168.178.62", model_id="QL-820NWB")]
    )

    assert panel.model_id() == "QL-820NWB"
    assert panel.address() == "tcp://192.168.178.62:9100"


def test_switching_to_network_starts_a_search(qapp):
    """Beim Wechsel auf Netzwerk wird gleich gesucht (wie am USB)."""
    from ql_editor.media_panel import CONNECTION_NETWORK, CONNECTION_USB, MediaPanel

    panel = MediaPanel()
    requested = []
    panel.network_search_requested.connect(lambda: requested.append(True))

    panel._conn_buttons[CONNECTION_USB].setChecked(True)
    assert requested == []  # USB sucht selbst, nicht im Netzwerk

    panel._conn_buttons[CONNECTION_NETWORK].setChecked(True)
    assert requested == [True]
    # Waehrend die Suche laeuft, wird nicht noch einmal gefragt.
    panel.set_network_searching(True)
    panel._request_network_search()
    assert requested == [True]


def test_network_search_shows_its_state(qapp):
    """Die Statuszeile sagt, was los ist - und der Knopf ist gesperrt."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    # Erster Start ohne Adresse: der Hinweis sagt, was zu tun ist. Sein Platz
    # ist reserviert, damit die Kaesten darunter nicht springen.
    assert panel._net_hint.text() == "Kein Drucker gewählt."

    panel.set_network_host("192.168.178.62")
    assert panel._net_hint.text() == ""

    panel.set_network_searching(True)
    assert panel._net_button.isEnabled() is False
    assert panel._net_hint.text() == "Suche läuft …"

    panel.set_network_searching(False)
    assert panel._net_button.isEnabled() is True
    assert panel._net_hint.text() == ""

    panel.refresh_network_devices([])
    assert panel._net_hint.text() == "Kein Drucker gefunden."


def test_media_panel_restores_a_network_address_from_settings(qapp):
    from ql_editor.media_panel import CONNECTION_NETWORK, MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.99:9100")

    assert panel.connection() == CONNECTION_NETWORK
    assert panel.address() == "tcp://192.168.178.99:9100"
    # Die Adresse steht sichtbar in der Liste (Handeingabe).
    assert panel._net_combo.currentData() == "tcp://192.168.178.99:9100"


def test_media_panel_usb_switch_finds_and_applies_the_device(qapp, monkeypatch):
    """Anschluss auf USB stellen genuegt: das Geraet wird gefunden und uebernommen."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(
        media_panel_module, "usb_printers", lambda: ["usb://0x04f9:0x2042"]
    )
    panel = MediaPanel()
    panel.set_model("QL-820NWB")

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.connection() == CONNECTION_USB
    assert panel.address() == "usb://0x04f9:0x2042"
    assert panel.model_id() == "QL-700"


def test_media_panel_usb_placeholder_is_not_an_address(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel, usb_placeholder

    monkeypatch.setattr(
        media_panel_module,
        "usb_printers",
        lambda: ["usb://0x04f9:0x2042", "/dev/usb/lp1"],
    )
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel._usb_combo.currentText() == usb_placeholder()
    assert panel.address() == ""


def test_media_panel_keeps_a_stored_usb_address_when_unplugged(qapp, monkeypatch):
    """Beim Laden der Einstellungen darf eine Adresse nicht verloren gehen."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    panel = MediaPanel()
    panel.set_address("usb://0x04f9:0x2042")

    assert panel.connection() == CONNECTION_USB
    assert panel.address() == "usb://0x04f9:0x2042"

    panel.refresh_usb_devices()  # Geraet ist inzwischen abgezogen

    assert panel.address() == "usb://0x04f9:0x2042"
    assert "nicht angeschlossen" in panel._usb_combo.currentText()


def test_media_panel_migrates_a_stored_libusb_address(qapp, monkeypatch):
    """Eine frueher gespeicherte libusb-Adresse zeigt auf den Kernel-Anschluss."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor import printer as printer_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(printer_module, "model_for_address", lambda address: "QL-700")
    panel = MediaPanel()
    panel.set_address("usb://0x04f9:0x2042")
    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    panel.refresh_usb_devices()

    assert panel.address() == "/dev/usb/lp1"
    assert "nicht angeschlossen" not in panel._usb_combo.currentText()


def test_media_panel_pulls_the_model_when_the_printer_shows_up_later(qapp, monkeypatch):
    """Drucker erst nach dem Start angesteckt: das Modell zieht beim Suchen nach."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import MediaPanel

    # Beim Start haengt der Drucker noch nicht am Kabel - das Modell bleibt
    # also stehen, wie es in den Einstellungen stand.
    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    monkeypatch.setattr(media_panel_module, "model_for_address", lambda address: None)
    panel = MediaPanel()
    panel.set_address("/dev/usb/lp1")
    panel.set_model("QL-800")

    # Jetzt steckt er am Kabel - und die USB-Kennung verraet das Modell.
    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(
        media_panel_module, "model_for_address", lambda address: "QL-700"
    )
    panel.refresh_usb_devices()

    assert panel.model_id() == "QL-700"
    assert panel.address() == "/dev/usb/lp1"


def test_media_panel_pulls_the_model_for_an_already_selected_device(qapp, monkeypatch):
    """Auch ohne Adresswechsel zieht das Modell nach (Suchen im Hauptfenster)."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "model_for_address", lambda address: None)
    panel = MediaPanel()
    panel.set_address("/dev/usb/lp1")
    panel.set_model("QL-800")

    monkeypatch.setattr(
        media_panel_module, "model_for_address", lambda address: "QL-700"
    )

    # Adresse bleibt (False = unveraendert), das Modell aber zieht nach.
    assert panel.select_usb_device("/dev/usb/lp1") is False
    assert panel.model_id() == "QL-700"


def test_media_panel_takes_the_single_printer_after_a_replug(qapp, monkeypatch):
    """Nach dem Umstecken heisst der Weg anders (lp1 -> lp0): Gerät übernehmen."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import MediaPanel

    # Gespeichert war lp1; der Kernel hat nach dem Umstecken lp0 vergeben.
    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    monkeypatch.setattr(media_panel_module, "model_for_address", lambda address: None)
    panel = MediaPanel()
    panel.set_address("/dev/usb/lp1")
    assert panel.address() == "/dev/usb/lp1"

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp0"])
    monkeypatch.setattr(
        media_panel_module, "model_for_address", lambda address: "QL-700"
    )
    panel.refresh_usb_devices()

    assert panel.address() == "/dev/usb/lp0"
    assert panel.model_id() == "QL-700"
    assert "nicht angeschlossen" not in panel._usb_combo.currentText()


def test_media_panel_keeps_the_stored_printer_when_several_are_attached(
    qapp, monkeypatch
):
    """Bei mehreren Geräten bleibt die gespeicherte Wahl stehen (Nutzer wählt)."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    monkeypatch.setattr(media_panel_module, "model_for_address", lambda address: None)
    panel = MediaPanel()
    panel.set_address("/dev/usb/lp1")

    monkeypatch.setattr(
        media_panel_module,
        "usb_printers",
        lambda: ["/dev/usb/lp0", "/dev/usb/lp2"],
    )
    panel.refresh_usb_devices()

    assert panel.address() == "/dev/usb/lp1"  # bleibt, bis der Nutzer waehlt
    assert "nicht angeschlossen" in panel._usb_combo.currentText()


def test_media_panel_offers_access_help_when_rights_are_missing(qapp, monkeypatch):
    """Ohne Rechte am Geraet steht im Panel, was zu tun ist."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "usb_access", lambda address: False)
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.access_allowed is False
    assert panel._access_button.isVisibleTo(panel)
    assert "Kein Zugriff" in panel._access_label.text()

    requested = []
    panel.usb_permission_requested.connect(lambda: requested.append(True))
    panel._access_button.click()
    assert requested == [True]


def test_media_panel_hides_access_help_when_the_device_works(qapp, monkeypatch):
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(media_panel_module, "usb_access", lambda address: True)
    panel = MediaPanel()

    panel._conn_buttons[CONNECTION_USB].setChecked(True)

    assert panel.access_allowed is True
    assert not panel._access_button.isVisibleTo(panel)


def test_media_panel_refresh_access_follows_the_new_state(qapp, monkeypatch):
    """Nach dem Einrichten der Regel verschwindet der Hinweis."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB, MediaPanel

    allowed = {"value": False}
    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: ["/dev/usb/lp1"])
    monkeypatch.setattr(
        media_panel_module, "usb_access", lambda address: allowed["value"]
    )
    panel = MediaPanel()
    panel._conn_buttons[CONNECTION_USB].setChecked(True)
    assert panel._access_button.isVisibleTo(panel)

    allowed["value"] = True
    assert panel.refresh_access() is True
    assert not panel._access_button.isVisibleTo(panel)


def test_media_panel_has_no_access_row_for_network(qapp):
    """Im Netzwerk gibt es keine Geraeterechte - also auch keinen Hinweis."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel.set_address("tcp://192.168.178.62:9100")

    assert panel.access_allowed is None
    assert not panel._access_button.isVisibleTo(panel)


def test_detect_button_only_works_where_readback_is_possible(qapp):
    """Band-Erkennung braucht einen Rueckkanal - nur USB hat einen."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    assert not panel._detect_button.isVisibleTo(panel)  # Netzwerk

    panel.set_address("usb://0x04f9:0x2042")
    assert panel._detect_button.isVisibleTo(panel)  # USB

    panel.set_address("tcp://192.168.178.62:9100")
    assert not panel._detect_button.isVisibleTo(panel)


def test_media_panel_finished_vs_content(qapp):
    from ql_editor.media_panel import MediaPanel
    from ql_editor.media import LengthMode

    panel = MediaPanel()
    panel._auto_check.setChecked(False)
    panel._length_spin.setValue(40)

    panel._mode_combo.setCurrentIndex(panel._mode_combo.findData(LengthMode.FINISHED.value))
    assert panel.canvas_size() == (554, 389)

    panel._mode_combo.setCurrentIndex(panel._mode_combo.findData(LengthMode.CONTENT.value))
    assert panel.canvas_size() == (554, 472)


def test_media_panel_model_switch_repopulates_bands(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    # 102 mm ist nur auf QL-1050/1060N erlaubt -> nicht bei QL-820NWB.
    assert panel._band_combo.findData("102") == -1
    idx = panel._model_combo.findData("QL-1050")
    panel._model_combo.setCurrentIndex(idx)
    assert panel._band_combo.findData("102") != -1


def test_media_panel_margins_from_feed_margin(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    margins = panel.margins()
    assert margins.left == margins.right == margins.top == margins.bottom == 0.0


# --------------------------------------------------------------------------- #
# Canvas
# --------------------------------------------------------------------------- #
def test_canvas_printable_rect_is_exact_width(qapp):
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    printable = canvas.printable_rect()
    assert printable.width() == 554
    assert printable.height() == 472
    # Die Szene selbst (Renderquelle) bleibt exakt die Designflaeche ...
    assert canvas.scene().sceneRect() == printable
    # ... der View zeigt ringsum eine Arbeitsflaeche (Scrollbereich).
    assert canvas.sceneRect().width() > printable.width()
    assert canvas.sceneRect().height() > printable.height()


def test_canvas_tape_rect_includes_side_border(qapp):
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    tape = canvas.tape_rect()
    assert tape.width() == pytest.approx(554 + 2 * label.side_border_dots)


def test_cut_offset_follows_the_last_printed_line(qapp):
    """Schnittversatz hinter der letzten Zeile: unten quer, links laengs."""
    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    assert printable.top() - tape.top() == pytest.approx(label.feed_margin)
    assert tape.bottom() - printable.bottom() == pytest.approx(
        label.feed_margin + media.CUT_OFFSET_DOTS
    )

    canvas.set_label(label, 472, orientation=media.Orientation.ALONG)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    assert printable.left() - tape.left() == pytest.approx(
        label.feed_margin + media.CUT_OFFSET_DOTS
    )
    assert tape.right() - printable.right() == pytest.approx(label.feed_margin)


def test_die_cut_length_matches_the_result_readout(qapp):
    """Die-cut: Laenge ist die Druckflaeche, wie die Ergebniszeile. Seitenkanten bleiben."""
    canvas = LabelCanvas()
    label = get_label("62x100")
    assert not label.is_endless
    assert label.dots_total[1] > label.dots_printable[1]
    canvas.set_label(label, label.height_dots)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    assert tape.top() == pytest.approx(printable.top())
    assert tape.bottom() == pytest.approx(printable.bottom())
    assert tape.left() == pytest.approx(printable.left() - label.side_border_dots)
    assert tape.right() == pytest.approx(printable.right() + label.side_border_dots)
    assert canvas._length_mm() == pytest.approx(media.dots_to_mm(label.height_dots))

    canvas.set_label(label, label.height_dots, orientation=media.Orientation.ALONG)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    assert tape.left() == pytest.approx(printable.left())
    assert tape.right() == pytest.approx(printable.right())
    assert tape.top() == pytest.approx(printable.top() - label.side_border_dots)
    assert tape.bottom() == pytest.approx(printable.bottom() + label.side_border_dots)


def test_tape_band_starts_after_the_full_label(qapp):
    """Grau erst hinter dem fertigen Etikett; das Etikett hat die volle Hoehe."""
    from PySide6.QtCore import QRectF

    canvas = LabelCanvas()
    label = get_label("50")
    canvas.set_label(label, 472)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    exposed = QRectF(-400, -200, 2000, 1600)
    band = canvas.tape_band_rect(exposed)
    extra = 2 * label.feed_margin + media.CUT_OFFSET_DOTS
    # ACROSS: volle Breite, Laenge inkl. Vorschub, Grau darunter.
    assert tape.left() == pytest.approx(printable.left() - label.side_border_dots)
    assert tape.width() == pytest.approx(printable.width() + 2 * label.side_border_dots)
    assert tape.height() == pytest.approx(printable.height() + extra)
    assert band.top() == pytest.approx(tape.bottom())
    assert band.left() == pytest.approx(tape.left())
    assert band.width() == pytest.approx(tape.width())
    assert band.bottom() == pytest.approx(exposed.bottom())

    canvas.set_label(label, 472, orientation=media.Orientation.ALONG)
    tape = canvas.tape_rect()
    printable = canvas.printable_rect()
    band = canvas.tape_band_rect(exposed)
    assert tape.height() == pytest.approx(label.width_dots + 2 * label.side_border_dots)
    assert tape.width() == pytest.approx(printable.width() + extra)
    assert band.left() == pytest.approx(tape.right())
    assert band.top() == pytest.approx(tape.top())
    assert band.height() == pytest.approx(tape.height())
    assert band.right() == pytest.approx(exposed.right())


def test_fitted_label_sits_at_the_top_left(qapp):
    """Wie im P-touch Editor: Etikett und Bandstreifen oben links, nicht mittig."""
    from ql_editor.canvas import FIT_MARGIN_MM
    from ql_editor.media import mm_to_dots

    canvas = LabelCanvas()
    canvas.resize(900, 600)
    canvas.show()
    qapp.processEvents()
    label = get_label("50")
    margin = mm_to_dots(FIT_MARGIN_MM)

    def origin_is_pinned():
        tape = canvas.tape_rect()
        corner = canvas.mapToScene(0, 0)
        assert corner.x() == pytest.approx(tape.left() - margin, abs=2)
        assert corner.y() == pytest.approx(tape.top() - margin, abs=2)
        # Die Mitte des Fensters liegt rechts unter der Etikettenmitte.
        view_center = canvas.mapToScene(canvas.viewport().rect().center())
        assert view_center.x() > tape.center().x()
        assert view_center.y() > tape.center().y()

    canvas.set_label(label, 472)
    canvas.fit_tape()
    qapp.processEvents()
    origin_is_pinned()

    canvas.set_label(label, 472, orientation=media.Orientation.ALONG)
    canvas.fit_tape()
    qapp.processEvents()
    origin_is_pinned()


def test_unprintable_edge_is_hatched_band_beyond_label_is_plain(qapp):
    """Kanten schraffiert; der graue Streifen hinter dem Etikett bleibt ohne Muster."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QColor, QImage, QPainter

    from ql_editor.canvas import TAPE_BAND_COLOR

    canvas = LabelCanvas()
    canvas.resize(900, 600)
    canvas.show()
    qapp.processEvents()
    label = get_label("50")
    assert label.side_border_dots > 0
    canvas.set_label(label, 472, orientation=media.Orientation.ALONG)
    canvas.fit_tape()
    qapp.processEvents()

    image = QImage(canvas.viewport().size(), QImage.Format.Format_RGB32)
    painter = QPainter(image)
    canvas.viewport().render(painter, QPoint())
    painter.end()

    tape = canvas.tape_rect()
    printable = canvas.printable_rect()

    def colors_at(scene_pt, radius):
        view = canvas.mapFromScene(scene_pt)
        found = set()
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                color = image.pixelColor(int(view.x()) + dx, int(view.y()) + dy)
                found.add((color.red(), color.green(), color.blue()))
        return found

    hatch = colors_at(QPointF(printable.center().x(), (tape.top() + printable.top()) / 2.0), 4)
    assert len(hatch) > 1
    # Schnittversatz hinter der letzten Zeile: bei ALONG links, noch Teil des Etiketts.
    cut = colors_at(
        QPointF((tape.left() + printable.left()) / 2.0, printable.center().y()),
        3,
    )
    assert len(cut) > 1
    # Vorschub vor der ersten Zeile: rechts, schmaler, ebenfalls schraffiert.
    lead = colors_at(
        QPointF((printable.right() + tape.right()) / 2.0, printable.center().y()),
        3,
    )
    assert len(lead) > 1
    plain = QColor(TAPE_BAND_COLOR)
    beyond = colors_at(QPointF(tape.right() + 30, tape.center().y()), 1)
    assert beyond == {(plain.red(), plain.green(), plain.blue())}
    # Vor dem Etikett kein Bandgrau - die Graustufe beginnt erst dahinter.
    before = colors_at(QPointF(tape.left() - 20, tape.center().y()), 1)
    assert (plain.red(), plain.green(), plain.blue()) not in before

    # Eigene Labelraender liegen in der bedruckbaren Flaeche und bleiben weiss.
    canvas.set_margins(4.0, 4.0, 4.0, 4.0)
    qapp.processEvents()
    painter = QPainter(image)
    canvas.viewport().render(painter, QPoint())
    painter.end()
    inner = canvas.margin_rect()
    printable = canvas.printable_rect()
    margin_sample = QPointF(printable.center().x(), (printable.top() + inner.top()) / 2.0)
    assert colors_at(margin_sample, 2) == {(255, 255, 255)}


def test_canvas_has_ruler_corner_with_unit(qapp):
    """Die Ecke zwischen den Linealen traegt die Einheit (wie P-touch Editor)."""
    from ql_editor.canvas import RULER_WIDTH, RulerCorner

    canvas = LabelCanvas()
    assert isinstance(canvas._corner, RulerCorner)
    assert canvas._corner.width() == RULER_WIDTH
    assert canvas._corner.height() == RULER_WIDTH


def test_canvas_size_labels_show_tape_width_and_length(qapp):
    """Bandbreite und Etikettenlaenge stehen am Etikett - wie im P-touch Editor."""
    from PySide6.QtCore import QLocale

    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    previous = QLocale()
    try:
        QLocale.setDefault(QLocale("de"))
        # Bandbreite der Rolle, fertige Laenge inkl. Vorschub (Ergebnis-Anzeige).
        assert canvas.size_labels() == ("50 mm", "47,0 mm")
        QLocale.setDefault(QLocale("en"))
        assert canvas.size_labels() == ("50 mm", "47.0 mm")
    finally:
        QLocale.setDefault(previous)


def test_canvas_size_labels_follow_the_orientation(qapp):
    """Bei ALONG tauschen die Achsen - die Angabe wandert mit."""
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472, orientation=media.Orientation.ALONG)
    horizontal, vertical = canvas.size_labels()
    assert vertical == "50 mm"
    assert horizontal.startswith("47")


def test_ruler_totals_match_the_label_size(qapp):
    """Was das Lineal beschriftet, ist die Groesse des Etiketts."""
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    finished = media.dots_to_mm(472 + 2 * get_label("50").feed_margin + media.CUT_OFFSET_DOTS)
    assert canvas._h_ruler.total_mm == pytest.approx(49.95, abs=0.05)
    assert canvas._v_ruler.total_mm == pytest.approx(finished, abs=0.05)
    canvas.set_label(get_label("50"), 472, orientation=media.Orientation.ALONG)
    assert canvas._h_ruler.total_mm == pytest.approx(finished, abs=0.05)
    assert canvas._v_ruler.total_mm == pytest.approx(49.95, abs=0.05)


def _shown_canvas(qapp, width=700, height=500):
    canvas = LabelCanvas()
    canvas.resize(width, height)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 472)
    canvas.fit_tape()
    qapp.processEvents()
    return canvas


def test_ruler_ticks_cover_the_whole_visible_length(qapp):
    """Das Lineal beschriftet die ganze Laenge - nicht nur das Etikett."""
    canvas = _shown_canvas(qapp)

    for ruler in (canvas._h_ruler, canvas._v_ruler):
        low, high = ruler._visible_mm_range()
        # Auch ausserhalb des Etiketts: davor negativ, dahinter ueber die
        # Etikettengroesse hinaus.
        assert low < 0
        assert high > ruler.total_mm


def test_ruler_label_step_follows_the_zoom(qapp):
    """Die Strich-Hierarchie haelt die Beschriftung auseinander (kein Geklebbe)."""
    from ql_editor.canvas import RULER_MIN_LABEL_PX, RULER_MIN_TICK_PX

    canvas = _shown_canvas(qapp)

    for zoom in (0.1, 0.3, 0.6, 1.0, 1.5, 3.0):
        canvas.zoom_by(zoom / canvas.transform().m11())
        qapp.processEvents()
        for ruler in (canvas._h_ruler, canvas._v_ruler):
            px_per_mm = ruler._px_per_mm()
            minor, medium, major = ruler._steps()
            assert minor * px_per_mm >= RULER_MIN_TICK_PX - 1e-6
            assert major * px_per_mm >= RULER_MIN_LABEL_PX - 1e-6
            # Beschriftete Striche liegen auf dem feinen Raster.
            assert abs(major / minor - round(major / minor)) < 1e-6
            if minor <= 1.0:
                assert medium == 5.0
            else:
                assert medium == major


def test_ruler_label_band_marks_the_label(qapp):
    """Grauer Streifen auf dem Lineal: so gross ist das Etikett."""
    from ql_editor.canvas import RULER_WIDTH

    canvas = _shown_canvas(qapp)

    for ruler, along_axis in ((canvas._h_ruler, "width"), (canvas._v_ruler, "height")):
        band = ruler.label_band_rect()
        assert not band.isEmpty()
        expected = ruler.total_mm * ruler._px_per_mm()
        if along_axis == "width":
            assert band.height() == RULER_WIDTH
            assert band.width() == pytest.approx(expected, abs=2)
            assert 0 <= band.left() < band.right() <= ruler.width()
        else:
            assert band.width() == RULER_WIDTH
            assert band.height() == pytest.approx(expected, abs=2)
            assert 0 <= band.top() < band.bottom() <= ruler.height()

    # Bei ALONG tauschen die Achsen - der Streifen wandert mit.
    across = canvas._h_ruler.label_band_rect().width()
    canvas.set_label(get_label("50"), 472, orientation=media.Orientation.ALONG)
    canvas.fit_tape()
    qapp.processEvents()
    assert canvas._h_ruler.label_band_rect().width() < across


def test_ruler_paints_when_zoomed_far_out(qapp):
    """Auch bei grobem Strich-Raster (stark herausgezoomt) sauber zeichnen."""
    canvas = _shown_canvas(qapp, width=600, height=400)
    canvas.zoom_by(0.15)
    qapp.processEvents()

    minor, _medium, major = canvas._h_ruler._steps()
    assert minor > 1.0  # nur noch zwei Strich-Ebenen
    assert _medium == major
    assert not canvas._h_ruler.grab().isNull()
    assert not canvas._v_ruler.grab().isNull()
    assert not canvas.grab().isNull()


def test_items_are_clamped_to_printable_area(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("x")
    canvas.add_item(item)

    printable = canvas.printable_rect()
    item.setPos(10_000, 10_000)
    br = item.sceneBoundingRect()
    assert br.right() <= printable.right() + 1
    assert br.bottom() <= printable.bottom() + 1

    item.setPos(-10_000, -10_000)
    br = item.sceneBoundingRect()
    assert br.left() >= printable.left() - 1
    assert br.top() >= printable.top() - 1


def test_canvas_item_serialization_roundtrip(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    canvas.add_item(TextItem("Hallo"))
    canvas.add_item(QRItem("https://example.org", 120))
    data = canvas.items_serialized()
    assert {d["type"] for d in data} == {"text", "qr"}

    canvas.clear_items()
    assert canvas.items_serialized() == []
    canvas.load_items(data)
    assert len(canvas.items_serialized()) == 2


def test_item_from_dict_unknown_type():
    with pytest.raises(ValueError):
        item_from_dict({"type": "nope"})


def test_barcode_item_invalid_value_raises(qapp):
    with pytest.raises(ValueError):
        BarcodeItem("not-a-number", "ean13")


def test_barcode_item_keeps_its_state_after_an_invalid_change(qapp):
    """Ungueltiger Inhalt aendert nichts - auch nicht den gespeicherten Wert.

    Frueher stand nach dem Fehler schon der neue Wert im Item, waehrend das
    Bild den alten zeigte; die gespeicherte Datei liess sich nicht mehr oeffnen.
    """
    from ql_editor.items import item_from_dict

    item = BarcodeItem("4006381333931", "ean13")
    width = item.pixmap().width()
    with pytest.raises(ValueError):
        item.set_value("abc")
    assert item.value == "4006381333931"
    assert item.pixmap().width() == width
    with pytest.raises(ValueError):
        item.set_symbology("ean8")  # 13 Stellen wuerden still auf 8 gekuerzt
    assert item.symbology == "ean13"
    assert item_from_dict(item.to_dict()).value == "4006381333931"


@pytest.mark.parametrize(
    ("symbology", "value", "printed"),
    [
        ("ean8", "4006381333931", "40063812"),  # gekuerzt
        ("ean13", "4006381333930", "4006381333931"),  # Pruefziffer ersetzt
        ("ean13", "40063813339312", "4006381333931"),  # zu lang
        ("upca", "036000291453", "036000291452"),  # Pruefziffer ersetzt
    ],
)
def test_barcode_rejects_input_that_would_print_differently(
    qapp, symbology, value, printed
):
    """Was python-barcode still umbaut, lehnen wir mit Hinweis ab."""
    with pytest.raises(ValueError, match=printed):
        BarcodeItem(value, symbology)


@pytest.mark.parametrize(
    ("symbology", "value"),
    [
        ("ean13", "400638133393"),  # 12 Stellen + Pruefziffer
        ("ean13", "4006381333931"),  # komplett mit richtiger Pruefziffer
        ("ean8", "1234567"),
        ("upca", "03600029145"),
        ("itf", "123"),  # fuehrende Null bei ungerader Stellenzahl
        ("code39", "abc"),  # Grossschreibung + Pruefzeichen
        ("code128", "Hallo Welt"),
        ("codabar", "A1234B"),
    ],
)
def test_barcode_accepts_regular_completions(qapp, symbology, value):
    BarcodeItem(value, symbology)


def test_inspector_reports_a_rejected_barcode_and_restores_the_field(qapp, tmp_path):
    """Ungueltige Eingabe: Meldung in der Statusleiste, Feld zeigt den alten Wert."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtWidgets import QApplication, QLineEdit

    win = _temp_window(qapp, tmp_path)
    item = BarcodeItem("4006381333931", "ean13")
    win._add_item(item, QPointF(10, 10))
    qapp.processEvents()
    item.setSelected(True)
    qapp.processEvents()
    field = next(
        e for e in win._inspector.findChildren(QLineEdit) if e.text() == item.value
    )
    field.setText("abc")
    field.editingFinished.emit()
    qapp.processEvents()
    qapp.processEvents()

    assert item.value == "4006381333931"
    assert "abc" in win.statusBar().currentMessage()
    assert win._history_before is None
    # Der alte Formularkoerper geht ueber deleteLater - erst aufraeumen lassen.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    fields = [e.text() for e in win._inspector.findChildren(QLineEdit)]
    assert "4006381333931" in fields and "abc" not in fields
    win.close()
    qapp.processEvents()


# --------------------------------------------------------------------------- #
# MainWindow
# --------------------------------------------------------------------------- #
def test_mainwindow_render_matches_canvas(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._media_panel._auto_check.setChecked(False)
    win._media_panel._length_spin.setValue(40)
    win._media_panel._mode_combo.setCurrentIndex(
        win._media_panel._mode_combo.findData("finished")
    )
    win._on_media_changed()
    win._add_text()
    win._recompute_canvas()
    image = win._current_render()
    assert image.width == 554
    assert image.height == win._canvas.height_dots


def test_canvas_print_preview_mode(qapp):
    from PIL import Image
    from PySide6.QtCore import QPointF

    from ql_editor.preview import binarize, to_qimage

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(40, 60)

    assert canvas.print_preview is False
    assert canvas.isInteractive() is True

    canvas.set_print_preview(True)
    assert canvas.print_preview is True
    assert canvas.isInteractive() is False
    assert canvas.selected_items() == []

    # Im Vorschau-Modus darf die Maus keine Items bewegen.
    before = QPointF(item.pos())
    center = item.sceneBoundingRect().center()
    _press(canvas, center)
    _drag_to(canvas, QPointF(center.x() + 50, center.y() + 40))
    _release(canvas, QPointF(center.x() + 50, center.y() + 40))
    assert item.pos() == before

    canvas.set_print_image(to_qimage(binarize(Image.new("L", (10, 10), 128))))
    assert canvas._print_image is not None

    canvas.set_print_preview(False)
    assert canvas.print_preview is False
    assert canvas.isInteractive() is True


def test_canvas_print_preview_paints(qapp):
    """Regression: das Zeichnen der Vorschau darf nicht abstuerzen."""
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(900, 650)
    win.show()
    qapp.processEvents()
    win._add_text()
    win._act_print_preview.setChecked(True)
    qapp.processEvents()

    pixmap = win._canvas.grab()
    assert not pixmap.isNull()


def test_canvas_print_preview_esc_requests_exit(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = _prepared_canvas(qapp)
    seen: list[int] = []
    canvas.print_preview_exit_requested.connect(lambda: seen.append(1))
    canvas.set_print_preview(True)

    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert seen == [1]

    # Ausserhalb des Vorschau-Modus darf Esc das Signal nicht ausloesen.
    canvas.set_print_preview(False)
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert seen == [1]


# --------------------------------------------------------------------------- #
# Inline-Bearbeitung / Interaktion
# --------------------------------------------------------------------------- #
def test_text_item_inline_editing(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("Hallo")
    canvas.add_item(item)
    assert item.is_editing is False
    item.start_editing()
    assert item.is_editing is True
    assert item.textCursor().hasSelection() is True  # Doppelklick markiert alles
    item.finish_editing()
    assert item.is_editing is False


def test_escape_ends_inline_editing(qapp):
    """Esc beendet die Bearbeitung (Qt laesst das Textfeld sonst offen)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo")
    canvas.add_item(item)
    item.start_editing()
    assert item.is_editing is True

    canvas.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert item.is_editing is False
    assert item.isSelected() is False


def test_new_text_is_empty_and_not_selected(qapp):
    """Doppelklick legt ein leeres Feld an - nichts ist markiert."""
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    item = win._new_text(QPointF(50, 50))
    qapp.processEvents()

    assert item.is_editing is True
    assert item.toPlainText() == ""
    assert item.textCursor().hasSelection() is False  # leeres Feld: nichts zu markieren
    # Sofort tippen schreibt den eigenen Text.
    item.textCursor().insertText("Hallo")
    assert item.toPlainText() == "Hallo"


def test_double_click_selects_existing_text(qapp):
    """Im offenen Text markiert der Doppelklick weiterhin alles."""
    from PySide6.QtCore import QEvent, QPointF, Qt

    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo Band", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    canvas.cancel_editing()

    click = item.mapToScene(QPointF(120, 20))
    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            click,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    cursor = item.textCursor()
    assert item.is_editing is True
    assert cursor.hasSelection() is True
    assert cursor.selectedText() == "Hallo Band"

    # Tippen ersetzt den markierten Text (Umbenennen-Verhalten).
    cursor.insertText("Neu")
    assert item.toPlainText() == "Neu"

    # Zweiter Doppelklick im offenen Feld markiert wieder alles.
    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            item.mapToScene(QPointF(20, 20)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert item.textCursor().hasSelection() is True
    assert item.textCursor().selectedText() == "Neu"


def test_empty_text_field_stays_when_editing_ends(qapp):
    """Wegklicken loescht ein leeres Textfeld nicht; es bleibt selektiert."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QSpinBox

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    item = win._new_text(QPointF(50, 50))
    qapp.processEvents()
    assert item.isSelected()
    assert item.is_editing is True
    win._canvas.cancel_editing()
    qapp.processEvents()
    assert item.scene() is not None
    assert item.toPlainText() == ""
    assert item.isSelected()
    assert item.is_editing is False
    size = next(
        spin
        for spin in win._inspector.findChildren(QSpinBox)
        if spin.minimum() == 4 and spin.maximum() == 2000
    )
    size.setFocus()
    qapp.processEvents()
    size.setValue(80)
    qapp.processEvents()
    assert item.scene() is not None
    assert item.font_pixel_size == 80
    assert item.isSelected()
    win.close()


def test_text_field_with_content_survives_editing(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    item = win._new_text(QPointF(50, 50))
    item.textCursor().insertText("Bleibt")
    win._canvas.cancel_editing()
    qapp.processEvents()
    texts = [i for i in win._canvas.scene().items() if isinstance(i, TextItem)]
    assert [i.toPlainText() for i in texts] == ["Bleibt"]


def _force_focus(window):
    """Fenster und Canvas wirklich fokussieren (offscreen sonst nicht).

    Genau dieser Fokus ist der Unterschied: ``setTextInteractionFlags`` nimmt
    einem **fokussierten** Feld den Fokus - ohne Fokus passiert nichts.
    """
    import warnings

    from PySide6.QtWidgets import QApplication

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        QApplication.setActiveWindow(window)
    window.setFocus()
    QApplication.processEvents()


def test_rendering_does_not_discard_a_new_text_field(qapp, tmp_path):
    """Regression: der Refresh nach dem Anlegen verwarf das leere Textfeld.

    ``LabelCanvas.suspend_text_caret`` blendet die Textmarke fuers Rendern aus.
    Frueher geschah das ueber die Interaktionsflags (``NoTextInteraction``) -
    das nimmt dem Feld den Fokus, beendet die Bearbeitung, und die App warf das
    gerade angelegte (noch leere) Feld sofort wieder weg. Jetzt blendet das
    Item die Marke selbst aus; Fokus und Bearbeitung bleiben unberuehrt.
    """
    from PySide6.QtCore import QPointF

    win = _temp_window(qapp, tmp_path)
    _force_focus(win)
    item = win._new_text(QPointF(60, 60))
    finished: list[bool] = []
    item.editing_finished.connect(lambda: finished.append(True))

    # Genau das, was der Refresh-Timer nach dem Anlegen tut.
    for _ in range(3):
        win._refresh_now()
        qapp.processEvents()

    assert finished == []
    assert item.is_editing is True
    assert item.scene() is not None
    assert win._canvas.scene().focusItem() is item


def test_suspend_text_caret_leaves_focus_and_editing_alone(qapp):
    """Textmarke ausblenden ohne die Interaktionsflags anzufassen."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(30, 30)
    item.start_editing()

    with canvas.suspend_text_caret():
        assert item.caret_hidden is True
        assert item.is_editing is True
        assert canvas.scene().focusItem() is item

    assert item.caret_hidden is False
    assert item.is_editing is True
    assert canvas.scene().focusItem() is item


def test_render_has_no_caret_and_no_selection(qapp):
    """Das Druckbild enthaelt weder Textmarke noch Auswahl."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(30, 30)
    canvas.cancel_editing()
    idle = canvas.render_printable()

    item.start_editing()  # markiert alles und setzt die Textmarke
    assert item.textCursor().hasSelection() is True
    editing = canvas.render_printable()

    assert editing.tobytes() == idle.tobytes()


def test_double_click_on_empty_canvas_requests_new_text(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt

    canvas = _prepared_canvas(qapp)
    seen: list[QPointF] = []
    canvas.text_requested.connect(seen.append)

    canvas.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            canvas,
            QPointF(200, 150),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert len(seen) == 1
    assert seen[0].x() == pytest.approx(200, abs=1)
    assert seen[0].y() == pytest.approx(150, abs=1)


def test_apply_resize_for_all_types(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPixmap

    from ql_editor.items import BarcodeItem, ImageItem, LineItem, QRItem, RectItem, ShapeItem

    qr = QRItem("x", 100)
    qr.apply_resize(200, 180)
    assert qr.boundingRect().width() == pytest.approx(180, abs=2)

    rect = RectItem()
    rect.apply_resize(150, 60)
    assert rect.rect().width() == pytest.approx(150)
    assert rect.rect().height() == pytest.approx(60)

    line = LineItem()
    line.apply_resize(120, 40)
    assert line.line().x2() == pytest.approx(120)

    image = ImageItem(QPixmap(40, 20))
    image.apply_resize(80, 40)
    assert image.sceneBoundingRect().width() == pytest.approx(80, abs=1)

    barcode = BarcodeItem("ABC123", "code128", height_dots=100)
    barcode.apply_resize(300, 200)
    assert barcode.boundingRect().height() == pytest.approx(200, abs=3)

    text = TextItem("Hi", font_pixel_size=40)
    text.apply_resize(300, 80)
    assert text.boundingRect().height() == pytest.approx(80, abs=8)

    shape = ShapeItem(QRectF(0, 0, 50, 50), "star")
    shape.apply_resize(160, 90)
    bounds = shape.path().boundingRect()
    assert bounds.width() == pytest.approx(160)
    assert bounds.height() == pytest.approx(90)


def test_canvas_handle_only_for_single_resizable_item(qapp):
    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    assert canvas._handle_scene_rect() is None

    first = TextItem("a")
    canvas.add_item(first)
    assert canvas._handle_scene_rect() is not None

    second = TextItem("b")
    canvas.add_item(second)  # Auswahl wechselt auf second
    first.setSelected(True)  # jetzt zwei ausgewaehlt
    assert canvas._handle_scene_rect() is None


def test_canvas_keyboard_delete_and_nudge(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    canvas = LabelCanvas()
    canvas.set_label(get_label("50"), 472)
    item = TextItem("x")
    canvas.add_item(item)
    item.setPos(50, 50)

    nudge = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(nudge)
    assert item.pos().x() == pytest.approx(51)

    delete = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(delete)
    assert canvas.items_serialized() == []


def test_inspector_shows_only_selected_kind(qapp):
    from ql_editor.inspector import InspectorPanel
    from ql_editor.items import QRItem

    inspector = InspectorPanel()
    inspector.set_item(TextItem("x"))
    assert inspector._title.text() == "Text"
    inspector.set_item(QRItem("y", 100))
    assert inspector._title.text() == "QR-Code"
    inspector.set_item(None)
    assert inspector._title.text() == "Nichts ausgewählt"


def test_inspector_puts_x_and_y_on_one_row(qapp):
    from PySide6.QtWidgets import QLabel, QSpinBox

    from ql_editor.inspector import InspectorPanel

    inspector = InspectorPanel()
    inspector.set_item(TextItem("Hallo"))

    labels = {label.text(): label for label in inspector.findChildren(QLabel)}
    assert "X" in labels
    assert "Y" in labels
    assert "X (Dots)" not in labels
    assert "Y (Dots)" not in labels
    assert labels["X"].parentWidget() is labels["Y"].parentWidget()

    xy_row = labels["X"].parentWidget()
    assert len(xy_row.findChildren(QSpinBox)) == 2
    assert "Drehung" in labels
    assert labels["Drehung"].parentWidget() is not xy_row


def test_inspector_rotation_field_is_left_aligned(qapp):
    from PySide6.QtWidgets import QLabel, QSpinBox

    from ql_editor.inspector import InspectorPanel

    inspector = InspectorPanel()
    inspector.resize(320, 700)
    inspector.show()
    inspector.set_item(TextItem("Hallo"))
    qapp.processEvents()

    labels = {label.text(): label for label in inspector.findChildren(QLabel)}
    x_label = labels["X"]
    rot_label = labels["Drehung"]
    xy_row = x_label.parentWidget()
    rot_row = rot_label.parentWidget()
    rot_spin = next(spin for spin in rot_row.findChildren(QSpinBox) if "°" in spin.suffix())

    assert rot_row.mapTo(inspector, rot_row.rect().topLeft()).x() == xy_row.mapTo(
        inspector, xy_row.rect().topLeft()
    ).x()
    assert rot_label.x() <= 2
    assert rot_spin.x() == rot_label.x() + rot_label.width() + 6
    assert rot_spin.width() <= rot_spin.sizeHint().width() + 4
    assert rot_row.width() - (rot_spin.x() + rot_spin.width()) > 40


def test_mainwindow_double_click_creates_text(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win._on_text_requested(QPointF(30, 30))
    texts = [i for i in win._canvas.scene().items() if isinstance(i, TextItem)]
    assert len(texts) == 1
    assert texts[0].is_editing is True


def test_mainwindow_print_preview_action(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    win._add_text()

    act = win._act_print_preview
    assert act.isCheckable()
    assert win._canvas.print_preview is False

    act.setChecked(True)
    assert win._canvas.print_preview is True
    assert win._canvas._print_image is not None
    assert not win._canvas._print_image.isNull()

    act.setChecked(False)
    assert win._canvas.print_preview is False
    assert win._canvas._print_image is None


def test_print_preview_exit_signal_unchecks_action(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._act_print_preview.setChecked(True)
    assert win._canvas.print_preview is True

    win._canvas.print_preview_exit_requested.emit()
    assert win._act_print_preview.isChecked() is False
    assert win._canvas.print_preview is False


# --------------------------------------------------------------------------- #
# Scrollen / Zoomen / Wheel-Guard
# --------------------------------------------------------------------------- #
def _wheel_event(modifiers, dy, dx=0, x=100, y=100):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    pos = QPointF(x, y)
    return QWheelEvent(
        pos, pos, QPoint(dx, dy), QPoint(dx, dy),
        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_wheel_guard_prevents_unfocused_change(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSpinBox, QVBoxLayout, QWidget

    from ql_editor.widgets import install_wheel_guard_recursive

    host = QWidget()
    layout = QVBoxLayout(host)
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    layout.addWidget(spin)
    install_wheel_guard_recursive(host)

    qapp.sendEvent(spin, _wheel_event(Qt.KeyboardModifier.NoModifier, 120))
    assert spin.value() == 10


def test_canvas_wheel_scrolls_instead_of_zooming(qapp):
    """Rad scrollt immer - zoomen nur mit Strg (oder Zoomgeste)."""
    import time

    from PySide6.QtCore import Qt

    canvas = LabelCanvas()
    canvas.resize(300, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 1400, refit=False)
    canvas.zoom_by(2.0)
    qapp.processEvents()

    vbar = canvas.verticalScrollBar()
    assert vbar.maximum() > 0
    before_zoom = canvas.transform().m11()
    before = vbar.value()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, -120))

    # Weiches Scrollen laeuft animiert -> kurz den Event-Loop bedienen.
    deadline = time.monotonic() + 2.0
    while vbar.value() == before and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert canvas.transform().m11() == pytest.approx(before_zoom)
    assert vbar.value() != before


def test_canvas_control_wheel_zooms(qapp):
    from PySide6.QtCore import Qt

    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    before = canvas.transform().m11()

    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.ControlModifier, 120))
    assert canvas.transform().m11() > before

    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.ControlModifier, -120))
    assert canvas.transform().m11() == pytest.approx(before)


def test_canvas_pinch_gesture_zooms(qapp):
    """Touchpad-Zoomgeste kommt als NativeGesture - die zoomt ohne Tastenzusatz."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QNativeGestureEvent

    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    before = canvas.transform().m11()

    event = QNativeGestureEvent(
        Qt.NativeGestureType.ZoomNativeGesture,
        _device(),
        2,
        QPointF(100, 100),
        QPointF(100, 100),
        QPointF(100, 100),
        0.2,
        QPointF(),
    )
    assert canvas.event(event) is True
    assert canvas.transform().m11() > before


def _device():
    from PySide6.QtGui import QPointingDevice

    return QPointingDevice.primaryPointingDevice()


def test_canvas_wheel_scrolls_when_zoomed(qapp):
    import time

    from PySide6.QtCore import Qt

    canvas = LabelCanvas()
    canvas.resize(300, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 1400, refit=False)
    canvas.zoom_by(2.0)
    qapp.processEvents()

    vbar = canvas.verticalScrollBar()
    assert vbar.maximum() > 0
    before = vbar.value()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, -120))

    # Weiches Scrollen laeuft animiert -> kurz den Event-Loop bedienen.
    deadline = time.monotonic() + 2.0
    while vbar.value() == before and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert vbar.value() != before


def test_smooth_scroll_area_wheel_scrolls_and_guard_keeps_value(qapp):
    """Rad ueber einem Feld scrollt das Panel, ohne den Feldwert zu aendern."""
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSpinBox, QVBoxLayout, QWidget

    from ql_editor.widgets import SmoothScrollArea, install_wheel_guard_recursive

    content = QWidget()
    layout = QVBoxLayout(content)
    first = QSpinBox()
    first.setRange(0, 100)
    first.setValue(10)
    layout.addWidget(first)
    others = []
    for _ in range(40):
        spin = QSpinBox()
        others.append(spin)
        layout.addWidget(spin)

    area = SmoothScrollArea()
    area.setWidgetResizable(True)
    area.resize(200, 120)
    area.setWidget(content)
    area.show()
    qapp.processEvents()
    install_wheel_guard_recursive(content)

    target = others[5]  # nicht das Fokus-Widget
    target.clearFocus()
    assert not target.hasFocus()

    vbar = area.verticalScrollBar()
    assert vbar.maximum() > 0
    before = vbar.value()
    qapp.sendEvent(target, _wheel_event(Qt.KeyboardModifier.NoModifier, -120))

    deadline = time.monotonic() + 2.0
    while vbar.value() == before and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert vbar.value() != before  # Panel scrollt
    assert target.value() == 0     # Feldwert bleibt


def test_side_panels_use_smooth_scroll_area(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.widgets import SmoothScrollArea

    win = MainWindow()
    assert len(win.findChildren(SmoothScrollArea)) >= 3


def test_open_panels_are_roomy(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import PANEL_WIDTH

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    assert win._left_panel.docked and win._right_panel.docked
    assert win._left_panel.visible_width == PANEL_WIDTH
    assert win._right_panel.visible_width == PANEL_WIDTH
    assert win._media_panel.minimumWidth() >= 200
    assert win._inspector.minimumWidth() >= 240


def test_set_label_height_change_keeps_zoom(qapp):
    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    canvas.zoom_by(2.0)
    zoom = canvas.transform().m11()
    canvas.set_label(get_label("50"), 900)  # nur Hoehe -> kein Refit
    assert canvas.transform().m11() == pytest.approx(zoom)


def test_canvas_zoom_actions_emit_zoom_changed(qapp):
    canvas = LabelCanvas()
    canvas.resize(600, 600)
    canvas.set_label(get_label("50"), 472)
    seen: list[float] = []
    canvas.zoom_changed.connect(seen.append)
    canvas.zoom_in()
    assert seen and seen[-1] > 0


# --------------------------------------------------------------------------- #
# Responsivitaet
# --------------------------------------------------------------------------- #
def test_canvas_refits_on_window_resize(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    zoom_big = win._canvas.transform().m11()

    win.resize(900, 620)
    qapp.processEvents()
    assert win._canvas._auto_fit is True
    assert win._canvas.transform().m11() < zoom_big


def test_manual_zoom_persists_across_resize(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    win._canvas.zoom_in()
    win._canvas.zoom_in()
    zoom = win._canvas.transform().m11()

    win.resize(900, 700)
    qapp.processEvents()
    assert win._canvas._auto_fit is False
    assert win._canvas.transform().m11() == pytest.approx(zoom)


def test_side_panels_are_scrollable(qapp):
    from PySide6.QtWidgets import QScrollArea

    from ql_editor.app import MainWindow

    win = MainWindow()
    # linkes Panel + Inspector + Vorschau/Druck = mindestens 3 Scrollbereiche
    assert len(win.findChildren(QScrollArea)) >= 3
    assert win.minimumWidth() <= 760


# --------------------------------------------------------------------------- #
# Moderne Maus-Bearbeitung: Verschieben, Groesse, Drehen, Snapping, Drag&Drop
# --------------------------------------------------------------------------- #
def _mouse_event(kind, canvas, scene_pos, button, buttons, mods):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    vp = canvas.mapFromScene(scene_pos)
    return QMouseEvent(kind, QPointF(vp), QPointF(vp), button, buttons, mods)


def _press(canvas, scene_pos, mods=None):
    from PySide6.QtCore import QEvent, Qt

    mods = Qt.KeyboardModifier.NoModifier if mods is None else mods
    canvas.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, canvas, scene_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)
    )


def _drag_to(canvas, scene_pos, mods=None):
    from PySide6.QtCore import QEvent, Qt

    mods = Qt.KeyboardModifier.NoModifier if mods is None else mods
    canvas.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, canvas, scene_pos, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, mods)
    )


def _release(canvas, scene_pos):
    from PySide6.QtCore import QEvent, Qt

    canvas.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, canvas, scene_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    )


def _prepared_canvas(qapp):
    canvas = LabelCanvas()
    canvas.resize(800, 700)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 472)
    return canvas


def test_canvas_has_eight_handles_and_rotate(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)

    points = canvas._handle_points(item)
    assert set(points) == {"nw", "n", "ne", "e", "se", "s", "sw", "w"}
    assert canvas._handle_at(points["se"]) == ("se", item)
    rotate = canvas._handle_at(canvas._rotate_handle_point(item))
    assert rotate is not None and rotate[0] == "rotate"


def test_canvas_drag_moves_item(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(40, 60)

    changed: list[int] = []
    canvas.items_changed.connect(lambda: changed.append(1))

    before = QPointF(item.pos())
    start = item.sceneBoundingRect().center()
    target = QPointF(start.x() + 60, start.y() + 40)
    _press(canvas, start)
    _drag_to(canvas, target)
    _release(canvas, target)

    assert item.pos().x() - before.x() == pytest.approx(60, abs=7)
    assert item.pos().y() - before.y() == pytest.approx(40, abs=7)
    assert changed == [1]


def test_canvas_resize_nw_keeps_opposite_corner(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(60, 80)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    b0 = item.sceneBoundingRect()
    nw = canvas._handle_points(item)["nw"]
    target = QPointF(nw.x() - 25, nw.y() - 18)
    _press(canvas, nw)
    _drag_to(canvas, target)
    _release(canvas, target)

    b1 = item.sceneBoundingRect()
    assert b1.right() == pytest.approx(b0.right(), abs=1.5)
    assert b1.bottom() == pytest.approx(b0.bottom(), abs=1.5)
    assert b1.width() > b0.width()


def test_canvas_resize_se_keeps_top_left(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(60, 80)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    b0 = item.sceneBoundingRect()
    se = canvas._handle_points(item)["se"]
    target = QPointF(se.x() + 20, se.y() + 15)
    _press(canvas, se)
    _drag_to(canvas, target)
    _release(canvas, target)

    b1 = item.sceneBoundingRect()
    assert b1.left() == pytest.approx(b0.left(), abs=0.5)
    assert b1.top() == pytest.approx(b0.top(), abs=0.5)
    assert b1.width() > b0.width()


def test_rotate_handle_shows_a_rotation_cursor(qapp):
    """Am Drehgriff zeigt der Zeiger ein Rotations-Symbol, kein Fadenkreuz.

    Qt hat keinen Rotations-Cursor - er wird wie die Icons gezeichnet und als
    Pixmap-Zeiger gesetzt (siehe :func:`ql_editor.icons.cursor`).
    """
    from PySide6.QtCore import QEvent, Qt

    from ql_editor import icons

    canvas = _prepared_canvas(qapp)
    item = TextItem("drehen", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(100, 120)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    canvas.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            canvas,
            canvas._rotate_handle_point(item),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    cursor = canvas.viewport().cursor()
    assert cursor.shape() == Qt.CursorShape.BitmapCursor
    assert cursor.pixmap().width() == icons.ROTATE_CURSOR_SIZE

    # Ueber einem Groessen-Griff bleibt es beim System-Cursor.
    east = canvas._handle_points(item)["e"]
    canvas.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            canvas,
            east,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert canvas.viewport().cursor().shape() == Qt.CursorShape.SizeHorCursor


def test_rotation_cursor_is_cached_and_unknown_names_raise(qapp):
    from ql_editor import icons

    assert icons.cursor("rotate") is icons.cursor("rotate")
    with pytest.raises(KeyError):
        icons.cursor("gibt-es-nicht")


def test_canvas_rotate_handle(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(100, 120)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    assert item.rotation() == pytest.approx(0)
    center = item.mapToScene(item.boundingRect().center())
    handle = canvas._rotate_handle_point(item)
    _press(canvas, handle)
    _drag_to(canvas, QPointF(center.x() + 120, center.y()))
    _release(canvas, QPointF(center.x() + 120, center.y()))

    assert item.rotation() == pytest.approx(90, abs=12)


def test_canvas_move_snaps_to_center_with_guide(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    other = TextItem("a", font_pixel_size=20)
    canvas.add_item(other)
    other.setPos(30, 30)

    item = TextItem("b", font_pixel_size=20)
    canvas.add_item(item)
    item.setPos(30, 200)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    center_y = canvas.printable_rect().center().y()
    start = item.sceneBoundingRect().center()
    target = QPointF(start.x(), center_y - 2)
    _press(canvas, start)
    _drag_to(canvas, target)
    axes = {axis for axis, _ in canvas._guides}
    _release(canvas, target)

    assert "h" in axes
    assert item.sceneBoundingRect().center().y() == pytest.approx(center_y, abs=0.6)


def test_canvas_small_drag_does_not_stick_to_own_edges(qapp):
    """Regression: ein bewegtess Item darf nicht an seiner eigenen alten Kante einrasten."""
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("x", font_pixel_size=30)
    canvas.add_item(item)
    item.setPos(120, 130)

    start = item.sceneBoundingRect().center()
    target = QPointF(start.x() + 3, start.y() + 3)
    _press(canvas, start)
    _drag_to(canvas, target)
    _release(canvas, target)

    assert item.pos().x() == pytest.approx(123, abs=1.5)
    assert item.pos().y() == pytest.approx(133, abs=1.5)


def test_mainwindow_drop_image_and_text(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDropEvent
    from PIL import Image as PILImage

    from ql_editor.app import MainWindow
    from ql_editor.items import ImageItem

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    canvas = win._canvas

    path = tmp_path / "bild.png"
    PILImage.new("RGB", (40, 30), "black").save(path)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ev = QDropEvent(
        QPointF(300, 200), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(ev)
    images = [i for i in canvas.scene().items() if isinstance(i, ImageItem)]
    assert len(images) == 1
    # am Mauszeiger zentriert
    center = images[0].sceneBoundingRect().center()
    assert center.x() == pytest.approx(canvas.mapToScene(300, 200).x(), abs=2)

    mime2 = QMimeData()
    mime2.setText("Hallo Welt")
    ev2 = QDropEvent(
        QPointF(120, 200), Qt.DropAction.CopyAction, mime2,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(ev2)
    texts = [i.to_dict().get("text") for i in canvas.scene().items() if getattr(i, "kind", None) == "text"]
    assert "Hallo Welt" in texts


def test_image_item_serialization_roundtrip(qapp):
    """Regression: Pixmap-Serialisierung muss ohne BytesIO funktionieren."""
    from PySide6.QtGui import QPixmap

    from ql_editor.items import ImageItem

    item = ImageItem(QPixmap(40, 20))
    data = item.to_dict()
    assert data["data_b64"]

    restored = item_from_dict(data)
    assert isinstance(restored, ImageItem)
    assert not restored.pixmap().isNull()
    assert restored.pixmap().width() == 40


def test_rotation_cannot_push_object_past_the_printable_edge(qapp, tmp_path):
    """Gedreht wird nur, solange das Objekt innerhalb der bedruckbaren Flaeche bleibt."""
    import math

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage

    from ql_editor.items import ImageItem

    path = tmp_path / "p.png"
    source = QImage(900, 1200, QImage.Format.Format_RGB32)
    source.fill(QColor("blue"))
    assert source.save(str(path))

    win = _temp_window(qapp, tmp_path)
    canvas = win._canvas
    item = ImageItem.from_file(str(path))
    win._add_item(item)
    item.apply_resize(260, 347)
    canvas.keep_inside_printable(item)
    assert canvas._inside_printable(item)

    center = item.mapToScene(item.boundingRect().center())
    for angle in range(0, 91, 10):
        canvas._op_item = item
        canvas._op_start_rotation = 0.0
        canvas._op_rotate_start = 0.0
        canvas._op_rotate_center = center
        rad = math.radians(angle)
        canvas._do_rotate(QPointF(center.x() + 100 * math.cos(rad), center.y() + 100 * math.sin(rad)))
        assert canvas._inside_printable(item), angle

    # Ein Bild, das die ganze Breite fuellt, ragt schon bei kleinem Winkel ueber den Rand.
    wide = ImageItem.from_file(str(path))
    win._add_item(wide)
    canvas.keep_inside_printable(wide)
    assert canvas._inside_printable(wide)
    center = wide.mapToScene(wide.boundingRect().center())
    canvas._op_item = wide
    canvas._op_start_rotation = 0.0
    canvas._op_rotate_start = 0.0
    canvas._op_rotate_center = center
    canvas._do_rotate(QPointF(center.x() + 100, center.y() + 100))
    assert canvas._inside_printable(wide)
    win.close()
    qapp.processEvents()


def test_webp_with_alpha_loads_and_stays_transparent_on_print(qapp, tmp_path):
    """WebP mit Transparenz: laden, und transparente Stellen werden auf dem Band weiss."""
    from PySide6.QtGui import QColor, QImage

    from ql_editor.items import ImageItem

    source = QImage(400, 200, QImage.Format.Format_ARGB32)
    source.fill(QColor(0, 0, 0, 0))
    for x in range(200, 400):
        for y in range(200):
            source.setPixelColor(x, y, QColor(0, 0, 0, 255))
    path = tmp_path / "alpha.webp"
    assert source.save(str(path), "WEBP", 90)

    item = ImageItem.from_file(str(path))
    assert item.pixmap().hasAlphaChannel()
    restored = ImageItem.from_dict(item.to_dict())
    assert restored.pixmap().hasAlphaChannel()
    before = item.pixmap().toImage()
    after = restored.pixmap().toImage()
    for x, y in ((10, 10), (300, 100), (399, 199)):
        assert after.pixelColor(x, y) == before.pixelColor(x, y)


def test_old_png_items_still_load(qapp):
    """Dateien aus aelteren Versionen (PNG in data_b64) bleiben lesbar."""
    import base64
    from io import BytesIO

    from PIL import Image

    from ql_editor.items import ImageItem

    buf = BytesIO()
    Image.new("RGBA", (30, 20), (255, 0, 0, 128)).save(buf, format="PNG")
    data = {
        "type": "image",
        "x": 0.0,
        "y": 0.0,
        "rotation": 0.0,
        "z": 0.0,
        "data_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "scale_x": 1.0,
        "scale_y": 1.0,
    }
    restored = ImageItem.from_dict(data)
    assert restored.pixmap().width() == 30
    assert restored.pixmap().hasAlphaChannel()


def test_large_image_is_downscaled_but_keeps_its_size(qapp, tmp_path):
    """Grosse Fotos werden beim Laden verkleinert; die Groesse im Etikett bleibt."""
    from PySide6.QtGui import QColor, QImage

    from ql_editor.items import IMAGE_MAX_SIDE_PX, ImageItem

    path = tmp_path / "big.png"
    source = QImage(6000, 4000, QImage.Format.Format_RGB32)
    source.fill(QColor("white"))
    assert source.save(str(path))

    item = ImageItem.from_file(str(path))
    assert max(item.pixmap().width(), item.pixmap().height()) == IMAGE_MAX_SIDE_PX
    rect = item.transform().mapRect(item.boundingRect())
    assert rect.width() == pytest.approx(6000, abs=5)
    assert rect.height() == pytest.approx(4000, abs=5)

    first = item.to_dict()["data_b64"]
    assert item.to_dict()["data_b64"] == first
    assert ImageItem.from_dict(item.to_dict()).pixmap().width() == IMAGE_MAX_SIDE_PX


# --------------------------------------------------------------------------- #
# Icons / icon-basiertes Menue
# --------------------------------------------------------------------------- #
def test_icons_render_for_all_names(qapp):
    from ql_editor import icons

    assert len(icons.available()) >= 15
    for name in icons.available():
        ic = icons.icon(name)
        assert not ic.isNull()
        assert not ic.pixmap(24, 24).isNull()
        if name.startswith("shape_"):
            assert name in icons.ICON_COLORS


def test_icon_unknown_name_raises(qapp):
    from ql_editor import icons

    with pytest.raises(KeyError):
        icons.icon("gibt-es-nicht")


def test_icon_color_is_configurable(qapp):
    from PySide6.QtGui import QColor

    from ql_editor import icons

    red = icons.icon("print", QColor("#ff0000"))
    assert not red.isNull()


def test_toolbar_has_undo_and_redo(qapp):
    """Rückgängig und Wiederholen liegen als eigene Icons in der Toolbar."""
    from PySide6.QtWidgets import QToolBar

    from ql_editor.app import MainWindow

    win = MainWindow()
    bar = win.findChild(QToolBar, "main_toolbar")
    actions = [a for a in bar.actions() if not a.isSeparator()]
    undo_at = actions.index(win._act_undo)
    redo_at = actions.index(win._act_redo)
    assert redo_at == undo_at + 1
    assert undo_at > actions.index(win._act_file_save)
    assert redo_at < actions.index(win._act_add_text)
    assert win._act_undo.toolTip() == "Rückgängig (Strg+Z)"
    assert win._act_redo.toolTip() == "Wiederholen (Strg+Umschalt+Z)"
    assert not win._act_undo.icon().isNull()
    assert not win._act_redo.icon().isNull()


def _visual_bottom_to_top(canvas):
    items = [item for item in canvas.scene().items() if hasattr(item, "to_dict")]
    items.reverse()
    return items


def _icon_bytes(action):
    from PySide6.QtGui import QImage

    image = action.icon().pixmap(24, 24).toImage()
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    return bytes(image.bits())


def test_stack_steps_one_place_and_extremes_keep_order(qapp, tmp_path):
    """Eine Ebene tauscht mit dem Nachbarn; Extrem legt die Gruppe ganz nach vorn oder hinten."""
    from PySide6.QtCore import QRectF

    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    bottom = RectItem(QRectF(0, 0, 40, 20))
    win._canvas.add_item(bottom)
    assert not win._act_forward.isEnabled()
    mid = RectItem(QRectF(10, 8, 40, 20))
    top = RectItem(QRectF(20, 16, 40, 20))
    win._canvas.add_item(mid)
    win._canvas.add_item(top)
    qapp.processEvents()
    assert _visual_bottom_to_top(win._canvas) == [bottom, mid, top]
    assert win._act_forward.icon().cacheKey() != win._act_front.icon().cacheKey()
    assert win._act_backward.icon().cacheKey() != win._act_back.icon().cacheKey()
    assert _icon_bytes(win._act_forward) != _icon_bytes(win._act_front)

    win._canvas.scene().clearSelection()
    bottom.setSelected(True)
    qapp.processEvents()
    assert win._act_forward.isEnabled() and win._act_back.isEnabled()
    win._act_forward.trigger()
    assert _visual_bottom_to_top(win._canvas) == [mid, bottom, top]
    assert bottom.zValue() < top.zValue()

    win._act_front.trigger()
    assert _visual_bottom_to_top(win._canvas) == [mid, top, bottom]
    assert win._undo_stack.undoText() == "Reihenfolge"

    win._act_back.trigger()
    assert _visual_bottom_to_top(win._canvas) == [bottom, mid, top]
    assert bottom.zValue() < mid.zValue() < top.zValue()

    win._canvas.scene().clearSelection()
    top.setSelected(True)
    qapp.processEvents()
    win._act_backward.trigger()
    assert _visual_bottom_to_top(win._canvas) == [bottom, top, mid]

    win._canvas.scene().clearSelection()
    bottom.setSelected(True)
    mid.setSelected(True)
    qapp.processEvents()
    win._act_front.trigger()
    assert _visual_bottom_to_top(win._canvas) == [top, bottom, mid]
    win.close()
    qapp.processEvents()


def test_snap_to_guides_applies_drag_snap_once(qapp, tmp_path):
    from ql_editor.canvas import SNAP_TOLERANCE_PX

    win = _temp_window(qapp, tmp_path)
    canvas = win._canvas
    item = TextItem("snap", font_pixel_size=40)
    canvas.add_item(item)
    left = canvas.printable_rect().left()
    tol = SNAP_TOLERANCE_PX / canvas._scale()
    box = item.sceneBoundingRect()
    item.moveBy((left + tol * 0.4) - box.left(), 80 - box.top())
    qapp.processEvents()
    before = item.sceneBoundingRect().left()
    assert before == pytest.approx(left + tol * 0.4, abs=0.6)
    win._act_snap_guides.trigger()
    qapp.processEvents()
    assert item.sceneBoundingRect().left() == pytest.approx(left, abs=0.6)
    assert win._undo_stack.undoText() == "An Hilfslinien ausrichten"
    assert canvas._guides
    assert any(axis == "v" and coord == pytest.approx(left, abs=0.6) for axis, coord in canvas._guides)
    win.close()
    qapp.processEvents()


def test_tab_switch_clears_the_rotate_hint(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    win._on_canvas_hint("Shift: 15°-Schritte")
    assert win._hint_label.isVisible()
    assert win._hint_label.text() == "Shift: 15°-Schritte"
    win._on_file_new()
    qapp.processEvents()
    assert win._hint_label.text() == ""
    assert not win._hint_label.isVisible()
    win.close()
    qapp.processEvents()


def test_toolbar_has_align_dropdown_before_front(qapp, tmp_path):
    """Ausrichten liegt als Dropdown in der Toolbar, vor Vordergrund und Hintergrund."""
    from PySide6.QtWidgets import QToolButton, QToolBar

    win = _temp_window(qapp, tmp_path)
    bar = win.findChild(QToolBar, "main_toolbar")
    button = win.findChild(QToolButton, "align_button")
    assert button is not None
    assert button.menu().actions() == [
        win._act_align_left,
        win._act_align_hcenter,
        win._act_align_right,
        win._act_align_top,
        win._act_align_vcenter,
        win._act_align_bottom,
    ]
    actions = bar.actions()
    button_at = next(i for i, a in enumerate(actions) if bar.widgetForAction(a) is button)
    assert button_at < actions.index(win._act_front) < actions.index(win._act_back)
    win.close()
    qapp.processEvents()


def test_shapes_menu_and_inspector_smoke(qapp, tmp_path):
    """Formen-Menue legt ShapeItem an; Inspector zeigt Form-Felder."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QComboBox, QToolButton

    from ql_editor.items import ShapeItem

    win = _temp_window(qapp, tmp_path)
    button = win.findChild(QToolButton, "shape_button")
    assert button is not None
    menu_labels = [action.text() for action in button.menu().actions() if action.text()]
    assert "Linie" in menu_labels
    assert "Rahmen" in menu_labels
    assert "Stern" in menu_labels
    assert "Ellipse" in menu_labels
    context_labels = [
        action.text()
        for action in win._build_context_menu(QPointF(10, 10)).actions()
        if action.text()
    ]
    for label in menu_labels:
        assert label in context_labels
    insert_labels = [
        action.text()
        for action in win._menu_button.menu().actions()
        if action.text()
    ]
    for label in ("Ellipse", "Dreieck", "Stern", "Pfeil rechts", "Pfeil links", "Doppelpfeil"):
        assert label in insert_labels

    win._add_shape("star")
    shapes = [item for item in win._canvas.scene().items() if isinstance(item, ShapeItem)]
    assert len(shapes) == 1
    assert shapes[0].shape_name == "star"

    win._inspector.set_item(shapes[0], allow_red=True)
    qapp.processEvents()
    assert win._inspector._title.text() == "Form"
    shape_combos = [
        combo
        for combo in win._inspector.findChildren(QComboBox)
        if combo.findData("star") >= 0 and combo.findData("ellipse") >= 0
    ]
    assert shape_combos
    assert shape_combos[0].currentData() == "star"
    win.close()
    qapp.processEvents()


def test_toolbar_is_icon_only(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolBar, QWidgetAction

    from ql_editor.app import MainWindow

    win = MainWindow()
    bar = win.findChild(QToolBar)
    assert bar is not None
    assert bar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    actions = [
        a
        for a in bar.actions()
        if not a.isSeparator() and not isinstance(a, QWidgetAction)
    ]
    assert actions
    assert all(not a.icon().isNull() for a in actions)
    assert all(a.toolTip() for a in actions)


def test_no_menu_bar_but_hamburger_menu(qapp):
    """Es gibt keine Menueleiste mehr - alle Befehle liegen im Hamburger-Menue."""
    from PySide6.QtWidgets import QMenuBar, QToolBar, QToolButton, QWidgetAction

    from ql_editor.app import MainWindow

    win = MainWindow()
    assert win.findChild(QMenuBar) is None

    button = win.findChild(QToolButton, "main_menu_button")
    assert button is not None
    assert not button.icon().isNull()
    assert button.toolTip()
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup

    menu = button.menu()
    assert menu is not None
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert items
    assert all(not a.icon().isNull() for a in items)
    # Die Befehle werden mit der Toolbar geteilt (dieselben QActions).
    bar_actions = {
        a
        for a in win.findChild(QToolBar).actions()
        if not a.isSeparator() and not isinstance(a, QWidgetAction)
    }
    assert bar_actions <= set(items)


def test_menu_actions_have_icons(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    menu = win._menu_button.menu()
    assert menu is not None
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert len(items) >= 10
    assert all(not a.icon().isNull() for a in items)


def test_context_menu_has_icons(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    menu = win._build_context_menu(QPointF(10, 10))
    items = [a for a in menu.actions() if not a.isSeparator()]
    assert items
    assert all(not a.icon().isNull() for a in items)


# --------------------------------------------------------------------------- #
# Ausrichtung (quer / laengs des Bandes)
# --------------------------------------------------------------------------- #
def test_panel_orientation_buttons_and_actions(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    across, along = panel.orientation_actions()
    assert (across.text(), along.text()) == ("Quer zum Band", "Längs des Bandes")
    assert across.isCheckable() and along.isCheckable()
    assert across.isChecked() and not along.isChecked()
    assert panel.orientation() is media.Orientation.ACROSS
    assert [b.isChecked() for b in panel._orientation_buttons] == [True, False]

    panel._orientation_buttons[1].click()
    assert panel.orientation() is media.Orientation.ALONG
    assert along.isChecked() and not across.isChecked()
    assert [b.isChecked() for b in panel._orientation_buttons] == [False, True]


def test_orientation_actions_are_exclusive_and_emit(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[str] = []
    panel.changed.connect(lambda: seen.append(panel.orientation().value))
    across, along = panel.orientation_actions()

    along.trigger()
    across.trigger()
    assert seen == ["along", "across"]
    assert across.isChecked() and not along.isChecked()


def test_orientation_ignored_when_unchanged(qapp):
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    seen: list[str] = []
    panel.changed.connect(lambda: seen.append("changed"))
    panel.set_orientation(media.Orientation.ACROSS)
    assert seen == []
    # Auch bei bereits gewaehlter Ausrichtung bleiben die Aktionen synchron.
    panel.orientation_actions()[1].setChecked(True)
    panel.set_orientation(media.Orientation.ACROSS)
    assert panel.orientation_actions()[0].isChecked() is True


def test_toolbar_has_no_orientation_buttons(qapp):
    from PySide6.QtWidgets import QToolBar

    from ql_editor.app import MainWindow

    win = MainWindow()
    bar = win.findChild(QToolBar)
    texts = {a.text() for a in bar.actions()}
    assert "Quer zum Band" not in texts
    assert "Längs des Bandes" not in texts


def test_orientation_is_in_hamburger_menu(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    items = win._menu_button.menu().actions()
    for act in win._media_panel.orientation_actions():
        assert act in items


def test_orientation_changes_canvas_and_print_image(qapp):
    from PySide6.QtCore import QSize

    from ql_editor.app import MainWindow

    win = MainWindow()
    # Auflösung festnageln: hier geht es um die Ausrichtung, nicht um 600 dpi.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_STANDARD.key)
    )
    win._new_text()
    win._canvas.cancel_editing()
    label = win._media_panel.label
    length = win._canvas.length_dots
    assert win._canvas.printable_rect().size().toSize() == QSize(label.width_dots, length)

    win._media_panel.set_orientation(media.Orientation.ALONG)
    assert win._canvas.printable_rect().size().toSize() == QSize(length, label.width_dots)
    assert win._canvas.length_dots == length
    # Das Druckbild ist in beiden Ausrichtungen bandbreit.
    assert win._for_print().size == (label.width_dots, length)

    # Im 600-dpi-Modus rendert die Designflaeche doppelt so fein - in beiden
    # Ausrichtungen, denn die feine Achse ist immer die Bandlaufrichtung.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    assert win._for_print().size == (label.width_dots * 2, length * 2)
    win._media_panel.set_orientation(media.Orientation.ACROSS)
    assert win._for_print().size == (label.width_dots * 2, length * 2)


def test_orientation_moves_side_border_to_tape_edges(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    label = win._media_panel.label
    win._media_panel.set_orientation(media.Orientation.ALONG)
    tape = win._canvas.tape_rect()
    printable = win._canvas.printable_rect()
    # Letzte Druckzeile ist links (ROTATE_90), dort sitzt der Schnittversatz.
    assert tape.top() == pytest.approx(-label.side_border_dots)
    assert tape.bottom() == pytest.approx(printable.bottom() + label.side_border_dots)
    assert printable.left() - tape.left() == pytest.approx(label.feed_margin + media.CUT_OFFSET_DOTS)
    assert tape.right() - printable.right() == pytest.approx(label.feed_margin)


def test_print_preview_image_stays_canvas_aligned(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win._new_text()
    win._canvas.cancel_editing()
    win._media_panel.set_orientation(media.Orientation.ALONG)
    win._act_print_preview.setChecked(True)
    win._refresh_now()
    image = win._canvas._print_image
    assert image is not None
    rect = win._canvas.printable_rect()
    assert image.width() == int(rect.width())
    assert image.height() == int(rect.height())


def test_panel_result_shows_real_content_length(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.items import TextItem

    win = MainWindow()
    win._add_item(TextItem("Hallo Welt", font_pixel_size=90))
    win._canvas.cancel_editing()
    assert "Inhalt" in win._media_panel._size_label.text()
    across = win._media_panel._size_label.text()

    win._media_panel.set_orientation(media.Orientation.ALONG)
    along = win._media_panel._size_label.text()
    assert across != along
    assert win._media_panel._act_orient_along.isChecked()


# --------------------------------------------------------------------------- #
# Seitenpanels: einklappen, Pfeil im Panel, Hover-Overlay
# --------------------------------------------------------------------------- #
def test_panel_actions_are_in_the_menu_not_the_toolbar(qapp):
    from PySide6.QtWidgets import QToolBar

    from ql_editor.app import MainWindow

    win = MainWindow()
    for act in (win._act_panel_left, win._act_panel_right):
        assert act.isCheckable() and act.isChecked()
        assert not act.icon().isNull()
        assert act.toolTip()
    assert win._act_panel_left.shortcut().toString() == "Ctrl+B"
    assert win._act_panel_right.shortcut().toString() == "Ctrl+Shift+B"

    bar = win.findChild(QToolBar)
    bar_actions = [a for a in bar.actions() if not a.isSeparator()]
    assert win._act_panel_left not in bar_actions
    assert win._act_panel_right not in bar_actions
    # Erreichbar bleiben sie im Hamburger-Menue (Shortcut-Wege).
    assert win._act_panel_left in win._menu_button.menu().actions()
    assert win._act_panel_right in win._menu_button.menu().actions()


def test_panel_arrow_sits_in_the_panel(qapp):
    from PySide6.QtCore import QPointF

    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    qapp.processEvents()

    for panel in (win._left_panel, win._right_panel):
        assert panel._button.parent() is panel
        assert not panel._button.icon().isNull()
        # Der Pfeil liegt im schmalen Streifen, nicht im Inhalt.
        assert panel._strip_rect().contains(QPointF(panel._button.geometry().center()))
        assert panel._button.toolTip()
        assert panel.content.isVisible()


def test_collapsing_panel_gives_canvas_more_room(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1300, 700)
    win.show()
    qapp.processEvents()
    before = win._canvas.width()

    win._act_panel_right.setChecked(False)
    win._right_panel.finish_animation()
    qapp.processEvents()
    assert win._right_panel.docked is False
    assert win._right_panel.visible_width == STRIP_WIDTH
    assert win._canvas.width() > before
    # Der Streifen mit Pfeil bleibt erreichbar, der Inhalt ist weg.
    assert win._right_panel.width() == STRIP_WIDTH
    assert win._right_panel._button.isVisible()
    assert not win._right_panel.content.isVisible()

    win._act_panel_right.setChecked(True)
    win._right_panel.finish_animation()
    qapp.processEvents()
    assert win._right_panel.docked is True
    assert win._right_panel.content.isVisible()


def test_both_panels_can_be_collapsed(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1300, 700)
    win.show()
    qapp.processEvents()

    win._act_panel_left.setChecked(False)
    win._act_panel_right.setChecked(False)
    win._left_panel.finish_animation()
    win._right_panel.finish_animation()
    qapp.processEvents()
    # Der Canvas bekommt alles bis auf die beiden Streifen.
    assert win._canvas.width() == pytest.approx(win.width() - 2 * STRIP_WIDTH, abs=4)


def _settle(win, qapp) -> None:
    """Panel-Animationen beenden und die Ereignisse durchlaufen lassen."""
    win._left_panel.finish_animation()
    win._right_panel.finish_animation()
    qapp.processEvents()


def test_small_window_hides_right_panel_then_left(qapp):
    """Kleines Fenster: erst verschwindet der Inspector, dann die Bandauswahl."""
    from ql_editor.app import MainWindow
    from ql_editor.panels import AUTO_COLLAPSE_LEFT_PX, AUTO_COLLAPSE_RIGHT_PX

    win = MainWindow()
    win.resize(AUTO_COLLAPSE_RIGHT_PX + 120, 700)
    win.show()
    _settle(win, qapp)
    assert win._left_panel.docked is True
    assert win._right_panel.docked is True

    # Erste Stufe: nur das rechte Panel.
    win.resize(AUTO_COLLAPSE_RIGHT_PX - 120, 700)
    _settle(win, qapp)
    assert win._right_panel.docked is False
    assert win._right_panel.auto_collapsed is True
    assert win._left_panel.docked is True
    assert win._right_panel.content.isVisible() is False

    # Zweite Stufe: auch das linke.
    win.resize(AUTO_COLLAPSE_LEFT_PX - 120, 700)
    _settle(win, qapp)
    assert win._left_panel.docked is False
    assert win._left_panel.auto_collapsed is True

    # Wieder breit: beide kommen zurueck, die Nutzerwahl war nie weg.
    win.resize(AUTO_COLLAPSE_RIGHT_PX + 120, 700)
    _settle(win, qapp)
    assert win._left_panel.docked is True
    assert win._right_panel.docked is True
    assert win._act_panel_left.isChecked() is True
    assert win._act_panel_right.isChecked() is True


def test_auto_collapse_keeps_user_setting(qapp):
    """Die Automatik aendert die Nutzerwahl (Menue, Settings) nicht."""
    from ql_editor.app import MainWindow
    from ql_editor.panels import AUTO_COLLAPSE_LEFT_PX

    win = MainWindow()
    win.resize(AUTO_COLLAPSE_LEFT_PX - 120, 700)
    win.show()
    _settle(win, qapp)

    assert win._right_panel.docked is False
    assert win._right_panel.wanted_docked is True
    assert win._act_panel_right.isChecked() is True


def test_auto_collapsed_panel_still_peeks(qapp):
    """Der Streifen bleibt bedienbar: Hover klappt das Panel ueber dem Canvas auf."""
    from ql_editor.app import MainWindow
    from ql_editor.panels import AUTO_COLLAPSE_LEFT_PX, STRIP_WIDTH

    win = MainWindow()
    win.resize(AUTO_COLLAPSE_LEFT_PX - 120, 700)
    win.show()
    _settle(win, qapp)
    canvas_width = win._canvas.width()

    win._right_panel.set_hovered(True)
    _settle(win, qapp)
    assert win._right_panel.peeking is True
    assert win._right_panel.content.isVisible() is True
    assert win._canvas.width() == canvas_width
    assert win._right_panel.canvas_reserved == STRIP_WIDTH


def test_panel_arrow_opens_auto_collapsed_panel(qapp):
    """Im kleinen Fenster oeffnet der Pfeil das Panel trotzdem - bewusst."""
    from ql_editor.app import MainWindow
    from ql_editor.panels import AUTO_COLLAPSE_RIGHT_PX

    win = MainWindow()
    win.resize(AUTO_COLLAPSE_RIGHT_PX - 120, 700)
    win.show()
    _settle(win, qapp)
    assert win._right_panel.docked is False

    win._right_panel._button.click()
    _settle(win, qapp)
    assert win._right_panel.docked is True
    assert win._right_panel.auto_collapsed is False
    # Die Nutzerwahl bleibt aus: der Pfeil ist kein "Panel abschalten".
    assert win._right_panel.wanted_docked is True


def test_window_keeps_canvas_minimum_width(qapp):
    """Das Fenster laesst sich nicht schmaler ziehen, als Canvas und Streifen brauchen."""
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    qapp.processEvents()
    floor = win._canvas.minimumWidth() + 2 * STRIP_WIDTH
    assert win._host.minimumWidth() == floor

    win.resize(120, 200)
    qapp.processEvents()
    assert win._host.width() >= floor


def test_panel_arrow_keeps_action_in_sync(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()

    win._left_panel._button.click()
    qapp.processEvents()
    assert win._left_panel.docked is False
    assert win._act_panel_left.isChecked() is False

    win._left_panel._button.click()
    qapp.processEvents()
    assert win._left_panel.docked is True
    assert win._act_panel_left.isChecked() is True


def test_collapsed_panel_peeks_over_canvas_on_hover(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.panels import STRIP_WIDTH

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    win._act_panel_left.setChecked(False)
    win._left_panel.finish_animation()
    qapp.processEvents()
    canvas_width = win._canvas.width()
    expanded = win._left_panel.reserved_width

    # Hover auf dem Streifen -> Panel klappt als Overlay auf.
    win._left_panel.set_hovered(True)
    win._left_panel.finish_animation()
    qapp.processEvents()
    assert win._left_panel.peeking is True
    assert win._left_panel.visible_width == expanded
    assert win._left_panel.content.isVisible()
    # Der Canvas behaelt seine Breite: Overlay statt Verschieben.
    assert win._canvas.width() == canvas_width
    assert win._left_panel.canvas_reserved == STRIP_WIDTH

    # Mauszeiger weg -> wieder einklappen.
    win._left_panel.set_hovered(False)
    win._left_panel.finish_animation()
    qapp.processEvents()
    assert win._left_panel.peeking is False
    assert win._left_panel.visible_width == STRIP_WIDTH
    assert not win._left_panel.content.isVisible()


def test_docked_panel_does_not_peek(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    qapp.processEvents()
    win._left_panel.set_hovered(True)
    assert win._left_panel.peeking is False
    assert win._left_panel.docked is True


def test_panel_visibility_is_persisted(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    qapp.processEvents()
    win._act_panel_right.setChecked(False)
    win.close()
    qapp.processEvents()

    again = MainWindow()
    # Bewusst breit: die Automatik fuer schmale Fenster soll hier nicht greifen.
    again.resize(1300, 800)
    again.show()
    qapp.processEvents()
    assert again._right_panel.docked is False
    assert again._act_panel_right.isChecked() is False
    assert again._left_panel.docked is True


def test_panel_icons_available(qapp):
    from ql_editor import icons

    names = icons.available()
    assert "panel_left" in names and "panel_right" in names


# --------------------------------------------------------------------------- #
# Arbeitsflaeche (Pasteboard) / Scrollen
# --------------------------------------------------------------------------- #
def _wide_image(width: int = 2400, height: int = 1600):
    from PySide6.QtGui import QPixmap

    from ql_editor.items import ImageItem

    pixmap = QPixmap(width, height)
    pixmap.fill()
    return ImageItem(pixmap)


def test_pasteboard_gives_scrollbars_for_oversized_items(qapp):
    canvas = _prepared_canvas(qapp)
    assert canvas.printable_rect().width() == 554
    # Arbeitsflaeche ist groesser als die Designflaeche -> es gibt etwas zu scrollen.
    assert canvas.sceneRect().width() > canvas.printable_rect().width()

    item = _wide_image()
    canvas.add_item(item)
    item.apply_resize(900, 600)
    canvas._update_pasteboard()
    qapp.processEvents()

    assert canvas.horizontalScrollBar().maximum() > 0
    assert canvas.sceneRect().contains(item.sceneBoundingRect())


def test_pasteboard_keeps_visible_area_when_items_grow(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    canvas.zoom_by(2.0)
    qapp.processEvents()
    before = canvas.mapToScene(canvas.viewport().rect().center())

    item = _wide_image()
    canvas.add_item(item)
    item.apply_resize(1200, 800)
    canvas._update_pasteboard()
    qapp.processEvents()

    after = canvas.mapToScene(canvas.viewport().rect().center())
    assert after.x() == pytest.approx(before.x(), abs=1.5)
    assert after.y() == pytest.approx(before.y(), abs=1.5)


def test_wheel_does_not_zoom_while_whole_label_is_visible(qapp):
    """Auch wenn das ganze Etikett sichtbar ist, zoomt das Rad nicht mehr."""
    from PySide6.QtCore import Qt

    canvas = _prepared_canvas(qapp)
    canvas.fit_tape()
    qapp.processEvents()

    before = canvas.transform().m11()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.NoModifier, 120))
    assert canvas.transform().m11() == pytest.approx(before)


def test_wheel_scrolls_horizontally_when_zoomed_in(qapp):
    from PySide6.QtCore import Qt

    canvas = _prepared_canvas(qapp)
    canvas.zoom_by(4.0)
    qapp.processEvents()

    bar = canvas.horizontalScrollBar()
    before_zoom = canvas.transform().m11()
    canvas.wheelEvent(_wheel_event(Qt.KeyboardModifier.ShiftModifier, -120))
    assert canvas.transform().m11() == pytest.approx(before_zoom)
    assert bar.maximum() > 0


def test_mainwindow_shrinks_oversized_image_to_tape_width(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    item = _wide_image(2400, 1600)
    win._add_item(item)

    width, height = win._canvas.item_scene_size(item)
    assert width == pytest.approx(win._canvas.printable_rect().width(), abs=1.0)
    assert height < width
    # Seitenverhaeltnis bleibt erhalten (1600/2400 = 2/3).
    assert height == pytest.approx(width * 1600 / 2400, rel=0.01)


def test_small_image_is_not_enlarged(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    item = _wide_image(120, 80)
    win._add_item(item)
    width, height = win._canvas.item_scene_size(item)
    # Pixmap-Items haben in Qt einen halben Dot "Rand" pro Seite.
    assert width == pytest.approx(120.0, abs=1.5)
    assert height == pytest.approx(80.0, abs=1.5)


# --------------------------------------------------------------------------- #
# Groesse / Drehung (auch bei gedrehten und skalierten Objekten)
# --------------------------------------------------------------------------- #
def test_resize_keeps_anchor_for_rotated_item(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("gedreht", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(150, 120)
    item.setRotation(30)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    anchor_before = canvas._handle_points(item)["nw"]
    se = canvas._handle_points(item)["se"]
    target = QPointF(se.x() + 40, se.y() + 30)
    _press(canvas, se)
    _drag_to(canvas, target)
    _release(canvas, target)

    anchor_after = canvas._handle_points(item)["nw"]
    assert anchor_after.x() == pytest.approx(anchor_before.x(), abs=0.5)
    assert anchor_after.y() == pytest.approx(anchor_before.y(), abs=0.5)


def test_resize_of_scaled_image_uses_scene_units(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = _wide_image(1000, 800)
    canvas.add_item(item)
    item.setPos(40, 40)
    item.setTransform(item.transform().scale(0.2, 0.2))  # angezeigte Breite 200
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    width_before = canvas.item_scene_size(item)[0]
    assert width_before == pytest.approx(200, abs=1)

    e = canvas._handle_points(item)["e"]
    target = QPointF(e.x() + 50, e.y())
    _press(canvas, e)
    _drag_to(canvas, target)
    _release(canvas, target)

    # Der Zeiger wanderte 50 Szenen-Dots -> das Bild waechst um 50 Dots,
    # nicht um 50 * 1/0.2.
    assert canvas.item_scene_size(item)[0] == pytest.approx(width_before + 50, abs=1.5)


def test_rotation_keeps_item_center(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("mitte", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(200, 150)
    canvas._scene.clearSelection()
    item.setSelected(True)
    qapp.processEvents()

    center_before = item.mapToScene(item.boundingRect().center())
    handle = canvas._rotate_handle_point(item)
    _press(canvas, handle)
    _drag_to(canvas, QPointF(center_before.x() + 120, center_before.y() + 60))
    _release(canvas, QPointF(center_before.x() + 120, center_before.y() + 60))

    center_after = item.mapToScene(item.boundingRect().center())
    assert item.rotation() != pytest.approx(0)
    assert center_after.x() == pytest.approx(center_before.x(), abs=0.5)
    assert center_after.y() == pytest.approx(center_before.y(), abs=0.5)


def test_rotation_snaps_to_15_degrees(qapp):
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("rastet", font_pixel_size=40)
    canvas.add_item(item)
    canvas._scene.clearSelection()
    item.setSelected(True)
    center = item.mapToScene(item.boundingRect().center())
    canvas._op_item = item
    canvas._op_rotate_center = center
    canvas._op_rotate_start = -math.pi / 2
    canvas._op_start_rotation = 0.0
    canvas._do_rotate(QPointF(center.x() + 100, center.y() + 17), snap=True)
    # atan2(17, 100) = 9.65 Grad, plus 90 Grad Startversatz -> auf 105 Grad gerastet.
    assert item.rotation() % 15 == pytest.approx(0, abs=0.01)
    assert item.rotation() == pytest.approx(105, abs=0.01)


def _rotate_to(canvas, item, degrees_from_start: float, *, snap: bool = False) -> float:
    from PySide6.QtCore import QPointF

    center = item.mapToScene(item.boundingRect().center())
    canvas._op_item = item
    canvas._op_rotate_center = center
    canvas._op_rotate_start = 0.0
    canvas._op_start_rotation = 0.0
    rad = math.radians(degrees_from_start)
    canvas._do_rotate(QPointF(center.x() + 100 * math.cos(rad), center.y() + 100 * math.sin(rad)), snap=snap)
    return item.rotation()


def test_rotation_is_free_except_sticky_90_degree_detent(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("sticky", font_pixel_size=40)
    canvas.add_item(item)
    canvas._rotate_detent = None
    assert _rotate_to(canvas, item, 85.0) == pytest.approx(85, abs=0.01)
    assert _rotate_to(canvas, item, 89.5) == pytest.approx(90)
    # Haftet weiter, solange der Winkel nicht deutlich weggedreht wird ...
    assert _rotate_to(canvas, item, 96.0) == pytest.approx(90)
    # ... danach wieder frei.
    assert _rotate_to(canvas, item, 99.0) == pytest.approx(99, abs=0.01)
    assert _rotate_to(canvas, item, 45.0) == pytest.approx(45, abs=0.01)


def _hover(canvas, scene_pos):
    from PySide6.QtCore import QEvent, Qt

    canvas.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            canvas,
            scene_pos,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def test_rotate_hint_follows_rotate_handle_hover(qapp):
    """Idle-Hover ueber dem Drehgriff, und nach der Geste weg vom Griff."""
    from PySide6.QtCore import QPointF

    canvas = _prepared_canvas(qapp)
    item = TextItem("hint", font_pixel_size=40)
    canvas.add_item(item)
    canvas._scene.clearSelection()
    item.setSelected(True)
    received: list[str] = []
    canvas.hint_changed.connect(received.append)
    handle = canvas._rotate_handle_point(item)
    _hover(canvas, handle)
    assert canvas._hint == "Shift: 15°-Schritte"
    assert received == ["Shift: 15°-Schritte"]
    _press(canvas, handle)
    away = QPointF(handle.x() + 400, handle.y() + 400)
    _release(canvas, away)
    assert "15°" not in canvas._hint


def test_rotate_handle_distance_is_constant_for_scaled_items(qapp):
    canvas = _prepared_canvas(qapp)
    item = _wide_image(1000, 800)
    canvas.add_item(item)
    item.setTransform(item.transform().scale(0.1, 0.1))
    qapp.processEvents()

    top = canvas._handle_points(item)["n"]
    handle = canvas._rotate_handle_point(item)
    distance = math.hypot(handle.x() - top.x(), handle.y() - top.y())
    assert distance == pytest.approx(ROTATE_OFFSET_PX / canvas.transform().m11(), rel=0.01)


def test_handle_cursor_follows_rotation(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("cursor", font_pixel_size=40)
    canvas.add_item(item)

    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeHorCursor
    item.setRotation(90)
    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeVerCursor
    item.setRotation(45)
    assert canvas._cursor_for_handle(item, "e") == Qt.CursorShape.SizeFDiagCursor


def test_rotated_item_is_clamped_by_rotated_hull(qapp):
    canvas = _prepared_canvas(qapp)
    item = TextItem("Rand", font_pixel_size=40)
    canvas.add_item(item)
    item.setRotation(90)
    item.setPos(10_000, 10_000)

    printable = canvas.printable_rect()
    hull = item.sceneBoundingRect()
    assert hull.right() <= printable.right() + 1
    assert hull.bottom() <= printable.bottom() + 1


def test_inspector_image_size_in_millimetres(qapp):
    from PySide6.QtWidgets import QDoubleSpinBox

    from ql_editor.inspector import InspectorPanel
    from ql_editor.media import DOTS_PER_MM

    inspector = InspectorPanel()
    item = _wide_image(600, 300)
    inspector.set_item(item)

    fields = inspector.findChildren(QDoubleSpinBox)
    assert len(fields) == 2
    width, height = fields
    assert width.value() == pytest.approx(600 / DOTS_PER_MM, abs=0.2)
    assert height.value() == pytest.approx(300 / DOTS_PER_MM, abs=0.2)

    # Breite aendern: Hoehe folgt im Seitenverhaeltnis (2:1).
    width.setValue(30.0)
    assert inspector._image_size(item)[0] == pytest.approx(30 * DOTS_PER_MM, abs=1.5)
    assert inspector._image_size(item)[1] == pytest.approx(15 * DOTS_PER_MM, abs=1.5)
    assert height.value() == pytest.approx(15.0, abs=0.2)

    # Hoehe aendern: Breite folgt.
    height.setValue(10.0)
    assert inspector._image_size(item)[1] == pytest.approx(10 * DOTS_PER_MM, abs=1.5)
    assert width.value() == pytest.approx(20.0, abs=0.2)


# --------------------------------------------------------------------------- #
# Druckbild: Auswahl, Textmarke und Qualitaetsoptionen
# --------------------------------------------------------------------------- #
def _render_1bit(canvas):
    """Druckbild der Szene als 1-bit-Vergleichsbytes (ohne Drucker)."""
    from ql_editor.preview import binarize

    return binarize(canvas.render_printable()).tobytes()


def _sample_items():
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPixmap

    from ql_editor.items import ImageItem, LineItem, RectItem

    pixmap = QPixmap(120, 80)
    pixmap.fill(QColor("black"))
    return {
        "Text": TextItem("Test 123", font_pixel_size=40),
        "Image": ImageItem(pixmap),
        "Barcode": BarcodeItem("123456789"),
        "QR": QRItem("test", 120),
        "Line": LineItem(0, 0, 200, 0, width_px=3),
        "Rect": RectItem(QRectF(0, 0, 200, 80)),
    }


def test_selection_is_not_printed(qapp):
    """Qt malt bei Auswahl einen gestrichelten Rahmen - der darf nicht drucken."""
    canvas = _prepared_canvas(qapp)
    for kind, item in _sample_items().items():
        canvas.clear_items()
        canvas.add_item(item)
        item.setPos(40, 40)
        canvas.scene().clearSelection()
        without = _render_1bit(canvas)
        item.setSelected(True)
        with_selection = _render_1bit(canvas)
        assert with_selection == without, f"{kind}: Auswahl landet im Druckbild"


def test_text_caret_is_not_printed(qapp):
    """Weder Einfuegemarke noch Textmarkierung duerfen im Etikett landen."""
    from PySide6.QtGui import QTextCursor

    canvas = _prepared_canvas(qapp)
    item = TextItem("Bearbeitung 123", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    qapp.processEvents()

    item.start_editing()
    qapp.processEvents()
    cursor = item.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    item.setTextCursor(cursor)
    editing = _render_1bit(canvas)
    item.finish_editing()
    qapp.processEvents()
    assert editing == _render_1bit(canvas)


def test_text_editing_survives_rendering(qapp):
    """Das Rendern blendet die Textmarke nur kurz aus - Bearbeitung bleibt."""
    canvas = _prepared_canvas(qapp)
    item = TextItem("Hallo", font_pixel_size=40)
    canvas.add_item(item)
    item.setPos(40, 40)
    item.start_editing()
    qapp.processEvents()
    cursor = item.textCursor()
    cursor.clearSelection()
    cursor.movePosition(cursor.MoveOperation.End)
    item.setTextCursor(cursor)

    canvas.render_printable()

    assert item.is_editing is True
    assert item.hasFocus() is True
    assert item.textCursor().position() == 5


def test_print_preview_zooms_to_1_1_and_restores(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1200, 700)
    win.show()
    qapp.processEvents()
    before = win._canvas.transform().m11()
    assert before < 1.0  # eingepasst

    win._act_print_preview.setChecked(True)
    qapp.processEvents()
    assert win._canvas.transform().m11() == pytest.approx(1.0)
    assert win._canvas.print_preview is True

    win._act_print_preview.setChecked(False)
    qapp.processEvents()
    assert win._canvas.transform().m11() == pytest.approx(before)
    assert win._canvas.print_preview is False


def test_zoom_label_hints_when_preview_is_not_1_1(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qapp.processEvents()
    win._act_print_preview.setChecked(True)
    qapp.processEvents()
    win._canvas.zoom_out()
    qapp.processEvents()
    assert "1:1" in win._zoom_label.text()
    win._act_print_preview.setChecked(False)
    qapp.processEvents()
    assert "1:1" not in win._zoom_label.text()


def test_zoom_100_action_exists(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qapp.processEvents()
    assert not win._act_zoom_100.icon().isNull()
    assert win._act_zoom_100.shortcut().toString() == "Ctrl+1"
    win._canvas.zoom_by(0.5)
    win._act_zoom_100.trigger()
    assert win._canvas.transform().m11() == pytest.approx(1.0)


def test_ink_readout_tracks_threshold(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win._add_item(TextItem("Tinte", font_pixel_size=40), None)
    win._canvas.cancel_editing()
    win._refresh_now()

    win._threshold_spin.setValue(20)
    win._refresh_now()
    low = win._ink_label.text()
    win._threshold_spin.setValue(95)
    win._refresh_now()
    high = win._ink_label.text()
    assert low.startswith("Tinte:") and high.startswith("Tinte:")
    assert float(low.split()[1].replace(",", ".")) < float(high.split()[1].replace(",", "."))


def _temp_window(qapp, tmp_path):
    """MainWindow mit Einstellungen in einer temporaeren INI-Datei.

    Damit bleiben Tests unabhaengig von den echten Nutzer-Einstellungen (und
    schreiben auch nicht hinein).
    """
    from PySide6.QtCore import QSettings

    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    win = MainWindow(settings=settings)
    win.show()
    qapp.processEvents()
    return win


def test_startup_keeps_the_stored_printer_address(qapp, tmp_path, monkeypatch):
    """Beim Start darf die gespeicherte Adresse nicht ueberschrieben werden.

    Das Setzen des Modells loest ``changed`` aus, und der Slot schreibt den
    gerade gueltigen Zustand zurueck. Wurde die Adresse erst danach gelesen,
    stand dort schon der Standarddrucker: die USB-Auswahl war beim naechsten
    Start weg (und das Modell, das daran haengt, gleich mit).
    """
    from PySide6.QtCore import QSettings

    from ql_editor import media_panel as media_panel_module
    from ql_editor.app import MainWindow
    from ql_editor.media_panel import CONNECTION_USB
    from ql_editor.settings import AppSettings

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda: [])
    monkeypatch.setattr(media_panel_module, "model_for_address", lambda address: None)
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.model = "QL-700"
    settings.address = "/dev/usb/lp1"

    win = MainWindow(settings=settings)
    qapp.processEvents()

    assert win._media_panel.address() == "/dev/usb/lp1"
    assert win._media_panel.connection() == CONNECTION_USB
    assert win._media_panel.model_id() == "QL-700"
    assert settings.address == "/dev/usb/lp1"


def _wait_startup_discovery(win, qapp):
    """Startsuche zu Ende laufen lassen (der Netzwerk-Thread ist asynchron)."""
    worker = win._network_worker
    if worker is not None and worker.isRunning():
        worker.wait(3000)
    qapp.processEvents()


def _hold_network_discovery(monkeypatch, printers):
    """Suche anhalten, bis der Test den Fensterstand geaendert hat.

    Liefert ``(entered, release)``. ``release.set()`` laesst die Treffer zu.
    """
    import threading

    from ql_editor import app as app_module

    entered = threading.Event()
    release = threading.Event()

    def _discover(*_args, **_kwargs):
        entered.set()
        release.wait(5)
        return printers

    monkeypatch.setattr(app_module, "discover_network_printers", _discover)
    return entered, release


def test_fresh_start_leaves_the_network_field_empty(qapp, tmp_path):
    """Ohne gespeicherte Adresse bleibt das Netzwerkfeld leer.

    ``192.168.178.62`` war frueher die fest eingebaute Adresse. Sie darf weder
    als Default noch als Platzhalter im Feld stehen.
    """
    from ql_editor.media_panel import CONNECTION_NETWORK
    from ql_editor.printer import DEFAULT_ADDRESS

    assert DEFAULT_ADDRESS == ""
    win = _temp_window(qapp, tmp_path)
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.connection() == CONNECTION_NETWORK
    assert win._media_panel.address() == ""
    assert win._media_panel._network_host == ""
    assert "192.168.178.62" not in win._media_panel._net_combo.currentText()
    assert "*" not in win.windowTitle()
    win.close()
    qapp.processEvents()


def test_startup_selects_the_saved_network_printer(qapp, tmp_path, monkeypatch):
    """Der letzte Netzwerkdrucker wird gewaehlt, wenn die Suche ihn findet."""
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [
        discovery.NetworkPrinter(host="192.0.2.10", model_id="QL-700"),
        discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB"),
    ]
    monkeypatch.setattr(
        app_module, "discover_network_printers", lambda *args, **kwargs: printers
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.address() == "tcp://192.0.2.20:9100"
    assert win._media_panel.model_id() == "QL-820NWB"
    assert settings.address == "tcp://192.0.2.20:9100"
    assert "*" not in win.windowTitle()
    win.close()
    qapp.processEvents()


def test_startup_falls_back_to_the_first_network_printer(qapp, tmp_path, monkeypatch):
    """Fehlt der letzte Drucker in den Treffern, gilt der erste."""
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [
        discovery.NetworkPrinter(host="192.0.2.10", model_id="QL-700"),
        discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB"),
    ]
    monkeypatch.setattr(
        app_module, "discover_network_printers", lambda *args, **kwargs: printers
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.address = "tcp://192.0.2.99:9100"

    win = MainWindow(settings=settings)
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.address() == "tcp://192.0.2.10:9100"
    assert win._media_panel.model_id() == "QL-700"
    assert settings.address == "tcp://192.0.2.10:9100"
    # Der Wechsel steht im Panel, nicht in der Statuszeile: die bleibt frei
    # fuer „Etikett geöffnet“.
    assert win._media_panel._net_hint.text() == (
        "Gespeicherten Drucker nicht gefunden, 192.0.2.10 gewählt."
    )
    assert "nicht gefunden" not in win.statusBar().currentMessage()
    win.close()
    qapp.processEvents()


def test_startup_picks_the_first_network_printer_without_a_saved_one(
    qapp, tmp_path, monkeypatch
):
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [
        discovery.NetworkPrinter(host="192.0.2.10", model_id="QL-800"),
        discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-700"),
    ]
    monkeypatch.setattr(
        app_module, "discover_network_printers", lambda *args, **kwargs: printers
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )

    win = MainWindow(settings=settings)
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.address() == "tcp://192.0.2.10:9100"
    assert settings.connection == "network"
    win.close()
    qapp.processEvents()


def test_startup_keeps_a_saved_address_when_the_network_is_empty(qapp, tmp_path):
    """Ohne Treffer bleibt die letzte Adresse stehen - sie ist nicht erfunden."""
    from ql_editor.media_panel import CONNECTION_NETWORK

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.0.2.20")
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    _wait_startup_discovery(again, qapp)

    assert again._media_panel.connection() == CONNECTION_NETWORK
    assert again._media_panel.address() == "tcp://192.0.2.20:9100"
    again.close()
    qapp.processEvents()


def test_startup_selects_the_saved_usb_printer(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from ql_editor import media_panel as media_panel_module
    from ql_editor.app import MainWindow
    from ql_editor.media_panel import CONNECTION_USB
    from ql_editor.settings import AppSettings

    monkeypatch.setattr(
        media_panel_module,
        "usb_printers",
        lambda devices=None: ["/dev/usb/lp0", "/dev/usb/lp1"],
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = CONNECTION_USB
    settings.address = "/dev/usb/lp1"

    win = MainWindow(settings=settings)
    qapp.processEvents()

    assert win._media_panel.connection() == CONNECTION_USB
    assert win._media_panel.address() == "/dev/usb/lp1"
    assert settings.connection == CONNECTION_USB
    win.close()
    qapp.processEvents()


def test_startup_falls_back_to_the_first_usb_printer(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from ql_editor import media_panel as media_panel_module
    from ql_editor.app import MainWindow
    from ql_editor.media_panel import CONNECTION_USB
    from ql_editor.settings import AppSettings

    monkeypatch.setattr(
        media_panel_module,
        "usb_printers",
        lambda devices=None: ["/dev/usb/lp0", "/dev/usb/lp2"],
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = CONNECTION_USB
    settings.address = "/dev/usb/lp1"

    win = MainWindow(settings=settings)
    qapp.processEvents()

    assert win._media_panel.connection() == CONNECTION_USB
    assert win._media_panel.address() == "/dev/usb/lp0"
    assert settings.address == "/dev/usb/lp0"
    win.close()
    qapp.processEvents()


def test_usb_connection_is_restored_when_nothing_is_plugged_in(
    qapp, tmp_path, monkeypatch
):
    """Der letzte Anschluss bleibt USB, auch wenn gerade kein Geraet da ist."""
    from ql_editor import media_panel as media_panel_module
    from ql_editor.media_panel import CONNECTION_USB

    monkeypatch.setattr(media_panel_module, "usb_printers", lambda devices=None: [])
    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_connection(CONNECTION_USB)
    win._on_media_changed()
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    qapp.processEvents()

    assert again._media_panel.connection() == CONNECTION_USB
    assert again._media_panel.address() == ""
    assert again._settings.connection == CONNECTION_USB
    again.close()
    qapp.processEvents()


def test_startup_keeps_a_loaded_label_until_the_user_adapts(
    qapp, tmp_path, monkeypatch
):
    """Ein geoeffnetes Etikett behaelt Modell und Raender, bis man zustimmt."""
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery, document
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB")]
    entered, release = _hold_network_discovery(monkeypatch, printers)
    choices = []

    def _ask(_parent, *, title, text, on_choice):
        choices.append((title, text))
        on_choice("keep")

    monkeypatch.setattr(app_module, "ask_label_printer", _ask)
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-700"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    assert entered.wait(3)
    win._media_panel._margin_spins["top"].setValue(9.0)
    path = tmp_path / "etikett.qlx"
    document.save(path, document.build(win._media_panel.media_state(), []))
    win.open_path(str(path))
    release.set()
    _wait_startup_discovery(win, qapp)

    assert choices
    assert "QL-700" in choices[0][1]
    assert "QL-820NWB" in choices[0][1]
    assert win._media_panel.model_id() == "QL-700"
    assert win._media_panel.margins().top == pytest.approx(9.0)
    assert "*" not in win.windowTitle()
    win.close()
    qapp.processEvents()


def test_startup_adapt_label_is_an_undo_step(qapp, tmp_path, monkeypatch):
    """Wer anpasst, bekommt einen Undo-Schritt und den Stern."""
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery, document
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB")]
    entered, release = _hold_network_discovery(monkeypatch, printers)
    monkeypatch.setattr(
        app_module,
        "ask_label_printer",
        lambda *_args, on_choice, **_kwargs: on_choice("adapt"),
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-700"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    assert entered.wait(3)
    win._media_panel._margin_spins["top"].setValue(9.0)
    path = tmp_path / "etikett.qlx"
    document.save(path, document.build(win._media_panel.media_state(), []))
    win.open_path(str(path))
    release.set()
    _wait_startup_discovery(win, qapp)
    qapp.processEvents()

    assert win._media_panel.model_id() == "QL-820NWB"
    assert win._media_panel.margins().top != pytest.approx(9.0)
    assert "*" in win.windowTitle()
    win._undo_stack.undo()
    qapp.processEvents()
    assert win._media_panel.model_id() == "QL-700"
    assert win._media_panel.margins().top == pytest.approx(9.0)
    win.close()
    qapp.processEvents()


def test_startup_does_not_ask_when_the_model_already_matches(
    qapp, tmp_path, monkeypatch
):
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery, document
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB")]
    entered, release = _hold_network_discovery(monkeypatch, printers)
    asked = []
    monkeypatch.setattr(
        app_module,
        "ask_label_printer",
        lambda *_args, **_kwargs: asked.append(True),
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-820NWB"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    assert entered.wait(3)
    path = tmp_path / "etikett.qlx"
    document.save(path, document.build(win._media_panel.media_state(), []))
    win.open_path(str(path))
    release.set()
    _wait_startup_discovery(win, qapp)

    assert asked == []
    assert win._media_panel.model_id() == "QL-820NWB"
    assert "*" not in win.windowTitle()
    win.close()
    qapp.processEvents()


def test_startup_ignores_an_address_typed_while_searching(
    qapp, tmp_path, monkeypatch
):
    """Eine IP aus der Suchsekunde wird nicht durch den ersten Treffer ersetzt."""
    from PySide6.QtCore import QSettings

    from ql_editor import discovery
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [
        discovery.NetworkPrinter(host="192.0.2.10", model_id="QL-820NWB"),
        discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-700"),
    ]
    entered, release = _hold_network_discovery(monkeypatch, printers)
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-700"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    assert entered.wait(3)
    win._media_panel.set_network_host("192.0.2.77")
    release.set()
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.address() == "tcp://192.0.2.77:9100"
    assert win._media_panel.model_id() == "QL-700"
    win.close()
    qapp.processEvents()


def test_startup_ignores_a_usb_switch_while_searching(qapp, tmp_path, monkeypatch):
    """Wer waehrend der Suche auf USB geht, behaelt Anschluss und Modell."""
    from PySide6.QtCore import QSettings

    from ql_editor import discovery
    from ql_editor import media_panel as media_panel_module
    from ql_editor.app import MainWindow
    from ql_editor.media_panel import CONNECTION_USB
    from ql_editor.settings import AppSettings

    printers = [discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB")]
    entered, release = _hold_network_discovery(monkeypatch, printers)
    monkeypatch.setattr(media_panel_module, "usb_printers", lambda devices=None: [])
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-700"
    settings.address = "tcp://192.0.2.20:9100"

    win = MainWindow(settings=settings)
    assert entered.wait(3)
    win._media_panel._conn_buttons[CONNECTION_USB].setChecked(True)
    release.set()
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.connection() == CONNECTION_USB
    assert win._media_panel.model_id() == "QL-700"
    win.close()
    qapp.processEvents()


def test_startup_matches_the_same_host_on_another_port(qapp, tmp_path, monkeypatch):
    """Gleicher Host, anderer Port: dieser Drucker, nicht der erste Treffer."""
    from PySide6.QtCore import QSettings

    from ql_editor import app as app_module
    from ql_editor import discovery
    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    printers = [
        discovery.NetworkPrinter(host="192.0.2.10", model_id="QL-700"),
        discovery.NetworkPrinter(host="192.0.2.20", model_id="QL-820NWB"),
    ]
    monkeypatch.setattr(
        app_module, "discover_network_printers", lambda *args, **kwargs: printers
    )
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    settings.model = "QL-820NWB"
    settings.address = "tcp://192.0.2.20:9101"

    win = MainWindow(settings=settings)
    _wait_startup_discovery(win, qapp)

    assert win._media_panel.address() == "tcp://192.0.2.20:9100"
    assert win._media_panel.model_id() == "QL-820NWB"
    assert win._media_panel._net_hint.text() == "Gleicher Drucker, Port 9100."
    assert "Port" not in win.statusBar().currentMessage()
    win.close()
    qapp.processEvents()


def test_language_switch_does_not_search_again(qapp, tmp_path, monkeypatch):
    """Der Neuaufbau uebernimmt die Auswahl und sucht nicht noch einmal."""
    from ql_editor import app as app_module
    from ql_editor.i18n import set_language

    calls = {"n": 0}

    def _discover(*_args, **_kwargs):
        calls["n"] += 1
        return []

    monkeypatch.setattr(app_module, "discover_network_printers", _discover)
    win = _temp_window(qapp, tmp_path)
    _wait_startup_discovery(win, qapp)
    assert calls["n"] == 1

    try:
        win.switch_language("en")
        qapp.processEvents()
        new = app_module._current_window
        _wait_startup_discovery(new, qapp)
        assert calls["n"] == 1
        assert new._network_worker is None
        new.close()
        qapp.processEvents()
    finally:
        set_language("de")


def test_close_drops_the_network_worker_before_delete_later(qapp, tmp_path):
    """Schliessen leert den Such-Thread, bevor deleteLater die Huelle abbaut.

    Ohne das bleibt ``_network_worker`` gesetzt, und die naechste Fixture
    ruft ``isRunning()`` auf einem schon geloeschten C++-Objekt auf.
    """
    from PySide6.QtCore import QSettings

    from ql_editor.app import MainWindow
    from ql_editor.settings import AppSettings

    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.connection = "network"
    win = MainWindow(settings=settings)
    assert win._network_worker is not None
    win.close()
    qapp.processEvents()
    assert win._network_worker is None


def test_resolution_and_hq_are_forwarded_to_the_printer(qapp, tmp_path):
    """Auflösung und HQ sind zwei Schalter - beide landen im Druckauftrag."""
    from ql_editor.printer import build_raster

    win = _temp_window(qapp, tmp_path)
    label = win._media_panel.label
    config = win._media_panel.printer_config()

    # Vorgabe: die Standardauflösung des Druckkopfs, HQ an.
    assert win._resolution().key == RESOLUTION_STANDARD.key
    assert win._hq() is True
    assert win._print_scale() == 1
    assert win._for_print().width == label.width_dots

    # 600 dpi nur in Bandlaufrichtung: doppelt so fein gerendert.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    qapp.processEvents()
    assert win._resolution().scale == 2
    assert win._print_scale() == 2
    assert win._for_print().width == label.width_dots * 2

    fine = win._for_print()
    with_hq = build_raster(fine, label, config, hq=True, dpi_600=True)
    without_hq = build_raster(fine, label, config, hq=False, dpi_600=True)
    assert with_hq != without_hq


def test_print_options_are_persisted(qapp, tmp_path):
    from ql_editor.printer import CUT_AT_END

    win = _temp_window(qapp, tmp_path)
    win._threshold_spin.setValue(88)
    win._dither_check.setChecked(True)
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    win._hq_check.setChecked(False)
    win._copies_spin.setValue(4)
    win._cut_combo.setCurrentIndex(win._cut_combo.findData(CUT_AT_END))
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    assert again._threshold_spin.value() == 88
    assert again._dither_check.isChecked() is True
    assert again._resolution_combo.currentData() == RESOLUTION_HIGH.key
    assert again._hq_check.isChecked() is False
    assert again._copies_spin.value() == 4
    assert again._cut_combo.currentData() == CUT_AT_END


def test_cut_at_end_needs_several_copies(qapp, tmp_path):
    """„Nur am Ende" ist bei einer Kopie keine Option.

    Eine Kopie am Ende zu schneiden ist dasselbe wie nach der Kopie zu
    schneiden - der Eintrag wird ausgegraut (nicht versteckt, das Panel soll
    nicht springen) und eine solche Auswahl faellt zurueck.
    """
    from ql_editor.printer import CUT_AT_END, CUT_EACH

    win = _temp_window(qapp, tmp_path)
    combo = win._cut_combo
    index = combo.findData(CUT_AT_END)

    assert combo.model().item(index).isEnabled() is False

    win._copies_spin.setValue(3)

    assert combo.model().item(index).isEnabled() is True

    combo.setCurrentIndex(index)
    assert combo.currentData() == CUT_AT_END

    win._copies_spin.setValue(1)

    assert combo.currentData() == CUT_EACH
    assert combo.model().item(index).isEnabled() is False
    win.close()
    qapp.processEvents()


def test_print_options_reach_the_print_job(qapp, tmp_path, monkeypatch):
    """Kopien und Zuschnitt kommen wirklich im Auftrag an (bis in die Schicht)."""
    from PySide6.QtCore import QObject, Signal

    from ql_editor import app as app_module
    from ql_editor.printer import CUT_AT_END

    captured: dict = {}

    class FakeWorker(QObject):
        succeeded = Signal(dict)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, image, label, config, options):
            super().__init__()
            captured.update(options)

        def start(self) -> None:
            pass

    monkeypatch.setattr(app_module, "PrintWorker", FakeWorker)
    win = _temp_window(qapp, tmp_path)
    # Ohne Drucker gibt es keinen Auftrag - die Adresse hier bewusst setzen.
    win._media_panel.set_network_host("192.168.178.62")
    win._copies_spin.setValue(3)
    win._cut_combo.setCurrentIndex(win._cut_combo.findData(CUT_AT_END))
    win._on_print()
    assert captured["copies"] == 3
    assert captured["cut_mode"] == CUT_AT_END
    win.close()
    qapp.processEvents()


def test_second_print_after_first_finished(qapp, tmp_path, monkeypatch):
    """Nach einem abgeschlossenen Druck darf ein zweiter Druck nicht abstuerzen."""
    from PySide6.QtCore import QThread, Signal
    from shiboken6 import delete

    from ql_editor import app as app_module

    created: list = []

    class FakeWorker(QThread):
        succeeded = Signal(dict)
        failed = Signal(str)

        def __init__(self, image, label, config, options):
            super().__init__()
            created.append(self)

        def run(self) -> None:
            pass

    monkeypatch.setattr(app_module, "PrintWorker", FakeWorker)
    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.168.178.62")
    win._on_print()
    created[0].wait()
    qapp.processEvents()
    delete(created[0])
    win._on_print()
    assert len(created) == 2
    win.close()
    qapp.processEvents()


def test_connection_and_address_are_persisted(qapp, tmp_path):
    """Der gewaehlte Anschluss samt Adresse ueberlebt einen Neustart."""
    from ql_editor.media_panel import CONNECTION_NETWORK

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.168.178.99")
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    assert again._media_panel.connection() == CONNECTION_NETWORK
    assert again._media_panel.address() == "tcp://192.168.178.99:9100"


def _sheet(win):
    """Das aktuell sichtbare Sheet im Hauptfenster (wie in test_sheet)."""
    from ql_editor.sheet import Sheet

    sheets = win.findChildren(Sheet)
    for sheet in sheets:
        if sheet.isVisible():
            return sheet
    return sheets[0] if sheets else None


class _FakePermissionProcess:
    """Steht fuer den laufenden pkexec-Prozess, damit der Abschluss pruefbar ist."""

    def __init__(self, stderr: bytes = b"") -> None:
        self._stderr = stderr
        self.killed = False

    def readAllStandardError(self) -> bytes:
        return self._stderr

    def kill(self) -> None:
        self.killed = True


def test_permission_button_without_a_prompt_shows_the_one_liner(
    qapp, tmp_path, monkeypatch
):
    """Ohne Passwort-Dialog bleibt der Befehl zum Abschreiben."""
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(access, "install_command", lambda: None)
    monkeypatch.setattr(access, "reason_no_prompt", lambda: "Es läuft kein Dialog.")

    win._on_usb_permission()
    qapp.processEvents()

    sheet = _sheet(win)
    assert sheet is not None
    box = sheet.findChild(QMessageBox)
    assert "Es läuft kein Dialog." in box.text()
    assert "install-udev-rule.sh" in box.text()
    # Der Befehl muss sich markieren (und damit kopieren) lassen.
    assert box.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_permission_failure_explains_the_abort(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    monkeypatch.setattr(access, "rule_installed", lambda: False)
    win._permission_process = _FakePermissionProcess()

    win._on_permission_finished(access.PKEXEC_DISMISSED)
    qapp.processEvents()

    sheet = _sheet(win)
    assert sheet is not None
    assert "Abgebrochen" in sheet.findChild(QMessageBox).text()


def test_permission_success_refreshes_the_panel(qapp, tmp_path, monkeypatch):
    win = _temp_window(qapp, tmp_path)
    win._permission_process = _FakePermissionProcess()
    refreshed = []
    monkeypatch.setattr(
        win._media_panel, "refresh_access", lambda: refreshed.append(True)
    )

    win._on_permission_finished(0)

    assert refreshed == [True]
    assert "eingerichtet" in win.statusBar().currentMessage()


def test_permission_success_retries_until_udev_applied_the_rule(
    qapp, tmp_path, monkeypatch
):
    """udev greift kurz verzoegert - die Anzeige darf kein zweites Klicken verlangen."""
    win = _temp_window(qapp, tmp_path)
    win._permission_process = _FakePermissionProcess()
    answers = [False, False, True]
    monkeypatch.setattr(
        win._media_panel, "refresh_access", lambda: answers.pop(0) if answers else True
    )

    win._on_permission_finished(0)
    assert win._access_retry.isActive()
    assert "geprüft" in win.statusBar().currentMessage()

    win._check_usb_access()
    assert win._access_retry.isActive()

    win._check_usb_access()
    assert not win._access_retry.isActive()
    assert "eingerichtet" in win.statusBar().currentMessage()


def test_permission_success_without_effect_hints_at_replugging(
    qapp, tmp_path, monkeypatch
):
    """Bleibt es bei fehlenden Rechten, sagt die App was zu tun ist."""
    from ql_editor.app import ACCESS_RETRY_COUNT

    win = _temp_window(qapp, tmp_path)
    win._permission_process = _FakePermissionProcess()
    monkeypatch.setattr(win._media_panel, "refresh_access", lambda: False)

    win._on_permission_finished(0)
    for _ in range(ACCESS_RETRY_COUNT + 1):
        win._check_usb_access()

    assert not win._access_retry.isActive()
    assert "ab- und anstecken" in win.statusBar().currentMessage()


def test_permission_timeout_kills_and_shows_the_one_liner(
    qapp, tmp_path, monkeypatch
):
    """Ein Agent, der nicht fragt, darf die Anzeige nicht blockieren."""
    from PySide6.QtWidgets import QMessageBox

    from ql_editor import access

    win = _temp_window(qapp, tmp_path)
    process = _FakePermissionProcess()
    win._permission_process = process
    monkeypatch.setattr(access, "reason_no_prompt", lambda: "Kein Dialog gefunden.")

    win._on_permission_timeout()
    qapp.processEvents()

    assert process.killed is True
    sheet = _sheet(win)
    assert sheet is not None
    assert "Kein Dialog gefunden." in sheet.findChild(QMessageBox).text()


def test_resolution_options_follow_the_printer_model(qapp):
    """Nur die Auflösungen, die der Druckkopf wirklich kann."""
    from ql_editor.printer import (
        maximum_resolution,
        resolution_by_key,
        resolution_options,
    )

    keys = [option.key for option in resolution_options("QL-820NWB")]
    assert keys == [RESOLUTION_STANDARD.key, RESOLUTION_HIGH.key]
    assert maximum_resolution("QL-820NWB").label == "300 × 600 dpi"
    assert maximum_resolution("QL-820NWB").scale == 2

    # Alle uebrigen Modelle der Bibliothek haben nur den 300-dpi-Druckkopf -
    # laut Datenblatt ohne High-Resolution-Modus.
    for model_id in ("QL-500", "QL-570", "QL-700", "QL-720NW", "QL-1050", "QL-1060N"):
        assert [option.key for option in resolution_options(model_id)] == [
            RESOLUTION_STANDARD.key
        ], model_id
        assert maximum_resolution(model_id).label == "300 × 300 dpi"

    # Eine nicht unterstuetzte Aufloesung faellt auf das Maximum des Modells zurueck.
    assert (
        resolution_by_key("QL-500", RESOLUTION_HIGH.key).key == RESOLUTION_STANDARD.key
    )
    assert resolution_by_key("QL-820NWB", RESOLUTION_HIGH.key).scale == 2


def test_resolution_combo_follows_a_model_change(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    assert win._resolution().key == RESOLUTION_STANDARD.key

    combo = win._media_panel._model_combo
    combo.setCurrentIndex(combo.findData("QL-500"))
    qapp.processEvents()
    assert [
        win._resolution_combo.itemData(i) for i in range(win._resolution_combo.count())
    ] == [RESOLUTION_STANDARD.key]
    assert "300 × 300 dpi" in win._resolution_combo.toolTip()

    # Zurueck zum QL-820NWB: 600 dpi ist wieder waehlbar.
    combo.setCurrentIndex(combo.findData("QL-820NWB"))
    qapp.processEvents()
    assert RESOLUTION_HIGH.key in [
        win._resolution_combo.itemData(i) for i in range(win._resolution_combo.count())
    ]

    # Eine Aufloesung, die das neue Modell nicht kann, faellt auf 300 dpi zurueck.
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    qapp.processEvents()
    assert win._resolution().scale == 2
    combo.setCurrentIndex(combo.findData("QL-500"))
    qapp.processEvents()
    assert win._resolution().scale == 1
    assert "QL-500" in win._resolution_combo.toolTip()


def test_print_options_fit_on_a_small_screen(qapp, tmp_path):
    """Auf dem Reiter "Drucken" braucht das Panel wenig Hoehe - der Drucken-
    Knopf bleibt ohne Scrollen sichtbar, auch auf kleinen Bildschirmen."""
    win = _temp_window(qapp, tmp_path)
    from ql_editor.adaptive import TABS

    win._right_pages.set_mode(TABS)
    win._right_pages.show_page(1)
    qapp.processEvents()
    page = win._right_pages.page(1)
    assert page.widget().sizeHint().height() <= 310
    assert win._print_button.isVisible()


def test_print_preview_in_600dpi_is_reduced_to_canvas_size(qapp, tmp_path):
    """Im 600-dpi-Modus zeigt die Vorschau die echten Druckdaten.

    Das 1-bit-Bild hat dann doppelt so viele Zeilen; fuer das Overlay wird es
    auf die Canvas-Groesse gemittelt (sonst waere die Vorschau gestaucht).
    """
    win = _temp_window(qapp, tmp_path)
    win._resolution_combo.setCurrentIndex(
        win._resolution_combo.findData(RESOLUTION_HIGH.key)
    )
    win._add_text()
    win._canvas.cancel_editing()
    win._canvas.set_print_preview(True)
    win._refresh_now()

    printable = win._canvas.printable_rect()
    preview = win._canvas._print_image
    assert preview is not None
    assert (preview.width(), preview.height()) == (
        int(printable.width()),
        int(printable.height()),
    )
    assert win._ink_label.text().startswith("Tinte:")


def test_threshold_is_disabled_while_dithering(qapp, tmp_path):
    """Dithering ignoriert die Tintenmenge - das Feld sagt das auch."""
    win = _temp_window(qapp, tmp_path)
    assert win._threshold_spin.isEnabled() is True

    win._dither_check.setChecked(True)
    qapp.processEvents()
    assert win._threshold_spin.isEnabled() is False
    assert "ohne Wirkung" in win._threshold_label.text()

    win._dither_check.setChecked(False)
    qapp.processEvents()
    assert win._threshold_spin.isEnabled() is True
    assert win._threshold_label.text() == "Tintenmenge"


def test_threshold_range_excludes_the_extremes(qapp, tmp_path):
    """Alles-schwarz und nur-reines-Schwarz sind nicht waehlbar."""
    from ql_editor.preview import THRESHOLD_MAX, THRESHOLD_MIN

    win = _temp_window(qapp, tmp_path)
    assert win._threshold_spin.minimum() == THRESHOLD_MIN
    assert win._threshold_spin.maximum() == THRESHOLD_MAX
    assert THRESHOLD_MIN < 70 < THRESHOLD_MAX

    win._threshold_spin.setValue(100)
    assert win._threshold_spin.value() == THRESHOLD_MAX
    win._threshold_spin.setValue(0)
    assert win._threshold_spin.value() == THRESHOLD_MIN

    # Alte Einstellungen ausserhalb der Spanne werden beim Laden begrenzt.
    win._settings.threshold = 5
    win._apply_saved_settings()
    assert win._threshold_spin.value() == THRESHOLD_MIN


def test_threshold_has_an_explanatory_tooltip(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    tooltip = win._threshold_spin.toolTip()
    assert tooltip == win._threshold_label.toolTip()
    assert "Schwärze" in tooltip          # was der Wert bedeutet
    assert "kräftiger" in tooltip         # hoeher = mehr Tinte
    assert "Dithering" in tooltip         # wann er nicht wirkt
    assert "40 %" in tooltip and "90 %" in tooltip  # waehlbare Spanne


def test_old_settings_are_migrated(qapp, tmp_path):
    """Bestehende Einstellungen (print/quality, print/hq) werden uebersetzt."""
    from PySide6.QtCore import QSettings

    from ql_editor.settings import AppSettings

    raw = QSettings(str(tmp_path / "migration.ini"), QSettings.Format.IniFormat)
    raw.setValue("print/hq", False)
    assert AppSettings(raw).hq is False
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key

    raw.setValue("print/hq", True)
    assert AppSettings(raw).hq is True

    # Die kombinierte "Qualitaet" einer aelteren Version: "maximum" war 600 dpi.
    raw.remove("print/hq")
    raw.setValue("print/quality", "maximum")
    assert AppSettings(raw).print_resolution == RESOLUTION_HIGH.key
    assert AppSettings(raw).hq is True

    raw.setValue("print/quality", "standard")
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key
    assert AppSettings(raw).hq is False

    # Die neuen Schluessel gewinnen, sobald sie gesetzt sind.
    settings = AppSettings(raw)
    settings.print_resolution = RESOLUTION_STANDARD.key
    settings.hq = True
    assert raw.value("print/resolution") == RESOLUTION_STANDARD.key
    assert raw.value("print/hq") is True
    assert settings.print_resolution == RESOLUTION_STANDARD.key
    assert settings.hq is True


def test_fresh_settings_use_the_standard_resolution(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from ql_editor.settings import AppSettings

    raw = QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat)
    assert AppSettings(raw).print_resolution == RESOLUTION_STANDARD.key
    assert AppSettings(raw).hq is True


# --------------------------------------------------------------------------- #
# Sprachumschaltung (DE/EN)
# --------------------------------------------------------------------------- #
def test_media_panel_state_round_trip(qapp):
    """Der Bedienzustand laesst sich sichern und wiederherstellen."""
    from ql_editor.media import LengthMode, Orientation
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    panel._auto_check.setChecked(False)
    panel._length_spin.setValue(66.5)
    panel._mode_combo.setCurrentIndex(
        panel._mode_combo.findData(LengthMode.CONTENT.value)
    )
    panel._margin_spins["top"].setValue(3.5)
    panel._margin_spins["left"].setValue(2.5)
    panel.set_orientation(Orientation.ALONG)
    state = panel.state()

    other = MediaPanel()
    other.apply_state(state)
    assert other.auto_length() is False
    assert other.length_mm() == pytest.approx(66.5)
    assert other.length_mode() is LengthMode.CONTENT
    assert other.margins().top == pytest.approx(3.5)
    assert other.margins().left == pytest.approx(2.5)
    assert other.orientation() is Orientation.ALONG
    assert other.model_id() == panel.model_id()
    assert other.label_id() == panel.label_id()


def test_language_switch_keeps_content_and_media(qapp, tmp_path):
    """DE -> EN: neues Fenster mit englischen Texten, Inhalt bleibt."""
    from ql_editor import app as app_module, i18n
    from ql_editor import printer as printer_module
    from ql_editor.items import TextItem
    from ql_editor.media import Orientation

    win = _temp_window(qapp, tmp_path)
    win._canvas.add_item(TextItem("Hallo", font_pixel_size=24))
    win._media_panel.set_orientation(Orientation.ALONG)
    win._media_panel._auto_check.setChecked(False)
    win._media_panel._length_spin.setValue(55.0)
    win._copies_spin.setValue(3)
    win._cut_combo.setCurrentIndex(
        win._cut_combo.findData(printer_module.CUT_AT_END)
    )

    win.switch_language("en")
    qapp.processEvents()

    new = app_module._current_window
    assert new is not win
    assert i18n.language() == "en"
    assert new._settings.language == "en"
    # Englische Oberflaeche ...
    assert new._act_about.text() == "About QLInux"
    assert new._media_panel._auto_check.text() == "Automatic length (content)"
    assert new._left_panel._title == "Label & printer"
    # ... bei unveraendertem Inhalt und unveraenderter Bandauswahl.
    assert len(new._canvas.items_serialized()) == 1
    assert new._media_panel.orientation() is Orientation.ALONG
    assert new._media_panel.auto_length() is False
    assert new._media_panel.length_mm() == pytest.approx(55.0)
    assert new._copies_spin.value() == 3
    assert new._cut_combo.currentData() == printer_module.CUT_AT_END
    assert new._cut_combo.currentText() == "At end"

    new.close()
    qapp.processEvents()


def test_language_switch_is_offered_in_the_menu(qapp, tmp_path):
    """Die Sprachwahl sitzt im Hamburger-Menue und ist angehakt."""
    win = _temp_window(qapp, tmp_path)
    menu = win._menu_button.menu()
    # Nach Titel suchen: im Menue liegen mehrere Untermenues (Vorlagen, Sprache).
    submenu = next(
        action.menu()
        for action in menu.actions()
        if action.menu() is not None and action.menu().title() == "Sprache"
    )
    assert submenu.title() == "Sprache"
    labels = {action.text(): action.isChecked() for action in submenu.actions()}
    assert labels == {"Deutsch": True, "English": False}
    win.close()


def test_english_ui_has_no_german_leftovers(qapp, tmp_path):
    """Die englische Oberflaeche ist wirklich durchgehend englisch.

    Geprueft werden alle sichtbaren Texte (Beschriftungen, Knoepfe, Listen,
    Tooltips, Aktionen) - deutsche Umlaute und die deutschen Anfuehrungszeichen
    verraten jeden vergessenen Text.
    """
    from PySide6.QtCore import QPointF, QSettings
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPushButton,
        QToolButton,
        QWidget,
    )

    from PySide6.QtCore import QRectF
    from PIL import Image

    from ql_editor import i18n
    from ql_editor.app import MainWindow
    from ql_editor.items import (
        BarcodeItem,
        ImageItem,
        LineItem,
        QRItem,
        RectItem,
        TextItem,
    )
    from ql_editor.settings import AppSettings
    from ql_editor.sheet import Sheet
    from ql_editor.translations import EN

    german_only = ("ä", "ö", "ü", "ß", "Ä", "Ö", "Ü", "„")
    i18n.set_language("en")
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    win = MainWindow(settings)
    # Inspector und Kontextmenue entstehen erst bei Bedarf - mit pruefen.
    picture = tmp_path / "probe.png"
    Image.new("RGB", (32, 32), "white").save(picture)
    items = [
        TextItem("Hallo", font_pixel_size=24),
        BarcodeItem("ABC-123", "code128", height_dots=60),
        QRItem("https://example.org", size_dots=90),
        LineItem(0, 0, 80, 0, width_px=3),
        RectItem(QRectF(0, 0, 80, 40)),
        ImageItem.from_file(str(picture)),
    ]
    for item in items:
        win._canvas.add_item(item)
    win._canvas.scene().items()[0].setSelected(True)
    qapp.processEvents()

    texts: list[str] = []

    def collect(widget: QWidget) -> None:
        if isinstance(widget, QLabel):
            texts.append(widget.text())
        if isinstance(widget, (QPushButton, QToolButton, QCheckBox)):
            texts.append(widget.text())
        if isinstance(widget, QGroupBox):
            texts.append(widget.title())
        if isinstance(widget, QComboBox):
            texts.extend(
                widget.itemText(index) for index in range(widget.count())
            )
        if isinstance(widget, QLineEdit):
            texts.append(widget.placeholderText())
        texts.append(widget.toolTip())

    for widget in win.findChildren(QWidget):
        collect(widget)
    for action in win._menu_button.menu().actions():
        texts.append(action.text())
        texts.append(action.toolTip())
        if action.menu() is not None:
            texts.extend(entry.text() for entry in action.menu().actions())
    for action in win._build_context_menu(QPointF(10, 10)).actions():
        texts.append(action.text())

    # Jede Objektart einmal in den Inspector legen (Titel + Feldnamen).
    for item in items:
        win._inspector.set_item(item, allow_red=True)
        qapp.processEvents()
        for widget in win._inspector.findChildren(QWidget):
            collect(widget)

    # Auch das Über-Sheet (Modellliste, Lizenz, Danksagung) muss englisch sein.
    win._show_about()
    qapp.processEvents()
    sheet = win.findChild(Sheet)
    assert sheet is not None
    for widget in sheet.findChildren(QWidget):
        collect(widget)
    sheet.close_sheet()
    qapp.processEvents()

    # Alles, was noch genauso heisst wie der deutsche Originaltext, ist
    # unuebersetzt - ebenso alles mit deutschen Umlauten/Anfuehrungszeichen.
    # Ausnahme: der Entwicklername (Eigenname, steht in beiden Sprachen).
    from ql_editor.about import DEVELOPER

    untranslated = set(EN) - {key for key, value in EN.items() if key == value}
    leftovers = sorted(
        {
            text
            for text in texts
            if DEVELOPER not in text
            and (text in untranslated or any(ch in text for ch in german_only))
        }
    )
    assert not leftovers, f"Noch deutsch: {leftovers}"
    win.close()
    qapp.processEvents()


# --------------------------------------------------------------------------- #
# Über QLInux
# --------------------------------------------------------------------------- #
def test_about_lists_models_licence_dank_and_developer(qapp, tmp_path):
    """Das „Über" ist ehrlich: alle Modelle der Bibliothek, Lizenz, Dank, Haus.

    QLInux ist kein QL-820NWB-Programm - es kann, was ``brother_ql`` kann.
    Genau das muss dort stehen, samt freier Lizenz und Danksagung.
    """
    from PySide6.QtWidgets import QLabel

    from ql_editor import media
    from ql_editor.about import DEVELOPER, DEVELOPER_URL, PROJECT_URL, credits
    from ql_editor.sheet import Sheet

    win = _temp_window(qapp, tmp_path)
    win._show_about()
    qapp.processEvents()

    sheet = win.findChild(Sheet)
    assert sheet is not None

    texts = [label.text() for label in sheet.findChildren(QLabel)]
    joined = "\n".join(texts)

    # Alle Modelle der Bibliothek - nicht nur das eigene Geraet.
    for spec in media.all_models():
        assert spec.identifier in joined, spec.identifier
    assert str(len(media.all_models())) in joined
    # Lizenz und Danksagung an die Upstream-Bibliotheken.
    assert "GPL-3.0-or-later" in joined
    for name, _author, license_id, _contribution in credits():
        assert name in joined, name
        assert license_id in joined, license_id
    assert "brother_ql" in joined
    # Entwickler aus dem Impressum.
    assert DEVELOPER in joined
    assert DEVELOPER_URL in joined
    assert PROJECT_URL in joined

    sheet.close_sheet()
    qapp.processEvents()
    win.close()
    qapp.processEvents()


# --------------------------------------------------------------------------- #
# Etiketten als Datei (.qlx)
# --------------------------------------------------------------------------- #
def test_a_design_survives_saving_and_opening(qapp, tmp_path):
    """Speichern/Öffnen bringt Band, Ausrichtung und Objekte zurueck.

    Der Drucker dieses Rechners darf sich dabei *nicht* aendern: die Adresse
    gehoert dem Rechner, nicht dem Etikett.
    """
    import json

    from ql_editor.media import Orientation

    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.168.178.62")
    win._media_panel.set_orientation(Orientation.ALONG)
    win._media_panel._length_spin.setValue(55.0)
    win._canvas.add_item(TextItem("Hallo", font_pixel_size=30))
    path = tmp_path / "design.qlx"

    win._save_document_to(str(path))

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "address" not in data["media"]
    assert data["media"]["orientation"] == Orientation.ALONG.value
    # Nach dem Speichern ist nichts mehr "geaendert", der Name steht im Titel.
    assert win._document_dirty is False
    assert path.name in win.windowTitle()

    # Anderes Fenster (anderer Drucker), dann das Design oeffnen.
    other = _temp_window(qapp, tmp_path)
    other._media_panel.set_address("tcp://192.168.178.99:9100")
    other._open_document_chosen(str(path))

    assert other._media_panel.orientation() is Orientation.ALONG
    assert other._media_panel.length_mm() == pytest.approx(55.0)
    assert [item["text"] for item in other._canvas.items_serialized()] == ["Hallo"]
    assert other._media_panel.address() == "tcp://192.168.178.99:9100"
    assert other._document_dirty is False

    win.close()
    other.close()
    qapp.processEvents()


def test_editing_marks_the_document_and_opening_a_broken_file_does_not(
    qapp, tmp_path
):
    """Ein Stern im Titel zeigt Aenderungen; eine kaputte Datei aendert nichts."""
    from ql_editor.sheet import Sheet

    win = _temp_window(qapp, tmp_path)
    assert win._is_document_dirty() is False

    win._add_item(TextItem("Hallo", font_pixel_size=30))
    qapp.processEvents()

    assert win._is_document_dirty() is True
    assert "*" in win.windowTitle()

    broken = tmp_path / "kaputt.qlx"
    broken.write_text("{ kein json", encoding="utf-8")
    win._open_document_chosen(str(broken))
    qapp.processEvents()

    # Fehler sichtbar (Sheet), aber kein halb geoeffnetes Etikett.
    assert win.findChild(Sheet) is not None
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Hallo"]
    assert win._is_document_dirty() is True
    win.close()
    qapp.processEvents()


def test_opening_an_lbx_imports_without_keeping_that_path(qapp, tmp_path):
    """``.lbx`` wird geladen, aber nicht als Speicherziel gemerkt.

    Sonst schriebe „Speichern" JSON in die Brother-Datei. Stattdessen bleibt
    das Fenster „Unbenannt*".
    """
    from tests.lbx_samples import write_lbx

    path = write_lbx(
        tmp_path / "logo.lbx",
        width_mm=62,
        height_mm=1000,
        orientation="landscape",
    )
    win = _temp_window(qapp, tmp_path)
    win._open_document_chosen(str(path))
    qapp.processEvents()

    assert win._document_path == ""
    assert win._is_document_dirty() is True
    assert win.windowTitle().startswith("Unbenannt*")
    assert win._media_panel.label_id() == "62"
    assert win._media_panel.orientation().value == "along"

    win.close()
    qapp.processEvents()


def test_files_given_on_the_command_line_are_opened(qapp, tmp_path):
    """Doppelklick im Dateimanager: ``ql-editor datei.qlx`` oeffnet die Datei.

    Optionen und fremde Argumente werden ignoriert.
    """
    from ql_editor.app import _document_args

    design = tmp_path / "design.qlx"
    brother = tmp_path / "logo.lbx"
    args = ["ql-editor", "--foo", "xcb", str(design), str(brother), "notiz.txt"]

    assert _document_args(args) == [str(design), str(brother)]

    win = _temp_window(qapp, tmp_path)
    win._canvas.add_item(TextItem("Datei", font_pixel_size=30))
    win._save_document_to(str(design))
    win.close()
    qapp.processEvents()

    win = _temp_window(qapp, tmp_path)
    for path in _document_args(["ql-editor", str(design)]):
        win.open_path(path)
    qapp.processEvents()

    # Das leere Ausgangs-Etikett ist weg, nur die Datei bleibt.
    assert len(win._tab_ids) == 1
    assert win._document_path == str(design)
    assert win.windowTitle().startswith("design")

    win.close()
    qapp.processEvents()


def test_an_untouched_tab_is_kept_when_a_file_opens(qapp, tmp_path):
    """Hat das Etikett Inhalt, bleibt es offen - die Datei kommt als eigener Reiter."""
    design = tmp_path / "design.qlx"
    from ql_editor import document

    document.save(design, document.build({}, []))
    win = _temp_window(qapp, tmp_path)
    win._canvas.add_item(TextItem("Entwurf", font_pixel_size=30))
    win.open_path(str(design))
    qapp.processEvents()

    assert len(win._tab_ids) == 2
    assert win._document_path == str(design)

    win.close()
    qapp.processEvents()


def test_opening_an_lbx_merges_the_csv_beside_it(qapp, tmp_path):
    """LBX-Import: CSV neben der Datei, Record 0-basiert, Speicherziel bleibt leer."""
    from ql_editor import document
    from tests.lbx_samples import text_object, write_lbx
    from tests.test_lbx_database import _database

    csv_path = tmp_path / "Fixture Data.csv"
    lines = ["Circuit;Filters"]
    for index in range(6):
        lines.append(f"c{index};f{index}")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    objects = (
        _database(database_path="/tmp/missing-fixture.csv", current_record="4")
        + text_object(body="CH:", x=2)
        + text_object(body="ALT", x=12, expanded="Circuit")
        + text_object(body="", x=22, expanded="Filters")
    )
    path = write_lbx(
        tmp_path / "labels.lbx",
        width_mm=62,
        height_mm=1000,
        objects=objects,
    )
    win = _temp_window(qapp, tmp_path)
    win._open_document_chosen(str(path))
    qapp.processEvents()

    texts = [item["text"] for item in win._canvas.items_serialized()]
    assert "CH:" in texts
    assert "c4" in texts
    assert "f4" in texts
    assert "ALT" not in texts
    assert win._document_path == ""
    assert win._active.current_record == 4
    assert win._database_panel.current_record() == 4
    assert win._active.data_source["containsFieldName"] is True

    qlx = tmp_path / "labels.qlx"
    assert win._save_document_to(str(qlx))
    saved = document.load(qlx)
    assert saved["data_source"]["path"] == "Fixture Data.csv"
    assert [item["text"] for item in saved["items"]] == ["CH:", "c4", "f4"]
    assert "records" not in saved["data_source"]

    win.close()
    qapp.processEvents()


def test_an_lbx_warning_is_shown(qapp, tmp_path):
    """Was nicht übernommen wird, steht danach in einem Hinweis."""
    from PySide6.QtWidgets import QLabel

    from ql_editor.sheet import Sheet
    from tests.lbx_samples import write_lbx

    path = write_lbx(
        tmp_path / "tabelle.lbx",
        width_mm=62,
        height_mm=1000,
        objects='<table:table xmlns:table="http://schemas.brother.info/ptouch/2007/lbx/table"/>',
    )
    win = _temp_window(qapp, tmp_path)
    win._open_document_chosen(str(path))
    qapp.processEvents()

    sheet = win.findChild(Sheet)
    assert sheet is not None
    labels = [label.text() for label in sheet.findChildren(QLabel)]
    assert any("Tabelle" in text for text in labels)
    win.close()
    qapp.processEvents()


def _sheet_button(win, label: str):
    from PySide6.QtWidgets import QMessageBox

    from ql_editor.sheet import Sheet

    sheet = next(
        (candidate for candidate in win.findChildren(Sheet) if candidate.isVisible()),
        None,
    )
    assert sheet is not None
    box = sheet.findChild(QMessageBox)
    for button in box.buttons():
        if button.text() == label:
            return button
    raise AssertionError(label)


def test_tabs_keep_items_tape_and_undo_apart(qapp, tmp_path):
    """Zwei Reiter behalten Objekte, Bandlänge und Undo für sich."""
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._media_panel._auto_check.setChecked(False)
    win._media_panel._length_spin.setValue(40.0)
    win._add_item(TextItem("Eins", font_pixel_size=24))
    address = win._media_panel.address()

    win._on_file_new()
    qapp.processEvents()
    assert win._tab_bar.count() == 2
    win._add_item(TextItem("Zwei", font_pixel_size=24))
    win._media_panel._length_spin.setValue(80.0)
    qapp.processEvents()

    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Eins"]
    assert win._media_panel.length_mm() == pytest.approx(40.0)
    assert win._media_panel.address() == address

    win._tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Zwei"]
    assert win._media_panel.length_mm() == pytest.approx(80.0)
    assert win._media_panel.address() == address
    win._act_undo.trigger()
    qapp.processEvents()
    assert win._media_panel.length_mm() == pytest.approx(40.0)
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Zwei"]

    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Eins"]
    assert win._media_panel.length_mm() == pytest.approx(40.0)
    win.close()
    qapp.processEvents()


def test_open_reuses_a_blank_tab_and_focuses_a_path_that_is_already_open(
    qapp, tmp_path
):
    """Ein leeres Fenster nimmt die Datei in den ersten Reiter; dieselbe Datei nicht zweimal."""
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    path = tmp_path / "eins.qlx"
    win._save_document_to(str(path))
    # Frisch gespeichert und ohne Objekte: immer noch ein Reiter.
    assert win._tab_bar.count() == 1

    other = tmp_path / "zwei.qlx"
    win._add_item(TextItem("Eins", font_pixel_size=20))
    win._save_document_to(str(other))
    win._open_document_chosen(str(path))
    qapp.processEvents()
    assert win._tab_bar.count() == 2
    assert win._document_path == str(path)
    assert win._canvas.items_serialized() == []

    win._add_item(TextItem("Noch da", font_pixel_size=20))
    win._open_document_chosen(str(path))
    qapp.processEvents()
    assert win._tab_bar.count() == 2
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Noch da"]
    win.close()
    qapp.processEvents()


def test_a_broken_file_does_not_open_another_tab(qapp, tmp_path):
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Hallo", font_pixel_size=20))
    broken = tmp_path / "kaputt.qlx"
    broken.write_text("{ kein json", encoding="utf-8")
    win._open_document_chosen(str(broken))
    qapp.processEvents()
    assert win._tab_bar.count() == 1
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Hallo"]
    win.close()
    qapp.processEvents()


def test_cancelling_a_tab_close_keeps_the_label(qapp, tmp_path):
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Bleibt", font_pixel_size=20))
    win._on_close_current_tab()
    qapp.processEvents()
    _sheet_button(win, "Abbrechen").click()
    qapp.processEvents()
    assert win._tab_bar.count() == 1
    assert [item["text"] for item in win._canvas.items_serialized()] == ["Bleibt"]
    assert win.isVisible()
    win._accept_close = True
    win.close()
    qapp.processEvents()


def test_discarding_the_last_tab_leaves_a_blank_label(qapp, tmp_path):
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Weg", font_pixel_size=20))
    win._on_close_current_tab()
    qapp.processEvents()
    _sheet_button(win, "Verwerfen").click()
    qapp.processEvents()
    assert win._tab_bar.count() == 1
    assert win._canvas.items_serialized() == []
    assert win._document_path == ""
    assert win._is_document_dirty() is False
    win.close()
    qapp.processEvents()


def test_language_switch_keeps_every_tab(qapp, tmp_path):
    from ql_editor import app as app_module
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Eins", font_pixel_size=20))
    win._on_file_new()
    win._add_item(TextItem("Zwei", font_pixel_size=20))
    win.switch_language("en")
    qapp.processEvents()

    new = app_module._current_window
    assert new is not win
    assert new._tab_bar.count() == 2
    assert [item["text"] for item in new._canvas.items_serialized()] == ["Zwei"]
    new._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert [item["text"] for item in new._canvas.items_serialized()] == ["Eins"]
    assert new._tab_bar.tabText(1).startswith("Untitled")
    new._accept_close = True
    new.close()
    qapp.processEvents()


def test_switching_tabs_commits_an_open_inspector_edit_and_keeps_empty_text(
    qapp, tmp_path
):
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QSpinBox

    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    item = TextItem("Hallo", font_pixel_size=28)
    win._add_item(item, QPointF(20, 20))
    win._on_file_new()
    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()

    item.setSelected(True)
    qapp.processEvents()
    size = next(
        spin
        for spin in win._inspector.findChildren(QSpinBox)
        if spin.minimum() == 4 and spin.maximum() == 2000
    )
    size.setValue(size.value() + 6)
    assert win._inspector.edit_open is True
    win._tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert win._inspector.edit_open is False

    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    win._new_text(QPointF(60, 60))
    win._tab_bar.setCurrentIndex(1)
    qapp.processEvents()

    first = win._tab_at(0)
    assert [
        first.undo.command(i).text() for i in range(first.undo.count())
    ] == ["Einfügen", "Eigenschaften", "Text"]
    texts = [
        entry
        for entry in first.canvas.scene().items()
        if isinstance(entry, TextItem)
    ]
    assert sorted(entry.toPlainText() for entry in texts) == ["", "Hallo"]
    win._accept_close = True
    win.close()
    qapp.processEvents()


def test_closing_the_window_saves_each_modified_tab(qapp, tmp_path):
    from ql_editor import document
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win.show()
    qapp.processEvents()
    first = tmp_path / "eins.qlx"
    second = tmp_path / "zwei.qlx"
    win._save_document_to(str(first))
    win._add_item(TextItem("Eins", font_pixel_size=20))
    win._on_file_new()
    win._save_document_to(str(second))
    win._add_item(TextItem("Zwei", font_pixel_size=20))
    qapp.processEvents()

    win.close()
    qapp.processEvents()
    assert win.isVisible()
    _sheet_button(win, "Speichern").click()
    qapp.processEvents()
    assert win.isVisible()
    _sheet_button(win, "Speichern").click()
    qapp.processEvents()

    assert not win.isVisible()
    assert [i["text"] for i in document.load(first)["items"]] == ["Eins"]
    assert [i["text"] for i in document.load(second)["items"]] == ["Zwei"]



# --------------------------------------------------------------------------- #
# Mitgelieferte Dateien (App-Symbol, Bundle-Pfade)
# --------------------------------------------------------------------------- #
def test_the_window_carries_the_app_icon(qapp, tmp_path):
    """Das Fenster hat das Symbol aus assets/ - nicht das Qt-Standardsymbol."""
    import ql_editor.resources as resources

    assert resources.asset(resources.APP_ICON).exists(), "Symbol fehlt in assets/"
    win = _temp_window(qapp, tmp_path)

    assert not win.windowIcon().isNull()
    win.close()
    qapp.processEvents()


def test_bundled_assets_are_found_via_the_environment(monkeypatch, tmp_path):
    """Aus dem AppImage heraus zeigt QLINUX_ASSETS_DIR auf das Bundle."""
    from ql_editor import resources

    monkeypatch.setenv(resources.ASSETS_ENV, str(tmp_path))

    assert resources.assets_dir() == tmp_path
    assert resources.asset(resources.APP_ICON) == tmp_path / resources.APP_ICON


# --------------------------------------------------------------------------- #
# Vorlagen
# --------------------------------------------------------------------------- #
def test_templates_menu_applies_a_template_as_a_new_label(qapp, tmp_path):
    """Vorlage anlegen = neues, ungespeichertes Etikett (kein alter Dateiname)."""
    from ql_editor import templates

    win = _temp_window(qapp, tmp_path)
    # Erst ein eigenes Etikett speichern - die Vorlage darf es nicht beerben.
    saved = tmp_path / "eigenes.qlx"
    win._save_document_to(str(saved))
    assert win._document_path == str(saved)

    name = templates.builtins()[0][0]
    win._on_template_builtin(name)
    qapp.processEvents()

    assert win._canvas.items_serialized(), "Vorlage hat keine Objekte angelegt"
    assert win._document_path == ""
    assert win._document_dirty is True
    assert win.windowTitle().startswith("Unbenannt*")
    # Die Vorlage liegt in einem eigenen Reiter, das gespeicherte Etikett bleibt.
    assert win._tab_bar.count() == 2
    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert win._document_path == str(saved)

    # Band/Design der Vorlage sind uebernommen, der Drucker bleibt.
    win._tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert win._media_panel.label_id() == templates.TEMPLATE_LABEL
    assert win._media_panel.auto_length() is True
    win.close()
    qapp.processEvents()


def test_the_template_menu_offers_builtins_and_saving(qapp, tmp_path, monkeypatch):
    """Das Menue hat die eingebauten Vorlagen und „Als Vorlage speichern…"."""
    from ql_editor import templates
    from ql_editor.templates import TEMPLATE_DIR_ENV

    monkeypatch.setenv(TEMPLATE_DIR_ENV, str(tmp_path))

    win = _temp_window(qapp, tmp_path)
    submenu = win._template_menu
    entries = [action.text() for action in submenu.actions()]

    for name, _data in templates.builtins():
        assert name in entries
    assert "Als Vorlage speichern…" in entries

    # Eigene Vorlage speichern und im Menue wiederfinden.
    win._save_template_named("Meins")
    win._fill_template_menu()

    assert "Meins" in [action.text() for action in submenu.actions()]
    assert templates.list_user() == [tmp_path / "Meins.qlx"]

    # Und anwenden.
    win._on_template_open(str(tmp_path / "Meins.qlx"))
    qapp.processEvents()

    assert win._document_path == ""
    win.close()
    qapp.processEvents()


def test_file_group_sits_right_after_the_burger(qapp, tmp_path):
    """Burger, dann Neu, Öffnen, Speichern, Vorlage laden - danach die Werkzeuge."""
    from PySide6.QtWidgets import QToolBar, QToolButton, QWidgetAction

    win = _temp_window(qapp, tmp_path)
    bar = win.findChild(QToolBar, "main_toolbar")
    items = [
        a for a in bar.actions() if not a.isSeparator()
    ]
    names = []
    for action in items:
        if isinstance(action, QWidgetAction):
            widget = bar.widgetForAction(action)
            names.append(widget.objectName() if widget else "")
        else:
            names.append(action.objectName() or action.text())

    assert names[0] == "main_menu_button"
    assert names[1] == win._act_file_new.text()
    assert names[2] == win._act_file_open.text()
    assert names[3] == win._act_file_save.text()
    assert names[4] == "template_button"
    template_button = win.findChild(QToolButton, "template_button")
    assert template_button.toolTip() == "Vorlage laden"
    # Der Knopf klappt die Vorlagenliste auf - eingebaute Vorlagen stehen drin.
    from ql_editor import templates

    menu = template_button.menu()
    menu.aboutToShow.emit()
    entries = [a.text() for a in menu.actions()]
    assert templates.builtins()[0][0] in entries
    win.close()
    qapp.processEvents()


def test_orientation_row_cannot_wrap_at_narrow_panel_width(qapp):
    """Die Ausrichtungs-Zeile ist nur die beiden Knoepfe - so passt sie in die
    Feldspalte auch im schmalsten Panel (sonst springt das Layout)."""
    from ql_editor.media_panel import MediaPanel

    panel = MediaPanel()
    row = panel._build_orientation_row()
    assert row.sizeHint().width() <= 120
    assert len(panel._orientation_buttons) == 2
    row.deleteLater()


def test_right_panel_stacks_when_tall_and_tabs_when_short(qapp, tmp_path):
    """Viel Hoehe: Objekt und Drucken untereinander. Wenig: als Reiter."""
    from ql_editor.adaptive import STACKED, TABS

    win = _temp_window(qapp, tmp_path)
    win.resize(1280, 900)
    win.show()
    qapp.processEvents()
    assert win._right_pages.mode == STACKED
    assert win._right_pages.page(0).isVisible()
    assert win._right_pages.page(1).isVisible()

    win.resize(1280, 420)
    qapp.processEvents()
    assert win._right_pages.mode == TABS

    win.resize(1280, 900)
    qapp.processEvents()
    assert win._right_pages.mode == STACKED
    assert win._right_pages.page(0).isVisible()
    assert win._right_pages.page(1).isVisible()
    win.close()
    qapp.processEvents()


def test_margin_edit_moves_objects_and_frame(qapp, tmp_path):
    """Linker/oberer Rand: Objekte wandern mit, und der Rahmen zieht nach."""
    from ql_editor import media
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Rand", font_pixel_size=60))
    qapp.processEvents()
    text = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    x_before, y_before = text.pos().x(), text.pos().y()

    win._media_panel._margin_spins["left"].setValue(8.0)
    win._media_panel._margin_spins["top"].setValue(6.0)
    qapp.processEvents()

    left_before = win._canvas._margins_mm  # Rahmen folgt dem Wert
    assert left_before[0] == 8.0
    assert win._canvas.margin_rect().left() == media.mm_to_dots(8.0)
    # Um die Differenz zum Standardrand verschoben (der ist beim Start 0 mm).
    assert text.pos().x() == pytest.approx(x_before + media.mm_to_dots(8.0))
    assert text.pos().y() == pytest.approx(y_before + media.mm_to_dots(6.0))
    win.close()
    qapp.processEvents()


def test_margin_edit_moves_full_label_and_grows_length(qapp, tmp_path):
    """Voller Inhalt: oberer Rand verschiebt trotzdem, die Laenge waechst mit."""
    from PySide6.QtCore import QRectF

    from ql_editor import media
    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    # Etikett von oben bis unten fuellen, damit die Klemme vorher die
    # Verschiebung geschluckt haette.
    height = int(win._canvas.printable_rect().height())
    win._add_item(RectItem(QRectF(0, 0, 200, height), width_px=4))
    qapp.processEvents()
    rect = next(i for i in win._canvas.scene().items() if isinstance(i, RectItem))
    y_before = rect.pos().y()
    height_before = win._canvas.printable_rect().height()

    win._media_panel._margin_spins["top"].setValue(5.0)
    qapp.processEvents()

    delta = media.mm_to_dots(5.0)
    assert rect.pos().y() == pytest.approx(y_before + delta)
    assert win._canvas.printable_rect().height() >= height_before + delta
    win.close()
    qapp.processEvents()


def test_content_length_ceils_fractional_dots(qapp, tmp_path):
    """Bruchteile eines Punktes in der Huelle runden die Laenge nach oben."""
    from PySide6.QtCore import QPointF, QRectF

    from ql_editor import media
    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    item = RectItem(QRectF(0, 0, 100, 50), width_px=2)
    win._add_item(item)
    qapp.processEvents()
    # Klemme aus: Position bewusst mit Bruchteil setzen.
    item._clamp_suspended = True
    item.setPos(QPointF(10.0, 100.6))
    item._clamp_suspended = False
    qapp.processEvents()
    hull = win._canvas.scene().itemsBoundingRect()
    length = win._content_length_dots(media.Orientation.ACROSS)
    assert length == math.ceil(hull.bottom())
    assert length > int(hull.bottom())  # Bruchteil vorhanden, sonst waere der Test leer
    win.close()
    qapp.processEvents()


def test_loading_a_document_does_not_shift_its_objects(qapp, tmp_path):
    """Beim Oeffnen bleiben die Objekte, wo sie gespeichert wurden."""
    from ql_editor import document
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._media_panel._margin_spins["left"].setValue(8.0)
    win._add_item(TextItem("Bleib", font_pixel_size=40))
    path = tmp_path / "rand.qlx"
    win._save_document_to(str(path))
    saved_x = next(
        i for i in win._canvas.scene().items() if isinstance(i, TextItem)
    ).pos().x()
    win.close()
    qapp.processEvents()

    again = _temp_window(qapp, tmp_path)
    again._open_document_chosen(str(path))
    qapp.processEvents()
    loaded = next(
        i for i in again._canvas.scene().items() if isinstance(i, TextItem)
    )
    assert loaded.pos().x() == saved_x
    again.close()
    qapp.processEvents()
    assert document.load(path)["media"]["margins"]["left"] == 8.0


def test_undo_redo_restores_item_position(qapp, tmp_path):
    """Verschieben + Undo stellt die Position wieder her; Redo ebenso."""
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("Undo", font_pixel_size=40))
    qapp.processEvents()
    text = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    x0, y0 = text.pos().x(), text.pos().y()

    win._canvas.gesture_begun.emit()
    text._clamp_suspended = True
    text.setPos(x0 + 40, y0 + 20)
    text._clamp_suspended = False
    win._canvas.items_changed.emit()
    qapp.processEvents()
    assert text.pos().x() == pytest.approx(x0 + 40)

    win._act_undo.trigger()
    qapp.processEvents()
    text = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    assert text.pos().x() == pytest.approx(x0)
    assert text.pos().y() == pytest.approx(y0)

    win._act_redo.trigger()
    qapp.processEvents()
    text = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    assert text.pos().x() == pytest.approx(x0 + 40)
    win.close()
    qapp.processEvents()


def test_align_left_and_undo(qapp, tmp_path):
    """Zwei Objekte links ausrichten; Undo stellt beide x-Werte zurueck."""
    from PySide6.QtCore import QPointF, QRectF

    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    first = RectItem(QRectF(0, 0, 40, 30), width_px=2)
    second = RectItem(QRectF(0, 0, 40, 30), width_px=2)
    win._add_item(first, QPointF(20, 10))
    win._add_item(second, QPointF(80, 50))
    qapp.processEvents()
    first.setSelected(True)
    second.setSelected(True)
    x_before = sorted(i.pos().x() for i in (first, second))
    win._align_selected("left")
    qapp.processEvents()
    assert first.pos().x() == pytest.approx(second.pos().x())
    win._act_undo.trigger()
    qapp.processEvents()
    again = [i for i in win._canvas.scene().items() if isinstance(i, RectItem)]
    assert sorted(i.pos().x() for i in again) == pytest.approx(x_before)
    win.close()
    qapp.processEvents()


def test_opening_a_document_clears_the_undo_stack(qapp, tmp_path):
    """Ein neu geöffnetes Etikett startet ohne Undo; das bisherige behält seinen Stapel."""
    from ql_editor import document
    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("A", font_pixel_size=40))
    qapp.processEvents()
    assert win._undo_stack.count() >= 1
    path = tmp_path / "clear.qlx"
    win._save_document_to(str(path))
    win._add_item(TextItem("B", font_pixel_size=40))
    qapp.processEvents()
    assert not win._undo_stack.isClean()
    kept = win._undo_stack.count()

    other = tmp_path / "anderes.qlx"
    document.save(other, document.build(win._media_panel.media_state(), []))
    win._open_document_chosen(str(other))
    qapp.processEvents()
    assert win._tab_bar.count() == 2
    assert win._document_path == str(other)
    assert win._undo_stack.count() == 0
    assert win._undo_stack.isClean()

    win._tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert win._undo_stack.count() == kept
    assert not win._undo_stack.isClean()
    win._accept_close = True
    win.close()
    qapp.processEvents()


def test_band_change_is_an_undo_step_and_keeps_the_star(qapp, tmp_path):
    """Bandwechsel liegt auf dem Stapel: Undo dreht ihn zurueck, und ein
    Undo eines spaeteren Schritts laesst das Band in Ruhe."""
    from PySide6.QtCore import QPointF, QRectF

    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    combo = win._media_panel._band_combo
    original = win._media_panel.label_id()
    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    qapp.processEvents()
    changed = win._media_panel.label_id()
    assert changed != original
    assert win._undo_stack.count() == 1
    assert "*" in win.windowTitle()

    win._add_item(RectItem(QRectF(0, 0, 40, 30), width_px=2), QPointF(10, 10))
    qapp.processEvents()
    win._act_undo.trigger()
    qapp.processEvents()
    # Nur das Einfuegen ist weg; das Band bleibt, der Stern auch.
    assert win._media_panel.label_id() == changed
    assert win._canvas.items_serialized() == []
    assert "*" in win.windowTitle()

    win._act_undo.trigger()
    qapp.processEvents()
    assert win._media_panel.label_id() == original
    assert win._undo_stack.isClean()
    assert "*" not in win.windowTitle()
    win.close()
    qapp.processEvents()


def test_text_items_restored_by_undo_are_wired(qapp, tmp_path):
    """Nach Undo sind Textfelder neue Objekte - Tippen muss weiter im Undo landen."""
    from PySide6.QtCore import QPointF, QRectF

    from ql_editor.items import RectItem, TextItem

    win = _temp_window(qapp, tmp_path)
    text = win._new_text(QPointF(50, 50))
    text.textCursor().insertText("Abc")
    win._canvas.cancel_editing()
    qapp.processEvents()
    win._add_item(RectItem(QRectF(0, 0, 40, 30), width_px=2), QPointF(10, 10))
    qapp.processEvents()
    win._act_undo.trigger()
    qapp.processEvents()

    restored = next(
        i for i in win._canvas.scene().items() if isinstance(i, TextItem)
    )
    assert restored is not text
    index = win._undo_stack.index()
    restored.start_editing()
    restored.textCursor().insertText("X")
    win._canvas.cancel_editing()
    qapp.processEvents()
    # Ein neuer Befehl ersetzt den Redo-Zweig: Index rueckt vor, Text "Text".
    assert win._undo_stack.index() == index + 1
    assert win._undo_stack.undoText() == "Text"

    # Leer gemacht: das Objekt bleibt, Undo stellt den Text wieder her.
    restored.start_editing()
    cursor = restored.textCursor()
    cursor.select(cursor.SelectionType.Document)
    cursor.removeSelectedText()
    win._canvas.cancel_editing()
    qapp.processEvents()
    assert restored in win._canvas.scene().items()
    assert restored.toPlainText() == ""
    assert win._undo_stack.undoText() == "Text"
    win._act_undo.trigger()
    qapp.processEvents()
    again = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    assert again.toPlainText() == "X"
    win.close()
    qapp.processEvents()


def test_cancelled_new_text_does_not_swallow_the_next_drag(qapp, tmp_path):
    """Leeres neues Textfeld bleibt; der folgende Zug ist ein eigener Schritt."""
    from PySide6.QtCore import QPointF, QRectF

    from ql_editor.items import RectItem, TextItem

    win = _temp_window(qapp, tmp_path)
    rect = RectItem(QRectF(0, 0, 40, 30), width_px=2)
    win._add_item(rect, QPointF(100, 80))
    qapp.processEvents()
    x0 = rect.pos().x()
    count = win._undo_stack.count()

    win._new_text(QPointF(20, 20))
    win._canvas.cancel_editing()
    qapp.processEvents()
    assert win._history_before is None
    assert win._undo_stack.count() == count + 1
    assert win._undo_stack.undoText() == "Text"
    assert any(isinstance(i, TextItem) for i in win._canvas.scene().items())
    win._canvas.gesture_begun.emit()
    rect._clamp_suspended = True
    rect.setPos(x0 + 30, rect.pos().y())
    rect._clamp_suspended = False
    win._canvas.items_changed.emit()
    qapp.processEvents()

    assert any(isinstance(i, TextItem) for i in win._canvas.scene().items())
    assert win._undo_stack.undoText() == "Bearbeiten"
    win._act_undo.trigger()
    qapp.processEvents()
    again = next(i for i in win._canvas.scene().items() if isinstance(i, RectItem))
    assert again.pos().x() == pytest.approx(x0)
    assert any(isinstance(i, TextItem) for i in win._canvas.scene().items())
    win.close()
    qapp.processEvents()


def test_clearing_an_existing_text_field_keeps_the_object(qapp, tmp_path):
    """Bestehenden Text leeren: das Objekt bleibt, Undo stellt den Text her."""
    from PySide6.QtCore import QPointF

    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    text = win._new_text(QPointF(40, 40))
    text.textCursor().insertText("Hallo")
    win._canvas.cancel_editing()
    qapp.processEvents()
    text = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    text.start_editing()
    cursor = text.textCursor()
    cursor.select(cursor.SelectionType.Document)
    cursor.removeSelectedText()
    win._canvas.cancel_editing()
    qapp.processEvents()

    assert win._undo_stack.undoText() == "Text"
    assert text in win._canvas.scene().items()
    assert text.toPlainText() == ""
    assert text.isSelected()
    win._act_undo.trigger()
    qapp.processEvents()
    restored = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    assert restored.toPlainText() == "Hallo"
    win.close()
    qapp.processEvents()


def test_redo_selects_only_the_item_that_was_selected(qapp, tmp_path):
    """Zwei Objekte am selben Ort: Redo stellt nur die vorherige Auswahl her."""
    from PySide6.QtCore import QRectF

    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(RectItem(QRectF(0, 0, 40, 30), width_px=2))
    win._add_item(RectItem(QRectF(0, 0, 50, 20), width_px=2))
    qapp.processEvents()
    assert sum(1 for i in win._canvas.ordered_items() if i.isSelected()) == 1

    win._act_undo.trigger()
    qapp.processEvents()
    win._act_redo.trigger()
    qapp.processEvents()

    selected = [item for item in win._canvas.ordered_items() if item.isSelected()]
    assert len(selected) == 1
    # Das zweite, zuletzt eingefuegte Rechteck (50 breit), nicht beide.
    assert selected[0].rect().width() == 50
    win.close()
    qapp.processEvents()


def test_band_change_stays_its_own_step_after_an_open_inspector_edit(qapp, tmp_path):
    """Spin ohne editingFinished, dann Bandwechsel: zwei getrennte Undo-Schritte."""
    from PySide6.QtWidgets import QSpinBox

    from ql_editor.items import TextItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(TextItem("X", font_pixel_size=40))
    qapp.processEvents()
    item = next(i for i in win._canvas.scene().items() if isinstance(i, TextItem))
    item.setSelected(True)
    qapp.processEvents()
    size = next(
        spin
        for spin in win._inspector.findChildren(QSpinBox)
        if spin.minimum() == 4 and spin.maximum() == 2000
    )
    size.setValue(size.value() + 4)
    assert win._inspector.edit_open is True
    original = win._media_panel.label_id()
    combo = win._media_panel._band_combo
    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    qapp.processEvents()

    names = [win._undo_stack.command(i).text() for i in range(win._undo_stack.count())]
    assert "Eigenschaften" in names
    assert "Band" in names
    assert names.index("Band") > names.index("Eigenschaften")
    assert win._inspector.edit_open is False
    assert win._media_panel.label_id() != original
    win.close()
    qapp.processEvents()


def test_content_beyond_a_margin_is_not_printed(qapp, tmp_path):
    """Der Rand schneidet ab: was hinter ihm liegt, fehlt im Druckbild -
    auch im Querformat, wo der rechte Rand die Bandbreite nicht veraendert."""
    from PySide6.QtCore import QRectF

    from ql_editor import media
    from ql_editor.items import RectItem

    win = _temp_window(qapp, tmp_path)
    win._add_item(RectItem(QRectF(0, 0, 690, 100), width_px=6))
    qapp.processEvents()
    win._media_panel._margin_spins["right"].setValue(0.0)
    qapp.processEvents()
    full = win._canvas.render_printable().convert("L")
    win._media_panel._margin_spins["right"].setValue(20.0)
    qapp.processEvents()
    cut = win._canvas.render_printable().convert("L")

    assert full.size == cut.size  # die Bandbreite bleibt gleich
    edge = cut.width - media.mm_to_dots(20.0) + 4  # knapp hinter dem Rand
    dark = [
        cut.getpixel((x, y)) < 128
        for x in range(edge, cut.width)
        for y in range(0, cut.height, 2)
    ]
    assert not any(dark)
    assert any(
        full.getpixel((x, y)) < 128
        for x in range(edge, full.width)
        for y in range(0, full.height, 2)
    )
    win.close()
    qapp.processEvents()


def _print_with_outcome(qapp, tmp_path, monkeypatch, outcome: str | None, error: str | None = None):
    from PySide6.QtCore import QObject, Signal

    from ql_editor import app as app_module

    class FakeWorker(QObject):
        succeeded = Signal(dict)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, image, label, config, options):
            super().__init__()

        def start(self) -> None:
            if error is not None:
                self.failed.emit(error)
            else:
                self.succeeded.emit({"outcome": outcome})
            self.finished.emit()

    monkeypatch.setattr(app_module, "PrintWorker", FakeWorker)
    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.168.178.62")
    win._on_print()
    qapp.processEvents()
    return win


def test_network_send_is_reported_as_sent_not_as_error(qapp, tmp_path, monkeypatch):
    win = _print_with_outcome(qapp, tmp_path, monkeypatch, "sent")
    assert "An Drucker gesendet" in win._last_job_label.text()
    assert "#b00020" not in win._last_job_label.styleSheet()
    assert [job.outcome for job in win._print_jobs] == ["sent"]
    win.close()
    qapp.processEvents()


def test_printer_error_is_marked_red_in_status_and_history(qapp, tmp_path, monkeypatch):
    win = _print_with_outcome(qapp, tmp_path, monkeypatch, None, error="Drucker nicht erreichbar")
    assert "#b00020" in win._last_job_label.styleSheet()
    assert win._print_jobs[-1].is_error
    assert win._print_jobs[-1].status_text() == "Nicht gesendet"
    win.close()
    qapp.processEvents()


def test_status_area_keeps_its_height_while_printing(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QObject, Signal

    from ql_editor import app as app_module

    class SlowWorker(QObject):
        succeeded = Signal(dict)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, image, label, config, options):
            super().__init__()

        def start(self) -> None:
            pass

    monkeypatch.setattr(app_module, "PrintWorker", SlowWorker)
    win = _temp_window(qapp, tmp_path)
    win._media_panel.set_network_host("192.168.178.62")
    qapp.processEvents()
    height_idle = win._status_stack.height()
    win._on_print()
    qapp.processEvents()
    assert win._status_stack.currentWidget() is win._feed_indicator
    assert win._status_stack.height() == height_idle
    assert not win._print_button.isEnabled()
    win._on_print_succeeded({"outcome": "printed"})
    win._on_print_finished()
    qapp.processEvents()
    assert win._status_stack.currentWidget() is win._last_job_label
    assert win._status_stack.height() == height_idle
    assert win._print_button.isEnabled()
    win.close()
    qapp.processEvents()


def test_print_and_history_buttons_share_height_and_row(qapp, tmp_path):
    win = _temp_window(qapp, tmp_path)
    page = win._right_pages.page(1)
    page.resize(176, 400)
    page.show()
    qapp.processEvents()
    assert win._print_button.height() == win._history_button.height()
    assert win._print_button.y() == win._history_button.y()
    win.close()
    qapp.processEvents()


def test_language_switch_keeps_session_print_history(qapp, tmp_path, monkeypatch):
    from ql_editor import app as app_module

    win = _print_with_outcome(qapp, tmp_path, monkeypatch, "sent")
    assert len(win._print_jobs) == 1
    previous = win._print_jobs[0]

    win.switch_language("en")
    qapp.processEvents()

    new = app_module._current_window
    assert new is not win
    assert new._print_jobs == [previous]
    assert "Sent to printer" in new._last_job_label.text()
    assert previous.model in new._last_job_label.text()

    new.close()
    qapp.processEvents()
