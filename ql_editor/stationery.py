"""Avery-Zweckform-Bögen nach den gLabels-Vorlagen.

Die Maße stehen in ``data/zweckform-iso-templates.xml`` (gLabels, GPL-3.0-or-later).
Ein Bogen ist eine Seite mit festem Raster. Der Datenbankdruck liefert die
Etiketten, dieses Modul nur die Felder: Leserichtung, erstes Feld auf einem
angefangenen Bogen, Kopien wiederholen dasselbe Etikett.

Kein Qt. Die Seite malt :mod:`ql_editor.sheet_output`.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from .i18n import tr
from .media import (
    Color,
    Kind,
    LabelSpec,
    mm_to_dots,
)

#: Ziel im Druck-Sheet.
OUTPUT_BROTHER = "brother"
OUTPUT_SHEET = "sheet"

#: Übliche Adressetiketten, wenn noch nichts gewählt ist.
DEFAULT_PART = "3475"

#: Obergrenze eines Bogenauftrags (Etiketten × Kopien). Ein PDF ist kein
#: zusammenhängender Brother-Datenstrom, darum liegt die Grenze über
#: :data:`ql_editor.printer.COPIES_MAX`.
SHEET_LABELS_MAX = 2000

#: Versatz, den die Oberfläche anbietet (Millimeter).
OFFSET_MM_MAX = 20.0

_TEMPLATE_NAME = "zweckform-iso-templates.xml"

#: Ohne Einheit sind gLabels-Maße Punkt (1/72 Zoll).
_UNIT_TO_MM = {
    "pt": 25.4 / 72.0,
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "pc": 25.4 / 6.0,
}

_PAPER_MM = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "US-Letter": (215.9, 279.4),
}

_LENGTH = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z]*)$")


class SheetError(Exception):
    """Vorlage oder Belegung nicht brauchbar."""


def template_file() -> Path:
    """Pfad der mitgelieferten Zweckform-Datei (Quelle und AppImage)."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        path = Path(bundled) / "ql_editor" / "data" / _TEMPLATE_NAME
        if path.is_file():
            return path
    return Path(__file__).resolve().parent / "data" / _TEMPLATE_NAME


def parse_length(value: str) -> float:
    """gLabels-Maß nach Millimeter. Ohne Einheit: Punkt."""
    match = _LENGTH.match(value.strip())
    if match is None:
        raise SheetError(tr("Unlesbares Maß: {value}.").format(value=value))
    number = float(match.group(1))
    unit = (match.group(2) or "pt").lower()
    factor = _UNIT_TO_MM.get(unit)
    if factor is None:
        raise SheetError(tr("Unbekannte Einheit: {unit}.").format(unit=unit))
    return number * factor


@dataclass(frozen=True)
class SheetTemplate:
    """Ein Bogen: Seitengröße und das Raster eines Etiketts."""

    brand: str
    part: str
    description: str
    page_width_mm: float
    page_height_mm: float
    label_width_mm: float
    label_height_mm: float
    corner_radius_mm: float
    hole_radius_mm: float
    nx: int
    ny: int
    x0_mm: float
    y0_mm: float
    dx_mm: float
    dy_mm: float

    @property
    def per_sheet(self) -> int:
        return self.nx * self.ny

    def slot_origin(self, index: int) -> tuple[float, float]:
        """Linke obere Ecke des Feldes ``index`` (0-basiert, zeilenweise)."""
        column = index % self.nx
        row = index // self.nx
        return (
            self.x0_mm + column * self.dx_mm,
            self.y0_mm + row * self.dy_mm,
        )


@dataclass(frozen=True)
class Placement:
    """Ein Etikett auf einem Bogen."""

    page: int
    slot: int
    image_index: int
    x_mm: float
    y_mm: float


