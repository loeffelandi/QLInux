"""Druck-Wrapper um ``brother_ql`` (in-process, kein Subprozess, kein Shell).

Kapselt:

* ``BrotherQLRaster`` + ``convert``  -> Rasterdaten erzeugen
* ``send``                           -> Rasterdaten an den Drucker schicken
* Statusabfrage / Band-Erkennung     -> soweit der Drucker Readback unterstuetzt

Alle Fehler werden als :class:`PrinterError` (bzw.
:class:`PrinterConnectionError`) sichtbar gemacht - nie stiller Absturz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import glob
import logging
import os
from pathlib import Path
import time

from PIL import Image

from brother_ql.backends import backend_factory, guess_backend
from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

from .media import DEFAULT_MODEL, Kind, LabelSpec, get_label, get_model

logger = logging.getLogger(__name__)

#: Standard-Druckport der Brother-Netzwerkdrucker (RAW/JetDirect).
NETWORK_PORT = 9100

#: Standard-Druckeradresse (aus den Settings ueberschreibbar).
DEFAULT_ADDRESS = f"tcp://192.168.178.62:{NETWORK_PORT}"

#: Status-Request-Kommando (ESC i S) - identisch zu ``add_status_information``.
_STATUS_REQUEST = b"\x1b\x69\x53"

#: Eine Statusantwort ist 32 Bytes lang.
_STATUS_RESPONSE_LEN = 32


# --------------------------------------------------------------------------- #
# Druckaufloesung (modellabhaengig) und Druckqualitaet (Schalter)
# --------------------------------------------------------------------------- #
#: Modelle mit "High resolution mode" (600 dpi in Bandlaufrichtung, quer
#: weiterhin 300 dpi). Belegt durch die Brother-Datenblaetter ("Print
#: resolution: Standard: 300 dpi x 300 dpi / High resolution mode: 300 dpi x
#: 600 dpi") von QL-800, QL-810W und QL-820NWB und durch die Raster Command
#: Reference der QL-800-Reihe: ``ESC i K``, Bit 7 - "1: It prints at 600 dpi in
#: the paper length direction". Die Datenblaetter der uebrigen Modelle nennen
#: nur den 300-dpi-Druckkopf und keinen High-Resolution-Modus.
#:
#: brother_ql 0.9.4 fuehrt diese Faehigkeit nicht mit, deshalb steht sie hier.
#: Bewusst konservativ: nur Modelle mit belegtem High-Resolution-Modus. Ein
#: neues Modell ist eine Zeile - die Aufloesung erscheint dann automatisch.
DPI_600_MODELS = frozenset({"QL-800", "QL-810W", "QL-820NWB"})

#: Renderfaktor fuer den 600-dpi-Modus: der Drucker setzt die Zeilen dann mit
#: halbem Abstand (600 dpi statt 300 dpi) - fuer die gleiche *Laenge* braucht
#: das Bild also doppelt so viele Zeilen. Genau das erwartet auch
#: ``convert()`` (``dots_expected = [el*2 for el in dots_printable]``).
DPI_600_SCALE = 2


@dataclass(frozen=True)
class PrintResolution:
    """Eine waehlbare Druckaufloesung - Abbildung auf ``convert()``-Schalter.

    ``scale`` ist der Renderfaktor (1 = 300 dpi, :data:`DPI_600_SCALE` = 600 dpi
    in Bandlaufrichtung). Der Wert ist **keine** Qualitaetsstufe: wie sauber der
    Druckkopf arbeitet, entscheidet er selbst - das Flag ``hq`` daneben stellt
    nur "Qualitaet vor Tempo".
    """

    key: str
    label: str
    detail: str
    scale: int = 1

    @property
    def dpi_600(self) -> bool:
        """True, wenn die Bandlaufrichtung feiner gesetzt wird (``ESC i K``)."""
        return self.scale > 1


#: Die Aufloesungen des 300-dpi-Druckkopfs. "300 x 600 dpi" gibt es nur bei
#: passendem Modell (siehe :data:`DPI_600_MODELS`).
RESOLUTION_STANDARD = PrintResolution(
    "standard",
    "300 × 300 dpi",
    "Standard des Druckkopfs - quer und in Bandlaufrichtung 300 dpi",
)
RESOLUTION_HIGH = PrintResolution(
    "high",
    "300 × 600 dpi",
    "High-Resolution-Modus: quer 300 dpi, in Bandlaufrichtung 600 dpi - "
    "feinere Zeilen, druckt langsamer",
    scale=DPI_600_SCALE,
)


def resolution_options(model_id: str) -> tuple[PrintResolution, ...]:
    """Waehlbare Aufloesungen fuer ein Modell - die hoechste steht zuletzt.

    Was ein Drucker kann, steht in seinen Datenblaettern; abfragen laesst es
    sich nicht (die Statusantwort kennt nur Band und Fehler). ``300 x 600 dpi``
    verlangt den Expanded-Mode **und** den High-Resolution-Druckkopf.
    """
    model = get_model(model_id)
    options = [RESOLUTION_STANDARD]
    if model.expanded_mode and model_id in DPI_600_MODELS:
        options.append(RESOLUTION_HIGH)
    return tuple(options)


def maximum_resolution(model_id: str) -> PrintResolution:
    """Die hoechste Aufloesung, die das Modell kann."""
    return resolution_options(model_id)[-1]


def resolution_by_key(model_id: str, key: str) -> PrintResolution:
    """Aufloesung per Schluessel; unbekannte Schluessel fallen auf das Maximum."""
    for option in resolution_options(model_id):
        if option.key == key:
            return option
    return maximum_resolution(model_id)


class PrinterError(RuntimeError):
    """Allgemeiner Druckfehler (ungueltige Parameter, Band, Modell, ...)."""


class PrinterConnectionError(PrinterError):
    """Der Drucker ist nicht erreichbar oder hat die Verbindung abgelehnt."""


#: Backends mit Rueckkanal - nur sie koennen eine Statusantwort empfangen.
#: Der Netzwerk-Anschluss (TCP 9100) ist eine reine Druckschnittstelle; das
#: sagt auch ``brother_ql`` selbst ("The network backend doesn't support
#: readback", ``backends/helpers.py``).
READBACK_BACKENDS = frozenset({"pyusb", "linux_kernel"})

#: Beispiele fuer die Adressfelder der Oberflaeche und Fehlermeldungen.
ADDRESS_EXAMPLES = (
    "tcp://192.168.178.62:9100",
    "usb://0x04f9:0x209b",
    "/dev/usb/lp0",
)


def backend_for_address(address: str) -> str:
    """Backend aus der Adresse ableiten (``brother_ql.backends.guess_backend``).

    ``usb://0x04f9:0x209b`` -> ``pyusb``, ``/dev/usb/lp0`` -> ``linux_kernel``,
    ``tcp://host:9100`` -> ``network``. Eine nackte ``host:port``-Angabe gilt
    ebenfalls als Netzwerk - brother_ql kennt sie nicht, hier ist sie
    offensichtlich. Alles Unbekannte faellt auf ``network`` zurueck (dann
    scheitert spaetestens der Verbindungsaufbau sichtbar, statt still das
    falsche Backend zu nehmen).
    """
    value = (address or "").strip()
    if not value:
        return "network"
    try:
        return guess_backend(value)
    except ValueError:
        logger.info(
            "Adresse %r passt zu keinem bekannten Praefix (%s) - nehme Netzwerk.",
            address,
            ", ".join(ADDRESS_EXAMPLES),
        )
        return "network"


def backend_supports_readback(backend: str) -> bool:
    """Kann dieses Backend eine Statusantwort empfangen (Band-Erkennung)?"""
    return backend in READBACK_BACKENDS


def parse_network_address(text: str) -> str:
    """Nutzerangabe -> vollstaendige Netzwerkadresse ``tcp://host:port``.

    Wer nur die IP tippt (``192.168.178.62``), bekommt Praefix und Port
    ergaenzt; wer ``tcp://`` oder einen anderen Port mitgibt, behaelt ihn.
    Leer bleibt leer - dann sagt der Druckdialog, dass die Adresse fehlt
    (besser als still auf einen fremden Standarddrucker zu senden).
    """
    value = (text or "").strip()
    if not value:
        return ""
    for prefix in ("tcp://", "socket://", "network://"):
        value = value.removeprefix(prefix)
    value = value.rstrip("/")
    if not value:
        return ""
    host, port = value, NETWORK_PORT
    if value.startswith("["):  # IPv6 in Klammern: [::1] oder [::1]:9101
        head, _, rest = value.partition("]")
        host = f"{head}]"
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    elif value.count(":") == 1:
        head, _, tail = value.partition(":")
        if tail.isdigit():
            host, port = head, int(tail)
    if not host.strip("[]"):
        return ""
    return f"tcp://{host}:{port}"


def network_host(address: str) -> str:
    """Anzeigeform einer Netzwerkadresse: ``tcp://host:9100`` -> ``host``.

    Der Standardport verschwindet, ein abweichender bleibt sichtbar - so sieht
    man im Feld genau das, was man auch eintippen wuerde.
    """
    value = (address or "").strip()
    for prefix in ("tcp://", "socket://", "network://"):
        value = value.removeprefix(prefix)
    value = value.rstrip("/")
    if value.endswith(f":{NETWORK_PORT}"):
        value = value[: -len(f":{NETWORK_PORT}")]
    return value


def usb_devices() -> list[str]:
    """Angeschlossene USB-Drucker als Adressen fuer :class:`PrinterConfig`.

    Liefert ``usb://0x04f9:0x209b`` (pyusb) **und** ``/dev/usb/lp0``
    (Kernel-Treiber, falls ``usblp`` das Geraet haelt). Die pyusb-Kennung wird
    auf Hersteller und Produkt gekuerzt: die Seriennummer aus
    ``list_available_devices()`` ist in brother_ql 0.9.4 nicht
    rueckuebersetzbar (``int("0x209b_SERIAL", 16)`` scheitert).
    """
    found: list[str] = []
    try:
        backend = backend_factory("pyusb")
        for device in backend["list_available_devices"]():
            identifier = str(device.get("identifier", ""))
            head = identifier.removeprefix("usb://").split("/")[0].split("_")[0]
            address = f"usb://{head}" if head else ""
            if address and address not in found:
                found.append(address)
    except Exception as exc:  # pragma: no cover - haengt an libusb/Rechten
        logger.info("USB-Suche (pyusb) fehlgeschlagen: %s", exc)
    for path in sorted(glob.glob("/dev/usb/lp*")):
        if path not in found:
            found.append(path)
    return found


#: USB-Kennungen (Hersteller:Produkt) der Modelle, die ``brother_ql`` kennt.
#:
#: Quelle: ``usb.ids``-Datenbank (Paket ``usb.ids``, ``/usr/share/misc/usb.ids``).
#: ``brother_ql`` 0.9.4 fuehrt selbst keine USB-Kennungen - ``ModelSpec`` hat
#: kein ``usb_identifiers``. Nur Modelle der Bibliothek sind aufgefuehrt; der
#: QL-580N fehlt, weil ``usb.ids`` fuer ihn keine Kennung nennt, und die
#: Massenspeicher-Modi (z. B. QL-700 als ``0x2049``) fehlen bewusst - dort wird
#: nicht gedruckt.
USB_MODELS: dict[str, str] = {
    "04f9:2015": "QL-500",
    "04f9:2016": "QL-550",
    "04f9:201b": "QL-650TD",
    "04f9:2020": "QL-1050",
    "04f9:2027": "QL-560",
    "04f9:2028": "QL-570",
    "04f9:202a": "QL-1060N",
    "04f9:2042": "QL-700",
    "04f9:2043": "QL-710W",
    "04f9:2044": "QL-720NW",
    "04f9:209b": "QL-800",
    "04f9:209c": "QL-810W",
    "04f9:209d": "QL-820NWB",
}


def usb_id_from_identifier(identifier: str) -> str | None:
    """USB-Kennung ``"04f9:2042"`` aus ``usb://0x04f9:0x2042[_serial]``."""
    head = identifier.strip().removeprefix("usb://").split("/")[0].split("_")[0]
    vendor, sep, product = head.partition(":")
    if not sep:
        return None
    try:
        return f"{int(vendor, 16):04x}:{int(product, 16):04x}"
    except ValueError:
        return None


