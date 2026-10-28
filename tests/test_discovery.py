"""Druckersuche im Netzwerk - Parser an echten Paketen, ohne Netz.

Die Rohpakete in ``tests/data`` sind echte Antworten eines QL-820NWB
(mDNS und SNMP); MAC-abgeleitete Namen und die Adresse sind anonymisiert
(laengenerhaltend, die Pakete bleiben also unveraendert lesbar).
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from ql_editor import discovery

DATA = Path(__file__).parent / "data"
MDNS_ANSWER = (DATA / "mdns_ql820nwb.bin").read_bytes()
MDNS_FOREIGN = (DATA / "mdns_epson_wf7720.bin").read_bytes()
SNMP_ANSWER = (DATA / "snmp_ql820nwb.bin").read_bytes()


def _record(name: str, rtype: int, data: bytes) -> bytes:
    """Ein Resource Record ohne Namenskomprimierung."""
    return (
        discovery.dns_name(name) + struct.pack(">HHIH", rtype, 1, 120, len(data)) + data
    )


def _txt(*entries: str) -> bytes:
    return b"".join(bytes([len(entry)]) + entry.encode() for entry in entries)


def _answer_without_address() -> bytes:
    """Minimale mDNS-Antwort mit PTR, SRV und TXT - aber ohne A-Record."""
    service = discovery.MDNS_SERVICE
    instance = f"Brother QL-820NWB.{service}"
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 3, 0, 0)
    return (
        header
        + _record(service, discovery.TYPE_PTR, discovery.dns_name(instance))
        + _record(
            instance,
            discovery.TYPE_SRV,
            struct.pack(">HHH", 0, 0, 9100) + discovery.dns_name("printer.local"),
        )
        + _record(
            instance,
            discovery.TYPE_TXT,
            _txt("ty=Brother QL-820NWB", "usb_MDL=QL-820NWB"),
        )
    )


def test_discovery_reads_a_real_mdns_answer():
    """Adresse, Port und Modell stehen in der Antwort des Druckers."""
    printers = discovery.parse_mdns_response(MDNS_ANSWER)

    assert len(printers) == 1
    printer = printers[0]
    assert printer.host == "192.0.2.62"
    assert printer.port == 9100
    assert printer.model_id == "QL-820NWB"
    assert printer.source == discovery.SOURCE_MDNS
    assert printer.address == "tcp://192.0.2.62:9100"
    assert printer.label() == "192.0.2.62 (QL-820NWB)"


def test_discovery_falls_back_to_the_sender_address():
    """Ohne A-Record im Paket gilt die Adresse, die geantwortet hat."""
    printers = discovery.parse_mdns_response(_answer_without_address(), "192.0.2.99")

    assert [printer.host for printer in printers] == ["192.0.2.99"]
    assert printers[0].model_id == "QL-820NWB"


def test_discovery_ignores_foreign_printers():
    """Ein Fremddrucker am selben Dienst darf nicht in der Liste stehen."""
    assert b"EPSON" in MDNS_FOREIGN  # Fixture ist wirklich der Fremddrucker
    assert discovery.parse_mdns_response(MDNS_FOREIGN) == []


def test_discovery_reads_a_real_snmp_answer():
    """SNMP liefert den Druckernamen (``hrDeviceDescr``) und den Hostnamen."""
    printers = discovery.parse_snmp_response(SNMP_ANSWER, "192.0.2.62")

    assert len(printers) == 1
    assert printers[0].host == "192.0.2.62"
    assert printers[0].model_id == "QL-820NWB"
    assert printers[0].source == discovery.SOURCE_SNMP
    # Der Hostname steht im Tooltip, nicht im Listeneintrag.
    assert printers[0].name.startswith("BRW")
    assert "BRW" in printers[0].detail()


def test_discovery_merges_both_ways_per_address():
    """Derselbe Drucker kommt zweimal - die IP fasst ihn zusammen."""
    merged = discovery.merge_printers(
        discovery.parse_mdns_response(MDNS_ANSWER)
        + discovery.parse_snmp_response(SNMP_ANSWER, "192.0.2.62")
    )

    assert len(merged) == 1
    printer = merged[0]
    assert printer.model_id == "QL-820NWB"
    # mDNS nennt den lesbaren Namen, SNMP nur den Hostnamen.
    assert printer.name == "Brother QL-820NWB"
    assert "Brother QL-820NWB" not in printer.detail()


def test_discovery_sorts_printers_by_address():
    """Die Liste springt nicht: erst .62, dann .108 (nicht alphabetisch)."""
    merged = discovery.merge_printers(
        [
            discovery.NetworkPrinter(host="192.0.2.108", model_id="QL-700"),
            discovery.NetworkPrinter(host="192.0.2.62", model_id="QL-820NWB"),
        ]
    )

    assert [printer.host for printer in merged] == ["192.0.2.62", "192.0.2.108"]


def test_discovery_keeps_unknown_ql_models_selectable():
    """Ein QL, den brother_ql noch nicht kennt: sichtbar, Modell bleibt offen."""
    assert discovery.model_id_for_name("Brother QL-9999NWB") is None
    assert discovery.looks_like_label_printer("Brother QL-9999NWB") is True
    # Fremde Geraete und Brother-Laserdrucker sind keine Etikettendrucker.
    assert discovery.looks_like_label_printer("EPSON WF-7720 Series") is False
    assert discovery.looks_like_label_printer("Brother HL-L2350DW") is False


def test_discovery_requests_are_well_formed():
    """Die Anfragen tragen Dienst bzw. OIDs und bitten um eine Antwort."""
    query = discovery.mdns_query()
    assert discovery.dns_name(discovery.MDNS_SERVICE) in query
    # Frageklasse mit QU-Bit: die Antwort kommt per Unicast zu uns.
    assert query.endswith(
        struct.pack(">HH", discovery.TYPE_PTR, discovery.DNS_FLAG_UNICAST_RESPONSE)
    )

    request = discovery.snmp_request()
    assert discovery.SNMP_COMMUNITY in request
    assert discovery._ber_oid(discovery.SNMP_OID_DEVICE_DESCR) in request


def test_discovery_ignores_broken_packets():
    """Muell im Netz darf die Suche nicht umwerfen."""
    with pytest.raises(ValueError):
        discovery.parse_mdns_response(b"\x00\x01")
    with pytest.raises(ValueError):
        discovery.parse_snmp_response(b"\x30\x00")
    # Eine gueltige Sequenz ohne GetResponse liefert einfach nichts.
    not_a_response = b"\x30\x08\x02\x01\x00\x04\x01a\xa1\x00"
    assert discovery.parse_snmp_response(not_a_response) == []


def test_discovery_stops_when_nothing_answers(monkeypatch):
    """Ohne Antwort endet die Suche nach dem Zeitlimit."""
    monkeypatch.setattr(discovery, "_udp_socket", lambda *args, **kwargs: _DeadSocket())
    assert discovery.mdns_printers(timeout=0.05) == []


def test_interface_broadcast_uses_interface_name(monkeypatch):
    """SIOCGIFBRDADDR braucht den Namen (en0), nicht den Index."""
    import fcntl

    captured: list[bytes] = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def fileno(self):
            return 3

    def fake_ioctl(fd, request, buf):
        captured.append(bytes(buf[:16]))
        # Antwort: Name + sockaddr_in mit Broadcast 192.168.1.255 ab Offset 20.
        out = bytearray(256)
        out[0:3] = b"en0"
        out[20:24] = bytes((192, 168, 1, 255))
        return bytes(out)

    monkeypatch.setattr(discovery.socket, "socket", lambda *a, **k: _FakeSocket())
    monkeypatch.setattr(fcntl, "ioctl", fake_ioctl)

    assert discovery.interface_broadcast("en0") == "192.168.1.255"
    assert captured, "ioctl wurde nicht aufgerufen"
    assert captured[0].startswith(b"en0")
    assert not captured[0].startswith(b"1")


def test_broadcast_targets_keeps_default_and_asks_by_name(monkeypatch):
    monkeypatch.setattr(
        discovery.socket, "if_nameindex", lambda: [(1, "en0"), (2, "lo0")]
    )
    seen: list[str] = []

    def fake_broadcast(name: str) -> str:
        seen.append(name)
        return "10.0.0.255" if name == "en0" else ""

    monkeypatch.setattr(discovery, "interface_broadcast", fake_broadcast)
    targets = discovery.broadcast_targets()
    assert discovery.BROADCAST_ADDRESS in targets
    assert "10.0.0.255" in targets
    assert seen == ["en0", "lo0"]


class _DeadSocket:
    """Steht fuer einen Socket, auf dem nie etwas ankommt."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sendto(self, *args):
        return None

    def connect(self, address):
        self.peer = address

    def send(self, data):
        return self.sendto(data, self.peer)

    def settimeout(self, value):
        self.timeout = value

    def recvfrom(self, size):

        raise TimeoutError()


