"""Datenmodell fuer Baender, Druckermodelle und Masseinheiten.

Bewusst **frei von Qt und Pillow**, damit die Logik headless testbar ist.

Einzige Quelle der Wahrheit sind die Datenstrukturen der installierten
``brother_ql`` (hier 0.9.4):

* :class:`brother_ql.labels.LabelsManager` - Baender (Label-Typen)
* :class:`brother_ql.models.ModelsManager` - Druckermodelle

Es werden **keine** Pixelbreiten oder Bandmasse hartcodiert: alle Werte
kommen dynamisch aus der Bibliothek.

Hinweis: Das historische Modul ``brother_ql.devicedependent`` ist in dieser
Version nur noch ein (deprecated) Shim ueber ``labels``/``models``. Wir
importieren daher direkt aus den modernen Modulen - das vermeidet auch die
Deprecation-Warnung beim Import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from brother_ql.labels import FormFactor as _FormFactor, Color as _Color, LabelsManager
from brother_ql.models import Model as _Model, ModelsManager

from .i18n import tr

#: Druckaufloesung der QL-Serie in dpi.
DPI: int = 300

#: Millimeter pro Zoll (exakte Definition).
MM_PER_INCH: float = 25.4

#: Umrechnungsfaktor mm -> Dots bei :data:`DPI`.
DOTS_PER_MM: float = DPI / MM_PER_INCH  # ~ 11.811

#: Standardmodell dieser Installation.
DEFAULT_MODEL: str = "QL-820NWB"

#: Standardband fuer die Erstauswahl in der GUI (50 mm Endlos).
DEFAULT_LABEL: str = "50"

#: Zusaetzlicher Schnittversatz (Dots) fuer Endlosband.
#:
#: Der QL-820NWB kann den Vorschub nicht auf 0 setzen: ``convert()`` sendet
#: ``feed_margin`` als Rand und das Band muss vor dem Schnitt bis zur Schneide
#: (hinter dem Druckkopf) vorgeschoben werden. Empirisch ergibt sich fuer ein
#: 50-mm-Endlosband bei 40 mm Inhalt eine Gesamtlaenge von ~47 mm, also
#: ``2 * feed_margin(35) + 13 = 83 Dots ≈ 7,0 mm``. Der Wert ist bewusst als
#: Konstante gefuehrt und nach einer Messung leicht nachjustierbar.
CUT_OFFSET_DOTS: int = 13


# --------------------------------------------------------------------------- #
# Masseinheiten
# --------------------------------------------------------------------------- #
def mm_to_dots(mm: float) -> int:
    """Rechne Millimeter in Dots (bei 300 dpi) um.

    ``px = mm * 300 / 25.4`` - gerundet auf die naechste ganze Zahl.
    """
    if mm < 0:
        raise ValueError(f"Negative Laenge nicht erlaubt: {mm!r} mm")
    return int(round(mm * DOTS_PER_MM))


def dots_to_mm(dots: float) -> float:
    """Rechne Dots (bei 300 dpi) in Millimeter um."""
    return dots / DOTS_PER_MM


def dots_to_px(dots: int) -> int:
    """Dots entsprechen bei 300 dpi direkt Pixeln - Explizitheit fuer Leser."""
    return int(dots)


# --------------------------------------------------------------------------- #
# Enums (entkoppelt von brother_ql-Interna)
# --------------------------------------------------------------------------- #
class Kind(str, Enum):
    """Band-Formfaktor."""

    ENDLESS = "endless"
    DIE_CUT = "die-cut"
    ROUND_DIE_CUT = "round"

    @classmethod
    def from_library(cls, form_factor: _FormFactor) -> "Kind":
        return _KIND_FROM_FORM_FACTOR[form_factor]

    @property
    def is_endless(self) -> bool:
        return self is Kind.ENDLESS

    @property
    def is_fixed_size(self) -> bool:
        """Die-cut / round: beide Dimensionen sind vorgegeben."""
        return not self.is_endless

    @property
    def label_de(self) -> str:
        """Kurzbezeichnung fuer die Oberflaeche."""
        if self is Kind.ENDLESS:
            return tr("Endlos")
        if self is Kind.DIE_CUT:
            return tr("Die-cut")
        return tr("Rund (Die-cut)")


_KIND_FROM_FORM_FACTOR = {
    _FormFactor.ENDLESS: Kind.ENDLESS,
    _FormFactor.DIE_CUT: Kind.DIE_CUT,
    _FormFactor.ROUND_DIE_CUT: Kind.ROUND_DIE_CUT,
}


class Color(str, Enum):
    """Bedruckbare Farben des Bandes."""

    BLACK_WHITE = "black_white"
    BLACK_RED_WHITE = "black_red_white"

    @classmethod
    def from_library(cls, color: _Color) -> "Color":
        return _COLOR_FROM_LIBRARY[color]

    @property
    def supports_red(self) -> bool:
        return self is Color.BLACK_RED_WHITE


_COLOR_FROM_LIBRARY = {
    _Color.BLACK_WHITE: Color.BLACK_WHITE,
    _Color.BLACK_RED_WHITE: Color.BLACK_RED_WHITE,
}


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Margins:
    """Druckraender in Millimetern."""

    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {"left": self.left, "right": self.right, "top": self.top, "bottom": self.bottom}


@dataclass(frozen=True)
class LabelSpec:
    """Ein waehlbares Band, dynamisch aus der Bibliothek gelesen."""

    identifier: str
    name: str
    tape_size: tuple[int, int]
    form_factor: Kind
    color: Color
    dots_printable: tuple[int, int]
    dots_total: tuple[int, int]
    right_margin_dots: int
    feed_margin: int
    restricted_to_models: tuple[str, ...]

    # -- Bequeme Kennzahlen -------------------------------------------------
    @property
    def kind(self) -> Kind:
        return self.form_factor

    @property
    def tape_width_mm(self) -> int:
        return self.tape_size[0]

    @property
    def width_dots(self) -> int:
        """Druckbare Breite in Dots - die **Canvas-Breite**."""
        return self.dots_printable[0]

    @property
    def height_dots(self) -> int:
        """Druckbare Hoehe in Dots (0 bei Endlosband)."""
        return self.dots_printable[1]

    @property
    def is_endless(self) -> bool:
        return self.form_factor.is_endless

    @property
    def printable_width_mm(self) -> float:
        return dots_to_mm(self.dots_printable[0])

    @property
    def feed_margin_mm(self) -> float:
        return dots_to_mm(self.feed_margin)

    @property
    def tape_total_width_dots(self) -> int:
        """Volle Bandbreite in Dots (inkl. nicht bedruckbarer Raender)."""
        return self.dots_total[0]

    @property
    def side_border_dots(self) -> int:
        """Nicht bedruckbarer Rand links/rechts in Dots.

        ``(dots_total - dots_printable) / 2`` - der Druckkopf kann die
        aeussersten Bandkanten nicht bedrucken (beim QL-820NWB ~18 Dots
        = 1,52 mm pro Seite). Der Canvas deckt bereits nur den bedruckbaren
        Bereich ab; dieser Wert dient der Anzeige/Begrenzung in der GUI.
        """
        return max(0, (self.dots_total[0] - self.dots_printable[0]) // 2)

    @property
    def side_border_mm(self) -> float:
        return dots_to_mm(self.side_border_dots)

    # -- Darstellung --------------------------------------------------------
    @property
    def display_name(self) -> str:
        """Dropdown-Text, z. B. ``"50 mm endlos"`` bzw. ``"62 mm endlos (schwarz/rot)"``."""
        kind = self.form_factor.label_de.lower()
        if self.kind.is_fixed_size:
            base = tr("{width} x {height} mm {kind}").format(
                width=self.tape_size[0], height=self.tape_size[1], kind=kind
            )
        else:
            base = tr("{width} mm {kind}").format(
                width=self.tape_size[0], kind=kind
            )
        if self.color.supports_red:
            base += f" {tr('(schwarz/rot)')}"
        return base

    # -- Modell-Kompatibilitaet --------------------------------------------
    def usable_by(self, model_identifier: str) -> bool:
        """True, wenn das Band auf dem angegebenen Modell verwendet werden darf.

        Ein leeres ``restricted_to_models`` bedeutet: fuer alle Modelle erlaubt.
        """
        if not self.restricted_to_models:
            return True
        return model_identifier in self.restricted_to_models

    def prints_on(self, loaded: "LabelSpec") -> bool:
        """True, wenn ein Auftrag fuer dieses Band auf das eingelegte passt.

        Groesse und Art muessen stimmen. Rot braucht ein schwarz/rotes Band,
        Schwarz passt auch darauf.
        """
        if self.tape_size != loaded.tape_size or self.form_factor != loaded.form_factor:
            return False
        return loaded.color.supports_red or not self.color.supports_red

    # -- Voreinstellungen ---------------------------------------------------
    def default_margins(self) -> Margins:
        """Startwerte fuer die Margin-Felder: alles 0 mm.

        Der Vorschub (``feed_margin``) und der nicht bedruckbare Seitenrand
        sind schon automatisch drin - ``brother_ql`` fuegt den Vorschub im
        Datenstrom ein, und die Bandbreite ist um den Seitenrand verkleinert.
        Ein zusaetzlicher Rand ist eine bewusste Entscheidung des Nutzers.
        """
        return Margins(left=0.0, right=0.0, top=0.0, bottom=0.0)


@dataclass(frozen=True)
class ModelSpec:
    """Ein unterstuetztes Druckermodell, dynamisch aus der Bibliothek."""

    identifier: str
    min_max_length_dots: tuple[int, int]
    number_bytes_per_row: int
    additional_offset_r: int
    two_color: bool
    cutting: bool
    compression: bool
    mode_setting: bool
    expanded_mode: bool

    @property
    def device_pixel_width(self) -> int:
        """Physische Druckkopfbreite in Dots (Vielfaches von 8)."""
        return self.number_bytes_per_row * 8

    @property
    def min_length_mm(self) -> float:
        return dots_to_mm(self.min_max_length_dots[0])

    @property
    def max_length_mm(self) -> float:
        return dots_to_mm(self.min_max_length_dots[1])

    def clamp_length_dots(self, dots: int) -> int:
        lo, hi = self.min_max_length_dots
        if dots < lo:
            return lo
        if dots > hi:
            return hi
        return dots


# --------------------------------------------------------------------------- #
# Registry / Zugriff
# --------------------------------------------------------------------------- #
def _label_spec_from_library(label: object) -> LabelSpec:
    return LabelSpec(
        identifier=label.identifier,
        name=label.name,
        tape_size=tuple(label.tape_size),
        form_factor=Kind.from_library(label.form_factor),
        color=Color.from_library(label.color),
        dots_printable=tuple(label.dots_printable),
        dots_total=tuple(label.dots_total),
        right_margin_dots=int(label.offset_r),
        feed_margin=int(label.feed_margin),
        restricted_to_models=tuple(label.restricted_to_models or ()),
    )


def _model_spec_from_library(model: _Model) -> ModelSpec:
    return ModelSpec(
        identifier=model.identifier,
        min_max_length_dots=tuple(model.min_max_length_dots),
        number_bytes_per_row=int(model.number_bytes_per_row),
        additional_offset_r=int(model.additional_offset_r),
        two_color=bool(model.two_color),
        cutting=bool(model.cutting),
        compression=bool(model.compression),
        mode_setting=bool(model.mode_setting),
        expanded_mode=bool(model.expanded_mode),
    )


@lru_cache(maxsize=1)
def all_labels() -> tuple[LabelSpec, ...]:
    """Alle Baender (in Bibliotheks-Reihenfolge)."""
    return tuple(_label_spec_from_library(el) for el in LabelsManager().iter_elements())


@lru_cache(maxsize=1)
def all_models() -> tuple[ModelSpec, ...]:
    """Alle unterstuetzten Druckermodelle."""
    return tuple(_model_spec_from_library(el) for el in ModelsManager().iter_elements())


@lru_cache(maxsize=1)
def _label_index() -> dict[str, LabelSpec]:
    return {spec.identifier: spec for spec in all_labels()}


@lru_cache(maxsize=1)
def _model_index() -> dict[str, ModelSpec]:
    return {spec.identifier: spec for spec in all_models()}


def get_label(identifier: str) -> LabelSpec:
    """Band nach Kennung (z. B. ``"50"``)."""
    try:
        return _label_index()[identifier]
    except KeyError as exc:
        raise KeyError(
            tr("Unbekanntes Band: {label!r}").format(label=identifier)
        ) from exc


def get_model(identifier: str) -> ModelSpec:
    """Druckermodell nach Kennung (z. B. ``"QL-820NWB"``)."""
    try:
        return _model_index()[identifier]
    except KeyError as exc:
        raise KeyError(
            tr("Unbekanntes Modell: {model!r}").format(model=identifier)
        ) from exc


def labels_for_model(model_identifier: str) -> tuple[LabelSpec, ...]:
    """Alle Baender, die fuer das Modell zugelassen sind."""
    # Wirft KeyError bei unbekanntem Modell - gewollt (frueher Fehler).
    get_model(model_identifier)
    return tuple(lbl for lbl in all_labels() if lbl.usable_by(model_identifier))


def has_two_color_support(model_identifier: str) -> bool:
    return get_model(model_identifier).two_color


# --------------------------------------------------------------------------- #
# Laengen-Semantik und Druckerrand
# --------------------------------------------------------------------------- #
class LengthMode(str, Enum):
    """Bedeutung der eingegebenen Laenge bei Endlosband.

    * ``CONTENT``  - die Laenge ist der **bedruckte Inhalt** (Canvas-Hoehe 1:1).
      Das fertige Etikett ist dann ``Inhalt + Druckerrand``.
    * ``FINISHED`` - die Laenge ist das **fertige Etikett** inklusive
      Druckerrand (Vorschub + Schnitt). Der Inhalt wird entsprechend reduziert.
    """

    CONTENT = "content"
    FINISHED = "finished"


class Orientation(str, Enum):
    """Ausrichtung des Etiketts relativ zum Bandvorschub.

    Die **bedruckbare Bandbreite** (``dots_printable[0]``) ist immer die
    Grenze quer zum Band - nur so wird der Druckkopf 1:1 angesteuert und
    ``brother_ql`` muss nicht skalieren. Die Ausrichtung bestimmt nur, welche
    Achse der Designflaeche diese Bandbreite belegt:

    * ``ACROSS`` (Voreinstellung) - die Etikettenlaenge laeuft **quer** zum
      Band: der Inhalt wird ueber die Bandbreite gesetzt (Text steht quer zum
      Band), die Laenge ergibt sich aus der **Inhaltshoehe**.
      Canvas = ``(Bandbreite x Laenge)``, Druck = Canvas 1:1.
    * ``ALONG`` - die Etikettenlaenge laeuft **laengs** des Bandes: der Inhalt
      wird in Bandrichtung gesetzt (Text steht laengs zum Band), die Laenge
      ergibt sich aus der **Inhaltsbreite**. Fuer den Druck wird die Szene um
      90 Grad gedreht (Gradzahl nur in :mod:`ql_editor.renderer`).
      Canvas = ``(Laenge x Bandbreite)``.

    Beide Ausrichtungen sind nuetzlich: ``ACROSS`` spart Band bei breitem,
    flachem Inhalt (lange Textzeile), ``ALONG`` bei hohem, schmalem Inhalt
    (mehrere gestapelte Zeilen), weil dann die Bandbreite als Hoehenbudget
    dient.
    """

    ACROSS = "across"
    ALONG = "along"

    @property
    def label_de(self) -> str:
        """Kurzbezeichnung fuer die Oberflaeche."""
        if self is Orientation.ACROSS:
            return tr("quer zum Band")
        return tr("längs des Bandes")

    @property
    def rotates_for_print(self) -> bool:
        """True, wenn fuer den Druck um 90 Grad gedreht werden muss."""
        return self is Orientation.ALONG


def printer_extra_dots(label: LabelSpec) -> int:
    """Zusaetzliche Laenge (Dots), die der Drucker bei Endlosband hinzufuegt.

    Bei Die-cut/Rund ist die Etikettenlaenge physisch fixiert -> 0.
    """
    if not label.is_endless:
        return 0
    return 2 * label.feed_margin + CUT_OFFSET_DOTS


def content_dots_for_finished_length(
    label: LabelSpec, model: ModelSpec, finished_length_mm: float
) -> int:
    """Rechne eine gewuenschte Gesamtlaenge in die noetige Inhaltshoehe um."""
    total = mm_to_dots(float(finished_length_mm))
    content = total - printer_extra_dots(label)
    return model.clamp_length_dots(max(content, model.min_max_length_dots[0]))


def finished_length_mm(label: LabelSpec, content_dots: int) -> float:
    """Gesamtlaenge (mm) eines Etiketts mit ``content_dots`` bedruckter Hoehe."""
    return dots_to_mm(content_dots + printer_extra_dots(label))


# --------------------------------------------------------------------------- #
# Canvas-Groesse
# --------------------------------------------------------------------------- #
def label_length_dots(
    label: LabelSpec,
    model: ModelSpec,
    *,
    auto_length: bool = True,
    fixed_length_mm: float | None = None,
    content_length_dots: int = 0,
    length_mode: LengthMode = LengthMode.CONTENT,
) -> int:
    """Laenge des Etiketts **in Bandrichtung** (Dots) - unabhaengig von der Ausrichtung.

    * Bei Die-cut/Rund ist die Laenge durch das Band vorgegeben
      (``dots_printable[1]``); ``auto_length``/``fixed_length_mm`` werden ignoriert.
    * Bei Endlosband bestimmt ``auto_length`` (Inhalt) bzw. ``fixed_length_mm``
      die Laenge; das Ergebnis wird auf die Modellgrenzen geklemmt.

    ``length_mode`` steuert die Bedeutung von ``fixed_length_mm``:

    * ``CONTENT``  - ``fixed_length_mm`` = bedruckter Inhalt (Canvas = 1:1).
      ``50 mm endlos`` + ``40 mm`` ergibt exakt ``554 x 472`` px (DoD #2).
    * ``FINISHED`` - ``fixed_length_mm`` = fertiges Etikett inkl. Druckerrand;
      der Inhalt wird um :func:`printer_extra_dots` reduziert.
    """
    if label.kind.is_fixed_size:
        return label.height_dots

    if auto_length:
        length = max(int(content_length_dots), 0)
        # Kleinstes sinnvolles Etikett = Modell-Minimum.
        return model.clamp_length_dots(length) if length else model.min_max_length_dots[0]

    if fixed_length_mm is None:
        raise ValueError("fixed_length_mm ist erforderlich, wenn auto_length=False")
    if length_mode is LengthMode.FINISHED:
        return content_dots_for_finished_length(label, model, fixed_length_mm)
    return model.clamp_length_dots(mm_to_dots(float(fixed_length_mm)))


def canvas_size_for_orientation(
    label: LabelSpec, length_dots: int, orientation: Orientation = Orientation.ACROSS
) -> tuple[int, int]:
    """Rechne eine Etikettenlaenge in die Canvas-Groesse ``(breite, hoehe)`` um.

    Die Laenge selbst ist immer in Bandrichtung definiert; hier wird nur
    entschieden, auf welche Canvas-Achse sie faellt.
    """
    if orientation is Orientation.ALONG:
        return int(length_dots), int(label.width_dots)
    return int(label.width_dots), int(length_dots)


def canvas_size_dots(
    label: LabelSpec,
    model: ModelSpec,
    *,
    auto_length: bool = True,
    fixed_length_mm: float | None = None,
    content_length_dots: int = 0,
    length_mode: LengthMode = LengthMode.CONTENT,
    orientation: Orientation = Orientation.ACROSS,
) -> tuple[int, int]:
    """Berechne die Canvas-Groesse ``(breite_dots, hoehe_dots)``.

    Die Designflaeche enthaelt **immer** die bedruckbare Bandbreite
    (``label.width_dots``) als eine ihrer Achsen - die einzige Breite, die
    :func:`brother_ql.conversion.convert` ohne Resize akzeptiert. ``orientation``
    bestimmt, ob die Laenge auf die Hoehe (``ACROSS``) oder die Breite
    (``ALONG``) faellt; Details siehe :class:`Orientation`.
    """
    length = label_length_dots(
        label,
        model,
        auto_length=auto_length,
        fixed_length_mm=fixed_length_mm,
        content_length_dots=content_length_dots,
        length_mode=length_mode,
    )
    return canvas_size_for_orientation(label, length, orientation)


def length_bounds_mm(model: ModelSpec) -> tuple[float, float]:
    """Erlaubter Laengenbereich fuer Endlosbaender in mm (fuer die GUI)."""
    return model.min_length_mm, model.max_length_mm


__all__ = [
    "DPI",
    "MM_PER_INCH",
    "DOTS_PER_MM",
    "DEFAULT_MODEL",
    "DEFAULT_LABEL",
    "CUT_OFFSET_DOTS",
    "Kind",
    "Color",
    "LengthMode",
    "Orientation",
    "Margins",
    "LabelSpec",
    "ModelSpec",
    "mm_to_dots",
    "dots_to_mm",
    "dots_to_px",
    "all_labels",
    "all_models",
    "get_label",
    "get_model",
    "labels_for_model",
    "has_two_color_support",
    "printer_extra_dots",
    "content_dots_for_finished_length",
    "finished_length_mm",
    "label_length_dots",
    "canvas_size_for_orientation",
    "canvas_size_dots",
    "length_bounds_mm",
]
