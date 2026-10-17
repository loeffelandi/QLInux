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
        discovery.dns_name(name)
        + struct.pack(">HHIH", rtype, 1, 120, len(data))
        + data
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
    monkeypatch.setattr(
        discovery, "_udp_socket", lambda *args, **kwargs: _DeadSocket()
    )
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

    def settimeout(self, value):
        self.timeout = value

    def recvfrom(self, size):
        import socket as socket_module

        raise socket_module.timeout()
