"""Druckersuche im Netzwerk - ohne Zusatzpakete.

Zwei Wege laufen gleichzeitig und werden ueber die IP zusammengefuehrt:

* **mDNS** (DNS-SD, Dienst ``_pdl-datastream._tcp.local``): Brother-Drucker
  kuendigen dort ihren Rohdruck-Port an und nennen in den TXT-Records ihr
  Modell (``usb_MDL=QL-820NWB``). Die Anfrage geht mit gesetztem QU-Bit von
  einem freien Port aus - die Antwort kommt also direkt (Unicast), ohne dass
  wir Port 5353 belegen oder der avahi-Daemon laufen muss.
* **SNMP-Broadcast** (UDP 161, Community ``public``): ein Paket an die
  Broadcast-Adresse, das die Geraetebeschreibung abfragt
  (``hrDeviceDescr`` -> "Brother QL-820NWB"). Damit werden auch Drucker
  gefunden, die kein mDNS sprechen.

Genommen wird nur, was ein Brother-Etikettendrucker ist (``brother_ql`` kennt
die Modelle, und nur die sprechen unseren Rasterauftrag). Ein Fremddrucker auf
Port 9100 hilft hier nicht.

Alle hier gemessenen Werte stehen in ``docs/API_NOTES.md``; die Rohpakete der
Tests liegen in ``tests/data/``.
"""

from __future__ import annotations

import dataclasses
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable
from urllib.parse import urlsplit

