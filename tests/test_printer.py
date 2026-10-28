"""Tests fuer :mod:`ql_editor.printer`.

Es wird **nicht** real gedruckt: der Netzwerk-Versand wird gemockt, die
Statusabfrage mit einer kuenstlichen Antwort getestet. Der ``convert``-Pfad
laeuft echt gegen die Bibliothek.
"""

from __future__ import annotations

import logging
import os

import pytest
from PIL import Image
from ql_editor import printer
from ql_editor.media import get_label, get_model
from ql_editor.printer import (
    PrinterConfig,
    PrinterConnectionError,
    PrinterError,
    PrinterStatus,
    build_raster,
    build_raster_sequence,
    detect_label,
    print_image,
    print_images,
    printer_error_bits,
    printer_error_texts,
    probe_status,
    send_instructions,
    validate_for_print,
)

CONFIG = PrinterConfig(model="QL-820NWB", address="tcp://192.168.178.62:9100")

#: Befehl "print-media and print-quality" (``ESC i z``) - genau einmal pro
#: Etikett im Datenstrom, also gut zum Zaehlen der Kopien.
_MEDIA_QUALITY = b"\x1b\x69\x7a"


# --------------------------------------------------------------------------- #
# Konfiguration / Validierung
# --------------------------------------------------------------------------- #
def test_config_rejects_unknown_model():
    with pytest.raises(PrinterError):
        PrinterConfig(model="QL-NOPE")


# --------------------------------------------------------------------------- #
# Anschluss: Backend aus der Adresse
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("address", "backend", "readback"),
    [
        ("tcp://192.168.178.62:9100", "network", False),
        ("192.168.178.62:9100", "network", False),  # ohne Praefix auch Netzwerk
        ("usb://0x04f9:0x209b", "pyusb", True),
        ("0x04f9:0x209b", "pyusb", True),
        ("/dev/usb/lp0", "linux_kernel", True),
        ("file:///dev/usb/lp0", "linux_kernel", True),
        ("huhu", "network", False),  # unbekannt -> Netzwerk, kein stiller Absturz
    ],
)
def test_backend_is_derived_from_the_address(address, backend, readback):
    assert printer.backend_for_address(address) == backend
    assert printer.backend_supports_readback(backend) is readback
    assert PrinterConfig(address=address).backend == backend


def test_config_keeps_an_explicit_backend():
    config = PrinterConfig(address="tcp://192.168.178.62:9100", backend="pyusb")
    assert config.backend == "pyusb"


def test_only_usb_backends_have_a_readback():
    """Der Netzwerk-Anschluss ist eine reine Druckschnittstelle."""
    assert printer.READBACK_BACKENDS == {"pyusb", "linux_kernel"}
    assert printer.backend_supports_readback("network") is False


def test_usb_devices_normalizes_pyusb_identifiers(monkeypatch):
    """Die Seriennummer aus der Geraeteliste ist nicht rueckuebersetzbar.

    ``list_available_devices()`` liefert ``usb://0x04f9:0x2015_C5Z315686``;
    der pyusb-Konstruktor von brother_ql 0.9.4 macht daraus
    ``int("0x2015_C5Z315686", 16)`` und scheitert. Deshalb wird auf
    Hersteller:Produkt gekuerzt - und das muss weiter parsebar sein.
    """
    monkeypatch.setattr(
        printer,
        "backend_factory",
        lambda name: {
            "list_available_devices": lambda: [
                {"identifier": "usb://0x04f9:0x2015_C5Z315686"},
                {"identifier": "usb://0x04f9:0x209b"},
                {"identifier": "usb://0x04f9:0x2015_C5Z315686"},  # Dublette
            ]
        },
    )
    monkeypatch.setattr(printer.glob, "glob", lambda pattern: [])

    assert printer.usb_devices() == ["usb://0x04f9:0x2015", "usb://0x04f9:0x209b"]
    # Gegenprobe: das gekuerzte Format versteht brother_ql wirklich.
    from brother_ql.backends import guess_backend

    assert guess_backend("usb://0x04f9:0x2015") == "pyusb"


def test_usb_devices_includes_kernel_paths(monkeypatch):
    monkeypatch.setattr(
        printer, "backend_factory", lambda name: {"list_available_devices": list}
    )
    monkeypatch.setattr(
        printer.glob, "glob", lambda pattern: ["/dev/usb/lp1", "/dev/usb/lp0"]
    )
    assert printer.usb_devices() == ["/dev/usb/lp0", "/dev/usb/lp1"]


def test_usb_devices_survives_a_broken_libusb(monkeypatch):
    """Ohne libusb/Rechte gibt es eine leere Liste - keinen Absturz."""

    def boom(name):
        raise OSError("libusb nicht verfuegbar")

    monkeypatch.setattr(printer, "backend_factory", boom)
    monkeypatch.setattr(printer.glob, "glob", lambda pattern: [])
    assert printer.usb_devices() == []