def usb_id_for_path(path: str, *, sysfs_root: str = "/sys") -> str | None:
    """USB-Kennung eines Kernel-Druckergeraets (``/dev/usb/lp1``) ueber sysfs.

    ``usblp`` legt ``/sys/class/usbmisc/lpN`` an; dessen ``device``-Verweis zeigt
    auf das USB-Interface, eine Ebene darueber liegt das Geraet mit
    ``idVendor``/``idProduct``. Ohne Kernel-Treiber gibt es diesen Weg nicht -
    dann bleibt nur die pyusb-Adresse.
    """
    name = path.strip().removeprefix("file://").rsplit("/", 1)[-1]
    try:
        interface = (Path(sysfs_root) / "class" / "usbmisc" / name / "device").resolve()
        vendor = (interface.parent / "idVendor").read_text().strip()
        product = (interface.parent / "idProduct").read_text().strip()
    except OSError:
        return None
    if not vendor or not product:
        return None
    return f"{vendor.lower()}:{product.lower()}"


def model_for_address(address: str) -> str | None:
    """Modell zu einer USB-Adresse - ``None``, wenn es nicht ableitbar ist.

    Netzwerkadressen liefern bewusst ``None``: welcher Drucker dort antwortet,
    verraet die reine TCP-Druckschnittstelle nicht.
    """
    address = address.strip()
    if backend_for_address(address) not in READBACK_BACKENDS:
        return None
    usb_id = (
        usb_id_from_identifier(address)
        if address.startswith("usb://")
        else usb_id_for_path(address)
    )
    return USB_MODELS.get(usb_id) if usb_id else None