from .i18n import tr
from .media import all_models
from .printer import (
    NETWORK_PORT,
    PrinterConfig,
    parse_network_address,
    printer_error_texts,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ mDNS --
#: Dienst, unter dem Drucker ihren Rohdruck-Port ankuendigen (RFC 6763).
MDNS_SERVICE = "_pdl-datastream._tcp.local"
#: Multicast-Gruppe und Port fuer mDNS.
MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
#: Zeit, in der Antworten eingesammelt werden (Sekunden).
MDNS_TIMEOUT = 2.0
#: Ruhezeit: danach gilt die Suche als fertig (die Antwort des QL-820NWB kam
#: nach rund einer Sekunde).
SEARCH_QUIET_TIME = 0.25
#: Groesse, in der Antworten gelesen werden (die mDNS-Antwort des QL-820NWB
#: ist 511 Byte gross).
PACKET_LIMIT = 9000

TYPE_A = 1
TYPE_PTR = 12
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
#: Antwortbit im Frage-Abschnitt: die Antwort kommt per Unicast zu uns.
DNS_FLAG_UNICAST_RESPONSE = 0x8001

# ------------------------------------------------------------------ SNMP --
SNMP_PORT = 161
SNMP_COMMUNITY = b"public"
SNMP_TIMEOUT = 1.5
#: Beschreibung des Betriebsmittels - hier steht der Druckername
#: ("Brother QL-820NWB"). Gemessen am QL-820NWB.
SNMP_OID_DEVICE_DESCR = (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 3, 1)
#: Geraetebeschreibung der Netzwerkkarte ("Brother NC-38002w, ...") sowie der
#: Geraetename (``BRWBCF4D4334A01``); beides dient nur als Ergaenzung.
SNMP_OID_SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SNMP_OID_SYS_NAME = (1, 3, 6, 1, 2, 1, 1, 5, 0)
SNMP_OIDS = (SNMP_OID_DEVICE_DESCR, SNMP_OID_SYS_DESCR, SNMP_OID_SYS_NAME)
#: Fehlerzustand des ersten Druckers (``hrPrinterDetectedErrorState``,
#: HOST-RESOURCES-MIB). Gemessen am QL-820NWB: Klappe offen setzt Bit 4; ein
#: falsches Band setzt kein Bit (dafuer gilt ``HR_DEVICE_STATUS_OID``).
HR_PRINTER_ERROR_OID = (1, 3, 6, 1, 2, 1, 25, 3, 5, 1, 2, 1)
#: Betriebszustand des Geraets (``hrDeviceStatus``). Ein falsches Band setzt
#: ihn auf "down" (5), ohne dass ein Fehlerbit gesetzt wird. Gemessen am QL-820NWB.
HR_DEVICE_STATUS_OID = (1, 3, 6, 1, 2, 1, 25, 3, 2, 1, 5, 1)
HR_DEVICE_DOWN = 5
#: Wartezeit nach dem Senden, bevor der Netzwerkdrucker nach Fehlern gefragt
#: wird - der Drucker braucht einen Moment, bis er den Fehler setzt.
NETWORK_CHECK_DELAY = 2.0
#: Broadcast-Adresse (Standardweg, wenn sich keine Schnittstelle meldet).
BROADCAST_ADDRESS = "255.255.255.255"
#: SIOCGIFBRDADDR: Broadcast-Adresse einer Schnittstelle erfragen (Linux).
IOCTL_INTERFACE_BROADCAST = 0x8919

SOURCE_MDNS = "mDNS"
SOURCE_SNMP = "SNMP"

#: Hersteller und Baureihe der Etikettendrucker, die wir ansprechen koennen.
LABEL_PRINTER_MANUFACTURER = "BROTHER"
LABEL_PRINTER_SERIES = "QL-"


# --------------------------------------------------------------------------- #
# Ergebnis
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NetworkPrinter:
    """Ein im Netzwerk gefundener Drucker."""

    host: str
    port: int = NETWORK_PORT
    model_id: str | None = None
    name: str = ""
    source: str = SOURCE_MDNS

    @property
    def address(self) -> str:
        """Adresse fuer :class:`~ql_editor.printer.PrinterConfig`."""
        return f"tcp://{self.host}:{self.port}"

    @property
    def display_name(self) -> str:
        """Was in der Liste steht: das Modell, sonst der gemeldete Name."""
        return self.model_id or self.name or self.host

    def label(self) -> str:
        """Listeneintrag wie ``192.168.178.62 (QL-820NWB)``.

        Erst die Adresse: sie unterscheidet zwei gleiche Drucker, und im
        schmalen Panel wird beim Abschneiden dann nur der Name gekuerzt.
        """
        if self.display_name == self.host:
            return self.host
        return f"{self.host} ({self.display_name})"

    def detail(self) -> str:
        """Tooltip: wo der Eintrag herkommt und was gemeldet wurde."""
        lines = [f"{self.host}:{self.port}"]
        # Den gemeldeten Namen nur zeigen, wenn er etwas Neues sagt: "Brother
        # QL-820NWB" steht schon im Listeneintrag, "BRWBCF4D4334A01" nicht.
        if self.name and self.name != self.display_name and not (
            self.model_id and self.model_id in self.name
        ):
            lines.append(self.name)
        lines.append(tr("gefunden über {source}").format(source=self.source))
        return "\n".join(lines)


@lru_cache(maxsize=1)
def known_model_ids() -> tuple[str, ...]:
    """Modellkennungen von ``brother_ql``, laengste zuerst.

    Die Reihenfolge ist wichtig: in "QL-820NWB" steckt auch "QL-820", wenn es
    beide Modelle gaebe - der laengste Treffer ist der richtige.
    """
    return tuple(sorted((spec.identifier for spec in all_models()), key=len, reverse=True))


def model_id_for_name(text: str) -> str | None:
    """Modell aus einem Geraetenamen lesen (``"Brother QL-820NWB"`` -> ``"QL-820NWB"``)."""
    haystack = (text or "").upper()
    if not haystack:
        return None
    for model_id in known_model_ids():
        if model_id.upper() in haystack:
            return model_id
    return None


def looks_like_label_printer(text: str) -> bool:
    """Ist das ein Brother-Etikettendrucker?

    Fremde Geraete hoeren zwar auch auf Port 9100, koennen aber nichts mit
    unserem Rasterauftrag anfangen - die sollen gar nicht erst in der Liste
    stehen. Ein unbekanntes QL-Modell bleibt dagegen sichtbar: das Modell
    waehlt man dann von Hand.
    """
    haystack = (text or "").upper()
    return (
        LABEL_PRINTER_MANUFACTURER in haystack and LABEL_PRINTER_SERIES in haystack
    )


# --------------------------------------------------------------------------- #
# DNS (nur so viel, wie mDNS braucht)
# --------------------------------------------------------------------------- #
class DnsReader:
    """Minimaler Leser fuer eine DNS-Nachricht.

    Namen koennen im Paket als Zeiger auf frueher genannte Namen stehen
    (Komprimierung, RFC 1035) - deshalb wird immer mit Offset gelesen.
    """

    #: So oft darf ein Name einem Zeiger folgen, bevor wir einen Ring vermuten.
    MAX_POINTERS = 32

    def __init__(self, data: bytes):
        self.data = data

    def name(self, offset: int) -> tuple[str, int]:
        """Namen lesen: ``(Name, Offset dahinter)``."""
        labels: list[str] = []
        following = False
        following_offset = offset
        pointers = 0
        while True:
            if offset >= len(self.data):
                raise ValueError("Name reicht ueber das Paket hinaus.")
            length = self.data[offset]
            if length == 0:
                offset += 1
                if not following:
                    following_offset = offset
                break
            if length & 0xC0 == 0xC0:
                if offset + 1 >= len(self.data):
                    raise ValueError("Zeiger reicht ueber das Paket hinaus.")
                target = ((length & 0x3F) << 8) | self.data[offset + 1]
                if not following:
                    following_offset = offset + 2
                    following = True
                pointers += 1
                if pointers > self.MAX_POINTERS:
                    raise ValueError("Namenszeiger im Kreis.")
                offset = target
                continue
            offset += 1
            labels.append(self.data[offset : offset + length].decode("utf-8", "replace"))
            offset += length
        return ".".join(labels), following_offset


@dataclass(frozen=True)
class DnsRecord:
    """Ein Resource Record, wie er im Paket steht."""

    name: str
    rtype: int
    offset: int
    data: bytes


def dns_records(reader: DnsReader) -> list[DnsRecord]:
    """Antwort- und Zusatzdatensaetze einer DNS-Nachricht."""
    if len(reader.data) < 12:
        raise ValueError("DNS-Kopf fehlt.")
    _ident, _flags, questions, answers, authority, additional = struct.unpack(
        ">HHHHHH", reader.data[:12]
    )
    offset = 12
    for _ in range(questions):
        _, offset = reader.name(offset)
        offset += 4  # Typ + Klasse
    records: list[DnsRecord] = []
    for _ in range(answers + authority + additional):
        name, offset = reader.name(offset)
        rtype, _rclass, _ttl, length = struct.unpack(
            ">HHIH", reader.data[offset : offset + 10]
        )
        offset += 10
        records.append(DnsRecord(name, rtype, offset, reader.data[offset : offset + length]))
        offset += length
    return records


def txt_fields(data: bytes) -> dict[str, str]:
    """``usb_MDL=QL-820NWB`` -> ``{"usb_MDL": "QL-820NWB"}``."""
    fields: dict[str, str] = {}
    offset = 0
    while offset < len(data):
        length = data[offset]
        offset += 1
        entry = data[offset : offset + length].decode("utf-8", "replace")
        offset += length
        key, separator, value = entry.partition("=")
        if separator:
            fields[key] = value
    return fields


def mdns_query(service: str = MDNS_SERVICE) -> bytes:
    """Eine PTR-Anfrage an die mDNS-Gruppe, Antwort bitte per Unicast."""
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    question = dns_name(service) + struct.pack(
        ">HH", TYPE_PTR, DNS_FLAG_UNICAST_RESPONSE
    )
    return header + question


def dns_name(name: str) -> bytes:
    """``_pdl-datastream._tcp.local`` als Laengen-praefigierte Labels."""
    encoded = b""
    for label in name.split("."):
        encoded += bytes([len(label)]) + label.encode("utf-8")
    return encoded + b"\x00"


def parse_mdns_response(data: bytes, source_host: str = "") -> list[NetworkPrinter]:
    """Drucker aus einer mDNS-Antwort lesen.

    Aufbau: PTR-Record je Dienstinstanz, dazu SRV (Ziel-Port), TXT (Modell)
    und A (Adresse). Wer antwortet, ist der Drucker selbst - die Adresse des
    Absenders gilt daher, falls im Paket keine A-Records stehen.
    """
    reader = DnsReader(data)
    records = dns_records(reader)
    service = MDNS_SERVICE.lower()
    instances: list[str] = []
    # Adressen stehen unter dem Namen des Zielhosts, nicht unter dem Dienst -
    # deshalb erst sammeln und je Instanz nachschlagen. (Nur IPv4: unsere
    # Verbindung ist AF_INET.)
    addressed: dict[str, list[str]] = {}
    for record in records:
        if record.rtype == TYPE_A and len(record.data) == 4:
            addressed.setdefault(record.name, []).append(socket.inet_ntoa(record.data))
        elif record.rtype == TYPE_PTR and record.name.lower() == service:
            target, _ = reader.name(record.offset)
            if target and target not in instances:
                instances.append(target)

    printers: list[NetworkPrinter] = []
    for instance in instances:
        port = NETWORK_PORT
        target_host = ""
        fields: dict[str, str] = {}
        for record in records:
            if record.name != instance:
                continue
            if record.rtype == TYPE_SRV and len(record.data) >= 6:
                _priority, _weight, port = struct.unpack(">HHH", record.data[:6])
                target_host, _ = reader.name(record.offset + 6)
            elif record.rtype == TYPE_TXT:
                fields.update(txt_fields(record.data))
        name = fields.get("ty") or fields.get("product") or instance.split(".")[0]
        text = " ".join([instance, *fields.values()])
        if not looks_like_label_printer(text):
            continue
        hosts = addressed.get(target_host, []) or ([source_host] if source_host else [])
        for host in hosts:
            printers.append(
                NetworkPrinter(
                    host=host,
                    port=port,
                    model_id=model_id_for_name(text),
                    name=name,
                    source=SOURCE_MDNS,
                )
            )
    return printers


# --------------------------------------------------------------------------- #
# SNMP (nur so viel, wie ein GET braucht)
# --------------------------------------------------------------------------- #
def _ber_length(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    encoded = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _ber(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _ber_length(len(payload)) + payload


def _ber_integer(value: int) -> bytes:
    if value == 0:
        return _ber(0x02, b"\x00")
    encoded = value.to_bytes((value.bit_length() + 8) // 8, "big")
    return _ber(0x02, encoded)


def _ber_oid(parts: tuple[int, ...]) -> bytes:
    encoded = bytes([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        if part < 0x80:
            encoded += bytes([part])
            continue
        chunk: list[int] = []
        while part:
            chunk.insert(0, part & 0x7F)
            part >>= 7
        encoded += bytes([byte | 0x80 for byte in chunk[:-1]] + [chunk[-1]])
    return _ber(0x06, encoded)


def _ber_read(data: bytes, offset: int) -> tuple[int, bytes, int]:
    """Ein BER-Element lesen: ``(Tag, Inhalt, Offset dahinter)``."""
    if offset + 2 > len(data):
        raise ValueError("BER-Element fehlt.")
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        if not 0 < count <= 4 or offset + count > len(data):
            raise ValueError("BER-Laenge unbrauchbar.")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    end = offset + length
    if end > len(data):
        raise ValueError("BER-Element zu kurz.")
    return tag, data[offset:end], end


def _ber_oid_value(data: bytes) -> tuple[int, ...]:
    """OID-Bytes zurueck in Zahlen (z. B. ``(1, 3, 6, 1, ...)``)."""
    if not data:
        return ()
    parts = [data[0] // 40, data[0] % 40]
    value = 0
    for byte in data[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return tuple(parts)


def snmp_request(oids: tuple[tuple[int, ...], ...] = SNMP_OIDS) -> bytes:
    """Ein SNMP-v1-GET fuer die uebergebenen OIDs."""
    varbinds = b"".join(_ber(0x30, _ber_oid(oid) + _ber(0x05, b"")) for oid in oids)
    body = (
        _ber_integer(0)
        + _ber(0x04, SNMP_COMMUNITY)
        + _ber(0xA0, _ber_integer(1) + _ber_integer(0) + _ber_integer(0) + _ber(0x30, varbinds))
    )
    return _ber(0x30, body)


def snmp_varbinds(data: bytes) -> dict[tuple[int, ...], tuple[int, bytes]]:
    """``OID -> (Tag, Inhalt)`` aller Werte einer SNMP-Antwort.

    Ein ``GetResponse`` ist eine Sequenz aus Version, Community und PDU; die
    PDU enthaelt Anfrage-Kennung, Fehlerfelder und die Werteliste.
    """
    tag, body, _ = _ber_read(data, 0)
    if tag != 0x30:
        raise ValueError("Keine SNMP-Sequenz.")
    offset = 0
    _, _, offset = _ber_read(body, offset)  # Version
    _, _, offset = _ber_read(body, offset)  # Community
    tag, pdu, _ = _ber_read(body, offset)
    if tag != 0xA2:  # GetResponse
        return {}
    offset = 0
    for _ in range(3):  # Anfrage-Kennung, Fehlerstatus, Fehlerindex
        _, _, offset = _ber_read(pdu, offset)
    _, varbinds, _ = _ber_read(pdu, offset)
    values: dict[tuple[int, ...], tuple[int, bytes]] = {}
    offset = 0
    while offset < len(varbinds):
        _, varbind, offset = _ber_read(varbinds, offset)
        inner = 0
        _, oid_bytes, inner = _ber_read(varbind, inner)
        tag, value, _ = _ber_read(varbind, inner)
        values[_ber_oid_value(oid_bytes)] = (tag, value)
    return values


def snmp_values(data: bytes) -> dict[tuple[int, ...], str]:
    """``OID -> Text`` aus einer SNMP-Antwort (nur Zeichenketten-Werte)."""
    return {
        oid: value.decode("utf-8", "replace")
        for oid, (tag, value) in snmp_varbinds(data).items()
        if tag == 0x04  # nur Zeichenketten sind fuer uns interessant
    }


def snmp_get(
    host: str, oids: tuple[tuple[int, ...], ...], *, timeout: float = SNMP_TIMEOUT
) -> dict[tuple[int, ...], tuple[int, bytes]]:
    """Werte gezielt von **einem** Geraet lesen (SNMP-GET per Unicast).

    Leer, wenn keine Antwort kommt (SNMP aus, andere Community, Drucker aus).
    """
    with _udp_socket() as sock:
        sock.settimeout(timeout)
        sock.sendto(snmp_request(oids), (host, SNMP_PORT))
        try:
            data, _address = sock.recvfrom(PACKET_LIMIT)
        except OSError:
            return {}
    return snmp_varbinds(data)


def network_printer_errors(
    address: str, *, timeout: float = SNMP_TIMEOUT
) -> tuple[str, ...] | None:
    """Fehlertexte des Netzwerkdruckers laut SNMP.

    ``None``: keine Antwort (dann ist nichts bekannt). ``()``: der Drucker
    meldet keinen Fehler. Sonst die Texte der gesetzten Fehlerbits, und bei
    einem Geraet im Zustand "down" zusaetzlich eine allgemeine Stoerung.
    """
    host = urlsplit(parse_network_address(address)).hostname
    if not host:
        return None
    try:
        values = snmp_get(
            host, (HR_PRINTER_ERROR_OID, HR_DEVICE_STATUS_OID), timeout=timeout
        )
    except (OSError, ValueError) as exc:
        logger.info("SNMP-Statusabfrage an %s fehlgeschlagen: %s", host, exc)
        return None
    bits = values.get(HR_PRINTER_ERROR_OID)
    device = values.get(HR_DEVICE_STATUS_OID)
    if bits is None and device is None:
        return None
    errors = list(printer_error_texts(bits[1])) if bits and bits[0] == 0x04 else []
    is_down = device is not None and device[0] == 0x02 and (
        int.from_bytes(device[1], "big") == HR_DEVICE_DOWN
    )
    if is_down and not errors:
        errors.append(tr("Drucker meldet eine Störung"))
    return tuple(errors)


def network_snmp_answers(address: str, *, timeout: float = SNMP_TIMEOUT) -> bool:
    """Ist SNMP am Drucker aktiv? Antwortet er auf eine Statusabfrage?

    Vor dem Druck gefragt: nur wenn SNMP vorher antwortet, gilt Stille nach
    dem Senden als Fehler. Ohne SNMP (Dienst aus) bleibt es bei "gesendet".
    """
    host = urlsplit(parse_network_address(address)).hostname
    if not host:
        return False
    try:
        device = snmp_get(host, (HR_DEVICE_STATUS_OID,), timeout=timeout).get(
            HR_DEVICE_STATUS_OID
        )
    except (OSError, ValueError):
        return False
    return device is not None and device[0] == 0x02


def confirm_network_job(
    config: PrinterConfig,
    status: dict,
    *,
    snmp_answered: bool = False,
    delay: float = NETWORK_CHECK_DELAY,
    timeout: float = SNMP_TIMEOUT,
    cancel: threading.Event | None = None,
) -> dict:
    """Nach dem Senden per SNMP nachsehen, ob der Drucker einen Fehler meldet.

    Der Netzwerkweg liefert nur "gesendet". Meldet der Drucker danach einen
    Fehler (z. B. falsches Band), wird der Auftrag zu ``outcome == "error"``
    mit den Fehlertexten in ``errors``. Antwortete der Drucker schon vor dem
    Senden per SNMP (``snmp_answered``), gilt auch Stille danach als Fehler.
    Mit ``cancel`` (Fenster schliesst) entfaellt die Pruefung.
    """
    if config.backend != "network":
        return status
    if cancel is None:
        time.sleep(delay)
    elif cancel.wait(delay):
        return status
    errors = network_printer_errors(config.address, timeout=timeout)
    if errors is None:
        if not snmp_answered:
            return status
        errors = (tr("Drucker antwortet nach dem Senden nicht"),)
    if not errors:
        return status
    return {**status, "outcome": "error", "errors": list(errors)}


def parse_snmp_response(data: bytes, source_host: str = "") -> list[NetworkPrinter]:
    """Drucker aus einer SNMP-Antwort lesen (eine Antwort je Geraet)."""
    values = snmp_values(data)
    text = " ".join(values.get(oid, "") for oid in SNMP_OIDS)
    if not looks_like_label_printer(text):
        return []
    name = values.get(SNMP_OID_SYS_NAME, "")
    return [
        NetworkPrinter(
            host=source_host,
            port=NETWORK_PORT,
            model_id=model_id_for_name(text),
            name=name,
            source=SOURCE_SNMP,
        )
    ]


def interface_broadcast(name: str) -> str:
    """Broadcast-Adresse einer Schnittstelle (Linux; sonst leer).

    ``SIOCGIFBRDADDR`` erwartet den Schnittstellennamen in ``ifr_name``
    (``en0``, ``eth0``), nicht den Index. ``255.255.255.255`` geht nur ueber
    die Standardschnittstelle; mit der Adresse je Schnittstelle werden auch
    mehrere Netze abgedeckt.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - nur ausserhalb von Linux
        return ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            request = struct.pack("256s", name.encode("utf-8")[:15])
            reply = fcntl.ioctl(sock.fileno(), IOCTL_INTERFACE_BROADCAST, request)
        return socket.inet_ntoa(reply[20:24])
    except OSError as exc:
        logger.debug("Broadcast-Adresse fuer Schnittstelle %s: %s", name, exc)
        return ""


def broadcast_targets() -> tuple[str, ...]:
    """Alle Adressen, an die ein Suchpaket geht."""
    targets = [BROADCAST_ADDRESS]
    for _index, name in socket.if_nameindex():
        address = interface_broadcast(name)
        if address and address not in targets:
            targets.append(address)
    return tuple(targets)


# --------------------------------------------------------------------------- #
# Suche
# --------------------------------------------------------------------------- #
def _udp_socket(port: int = 0) -> socket.socket:
    """UDP-Socket fuer die Suche (Broadcast erlaubt, wiederverwendbar)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    return sock


def _ask(
    targets: Iterable[str],
    port: int,
    packet: bytes,
    timeout: float,
    parse: Callable[[bytes, str], list[NetworkPrinter]],
    cancel: threading.Event | None = None,
) -> list[NetworkPrinter]:
    """Paket(e) senden und Antworten einsammeln.

    Gesammelt wird so lange, bis nach der letzten Antwort
    :data:`SEARCH_QUIET_TIME` lang Ruhe war - hoechstens aber ``timeout``.
    Mit ``cancel`` (z. B. beim Schliessen des Fensters) bricht die Suche ab.
    """
    found: list[NetworkPrinter] = []
    deadline = time.monotonic() + timeout
    last_response: float | None = None
    with _udp_socket() as sock:
        for target in targets:
            try:
                sock.sendto(packet, (target, port))
            except OSError as exc:  # pragma: no cover - haengt am Netz
                logger.info("Suche an %s:%s nicht möglich: %s", target, port, exc)
        while True:
            now = time.monotonic()
            if cancel is not None and cancel.is_set():
                break
            limit = deadline
            if last_response is not None:
                if now - last_response >= SEARCH_QUIET_TIME:
                    break
                limit = min(deadline, last_response + SEARCH_QUIET_TIME)
            if now >= limit:
                break
            sock.settimeout(limit - now)
            try:
                data, address = sock.recvfrom(PACKET_LIMIT)
            except OSError:
                break  # Ruhezeit bzw. Zeitlimit ohne Antwort
            last_response = time.monotonic()
            try:
                found.extend(parse(data, address[0]))
            except (ValueError, struct.error) as exc:
                logger.debug("Antwort von %s nicht lesbar: %s", address[0], exc)
    return found


def mdns_printers(
    timeout: float = MDNS_TIMEOUT, cancel: threading.Event | None = None
) -> list[NetworkPrinter]:
    """Drucker per mDNS fragen (eine Anfrage, Antworten einsammeln)."""
    return _ask(
        (MDNS_GROUP,),
        MDNS_PORT,
        mdns_query(),
        timeout,
        parse_mdns_response,
        cancel,
    )


def snmp_printers(
    timeout: float = SNMP_TIMEOUT, cancel: threading.Event | None = None
) -> list[NetworkPrinter]:
    """Drucker per SNMP-Broadcast fragen (ein Paket, Antworten einsammeln)."""
    return _ask(
        broadcast_targets(),
        SNMP_PORT,
        snmp_request(),
        timeout,
        parse_snmp_response,
        cancel,
    )


def merge_printers(printers: Iterable[NetworkPrinter]) -> list[NetworkPrinter]:
    """Treffer beider Wege ueber die IP zusammenfassen.

    Derselbe Drucker meldet sich bei beiden Wegen. Der erste Eintrag gewinnt
    (mDNS zuerst: dessen Name ist der lesbare, "Brother QL-820NWB"), fehlende
    Angaben werden aus dem anderen uebernommen.
    """
    merged: dict[str, NetworkPrinter] = {}
    for printer in printers:
        current = merged.get(printer.host)
        if current is None:
            merged[printer.host] = printer
            continue
        merged[printer.host] = dataclasses.replace(
            current,
            model_id=current.model_id or printer.model_id,
            name=current.name or printer.name,
        )
    return sorted(
        merged.values(),
        key=lambda printer: (_host_sort_key(printer.host), printer.label()),
    )


def _host_sort_key(host: str) -> tuple[int, ...]:
    """IPs der Groesse nach sortieren (192.168.178.62 vor .108)."""
    try:
        return tuple(socket.inet_aton(host))
    except OSError:
        return ()


def discover_network_printers(
    timeout: float | None = None, cancel: threading.Event | None = None
) -> list[NetworkPrinter]:
    """Drucker im Netzwerk suchen - mDNS und SNMP gleichzeitig.

    Beide Wege laufen in eigenen Threads (zusammen also rund ``timeout``
    Sekunden, nicht doppelt so lange). Faellt ein Weg aus, liefert der andere
    trotzdem; ein Fehler wird nur protokolliert. Mit ``cancel`` bricht die
    Suche ab (z. B. beim Schliessen des Fensters).
    """
    ways: tuple[tuple[str, Callable[..., list[NetworkPrinter]]], ...] = (
        (SOURCE_MDNS, mdns_printers),
        (SOURCE_SNMP, snmp_printers),
    )
    results: list[list[NetworkPrinter]] = [[] for _ in ways]
    limit = timeout if timeout is not None else max(MDNS_TIMEOUT, SNMP_TIMEOUT)

    def search(index: int, search_call: Callable[..., list[NetworkPrinter]]) -> None:
        try:
            results[index] = search_call(limit, cancel)
        except Exception as exc:  # pragma: no cover - defensiv (Netz, Parser)
            logger.info("Suche fehlgeschlagen: %s", exc)

    threads = [
        threading.Thread(target=search, args=(index, call), name=name, daemon=True)
        for index, (name, call) in enumerate(ways)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return merge_printers(printer for group in results for printer in group)


__all__ = [
    "MDNS_SERVICE",
    "NetworkPrinter",
    "SOURCE_MDNS",
    "SOURCE_SNMP",
    "discover_network_printers",
    "known_model_ids",
    "looks_like_label_printer",
    "mdns_printers",
    "mdns_query",
    "merge_printers",
    "model_id_for_name",
    "parse_mdns_response",
    "parse_snmp_response",
    "confirm_network_job",
    "network_printer_errors",
    "network_snmp_answers",
    "snmp_get",
    "snmp_printers",
    "snmp_request",
    "snmp_varbinds",
]