def test_validate_rejects_wrong_width():
    label = get_label("50")  # 554 px
    wrong = Image.new("RGB", (500, 400), "white")
    with pytest.raises(PrinterError):
        validate_for_print(wrong, label)


def test_validate_rejects_red_on_mono_label():
    label = get_label("50")  # schwarz/weiss
    img = Image.new("RGB", (label.width_dots, 400), "white")
    with pytest.raises(PrinterError):
        validate_for_print(img, label, red=True)


# --------------------------------------------------------------------------- #
# Rasterdaten erzeugen
# --------------------------------------------------------------------------- #
def test_build_raster_endless_exact_width_without_resize(caplog):
    caplog.set_level(logging.WARNING, logger="brother_ql.conversion")
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG)
    assert isinstance(data, bytes) and len(data) > 0
    assert "Need to resize" not in caplog.text


def test_build_raster_wrong_width_is_rejected_before_convert():
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots - 10, 472), "white")
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG)


def test_build_raster_die_cut_exact_size():
    label = get_label("62x100")  # 696 x 1109
    img = Image.new("RGB", label.dots_printable, "white")
    data = build_raster(img, label, CONFIG)
    assert len(data) > 0


def test_build_raster_die_cut_wrong_size():
    label = get_label("62x100")
    img = Image.new("RGB", (label.width_dots, 500), "white")  # Hoehe falsch
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG)


def test_build_raster_red_two_color_label():
    label = get_label("62red")
    img = Image.new("RGB", (label.width_dots, 400), "white")
    data = build_raster(img, label, CONFIG, red=True)
    assert len(data) > 0


def test_build_raster_red_rejected_for_mono_label():
    label = get_label("62")  # schwarz/weiss
    img = Image.new("RGB", (label.width_dots, 400), "white")
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG, red=True)


def _flags(data: bytes, command: bytes) -> list[int]:
    """Parameterbytes aller ``command``-Befehle im Strom (pro Etikett einer)."""
    parts = data.split(command)[1:]
    return [part[0] for part in parts if part]


def test_build_raster_cut_none_sends_no_auto_cut_and_no_cut_at_end():
    """Nicht schneiden: kein Auto Cut (sonst Schnitt je Etikett) und
    "Cut at End" aus - der Streifen bleibt am Band."""
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, cut_mode=printer.CUT_NONE)

    assert len(data) > 0
    auto_cut = _flags(data, b"\x1b\x69\x4d")
    assert auto_cut == [0] * len(auto_cut) and auto_cut  # Auto Cut ausdruecklich aus
    flags = _flags(data, b"\x1b\x69\x4b")
    assert flags, "Expanded Mode fehlt"
    assert all(not f & printer.CUT_AT_END_BIT for f in flags)


def test_build_raster_copies_repeat_the_label():
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    one = build_raster(img, label, CONFIG)
    three = build_raster(img, label, CONFIG, copies=3)
    assert three.count(_MEDIA_QUALITY) == 3
    assert one.count(_MEDIA_QUALITY) == 1


def test_build_raster_cut_each_is_the_default():
    """Nach jeder Kopie: Auto Cut an (Bit 7) und "Cut at End" an - in jedem
    der drei Etikett-Bloecke, denn der Kopf wiederholt sich pro Etikett."""
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, copies=3)

    assert b"\x1b\x69\x41\x01" in data  # "cut each * labels"
    auto_cut = _flags(data, b"\x1b\x69\x4d")
    assert auto_cut == [printer.AUTO_CUT_BIT] * 3
    cut_at_end = _flags(data, b"\x1b\x69\x4b")
    assert cut_at_end == [printer.CUT_AT_END_BIT] * 3


def test_build_raster_cut_at_end_turns_auto_cut_off():
    """Erst am Ende schneiden: Auto Cut *aus*, "Cut at End" *an*.

    Genau das war der Fehler in der ersten Fassung: "Auto Cut" heisst beim QL
    "nach jedem Etikett schneiden" (Raster Command Reference, ESC i M Bit 7) -
    mit eingeschaltetem Auto Cut kommt der Streifen nie zusammenhaengend heraus,
    egal welche Seitenzahl in ESC i A steht.
    """
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, copies=3, cut_mode=printer.CUT_AT_END)

    assert not any(f & printer.AUTO_CUT_BIT for f in _flags(data, b"\x1b\x69\x4d"))
    cut_at_end = _flags(data, b"\x1b\x69\x4b")
    assert cut_at_end == [printer.CUT_AT_END_BIT] * 3