def usb_device_label(address: str) -> str:
    """Beschriftung eines USB-Geraets fuer die Auswahlliste der USB-Suche."""
    backend = backend_for_address(address)
    if backend not in READBACK_BACKENDS:
        return address
    kind = "Kernel-Anschluss" if backend == "linux_kernel" else "libusb"
    model = model_for_address(address)
    suffix = f", {model}" if model else ""
    return f"{address}  ({kind}{suffix})"


def writable(path: str | Path) -> bool | None:
    """Darf der Benutzer diesen Geraeteknoten schreiben?

    ``None``, wenn es den Knoten nicht gibt - dann ist die Frage nicht
    beantwortbar (z. B. Drucker abgesteckt).
    """
    path = Path(path)
    if not path.exists():
        return None
    return os.access(path, os.W_OK)


def usb_access(
    address: str,
    *,
    sysfs_root: str = "/sys",
    dev_root: str = "/dev",
) -> bool | None:
    """Darf der Benutzer diesen USB-Drucker oeffnen? ``None`` = nicht feststellbar.

    Es wird nur das Schreibrecht geprueft, kein Geraet geoeffnet - die Abfrage
    hat also keinen Nebeneffekt am Drucker. Kernel-Anschluss: ``/dev/usb/lpN``.
    libusb: der rohe Knoten ``/dev/bus/usb/BBB/DDD``, ueber sysfs aufgeloest
    (``busnum``/``devnum`` des Geraets mit passender USB-Kennung).

    ``sysfs_root``/``dev_root`` sind fuer Tests injizierbar.
    """
    address = (address or "").strip()
    backend = backend_for_address(address)
    if backend == "linux_kernel":
        path = address.removeprefix("file://")
        if not path.startswith("/dev/"):
            return None
        return writable(Path(dev_root, path[len("/dev/") :]))
    if backend != "pyusb":
        return None
    usb_id = usb_id_from_identifier(address)
    if not usb_id:
        return None
    vendor, _, product = usb_id.partition(":")
    for device in sorted((Path(sysfs_root) / "bus" / "usb" / "devices").glob("*")):
        try:
            if (device / "idVendor").read_text().strip().lower() != vendor:
                continue
            if (device / "idProduct").read_text().strip().lower() != product:
                continue
            busnum = int((device / "busnum").read_text().strip())
            devnum = int((device / "devnum").read_text().strip())
        except (OSError, ValueError):
            continue
        node = Path(dev_root) / "bus" / "usb" / f"{busnum:03d}" / f"{devnum:03d}"
        return writable(node)
    return None


