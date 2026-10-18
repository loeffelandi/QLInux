"""Merge-Engine: Bindings auf Anzeigewerte aufloesen (headless).

Liest optional Datenbank-Records und Serienwerte und schreibt Snapshots auf
Text/Barcode/QR. Keine Qt-Abhaengigkeit - fuer Canvas und spaeteren Druck
gemeinsam nutzbar.

* D4: Binding ``database`` / ``serial`` / keines (exklusiv am Objekt)
* D5: Pro gewaehltem Record die Serie einmal, dann ``+step``.
  ``copies`` wiederholt jedes Bild identisch und zaehlt nicht mit.
* D10: Vorschau = aktueller Record + Serienwert Index 0
* D11: Anzeigewert = Snapshot; Record-Wechsel ueberschreibt ihn.
  Fehlt die CSV (``record is None``), bleiben Database-Snapshots erhalten;
  nur Serial-Bindings werden weiter angewendet.
* D15: ``current_record`` 0-basiert steuert den Merge
"""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Mapping, Sequence

from .document import DEFAULT_SERIAL, merge_serial
from .i18n import tr
from .printer import COPIES_MAX

#: Binding-Quellen, die ein Anzeigewert-Merge betreffen.
_MERGE_KINDS = frozenset({"text", "qr", "barcode"})

#: Druckbereich wie im Brother-Drucksheet (D16).
PRINT_SELECTED = "selected"
PRINT_ALL = "all"
PRINT_RANGE = "range"
PRINT_SCOPES = frozenset({PRINT_SELECTED, PRINT_ALL, PRINT_RANGE})


class MergeError(Exception):
    """Binding oder Serienparameter nicht aufloesbar."""