def test_build_raster_cut_at_end_handles_every_copy_block():
    """Jeder Block muss stimmen - er wird pro Etikett geschrieben.

    Bei fünf Kopien also fuenfmal; ein einzelnes Ersetzen am Anfang (der erste
    Versuch) haette nur den ersten Block erwischt.
    """
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, copies=5, cut_mode=printer.CUT_AT_END)

    assert len(_flags(data, b"\x1b\x69\x4b")) == 5
    assert _flags(data, b"\x1b\x69\x4b") == [printer.CUT_AT_END_BIT] * 5
    # Und bei einer Kopie genauso (Schnitt danach, nicht davor).
    single = build_raster(img, label, CONFIG, copies=1, cut_mode=printer.CUT_AT_END)
    assert _flags(single, b"\x1b\x69\x4b") == [printer.CUT_AT_END_BIT]


def test_build_raster_cut_at_end_keeps_the_other_flags():
    """Beim Umbau duerfen 600 dpi und Rotdruck nicht verloren gehen."""
    label = get_label("50")
    # 600 dpi in Bandlaufrichtung: der Renderer liefert doppelt so viele
    # Zeilen - die Breite muss der Renderfaktor mitbringen (printer prueft das).
    img = Image.new("RGB", (label.width_dots * 2, 944), "white")
    data = build_raster(
        img, label, CONFIG, copies=2, cut_mode=printer.CUT_AT_END, dpi_600=True
    )

    flags = _flags(data, b"\x1b\x69\x4b")
    assert all(f & 0x40 for f in flags), "600-dpi-Bit fehlt"
    assert all(f & printer.CUT_AT_END_BIT for f in flags)


def test_build_raster_cut_leaves_payload_esc_im_untouched(monkeypatch):
    """Schnitt schreibt nur echte Befehle - Bildbytes mit ESC i M bleiben."""
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    sentinel = b"\x1b\x69\x4d\xff"

    original = printer._JobRaster.add_raster_data

    def inject(self, image, second_image=None):
        original(self, image, second_image)
        self.data += sentinel

    monkeypatch.setattr(printer._JobRaster, "add_raster_data", inject)
    data = build_raster(img, label, CONFIG, cut_mode=printer.CUT_AT_END, copies=1)
    assert sentinel in data
    # Echte Auto-Cut-Befehle sind aus; das Payload-Byte \xff bleibt \xff
    # (eine Byte-Suche haette Bit 0x40 geloescht -> \xbf).
    head, _, _ = data.partition(sentinel)
    assert _flags(head, b"\x1b\x69\x4d") == [0]


def test_validate_rejects_wrong_die_cut_height():
    label = get_label("62x100")
    img = Image.new("RGB", (label.width_dots, label.height_dots - 10), "white")
    with pytest.raises(PrinterError, match="Bildhöhe"):
        validate_for_print(img, label)


@pytest.mark.parametrize("copies", [0, -1, printer.COPIES_MAX + 1])
def test_build_raster_rejects_impossible_copies(copies):
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG, copies=copies)


def test_build_raster_rejects_unknown_cut_mode():
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG, cut_mode="vielleicht")


def test_build_raster_without_a_cutter_needs_cut_none():
    """Der QL-500 hat keine Schneideeinrichtung - das wird gesagt, nicht ignoriert."""
    label = get_label("29")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    config = PrinterConfig(model="QL-500", address=CONFIG.address)
    with pytest.raises(PrinterError):
        build_raster(img, label, config, cut_mode=printer.CUT_EACH)
    data = build_raster(img, label, config, cut_mode=printer.CUT_NONE)
    assert len(data) > 0


def _capture_raster_images(monkeypatch) -> list[tuple[int, int]]:
    """Fange die Bildgroessen ab, die ``convert`` an den Drucker gibt."""
    from brother_ql.raster import BrotherQLRaster

    sizes: list[tuple[int, int]] = []
    original = BrotherQLRaster.add_raster_data

    def spy(self, image_black, image_red=None):
        sizes.append(image_black.size)
        return original(self, image_black, image_red)

    monkeypatch.setattr(BrotherQLRaster, "add_raster_data", spy)
    return sizes


def _expanded_mode_flags(data: bytes) -> int:
    """Das Flag-Byte des ``ESC i K`` (Expanded Mode) aus den Rasterdaten."""
    marker = b"\x1b\x69\x4b"
    index = data.index(marker)
    return data[index + len(marker)]