def description_text(english: str) -> str:
    """Kurztext der gLabels-Vorlage, auf Deutsch (Schlüssel für die Übersetzung)."""
    return {
        "Address labels": tr("Adressetiketten"),
        "Mailing labels": tr("Adressetiketten"),
        "Multipurpose labels": tr("Universaletiketten"),
        "Rectangular labels": tr("Rechteckige Etiketten"),
        "Lever arch file labels": tr("Ordnerrücken"),
        "CD/DVD labels": tr("CD/DVD-Etiketten"),
        "Video tape spine labels": tr("Videokassetten-Rücken"),
        "Correction labels": tr("Korrekturetiketten"),
        "CD/DVD booklet": tr("CD/DVD-Booklet"),
        "CD/DVD insert": tr("CD/DVD-Einleger"),
        "Business cards": tr("Visitenkarten"),
    }.get(english, english)


def templates() -> tuple[SheetTemplate, ...]:
    """Alle Zweckform-Bögen, nach Teilenummer sortiert."""
    return _catalog()


def get_template(part: str) -> SheetTemplate:
    found = _by_part().get(part)
    if found is None:
        raise SheetError(tr("Unbekannte Vorlage: {part}.").format(part=part))
    return found


def as_label_spec(template: SheetTemplate) -> LabelSpec:
    """Designfläche in der Größe eines Etiketts dieser Vorlage.

    Feste Kanten, kein Brother-Rand: was auf der Fläche steht, füllt das
    Feld auf dem Bogen.
    """
    width = mm_to_dots(template.label_width_mm)
    height = mm_to_dots(template.label_height_mm)
    return LabelSpec(
        identifier=f"zweckform-{template.part}",
        name=template.part,
        tape_size=(
            max(1, round(template.label_width_mm)),
            max(1, round(template.label_height_mm)),
        ),
        form_factor=Kind.DIE_CUT,
        color=Color.BLACK_WHITE,
        dots_printable=(width, height),
        dots_total=(width, height),
        right_margin_dots=0,
        feed_margin=0,
        restricted_to_models=(),
    )