class _AnswerSocket(_DeadSocket):
    """Ein Socket, der genau ein Paket liefert."""

    def __init__(self, answer: bytes):
        self._answer = answer

    def recvfrom(self, size):
        return self._answer, ("192.0.2.62", 161)


def _snmp_answer(
    *values: tuple[tuple[int, ...], int, bytes], error_status: int = 0
) -> bytes:
    """Eine GetResponse mit den Werten ``(OID, Tag, Inhalt)`` (wie ein Drucker sie schickt)."""
    varbinds = b"".join(
        discovery._ber(0x30, discovery._ber_oid(oid) + discovery._ber(tag, value))
        for oid, tag, value in values
    )
    pdu = (
        discovery._ber_integer(1)
        + discovery._ber_integer(error_status)
        + discovery._ber_integer(0)
        + discovery._ber(0x30, varbinds)
    )
    return discovery._ber(
        0x30,
        discovery._ber_integer(0)
        + discovery._ber(0x04, discovery.SNMP_COMMUNITY)
        + discovery._ber(0xA2, pdu),
    )


_BITS = discovery.HR_PRINTER_ERROR_OID
_DEVICE = discovery.HR_DEVICE_STATUS_OID
_PRINTER = "tcp://192.0.2.62:9100"


def _printer_answers(monkeypatch, *values, error_status: int = 0) -> None:
    answer = _snmp_answer(*values, error_status=error_status)
    monkeypatch.setattr(discovery, "_udp_socket", lambda: _AnswerSocket(answer))