def test_build_raster_600dpi_sets_high_resolution_and_doubles_rows(monkeypatch):
    """600-dpi-Modus: Bit 7 an, doppelt so viele Zeilen.

    Die Raster Command Reference der QL-800-Reihe: ``ESC i K`` Bit 7
    ("High resolution printing") - "1: It prints at 600 dpi in the paper length
    direction". Der Drucker setzt die Zeilen also mit halbem Abstand; fuer
    dieselbe Laenge braucht das Bild deshalb doppelt so viele Zeilen (und
    ``convert`` erwartet genau das: ``dots_expected = [el*2]``).
    """
    label = get_label("62")  # 696 px breit
    device_width = get_model(CONFIG.model).device_pixel_width
    sizes = _capture_raster_images(monkeypatch)

    design_height = 100  # Dots der Designflaeche in Bandlaufrichtung
    normal = build_raster(
        Image.new("RGB", (label.width_dots, design_height), "white"), label, CONFIG
    )
    high = build_raster(
        Image.new(
            "RGB",
            (
                label.width_dots * printer.DPI_600_SCALE,
                design_height * printer.DPI_600_SCALE,
            ),
            "white",
        ),
        label,
        CONFIG,
        dpi_600=True,
    )

    assert _expanded_mode_flags(normal) & 0x40 == 0
    assert _expanded_mode_flags(high) & 0x40 == 0x40

    # convert() halbiert die doppelte Breite wieder (Bandbreite) und fuellt auf
    # die Druckkopfbreite auf - die Zeilenzahl bleibt doppelt.
    rows_normal, rows_high = sizes[0][1], sizes[1][1]
    assert sizes[0][0] == device_width == sizes[1][0]
    assert rows_high == rows_normal * printer.DPI_600_SCALE
    # Gleiche Laenge: die 600-dpi-Zeilen sind halb so lang wie die 300-dpi-Zeilen.
    assert rows_normal / 300 == pytest.approx(rows_high / 600)


def test_build_raster_600dpi_needs_the_scaled_size():
    """Ohne Renderfaktor 2 lehnt der Druckpfad ab, statt halb zu drucken."""
    label = get_label("62")
    img = Image.new("RGB", (label.width_dots, 100), "white")
    with pytest.raises(PrinterError):
        build_raster(img, label, CONFIG, dpi_600=True)


def test_build_raster_600dpi_die_cut_keeps_the_label_size(monkeypatch):
    """Auch auf Formetiketten bleibt das 600-dpi-Bild bandbreit und doppelt hoch."""
    label = get_label("62x100")
    sizes = _capture_raster_images(monkeypatch)
    width, height = label.dots_printable
    build_raster(
        Image.new(
            "RGB",
            (width * printer.DPI_600_SCALE, height * printer.DPI_600_SCALE),
            "white",
        ),
        label,
        CONFIG,
        dpi_600=True,
    )
    assert sizes[0][1] == height * printer.DPI_600_SCALE


def test_validate_accepts_the_600dpi_scale():
    label = get_label("50")
    validate_for_print(
        Image.new("RGB", (label.width_dots * 2, 400), "white"), label, scale=2
    )
    with pytest.raises(PrinterError):
        validate_for_print(
            Image.new("RGB", (label.width_dots, 400), "white"), label, scale=2
        )


# --------------------------------------------------------------------------- #
# Senden (gemockt)
# --------------------------------------------------------------------------- #
def test_print_images_logs_page_count_including_copies(monkeypatch, caplog):
    """Das Log zaehlt Varianten × Kopien, nicht nur die Bildliste."""

    def fake_send(*_args, **_kwargs):
        return {"outcome": "sent", "did_print": False}

    monkeypatch.setattr(printer, "send", fake_send)
    label = get_label("50")
    first = Image.new("RGB", (label.width_dots, 80), "white")
    second = Image.new("RGB", (label.width_dots, 90), "white")
    caplog.set_level(logging.INFO, logger="ql_editor.printer")
    print_images([first, second], label, CONFIG, copies=2)
    assert "Sende 4 Etiketten" in caplog.text


def test_print_image_calls_send_with_config(monkeypatch):
    captured = {}

    def fake_send(
        instructions, printer_identifier=None, backend_identifier=None, blocking=True
    ):
        captured.update(
            instructions=instructions,
            identifier=printer_identifier,
            backend=backend_identifier,
            blocking=blocking,
        )
        return {"outcome": "sent", "did_print": False}

    monkeypatch.setattr(printer, "send", fake_send)
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    status = print_image(img, label, CONFIG)
    assert status["outcome"] == "sent"
    assert captured["identifier"] == CONFIG.address
    assert captured["backend"] == "network"
    assert isinstance(captured["instructions"], bytes)


def test_send_instructions_connection_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(printer, "send", boom)
    with pytest.raises(PrinterConnectionError):
        send_instructions(b"\x00", CONFIG)


# --------------------------------------------------------------------------- #
# Status / Erkennung
# --------------------------------------------------------------------------- #
class _FakeBackend:
    def __init__(self, address):
        self.address = address
        self._payload = b""

    def write(self, data):
        pass

    def read(self, length=32):
        return self._payload

    def dispose(self):
        pass


