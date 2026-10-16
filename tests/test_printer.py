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
from ql_editor.media import get_label
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