def test_snmp_varbinds_keeps_the_tag_of_each_value():
    answer = _snmp_answer((_BITS, 0x04, b"\x40\x00"))
    assert discovery.snmp_varbinds(answer) == {_BITS: (0x04, b"\x40\x00")}


def test_snmp_varbinds_is_empty_when_the_agent_reports_an_error():
    """SNMPv1 ``noSuchName``: die Werte sind nur Platzhalter, nicht "alles ok"."""
    answer = _snmp_answer((_BITS, 0x05, b""), (_DEVICE, 0x05, b""), error_status=2)
    assert discovery.snmp_varbinds(answer) == {}


def test_network_printer_status_reads_a_fatal_error_bit(monkeypatch):
    """Bit 1 (``noPaper``) gesetzt: ein Band fehlt oder passt nicht."""
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x40\x00"))
    status = discovery.network_printer_status(_PRINTER)
    assert status == discovery.NetworkStatus(
        fault=True, texts=("Kein Papier oder Band eingelegt",)
    )


def test_network_printer_status_is_fine_without_error(monkeypatch):
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x00\x00"), (_DEVICE, 0x02, b"\x02"))
    assert discovery.network_printer_status(_PRINTER) == discovery.NetworkStatus(
        fault=False
    )


def test_network_printer_status_is_none_without_answer(monkeypatch):
    """Keine SNMP-Antwort heisst: unbekannt, nicht "alles in Ordnung"."""
    monkeypatch.setattr(discovery, "_udp_socket", lambda: _DeadSocket())
    assert discovery.network_printer_status(_PRINTER) is None