def _install_fake_backend(monkeypatch, payload: bytes):
    def factory(name):
        def cls(address):
            b = _FakeBackend(address)
            b._payload = payload
            return b

        return {"backend_class": cls, "list_available_devices": list}

    monkeypatch.setattr(printer, "backend_factory", factory)


def _status_bytes(
    media_width=50, media_type=0x0A, media_length=0, errors=(0, 0)
) -> bytes:
    data = bytearray(32)
    data[0:3] = b"\x80\x20\x42"
    data[8] = errors[0]
    data[9] = errors[1]
    data[10] = media_width
    data[11] = media_type
    data[17] = media_length
    data[18] = 0x00
    data[19] = 0x00
    return bytes(data)


def test_probe_status_parses_response(monkeypatch):
    _install_fake_backend(monkeypatch, _status_bytes(media_width=50))
    status = probe_status(CONFIG, timeout=0.2)
    assert isinstance(status, PrinterStatus)
    assert status.media_width_mm == 50
    assert status.media_type == "Continuous length tape"
    assert status.has_errors is False


def test_probe_status_returns_none_without_readback(monkeypatch):
    _install_fake_backend(monkeypatch, b"")  # keine Antwort
    assert probe_status(CONFIG, timeout=0.1) is None


def test_probe_status_returns_none_on_connection_error(monkeypatch):
    def factory(name):
        raise OSError("no route to host")

    monkeypatch.setattr(printer, "backend_factory", factory)
    assert probe_status(CONFIG, timeout=0.1) is None


def test_detect_label_endless(monkeypatch):
    monkeypatch.setattr(
        printer,
        "probe_status",
        lambda cfg, timeout=2.0: PrinterStatus(
            status_type="Reply to status request",
            phase_type="Waiting to receive",
            media_type="Continuous length tape",
            media_width_mm=50,
            media_length_mm=0,
        ),
    )
    assert detect_label(CONFIG).identifier == "50"


def test_detect_label_die_cut_matches_length(monkeypatch):
    monkeypatch.setattr(
        printer,
        "probe_status",
        lambda cfg, timeout=2.0: PrinterStatus(
            status_type="Reply to status request",
            phase_type="Waiting to receive",
            media_type="Die-cut labels",
            media_width_mm=62,
            media_length_mm=100,
        ),
    )
    assert detect_label(CONFIG).identifier == "62x100"


def test_detect_label_none_without_status(monkeypatch):
    monkeypatch.setattr(printer, "probe_status", lambda cfg, timeout=2.0: None)
    assert detect_label(CONFIG) is None


def test_detect_label_respects_model_restriction(monkeypatch):
    # 102 mm gibt es nur fuer QL-1050/1060N.
    monkeypatch.setattr(
        printer,
        "probe_status",
        lambda cfg, timeout=2.0: PrinterStatus(
            status_type="Reply to status request",
            phase_type="Waiting to receive",
            media_type="Continuous length tape",
            media_width_mm=102,
            media_length_mm=0,
        ),
    )
    assert detect_label(CONFIG) is None


# --------------------------------------------------------------------------- #
# USB-Kennung -> Modell
# --------------------------------------------------------------------------- #
def test_usb_id_from_identifier():
    assert printer.usb_id_from_identifier("usb://0x04f9:0x2042") == "04f9:2042"
    # Serialnummer (mit Unterstrich) und Pfadform werden toleriert.
    assert (
        printer.usb_id_from_identifier("usb://0x04f9:0x2015_C5Z315686") == "04f9:2015"
    )
    assert printer.usb_id_from_identifier("usb://0x04f9:0x2015/SN") == "04f9:2015"
    assert printer.usb_id_from_identifier("/dev/usb/lp0") is None
    assert printer.usb_id_from_identifier("usb://kaputt") is None
    assert printer.usb_id_from_identifier("usb://0xzz:0x2042") is None


def test_usb_id_for_path_reads_sysfs(tmp_path):
    # Layout wie im echten sysfs: class/usbmisc/lp1/device -> Interface-Verzeichnis,
    # eine Ebene darueber liegt das Geraet mit idVendor/idProduct.
    interface = tmp_path / "devices" / "1-9:1.0"
    interface.mkdir(parents=True)
    (tmp_path / "devices" / "idVendor").write_text("04f9\n")
    (tmp_path / "devices" / "idProduct").write_text("2042\n")
    (tmp_path / "class" / "usbmisc" / "lp1").mkdir(parents=True)
    (tmp_path / "class" / "usbmisc" / "lp1" / "device").symlink_to(interface)

    assert (
        printer.usb_id_for_path("/dev/usb/lp1", sysfs_root=str(tmp_path)) == "04f9:2042"
    )
    assert (
        printer.usb_id_for_path("file:///dev/usb/lp1", sysfs_root=str(tmp_path))
        == "04f9:2042"
    )
    assert printer.usb_id_for_path("/dev/usb/lp7", sysfs_root=str(tmp_path)) is None


