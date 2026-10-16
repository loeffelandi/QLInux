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

#: Druckaufloesung der QL-Serie in dpi.
DPI: int = 300

#: Millimeter pro Zoll (exakte Definition).
MM_PER_INCH: float = 25.4

#: Umrechnungsfaktor mm -> Dots bei :data:`DPI`.
DOTS_PER_MM: float = DPI / MM_PER_INCH  # ~ 11.811

#: Standardmodell dieser Installation.
DEFAULT_MODEL: str = "QL-820NWB"


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
        return {
            Kind.ENDLESS: "Endlos",
            Kind.DIE_CUT: "Die-cut",
            Kind.ROUND_DIE_CUT: "Rund (Die-cut)",
        }[self]


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

    # -- Darstellung --------------------------------------------------------
    @property
    def display_name(self) -> str:
        """Dropdown-Text, z. B. ``"50 mm endlos"`` bzw. ``"62 mm endlos (schwarz/rot)"``."""
        base = f"{self.tape_size[0]} mm {self.form_factor.label_de.lower()}"
        if self.kind.is_fixed_size:
            base = f"{self.tape_size[0]} x {self.tape_size[1]} mm {self.form_factor.label_de.lower()}"
        if self.color.supports_red:
            base += " (schwarz/rot)"
        return base

    # -- Modell-Kompatibilitaet --------------------------------------------
    def usable_by(self, model_identifier: str) -> bool:
        """True, wenn das Band auf dem angegebenen Modell verwendet werden darf.

        Ein leeres ``restricted_to_models`` bedeutet: fuer alle Modelle erlaubt.
        """
        if not self.restricted_to_models:
            return True
        return model_identifier in self.restricted_to_models

    # -- Voreinstellungen ---------------------------------------------------
    def default_margins(self) -> Margins:
        """Startwerte fuer die Margin-Felder.

        Der ``feed_margin`` der Bibliothek ist der physische Vorschub vor
        dem Schnitt; er wird als Startwert fuer oben/unten verwendet.
        Links/rechts starten bei 0 mm (Design-Raender sind Nutzerentscheidung).
        """
        fm = self.feed_margin_mm
        return Margins(left=0.0, right=0.0, top=fm, bottom=fm)


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
        raise KeyError(f"Unbekanntes Band: {identifier!r}") from exc


def get_model(identifier: str) -> ModelSpec:
    """Druckermodell nach Kennung (z. B. ``"QL-820NWB"``)."""
    try:
        return _model_index()[identifier]
    except KeyError as exc:
        raise KeyError(f"Unbekanntes Modell: {identifier!r}") from exc


def labels_for_model(model_identifier: str) -> tuple[LabelSpec, ...]:
    """Alle Baender, die fuer das Modell zugelassen sind."""
    # Wirft KeyError bei unbekanntem Modell - gewollt (frueher Fehler).
    get_model(model_identifier)
    return tuple(lbl for lbl in all_labels() if lbl.usable_by(model_identifier))


def has_two_color_support(model_identifier: str) -> bool:
    return get_model(model_identifier).two_color


# --------------------------------------------------------------------------- #
# Canvas-Groesse
# --------------------------------------------------------------------------- #
def canvas_size_dots(
    label: LabelSpec,
    model: ModelSpec,
    *,
    auto_length: bool = True,
    fixed_length_mm: float | None = None,
    content_length_dots: int = 0,
) -> tuple[int, int]:
    """Berechne die Canvas-Groesse ``(breite_dots, hoehe_dots)``.

    * Breite ist **immer** ``label.dots_printable[0]`` - die einzige Breite,
      die :func:`brother_ql.conversion.convert` ohne Resize akzeptiert.
    * Bei Die-cut/Rund ist die Hoehe durch das Band vorgegeben
      (``dots_printable[1]``); ``auto_length``/``fixed_length_mm`` werden ignoriert.
    * Bei Endlosband bestimmt ``auto_length`` (Inhalt) bzw. ``fixed_length_mm``
      die Hoehe; das Ergebnis wird auf die Modellgrenzen geklemmt.
    """
    width = label.width_dots

    if label.kind.is_fixed_size:
        return width, label.height_dots

    if auto_length:
        height = max(int(content_length_dots), 0)
        # Kleinstes sinnvolles Etikett = Modell-Minimum.
        height = model.clamp_length_dots(height) if height else model.min_max_length_dots[0]
    else:
        if fixed_length_mm is None:
            raise ValueError("fixed_length_mm ist erforderlich, wenn auto_length=False")
        height = model.clamp_length_dots(mm_to_dots(float(fixed_length_mm)))

    return width, height


def length_bounds_mm(model: ModelSpec) -> tuple[float, float]:
    """Erlaubter Laengenbereich fuer Endlosbaender in mm (fuer die GUI)."""
    return model.min_length_mm, model.max_length_mm


__all__ = [
    "DPI",
    "MM_PER_INCH",
    "DOTS_PER_MM",
    "DEFAULT_MODEL",
    "Kind",
    "Color",
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
    "canvas_size_dots",
    "length_bounds_mm",
]