def test_network_printer_status_flags_a_down_device_without_error_bits(monkeypatch):
    """Falsches Band: kein Fehlerbit, aber das Geraet steht auf "down"."""
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x00\x00"), (_DEVICE, 0x02, b"\x05"))
    status = discovery.network_printer_status(_PRINTER)
    assert status == discovery.NetworkStatus(
        fault=True, texts=("Störung, z. B. falsches Band",)
    )


def test_network_printer_status_reads_cover_open_from_one_answer(monkeypatch):
    """Am QL-820NWB gemessen: Klappe offen setzt Bit 4 und "down" in einer Antwort."""
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x08\x00"), (_DEVICE, 0x02, b"\x05"))
    status = discovery.network_printer_status(_PRINTER)
    assert status == discovery.NetworkStatus(fault=True, texts=("Klappe offen",))


def test_network_printer_status_keeps_warning_bits_apart_from_faults(monkeypatch):
    """Wenig Papier bei laufendem Geraet: ein Hinweis, kein Auftragsfehler."""
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x80\x00"), (_DEVICE, 0x02, b"\x03"))
    status = discovery.network_printer_status(_PRINTER)
    assert status == discovery.NetworkStatus(fault=False, texts=("Papier wird knapp",))


def test_network_printer_status_treats_a_fatal_bit_as_fault_without_down(monkeypatch):
    """Andere Modelle setzen "down" vielleicht nicht - ein Papierstau bleibt ein Fehler."""
    _printer_answers(monkeypatch, (_BITS, 0x04, b"\x04\x00"), (_DEVICE, 0x02, b"\x02"))
    status = discovery.network_printer_status(_PRINTER)
    assert status == discovery.NetworkStatus(fault=True, texts=("Papierstau",))


def test_network_printer_status_ignores_unsupported_objects(monkeypatch):
    """Ein Drucker, der die Gerätetabelle nicht kennt (noSuchObject), zaehlt nicht als SNMP-aktiv."""
    _printer_answers(monkeypatch, (_DEVICE, 0x80, b""))
    assert discovery.network_printer_status(_PRINTER) is None


def test_network_printer_status_survives_a_broken_address(monkeypatch):
    """``urlsplit`` wirft bei ``a[b`` - der Druck-Thread darf daran nicht sterben."""
    monkeypatch.setattr(discovery, "_udp_socket", lambda: _DeadSocket())
    assert discovery.network_printer_status("a[b") is None


def _status_after_job(monkeypatch, printer_status, **kwargs) -> dict:
    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        discovery, "network_printer_status", lambda address, **kw: printer_status
    )
    config = discovery.PrinterConfig(address=_PRINTER)
    return discovery.confirm_network_job(config, {"outcome": "sent"}, **kwargs)


def test_confirm_network_job_marks_an_error_after_sending(monkeypatch):
    printer = discovery.NetworkStatus(fault=True, texts=("Papierstau",))
    status = _status_after_job(monkeypatch, printer, snmp_answered=True)
    assert status == {"outcome": "error", "errors": ["Papierstau"]}


def test_confirm_network_job_confirms_a_clean_job(monkeypatch):
    printer = discovery.NetworkStatus(fault=False)
    assert _status_after_job(monkeypatch, printer, snmp_answered=True) == {
        "outcome": "sent",
        "snmp_ok": True,
        "warnings": [],
    }


def test_confirm_network_job_keeps_sent_with_a_warning(monkeypatch):
    printer = discovery.NetworkStatus(fault=False, texts=("Papier wird knapp",))
    status = _status_after_job(monkeypatch, printer, snmp_answered=True)
    assert status == {
        "outcome": "sent",
        "snmp_ok": True,
        "warnings": ["Papier wird knapp"],
    }


def test_confirm_network_job_skips_usb(monkeypatch):
    """USB meldet den Druck selbst - dort wird nicht per SNMP nachgefragt."""

    def fail(*args, **kwargs):
        raise AssertionError("kein SNMP bei USB")

    monkeypatch.setattr(discovery, "network_printer_status", fail)
    config = discovery.PrinterConfig(address="usb://0x04f9:0x209b")
    assert discovery.confirm_network_job(config, {"outcome": "printed"}) == {
        "outcome": "printed"
    }