def test_model_for_address():
    assert printer.model_for_address("usb://0x04f9:0x2042") == "QL-700"
    assert printer.model_for_address("usb://0x04f9:0x209d") == "QL-820NWB"
    assert printer.model_for_address("usb://0x04f9:0x9999") is None
    # Netzwerk verraet kein Modell - und /dev/usb/lp0 gibt es hier nicht.
    assert printer.model_for_address("tcp://192.168.178.62:9100") is None
    assert printer.model_for_address("/dev/usb/lp0") is None


def test_usb_models_are_known_to_the_library():
    from ql_editor import media

    known = {model.identifier for model in media.all_models()}
    assert set(printer.USB_MODELS.values()) <= known


def test_usb_device_detail_names_backend_and_model():
    assert printer.usb_device_detail("usb://0x04f9:0x2042") == (
        "usb://0x04f9:0x2042  (libusb, QL-700)"
    )
    assert printer.usb_device_detail("/dev/usb/lp0") == (
        "/dev/usb/lp0  (Kernel-Anschluss)"
    )
    # Kein USB - dann keine irrefuehrende Beschriftung.
    assert printer.usb_device_detail("tcp://192.168.178.62:9100") == (
        "tcp://192.168.178.62:9100"
    )


def test_usb_device_label_names_the_model_only(monkeypatch):
    """In der Liste zaehlt der Druckertyp, nicht der Anschlusspfad."""
    assert printer.usb_device_label("usb://0x04f9:0x2042") == "QL-700 (USB)"
    # Unbekannte Kennung: dann bleibt die Adresse stehen (besser als nichts).
    assert printer.usb_device_label("usb://0x04f9:0x9999") == "usb://0x04f9:0x9999"


def test_usb_device_labels_keep_identical_printers_apart(monkeypatch):
    monkeypatch.setattr(printer, "model_for_address", lambda address: "QL-700")
    labels = printer.usb_device_labels(
        ["/dev/usb/lp0", "/dev/usb/lp1", "usb://0x04f9:0x2042"]
    )
    # Gleiches Modell: jeder Eintrag bekommt seinen Anschlusspfad dazu.
    assert labels == [
        "QL-700 (USB) [lp0]",
        "QL-700 (USB) [lp1]",
        "QL-700 (USB) [04f9:2042]",
    ]


def test_usb_printers_offer_one_entry_per_printer(monkeypatch):
    """Derselbe Drucker ueber Kernel *und* libusb ist ein Eintrag."""
    monkeypatch.setattr(
        printer,
        "usb_devices",
        lambda: ["usb://0x04f9:0x2042", "/dev/usb/lp1", "/dev/usb/lp0"],
    )
    monkeypatch.setattr(
        printer,
        "model_for_address",
        lambda address: (
            "QL-700" if address in ("usb://0x04f9:0x2042", "/dev/usb/lp1") else None
        ),
    )

    # Der libusb-Eintrag faellt weg, weil der Kernel-Anschluss denselben
    # Drucker eindeutig adressiert; lp0 steht fuer ein anderes Geraet.
    assert printer.usb_printers() == ["/dev/usb/lp1", "/dev/usb/lp0"]


def test_usb_printers_keep_libusb_when_there_is_no_kernel_node(monkeypatch):
    monkeypatch.setattr(printer, "usb_devices", lambda: ["usb://0x04f9:0x2042"])
    monkeypatch.setattr(printer, "model_for_address", lambda address: "QL-700")
    assert printer.usb_printers() == ["usb://0x04f9:0x2042"]


def test_preferred_usb_address_migrates_an_old_libusb_entry(monkeypatch):
    """Eine gespeicherte libusb-Adresse zeigt danach auf den Kernel-Anschluss."""
    monkeypatch.setattr(
        printer, "usb_devices", lambda: ["usb://0x04f9:0x2042", "/dev/usb/lp1"]
    )
    monkeypatch.setattr(printer, "model_for_address", lambda address: "QL-700")

    assert printer.preferred_usb_address("usb://0x04f9:0x2042") == "/dev/usb/lp1"
    assert printer.preferred_usb_address("/dev/usb/lp1") == "/dev/usb/lp1"
    # Netzwerkadressen bleiben unberuehrt.
    assert printer.preferred_usb_address("tcp://192.168.178.62:9100") == (
        "tcp://192.168.178.62:9100"
    )


