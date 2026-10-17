"""Tests fuer :mod:`ql_editor.printer`.

Es wird **nicht** real gedruckt: der Netzwerk-Versand wird gemockt, die
Statusabfrage mit einer kuenstlichen Antwort getestet. Der ``convert``-Pfad
laeuft echt gegen die Bibliothek.
"""

from __future__ import annotations

import logging

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
    detect_label,
    print_image,
    probe_status,
    send_instructions,
    validate_for_print,
)

CONFIG = PrinterConfig(model="QL-820NWB", address="tcp://192.168.178.62:9100")


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
        printer, "backend_factory", lambda name: {"list_available_devices": lambda: []}
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


def test_build_raster_no_cut_option():
    label = get_label("50")
    img = Image.new("RGB", (label.width_dots, 472), "white")
    data = build_raster(img, label, CONFIG, cut=False)
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
            (label.width_dots * printer.DPI_600_SCALE, design_height * printer.DPI_600_SCALE),
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
        Image.new("RGB", (width * printer.DPI_600_SCALE, height * printer.DPI_600_SCALE), "white"),
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
def test_print_image_calls_send_with_config(monkeypatch):
    captured = {}

    def fake_send(instructions, printer_identifier=None, backend_identifier=None, blocking=True):
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

        return {"backend_class": cls, "list_available_devices": lambda: []}

    monkeypatch.setattr(printer, "backend_factory", factory)


def _status_bytes(media_width=50, media_type=0x0A, media_length=0, errors=(0, 0)) -> bytes:
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