def test_confirm_network_job_reports_silence_as_unconfirmed(monkeypatch):
    """Stille nach dem Senden ist kein Fehler: der Auftrag kann gedruckt sein."""
    asked = []

    def silent(address, **kwargs):
        asked.append(kwargs.get("attempts"))

    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(discovery, "network_printer_status", silent)
    config = discovery.PrinterConfig(address=_PRINTER)
    status = discovery.confirm_network_job(
        config, {"outcome": "sent"}, snmp_answered=True
    )
    assert status == {"outcome": "unconfirmed"}
    assert asked == [discovery.NETWORK_CHECK_ATTEMPTS]


def test_confirm_network_job_without_snmp_neither_waits_nor_asks(monkeypatch):
    """Ohne SNMP-Antwort vor dem Druck ist der Auftrag sofort fertig: "gesendet"."""

    def fail(*args, **kwargs):
        raise AssertionError("ohne SNMP weder warten noch fragen")

    monkeypatch.setattr(discovery.time, "sleep", fail)
    monkeypatch.setattr(discovery, "network_printer_status", fail)
    config = discovery.PrinterConfig(address=_PRINTER)
    assert discovery.confirm_network_job(config, {"outcome": "sent"}) == {
        "outcome": "sent"
    }


class _LossySocket(_AnswerSocket):
    """Verliert die ersten ``losses`` Antworten (WLAN)."""

    def __init__(self, answer: bytes, losses: int):
        super().__init__(answer)
        self.losses = losses
        self.sent = 0

    def sendto(self, *args):
        self.sent += 1

    def recvfrom(self, size):
        if self.sent <= self.losses:
            raise TimeoutError()
        return super().recvfrom(size)


def test_network_printer_status_asks_again_after_a_lost_packet(monkeypatch):
    sock = _LossySocket(_snmp_answer((_DEVICE, 0x02, b"\x02")), losses=1)
    monkeypatch.setattr(discovery, "_udp_socket", lambda: sock)
    assert discovery.network_printer_status(_PRINTER, attempts=1) is None
    sock.sent = 0
    assert discovery.network_printer_status(
        _PRINTER, attempts=2
    ) == discovery.NetworkStatus(fault=False)
    assert sock.sent == 2


def test_snmp_get_resolves_the_name_once_and_stops_when_refused(monkeypatch):
    """Ein Name wird einmal aufgeloest. "Port nicht erreichbar" (SNMP aus)
    beendet die Abfrage sofort, statt jeden Versuch auszusitzen."""

    class RefusedSocket(_DeadSocket):
        def __init__(self):
            self.peers = []
            self.sent = 0

        def connect(self, address):
            self.peers.append(address)
            super().connect(address)

        def sendto(self, *args):
            self.sent += 1

        def recvfrom(self, size):
            raise ConnectionRefusedError()

    sock = RefusedSocket()
    monkeypatch.setattr(discovery, "_udp_socket", lambda: sock)
    assert discovery.snmp_get("drucker.local", (_DEVICE,), attempts=3) == {}
    assert sock.peers == [("drucker.local", discovery.SNMP_PORT)]
    assert sock.sent == 1


def test_confirm_network_job_skips_the_check_when_cancelled(monkeypatch):
    """Schliesst das Fenster, wartet der Druck-Thread nicht mehr auf den Drucker."""
    import threading

    def fail(*args, **kwargs):
        raise AssertionError("kein SNMP nach dem Abbruch")

    monkeypatch.setattr(discovery, "network_printer_status", fail)
    cancel = threading.Event()
    cancel.set()
    config = discovery.PrinterConfig(address=_PRINTER)
    status = discovery.confirm_network_job(
        config, {"outcome": "sent"}, snmp_answered=True, delay=30.0, cancel=cancel
    )
    assert status == {"outcome": "sent"}