def test_preferred_usb_address_keeps_libusb_when_two_same_models(monkeypatch):
    """Zwei gleiche Modelle: libusb nicht still auf den ersten Kernel-Knoten legen."""
    monkeypatch.setattr(
        printer,
        "usb_devices",
        lambda: ["usb://0x04f9:0x2042", "/dev/usb/lp0", "/dev/usb/lp1"],
    )
    monkeypatch.setattr(printer, "model_for_address", lambda address: "QL-700")

    assert printer.preferred_usb_address("usb://0x04f9:0x2042") == "usb://0x04f9:0x2042"


# --------------------------------------------------------------------------- #
# Netzwerkadresse: nur die IP eintippen
# --------------------------------------------------------------------------- #
def test_parse_network_address_fills_prefix_and_port():
    assert (
        printer.parse_network_address("192.168.178.62") == "tcp://192.168.178.62:9100"
    )
    assert (
        printer.parse_network_address(" 192.168.178.62 ") == "tcp://192.168.178.62:9100"
    )
    assert (
        printer.parse_network_address("tcp://192.168.178.62:9100")
        == "tcp://192.168.178.62:9100"
    )
    assert (
        printer.parse_network_address("192.168.178.62/") == "tcp://192.168.178.62:9100"
    )
    assert printer.parse_network_address("ql820.local") == "tcp://ql820.local:9100"
    # Abweichender Port bleibt erhalten.
    assert (
        printer.parse_network_address("192.168.178.62:9101")
        == "tcp://192.168.178.62:9101"
    )
    # IPv6 in Klammern wird nicht am Doppelpunkt zerschnitten.
    assert printer.parse_network_address("[::1]") == "tcp://[::1]:9100"
    assert printer.parse_network_address("[::1]:9101") == "tcp://[::1]:9101"
    assert printer.parse_network_address("") == ""
    assert printer.parse_network_address("   ") == ""
    assert printer.parse_network_address("tcp://") == ""


def test_network_host_hides_only_the_default_port():
    assert printer.network_host("tcp://192.168.178.62:9100") == "192.168.178.62"
    assert printer.network_host("tcp://192.168.178.62:9101") == "192.168.178.62:9101"
    assert printer.network_host("192.168.178.62") == "192.168.178.62"
    assert printer.network_host("[::1]:9100") == "[::1]"


def test_network_address_survives_the_display_roundtrip():
    for address in (
        "tcp://192.168.178.62:9100",
        "tcp://ql820.local:9101",
        "tcp://[::1]:9100",
    ):
        assert printer.parse_network_address(printer.network_host(address)) == address


# --------------------------------------------------------------------------- #
# Schreibrechte am Geraeteknoten (Grund fuer "Zugriff einrichten")
# --------------------------------------------------------------------------- #
# Als root sagt os.access() immer True - dann ist hier nichts zu pruefen.
needs_unprivileged_user = pytest.mark.skipif(
    os.geteuid() == 0, reason="Schreibrechte lassen sich als root nicht pruefen"
)


@needs_unprivileged_user
def test_writable_reports_missing_node_and_rights(tmp_path):
    assert printer.writable(tmp_path / "gibtsnicht") is None

    node = tmp_path / "lp1"
    node.write_text("")
    node.chmod(0o600)
    assert printer.writable(node) is True

    node.chmod(0o000)
    assert printer.writable(node) is False


@needs_unprivileged_user
def test_usb_access_checks_the_kernel_printer_node(tmp_path):
    dev_root = tmp_path / "dev"
    node = dev_root / "usb" / "lp1"
    node.parent.mkdir(parents=True)
    node.write_text("")
    node.chmod(0o600)

    assert printer.usb_access("/dev/usb/lp1", dev_root=str(dev_root)) is True
    assert printer.usb_access("file:///dev/usb/lp1", dev_root=str(dev_root)) is True

    node.chmod(0o000)
    assert printer.usb_access("/dev/usb/lp1", dev_root=str(dev_root)) is False

    # Abgesteckt oder unbekannt: keine Aussage.
    assert printer.usb_access("/dev/usb/lp9", dev_root=str(dev_root)) is None
    assert printer.usb_access("/dev/ttyUSB0", dev_root=str(dev_root)) is None