def plan_sheet(
    template: SheetTemplate,
    count: int,
    *,
    start: int = 1,
    copies: int = 1,
) -> list[Placement]:
    """Belege die Felder: Datensätze der Reihe nach, Kopien direkt dahinter.

    ``start`` ist 1-basiert und gilt nur für den ersten Bogen. Der nächste
    Bogen beginnt wieder beim ersten Feld. ``count`` ist die Zahl der
    verschiedenen Etiketten, nicht mal Kopien.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SheetError(tr("Keine Etiketten für den Bogen."))
    if isinstance(copies, bool) or not isinstance(copies, int) or copies < 1:
        raise SheetError(tr("Kopienzahl muss mindestens 1 sein."))
    per_sheet = template.per_sheet
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or start < 1
        or start > per_sheet
    ):
        raise SheetError(
            tr("Erstes Etikett muss zwischen 1 und {count} liegen.").format(
                count=per_sheet
            )
        )
    total = count * copies
    if total > SHEET_LABELS_MAX:
        raise SheetError(
            tr("Höchstens {max} Etiketten pro Bogenauftrag.").format(
                max=SHEET_LABELS_MAX
            )
        )
    placements: list[Placement] = []
    page = 0
    slot = start - 1
    for image_index in range(count):
        for _copy in range(copies):
            if slot >= per_sheet:
                page += 1
                slot = 0
            x_mm, y_mm = template.slot_origin(slot)
            placements.append(Placement(page, slot, image_index, x_mm, y_mm))
            slot += 1
    return placements


def page_count(placements: list[Placement]) -> int:
    if not placements:
        return 0
    return placements[-1].page + 1


def filled_per_page(placements: list[Placement]) -> list[int]:
    """Wie viele Felder jeder Bogen in diesem Auftrag belegt, der Reihe nach."""
    if not placements:
        return []
    counts = [0] * (placements[-1].page + 1)
    for place in placements:
        counts[place.page] += 1
    return counts


def fill_caption(counts: list[int], capacity: int) -> str:
    """„x von y“ je Bogen. Gleiche Bögen hintereinander werden zusammengefasst."""
    if not counts or capacity < 1:
        return tr("Keine Etiketten für den Bogen.")
    if len(counts) == 1:
        return tr("{filled} von {capacity} Etiketten belegt").format(
            filled=counts[0], capacity=capacity
        )
    parts: list[str] = []
    start = 0
    for index, count in enumerate(counts + [-1]):
        if index < len(counts) and count == counts[start]:
            continue
        first = start + 1
        last = index
        filled = counts[start]
        if first == last:
            parts.append(
                tr("Bogen {page}: {filled} von {capacity}").format(
                    page=first, filled=filled, capacity=capacity
                )
            )
        else:
            parts.append(
                tr("Bogen {start}–{end}: {filled} von {capacity}").format(
                    start=first, end=last, filled=filled, capacity=capacity
                )
            )
        start = index
    return "\n".join(parts)


def _part_key(part: str) -> tuple[int, str]:
    numbers = re.findall(r"\d+", part)
    return (int(numbers[0]) if numbers else 10**9, part)


@lru_cache(maxsize=1)
def _catalog() -> tuple[SheetTemplate, ...]:
    path = template_file()
    if not path.is_file():
        raise SheetError(tr("Vorlagendatei fehlt."))
    root = ET.parse(path).getroot()
    resolved: dict[tuple[str, str], SheetTemplate] = {}
    found: list[SheetTemplate] = []
    for element in root.findall("Template"):
        brand = element.get("brand") or ""
        part = element.get("part") or ""
        equiv = element.get("equiv")
        if equiv:
            source = resolved.get((brand, equiv))
            if source is None:
                raise SheetError(
                    tr("Vorlage {part} verweist auf unbekannte {equiv}.").format(
                        part=part, equiv=equiv
                    )
                )
            clone = replace(source, part=part)
            resolved[(brand, part)] = clone
            found.append(clone)
            continue
        template = _parse_template(element)
        resolved[(brand, part)] = template
        found.append(template)
    return tuple(sorted(found, key=lambda item: _part_key(item.part)))


@lru_cache(maxsize=1)
def _by_part() -> dict[str, SheetTemplate]:
    return {template.part: template for template in _catalog()}


def _parse_template(element: ET.Element) -> SheetTemplate:
    part = element.get("part") or ""
    size = element.get("size") or ""
    paper = _PAPER_MM.get(size)
    if paper is None:
        raise SheetError(
            tr("Unbekanntes Papierformat: {size}.").format(size=size or part)
        )
    label = next(
        (child for child in element if child.tag.startswith("Label-")),
        None,
    )
    layout = None if label is None else label.find("Layout")
    if label is None or layout is None:
        raise SheetError(tr("Vorlage {part} hat kein Raster.").format(part=part))
    if label.tag == "Label-cd":
        radius = parse_length(label.get("radius") or "0")
        width = height = radius * 2.0
        corner = 0.0
        hole = parse_length(label.get("hole") or "0")
    else:
        width = parse_length(label.get("width") or "0")
        height = parse_length(label.get("height") or "0")
        corner = parse_length(label.get("round") or "0")
        hole = 0.0
    nx = int(layout.get("nx") or "0")
    ny = int(layout.get("ny") or "0")
    if nx < 1 or ny < 1 or width <= 0 or height <= 0:
        raise SheetError(tr("Vorlage {part} hat kein Raster.").format(part=part))
    return SheetTemplate(
        brand=element.get("brand") or "",
        part=part,
        description=element.get("_description") or element.get("description") or "",
        page_width_mm=paper[0],
        page_height_mm=paper[1],
        label_width_mm=width,
        label_height_mm=height,
        corner_radius_mm=corner,
        hole_radius_mm=hole,
        nx=nx,
        ny=ny,
        x0_mm=parse_length(layout.get("x0") or "0"),
        y0_mm=parse_length(layout.get("y0") or "0"),
        dx_mm=parse_length(layout.get("dx") or "0"),
        dy_mm=parse_length(layout.get("dy") or "0"),
    )


__all__ = [
    "DEFAULT_PART",
    "OFFSET_MM_MAX",
    "OUTPUT_BROTHER",
    "OUTPUT_SHEET",
    "SHEET_LABELS_MAX",
    "Placement",
    "SheetError",
    "SheetTemplate",
    "as_label_spec",
    "description_text",
    "fill_caption",
    "filled_per_page",
    "get_template",
    "page_count",
    "parse_length",
    "plan_sheet",
    "template_file",
    "templates",
]