@dataclass(frozen=True)
class PrinterConfig:
    """Verbindungs- und Geraeteparameter.

    Bewusst als Datenklasse - die UI liest/schreibt diese Werte in QSettings
    und hardcodet keine Adresse.

    ``backend`` wird aus der Adresse abgeleitet, wenn es leer bleibt: das haelt
    Netzwerk-, pyusb- und Kernel-USB-Anschluss in *einem* Feld (siehe
    :func:`backend_for_address`).
    """

    model: str = DEFAULT_MODEL
    address: str = DEFAULT_ADDRESS
    backend: str = ""

    def __post_init__(self) -> None:
        # Frueh validieren: unbekanntes Modell -> klarer Fehler statt spaeter.
        try:
            get_model(self.model)
        except KeyError as exc:
            raise PrinterError(f"Unbekanntes Druckermodell: {self.model!r}") from exc
        if not self.backend:
            object.__setattr__(self, "backend", backend_for_address(self.address))


@dataclass(frozen=True)
class PrinterStatus:
    """Geparster Druckerstatus (siehe ``brother_ql.reader``)."""

    status_type: str
    phase_type: str
    media_type: str
    media_width_mm: int
    media_length_mm: int
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# --------------------------------------------------------------------------- #
# Rasterdaten erzeugen
# --------------------------------------------------------------------------- #
def validate_for_print(
    image: Image.Image,
    label: LabelSpec,
    *,
    red: bool = False,
    scale: int = 1,
) -> None:
    """Pruefe Bild und Band *vor* der Konvertierung.

    Erzwingt das Kernprinzip: Bildbreite == ``scale * label.dots_printable[0]``.
    ``scale=2`` ist der 600-dpi-Modus - dort erwartet ``convert()`` genau die
    doppelte Breite (``dots_expected``).
    """
    expected = label.width_dots * scale
    if image.width != expected:
        raise PrinterError(
            f"Bildbreite {image.width} px != {expected} px "
            f"(Band {label.identifier!r}, Faktor {scale}). Bitte ueber den "
            f"Renderer erzeugen."
        )
    if red and not label.color.supports_red:
        raise PrinterError(
            f"Rotdruck ist mit Band {label.identifier!r} "
            f"({label.display_name}) nicht moeglich."
        )