def normalize_binding(
    binding: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Binding lesen ohne Qt (D4); gleiche Regeln wie ``items.normalize_binding``."""
    if binding is None:
        return None
    source = binding.get("source")
    if source in (None, "", "none"):
        return None
    if source == "database":
        field = binding.get("field")
        if not isinstance(field, str) or not field:
            raise MergeError(tr("Datenbank-Binding braucht einen Spaltennamen."))
        return {"source": "database", "field": field}
    if source == "serial":
        return {"source": "serial"}
    raise MergeError(
        tr("Unbekannte Binding-Quelle: {source!r}.").format(source=source)
    )


# Rueckwaerts-Alias (interne Aufrufer / aeltere Tests).
_normalized_binding = normalize_binding


def format_serial(
    serial: Mapping[str, Any] | None = None,
    *,
    index: int = 0,
) -> str:
    """Serienwert fuer Varianten-Index ``index`` formatieren (D10: Vorschau = 0).

    ``start + index * step``, optional Zero-Pad, Prefix/Suffix. Negative
    ``index`` sind unzulaessig.
    """
    if index < 0:
        raise MergeError(tr("Serien-Index darf nicht negativ sein."))
    spec = merge_serial(serial)
    start = int(spec.get("start", DEFAULT_SERIAL["start"]))
    step = int(spec.get("step", DEFAULT_SERIAL["step"]))
    prefix = str(spec.get("prefix", "") or "")
    suffix = str(spec.get("suffix", "") or "")
    pad_width = int(spec.get("pad_width", 0) or 0)
    number = start + index * step
    body = str(number)
    if number >= 0 and pad_width > 0:
        body = body.zfill(pad_width)
    return f"{prefix}{body}{suffix}"


def resolve_binding(
    binding: Mapping[str, Any] | None,
    *,
    record: Mapping[str, str] | None = None,
    serial_value: str = "",
) -> str | None:
    """Binding → Anzeigewert, oder ``None`` wenn kein Merge noetig.

    ``None``: kein Binding, oder Database ohne Record (Snapshot behalten, D11/D12).
    Fehlende Spalten im Record liefern ``""`` (leere Merge-Felder bleiben sichtbar).
    """
    normalized = normalize_binding(binding)
    if normalized is None:
        return None
    source = normalized["source"]
    if source == "database":
        if record is None:
            # CSV fehlt / noch nicht geladen: Snapshot nicht mit "" ueberschreiben.
            return None
        field = normalized["field"]
        value = record.get(field)
        return "" if value is None else str(value)
    if source == "serial":
        return serial_value
    return None


def resolve_item_display(
    item: Any,
    *,
    record: Mapping[str, str] | None = None,
    serial: Mapping[str, Any] | None = None,
    serial_index: int = 0,
) -> str | None:
    """Anzeigewert fuer ein Canvas-Objekt, oder ``None`` ohne Binding."""
    binding = getattr(item, "binding", None)
    if callable(binding):
        binding = binding()
    return resolve_binding(
        binding,
        record=record,
        serial_value=format_serial(serial, index=serial_index),
    )


def apply_display_value(item: Any, value: str) -> bool:
    """Snapshot auf Text/Barcode/QR setzen (D11).

    Liefert ``True``, wenn der Snapshot geschrieben wurde. Ungueltige Barcodes
    behalten den bisherigen Snapshot (kein Abbruch der Live-Vorschau) und
    zaehlen nicht als Update.
    """
    kind = getattr(item, "kind", None)
    if kind == "text" and hasattr(item, "set_text_value"):
        item.set_text_value(value)
        return True
    if kind == "qr" and hasattr(item, "set_data"):
        item.set_data(value)
        return True
    if kind == "barcode" and hasattr(item, "set_value"):
        try:
            item.set_value(value)
        except ValueError:
            return False
        return True
    raise MergeError(
        tr("Objekt {kind!r} unterstuetzt keinen Merge.").format(kind=kind)
    )


def apply_record(
    items: Sequence[Any],
    *,
    record: Mapping[str, str] | None = None,
    serial: Mapping[str, Any] | None = None,
    serial_index: int = 0,
    strict: bool = False,
) -> int:
    """Alle gebundenen Objekte mit Record/Serie aktualisieren.

    Liefert die Anzahl der geschriebenen Snapshots. Objekte ohne Binding
    und Database-Bindings ohne Record bleiben unveraendert.

    ``strict=True`` (Druck): ein Barcode, den die Symbologie ablehnt, bricht
    ab. Die Live-Vorschau bleibt bei ``strict=False`` und behaelt den
    letzten gueltigen Snapshot.
    """
    serial_value = format_serial(serial, index=serial_index)
    updated = 0
    for item in items:
        kind = getattr(item, "kind", None)
        if kind not in _MERGE_KINDS:
            continue
        binding = getattr(item, "binding", None)
        if callable(binding):
            binding = binding()
        value = resolve_binding(
            binding, record=record, serial_value=serial_value
        )
        if value is None:
            continue
        if apply_display_value(item, value):
            updated += 1
        elif strict:
            raise MergeError(
                tr("Barcode '{value}' lässt sich nicht drucken.").format(
                    value=value
                )
            )
    return updated


@dataclass(frozen=True)
class PrintVariant:
    """Ein Etikett im Auftrag: ein Record oder der virtuelle Einzeldruck.

    ``record is None`` heisst: keine CSV (oder leer) - der Canvas bleibt,
    wie er ist. ``index`` ist 0-basiert, analog ``current_record``.
    """

    record: Mapping[str, str] | None
    index: int | None


def plan_print_variants(
    records: Sequence[Mapping[str, str]] | None,
    *,
    scope: str = PRINT_SELECTED,
    selected: int | Sequence[int] | None = None,
    range_from: int = 1,
    range_to: int = 1,
) -> list[PrintVariant]:
    """Druckliste Selected / All / Record Range (D16).

    Ohne Records ein virtueller Eintrag (ein Bild, der aktuelle Canvas).
    Selected ist die Tabellenauswahl; eine einzelne Zahl wird geklemmt,
    eine Liste behaelt die Reihenfolge und laesst ungueltige Indizes weg
    (Mehrfachauswahl ist vorbereitet, die Oberflaeche waehlt eine Zeile).
    Record Range ist 1-basiert und einschliesslich; vertauschte Grenzen
    werden getauscht.

    Serien-Count vervielfacht die Liste hier nicht; das macht
    :func:`plan_serial_labels` (D5).
    """
    if not records:
        return [PrintVariant(None, None)]
    if scope not in PRINT_SCOPES:
        raise MergeError(
            tr("Unbekannter Druckbereich: {scope!r}.").format(scope=scope)
        )
    count = len(records)
    if scope == PRINT_ALL:
        indexes = list(range(count))
    elif scope == PRINT_RANGE:
        indexes = _range_indexes(count, range_from, range_to)
    else:
        indexes = _selected_indexes(count, selected)
    return [PrintVariant(records[index], index) for index in indexes]


@dataclass(frozen=True)
class PlannedLabel:
    """Ein zu renderndes Etikett: Record-Variante plus Serien-Index (D5)."""

    variant: PrintVariant
    serial_index: int


def serial_length(serial: Mapping[str, Any] | None = None) -> int:
    """Wie viele Serienwerte pro Record gedruckt werden (D5).

    Ausgeschaltet (``enabled`` fehlt oder falsch) bleibt es bei einem
    Durchgang, Index 0 — auch wenn ``count`` groesser ist. ``copies``
    gehoert nicht hierher.
    """
    spec = merge_serial(serial)
    if not spec.get("enabled"):
        return 1
    count = spec.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise MergeError(tr("Serien-Anzahl muss mindestens 1 sein."))
    return count


def plan_serial_labels(
    variants: Sequence[PrintVariant],
    serial: Mapping[str, Any] | None = None,
) -> list[PlannedLabel]:
    """Serie innen, Records aussen (D5).

    Fuer jeden Eintrag aus :func:`plan_print_variants` die Indizes
    ``0 .. count-1``. Ohne Datenbank ist das der eine virtuelle Record.
    Kopien wiederholt der Drucker danach identisch.
    """
    span = serial_length(serial)
    return [
        PlannedLabel(variant, index)
        for variant in variants
        for index in range(span)
    ]


def job_page_count(
    variant_count: int, copies: int, *, limit: int = COPIES_MAX
) -> int:
    """Seiten = Varianten × Kopien; ueber :data:`COPIES_MAX` abbrechen (D7)."""
    if (
        isinstance(variant_count, bool)
        or not isinstance(variant_count, int)
        or variant_count < 1
    ):
        raise MergeError(tr("Keine Etiketten zum Drucken."))
    if isinstance(copies, bool) or not isinstance(copies, int) or copies < 1:
        raise MergeError(tr("Kopienzahl muss mindestens 1 sein."))
    pages = variant_count * copies
    if pages > limit:
        raise MergeError(
            tr(
                "Höchstens {max} Seiten pro Auftrag (Datensätze × Serie × Kopien)."
            ).format(max=limit)
        )
    return pages


def _selected_indexes(
    count: int, selected: int | Sequence[int] | None
) -> list[int]:
    if selected is None:
        return [clamp_record_index(0, count)]
    if isinstance(selected, bool):
        raise MergeError(tr("Keine Datensätze im Druckbereich."))
    if isinstance(selected, int):
        return [clamp_record_index(selected, count)]
    indexes: list[int] = []
    seen: set[int] = set()
    for raw in selected:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise MergeError(tr("Keine Datensätze im Druckbereich."))
        if raw < 0 or raw >= count or raw in seen:
            continue
        seen.add(raw)
        indexes.append(raw)
    if not indexes:
        raise MergeError(tr("Keine Datensätze im Druckbereich."))
    return indexes


def _range_indexes(count: int, start: int, end: int) -> list[int]:
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise MergeError(tr("Datensatzbereich braucht ganze Zahlen."))
    if start > end:
        start, end = end, start
    start = max(1, start)
    end = min(count, end)
    if start > end:
        raise MergeError(tr("Keine Datensätze im Druckbereich."))
    return list(range(start - 1, end))


def clamp_record_index(index: int, record_count: int) -> int:
    """``current_record`` auf gueltigen Bereich klemmen (0-basiert, D15)."""
    if record_count <= 0:
        return 0
    if index < 0:
        return 0
    if index >= record_count:
        return record_count - 1
    return int(index)


def resolve_csv_path(
    stored_path: str | PathLike[str],
    *,
    document_path: str | PathLike[str] | None = None,
) -> Path:
    """CSV-Pfad aus ``data_source`` aufloesen (relativ zur ``.qlx``, D3).

    Relative Pfade werden zuerst neben der ``.qlx`` gesucht; erst danach gilt
    ein Treffer im aktuellen Arbeitsverzeichnis (vermeidet CWD-Shadowing).
    """
    candidate = Path(stored_path).expanduser()
    if candidate.is_absolute():
        return candidate
    if document_path is not None:
        root = Path(document_path).expanduser()
        if root.is_file() or root.suffix:
            root = root.parent
        joined = (root / candidate).expanduser()
        if joined.is_file():
            return joined
        try:
            resolved = joined.resolve()
            if resolved.is_file():
                return resolved
        except OSError:
            pass
    if candidate.is_file():
        return candidate
    return candidate


__all__ = [
    "MergeError",
    "PRINT_ALL",
    "PRINT_RANGE",
    "PRINT_SCOPES",
    "PRINT_SELECTED",
    "PrintVariant",
    "apply_display_value",
    "apply_record",
    "clamp_record_index",
    "format_serial",
    "job_page_count",
    "normalize_binding",
    "PlannedLabel",
    "plan_print_variants",
    "plan_serial_labels",
    "resolve_binding",
    "serial_length",
    "resolve_csv_path",
    "resolve_item_display",
]
