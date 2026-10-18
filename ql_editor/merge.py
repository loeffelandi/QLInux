"""Merge-Engine: Bindings auf Anzeigewerte aufloesen (headless).

Liest optional Datenbank-Records und Serienwerte und schreibt Snapshots auf
Text/Barcode/QR. Keine Qt-Abhaengigkeit - fuer Canvas und spaeteren Druck
gemeinsam nutzbar.

* D4: Binding ``database`` / ``serial`` / keines (exklusiv am Objekt)
* D10: Vorschau = aktueller Record + Serienwert Index 0
* D11: Anzeigewert = Snapshot; Record-Wechsel ueberschreibt ihn
* D15: ``current_record`` 0-basiert steuert den Merge
"""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Any, Mapping, Sequence

from .document import DEFAULT_SERIAL, merge_serial
from .i18n import tr

#: Binding-Quellen, die ein Anzeigewert-Merge betreffen.
_MERGE_KINDS = frozenset({"text", "qr", "barcode"})


class MergeError(Exception):
    """Binding oder Serienparameter nicht aufloesbar."""


def _normalized_binding(
    binding: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Binding lesen ohne Qt (gleiche Regeln wie ``normalize_binding``, D4)."""
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
    """Binding → Anzeigewert, oder ``None`` wenn kein Binding.

    Fehlende Spalten liefern ``""`` (leere Merge-Felder bleiben sichtbar, D11).
    """
    normalized = _normalized_binding(binding)
    if normalized is None:
        return None
    source = normalized["source"]
    if source == "database":
        field = normalized["field"]
        if record is None:
            return ""
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


def apply_display_value(item: Any, value: str) -> None:
    """Snapshot auf Text/Barcode/QR setzen (D11).

    Ungueltige Barcodes behalten den bisherigen Snapshot (kein Abbruch der
    Live-Vorschau).
    """
    kind = getattr(item, "kind", None)
    if kind == "text" and hasattr(item, "set_text_value"):
        item.set_text_value(value)
        return
    if kind == "qr" and hasattr(item, "set_data"):
        item.set_data(value)
        return
    if kind == "barcode" and hasattr(item, "set_value"):
        try:
            item.set_value(value)
        except ValueError:
            return
        return
    raise MergeError(
        tr("Objekt {kind!r} unterstuetzt keinen Merge.").format(kind=kind)
    )


def apply_record(
    items: Sequence[Any],
    *,
    record: Mapping[str, str] | None = None,
    serial: Mapping[str, Any] | None = None,
    serial_index: int = 0,
) -> int:
    """Alle gebundenen Objekte mit Record/Serie aktualisieren.

    Liefert die Anzahl der geschriebenen Snapshots. Objekte ohne Binding
    bleiben unveraendert.
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
        apply_display_value(item, value)
        updated += 1
    return updated


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
    """CSV-Pfad aus ``data_source`` aufloesen (relativ zur ``.qlx``, D3)."""
    candidate = Path(stored_path).expanduser()
    if candidate.is_file():
        return candidate
    if document_path and not candidate.is_absolute():
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
    return candidate


__all__ = [
    "MergeError",
    "apply_display_value",
    "apply_record",
    "clamp_record_index",
    "format_serial",
    "resolve_binding",
    "resolve_csv_path",
    "resolve_item_display",
]