def build_raster(
    image: Image.Image,
    label: LabelSpec,
    config: PrinterConfig,
    *,
    threshold: int = 70,
    dither: bool = False,
    compress: bool = True,
    red: bool = False,
    rotate: int | str = 0,
    cut: bool = True,
    dpi_600: bool = False,
    hq: bool = True,
) -> bytes:
    """Erzeuge die Raster-Instruktionsbytes fuer ``image`` (ohne zu drucken).

    Reiner Rechenweg - ideal fuer ``--dry-run`` und Tests.

    Mit ``dpi_600=True`` muss ``image`` ``DPI_600_SCALE`` mal so gross sein
    (siehe :data:`DPI_600_SCALE`); ``convert()`` setzt dann das High-Resolution-
    Bit und erwartet genau diese Groesse.
    """
    validate_for_print(
        image, label, red=red, scale=DPI_600_SCALE if dpi_600 else 1
    )

    model = get_model(config.model)
    if red and not model.two_color:
        raise PrinterError(
            f"Modell {config.model!r} unterstuetzt keinen Rotdruck."
        )

    qlr = BrotherQLRaster(model=config.model)
    qlr.exception_on_warning = True  # Warnungen als Fehler sichtbar machen
    try:
        convert(
            qlr=qlr,
            images=[image],
            label=label.identifier,
            rotate=rotate,
            threshold=threshold,
            dither=dither,
            compress=compress,
            red=red,
            cut=cut,
            dpi_600=dpi_600,
            hq=hq,
        )
    except PrinterError:
        raise
    except Exception as exc:  # brother_ql-Fehler in unser Modell uebersetzen
        raise PrinterError(f"Konvertierung fehlgeschlagen: {exc}") from exc

    return bytes(qlr.data)


