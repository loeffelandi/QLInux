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
import logging
import time

from PIL import Image

from brother_ql.backends import backend_factory
from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

from .media import DEFAULT_MODEL, Kind, LabelSpec, get_label, get_model

logger = logging.getLogger(__name__)

#: Standard-Druckeradresse (aus den Settings ueberschreibbar).
DEFAULT_ADDRESS = "tcp://192.168.178.62:9100"

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


@dataclass(frozen=True)
class PrinterConfig:
    """Verbindungs- und Geraeteparameter.

    Bewusst als Datenklasse - die UI liest/schreibt diese Werte in QSettings
    und hardcodet keine Adresse.
    """

    model: str = DEFAULT_MODEL
    address: str = DEFAULT_ADDRESS
    backend: str = "network"

    def __post_init__(self) -> None:
        # Frueh validieren: unbekanntes Modell -> klarer Fehler statt spaeter.
        try:
            get_model(self.model)
        except KeyError as exc:
            raise PrinterError(f"Unbekanntes Druckermodell: {self.model!r}") from exc


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
    "DEFAULT_ADDRESS",
    "PrinterError",
    "PrinterConnectionError",
    "PrinterConfig",
    "PrinterStatus",
    "validate_for_print",
    "build_raster",
    "send_instructions",
    "print_image",
    "probe_status",
    "detect_label",
]