@needs_unprivileged_user
def test_usb_access_resolves_the_raw_node_for_libusb(tmp_path):
    sysfs_root = tmp_path / "sys"
    device = sysfs_root / "bus" / "usb" / "devices" / "1-9"
    device.mkdir(parents=True)
    (device / "idVendor").write_text("04f9\n")
    (device / "idProduct").write_text("2042\n")
    (device / "busnum").write_text("1\n")
    (device / "devnum").write_text("5\n")

    dev_root = tmp_path / "dev"
    node = dev_root / "bus" / "usb" / "001" / "005"
    node.parent.mkdir(parents=True)
    node.write_text("")
    node.chmod(0o600)

    kwargs = {"sysfs_root": str(sysfs_root), "dev_root": str(dev_root)}
    assert printer.usb_access("usb://0x04f9:0x2042", **kwargs) is True

    node.chmod(0o000)
    assert printer.usb_access("usb://0x04f9:0x2042", **kwargs) is False

    # Anderes Geraet und Netzwerk: keine Aussage.
    assert printer.usb_access("usb://0x04f9:0x209d", **kwargs) is None
    assert printer.usb_access("tcp://192.168.178.62:9100", **kwargs) is None
    assert printer.usb_access("", **kwargs) is None

    # Geraet bekannt, aber kein Knoten im dev_root (z. B. anderer Namespace).
    empty_dev = tmp_path / "leer"
    assert (
        printer.usb_access(
            "usb://0x04f9:0x2042",
            sysfs_root=str(sysfs_root),
            dev_root=str(empty_dev),
        )
        is None
    )


def test_copies_are_one_job_with_form_feeds_between_pages():
    """Zwischen den Kopien ``0x0C`` (Form Feed), nur am Ende ``0x1A``.

    Mit ``0x1A`` nach jeder Kopie wuerde der Drucker jede Kopie als fertigen
    Auftrag behandeln und danach schneiden - unabhaengig von Auto Cut.
    """
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, copies=3, cut_mode=printer.CUT_AT_END)

    starts = []
    i = data.find(b"\x1b\x69\x53")  # Beginn jeder Seite (Statusanfrage)
    while i >= 0:
        starts.append(i)
        i = data.find(b"\x1b\x69\x53", i + 1)
    assert len(starts) == 3
    assert [data[s - 1] for s in starts[1:]] == [0x0C, 0x0C]
    assert data[-1] == 0x1A


def test_build_raster_sequence_repeats_each_variant_then_the_next():
    """Kopien haengen am einzelnen Etikett, nicht als Kreuzprodukt dazwischen."""
    label = get_label("50")
    first = Image.new("RGB", (label.width_dots, 200), "white")
    second = Image.new("RGB", (label.width_dots, 240), "black")
    single = build_raster(first, label, CONFIG, copies=2)
    sequence = build_raster_sequence(
        [first, second], label, CONFIG, copies=2, cut_mode=printer.CUT_AT_END
    )
    assert build_raster_sequence([first], label, CONFIG, copies=2) == single
    assert sequence.count(_MEDIA_QUALITY) == 4
    assert sequence != single

    starts = []
    cursor = sequence.find(b"\x1b\x69\x53")
    while cursor >= 0:
        starts.append(cursor)
        cursor = sequence.find(b"\x1b\x69\x53", cursor + 1)
    assert len(starts) == 4
    assert [sequence[pos - 1] for pos in starts[1:]] == [0x0C, 0x0C, 0x0C]
    assert sequence[-1] == 0x1A


def test_build_raster_sequence_rejects_empty_and_oversized_jobs():
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 80), "white")
    with pytest.raises(PrinterError):
        build_raster_sequence([], label, CONFIG)
    with pytest.raises(PrinterError):
        build_raster_sequence([img, img], label, CONFIG, copies=50)


def test_printer_error_texts_read_the_bits_from_the_top():
    """Bit 0 ist das hoechste Bit des ersten Bytes - so steht es im MIB."""
    assert printer_error_texts(b"\x00\x00") == ()
    assert printer_error_texts(b"\x80\x00") == ("Papier wird knapp",)
    assert printer_error_texts(b"\x40\x00") == ("Kein Papier oder Band eingelegt",)
    assert printer_error_texts(b"\x00\x02") == ("Wartung überfällig",)
    assert printer_error_texts(b"\x00\x01") == ()
    assert len(printer_error_texts(b"\xff\xff")) == 15
    assert printer_error_bits(b"\x88\x01") == (0, 4, 15)


def test_loaded_label_is_stored_per_printer(tmp_path):
    from PySide6.QtCore import QSettings
    from ql_editor.settings import AppSettings

    settings = AppSettings(
        QSettings(str(tmp_path / "qlinux.ini"), QSettings.Format.IniFormat)
    )
    assert settings.loaded_label(CONFIG.address) is None
    settings.set_loaded_label(CONFIG.address, "62")
    settings.set_loaded_label("tcp://192.0.2.99:9100", "50")
    assert settings.loaded_label(CONFIG.address) == "62"
    assert settings.loaded_label("tcp://192.0.2.99:9100") == "50"
    settings.forget_loaded_label(CONFIG.address)
    assert settings.loaded_label(CONFIG.address) is None
    assert settings.loaded_label("tcp://192.0.2.99:9100") == "50"