# --------------------------------------------------------------------------- #
# Senden
# --------------------------------------------------------------------------- #
def send_instructions(
    data: bytes, config: PrinterConfig, *, blocking: bool = True
) -> dict:
    """Sende ``data`` an den Drucker. Uebersetzt Verbindungsfehler."""
    try:
        status = send(
            instructions=data,
            printer_identifier=config.address,
            backend_identifier=config.backend,
            blocking=blocking,
        )
    except (ConnectionError, OSError, TimeoutError) as exc:
        raise PrinterConnectionError(
            f"Drucker {config.address!r} nicht erreichbar: {exc}"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise PrinterError(f"Senden fehlgeschlagen: {exc}") from exc
    return status


def print_image(
    image: Image.Image, label: LabelSpec, config: PrinterConfig, **options
) -> dict:
    """Komfortfunktion: Rasterdaten erzeugen und drucken.

    ``**options`` wird an :func:`build_raster` durchgereicht.
    """
    data = build_raster(image, label, config, **options)
    logger.info(
        "Sende Etikett: Band %s, Modell %s, %d Bytes an %s",
        label.identifier,
        config.model,
        len(data),
        config.address,
    )
    return send_instructions(data, config)


# --------------------------------------------------------------------------- #
# Status / Band-Erkennung
# --------------------------------------------------------------------------- #
def probe_status(config: PrinterConfig, *, timeout: float = 2.0) -> PrinterStatus | None:
    """Frage den Druckerstatus ab.

    :returns: :class:`PrinterStatus` oder ``None``, wenn der Drucker keinen
        Readback liefert (z. B. reine TCP-Druckschnittstelle) oder nicht
        erreichbar ist. Wirft in diesem Fall **nicht** - die UI soll sauber
        auf manuelle Auswahl zurueckfallen koennen.
    """
    from brother_ql.reader import interpret_response

    try:
        be = backend_factory(config.backend)
        backend = be["backend_class"](config.address)
    except Exception as exc:
        logger.debug("Statusabfrage: Verbindungsaufbau fehlgeschlagen: %s", exc)
        return None

    try:
        backend.write(_STATUS_REQUEST)
        data = b""
        start = time.monotonic()
        while len(data) < _STATUS_RESPONSE_LEN and time.monotonic() - start < timeout:
            chunk = backend.read(_STATUS_RESPONSE_LEN - len(data))
            if chunk:
                data += chunk
            else:
                time.sleep(0.02)
        if len(data) < _STATUS_RESPONSE_LEN:
            logger.info(
                "Statusabfrage: keine/zu kurze Antwort (%d Bytes) - "
                "Drucker unterstuetzt vermutlich keinen Readback.",
                len(data),
            )
            return None
        result = interpret_response(data)
    except Exception as exc:
        logger.info("Statusabfrage fehlgeschlagen: %s", exc)
        return None
    finally:
        backend.dispose()

    return PrinterStatus(
        status_type=result["status_type"],
        phase_type=result["phase_type"],
        media_type=result["media_type"],
        media_width_mm=result["media_width"],
        media_length_mm=result["media_length"],
        errors=tuple(result["errors"]),
    )


def detect_label(config: PrinterConfig, *, timeout: float = 2.0) -> LabelSpec | None:
    """Versuche das eingelegte Band zu erkennen.

    :returns: passendes :class:`LabelSpec` oder ``None`` (kein Readback /
        unbekanntes Band). Verhindert den "wrong roll type"-Fehler, wenn der
        Drucker Readback unterstuetzt.
    """
    status = probe_status(config, timeout=timeout)
    if status is None or status.media_width_mm <= 0:
        return None

    endless = status.media_type == "Continuous length tape"
    candidates = _match_labels(
        status.media_width_mm,
        status.media_length_mm,
        endless=endless,
    )
    for label in candidates:
        if label.usable_by(config.model):
            return label
    logger.info(
        "Statusabfrage: Band %d mm / Laenge %d mm (%s) passt zu keinem bekannten Band.",
        status.media_width_mm,
        status.media_length_mm,
        status.media_type,
    )
    return None


def _match_labels(width_mm: int, length_mm: int, *, endless: bool) -> list[LabelSpec]:
    """Finde Kandidaten-Baender zu Breite (und optional Laenge) aus dem Status.

    Die Reihenfolge ist die Praeferenz: exakte Laengentreffer zuerst.
    """
    from .media import all_labels

    def kind_ok(label: LabelSpec) -> bool:
        if endless:
            return label.kind is Kind.ENDLESS
        # Die-cut und rund melden beide 'Die-cut labels'.
        return label.kind in (Kind.DIE_CUT, Kind.ROUND_DIE_CUT)

    width_matches = [
        lbl for lbl in all_labels() if lbl.tape_width_mm == width_mm and kind_ok(lbl)
    ]
    if endless or length_mm <= 0:
        return width_matches
    exact = [lbl for lbl in width_matches if lbl.tape_size[1] == length_mm]
    return exact or width_matches


__all__ = [
    "ADDRESS_EXAMPLES",
    "DEFAULT_ADDRESS",
    "NETWORK_PORT",
    "PrinterError",
    "PrinterConnectionError",
    "PrinterConfig",
    "PrinterStatus",
    "READBACK_BACKENDS",
    "USB_MODELS",
    "backend_for_address",
    "backend_supports_readback",
    "model_for_address",
    "network_host",
    "parse_network_address",
    "usb_access",
    "usb_device_label",
    "usb_id_for_path",
    "usb_id_from_identifier",
    "validate_for_print",
    "build_raster",
    "send_instructions",
    "print_image",
    "probe_status",
    "detect_label",
    "usb_devices",
    "writable",
]
