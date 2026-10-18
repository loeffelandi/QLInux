"""CSV-Datenquelle fuer Datenbank-Merge (headless).

Laedt Tabellen fuer den spaeteren Merge: Spalten = Felder, Zeilen = Records.
Encoding und Trennzeichen folgen den Defaults D1/D2:

* Encoding ``utf-8-sig`` (BOM) oder ``utf-8``
* Delimiter-Sniff zwischen ``;`` und ``,``
* Inhalt als SHA-256 (CSV wird nicht in ``.qlx`` eingebettet)
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .i18n import tr

#: Erlaubte Trennzeichen (D2).
_DELIMITERS = (",", ";")


class CsvSourceError(Exception):
    """CSV fehlt, ist leer oder nicht lesbar."""


@dataclass(frozen=True)
class CsvTable:
    """Geladene CSV: Felder, Records und erkannte Meta-Angaben."""

    fields: tuple[str, ...]
    records: tuple[Mapping[str, str], ...]
    encoding: str
    delimiter: str
    content_sha256: str
    path: Path | None = None

    @property
    def field_names(self) -> list[str]:
        return list(self.fields)

    def record(self, index: int) -> dict[str, str]:
        """Einen Record (0-basiert) als flaches ``dict`` liefern."""
        if index < 0 or index >= len(self.records):
            raise IndexError(index)
        return dict(self.records[index])


def content_sha256(data: bytes) -> str:
    """SHA-256 des Rohinhalts (hex), fuer Drift-Warnung (D1)."""
    return hashlib.sha256(data).hexdigest()


def detect_encoding(raw: bytes) -> str:
    """BOM → ``utf-8-sig``, sonst ``utf-8`` (D2)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def sniff_delimiter(sample: str) -> str:
    """Trennzeichen aus einer Textprobe: ``;`` oder ``,`` (D2).

    Zaehlt Vorkommen in der ersten nicht-leeren Zeile. Bei Gleichstand
    gewinnt ``,`` (RFC-ueblich). Andere Zeichen werden nicht erkannt.
    """
    for line in sample.splitlines():
        if line.strip():
            sample_line = line
            break
    else:
        return ","
    counts = {d: sample_line.count(d) for d in _DELIMITERS}
    if counts[";"] > counts[","]:
        return ";"
    return ","


def decode_csv_bytes(raw: bytes) -> tuple[str, str]:
    """Rohbytes → ``(text, encoding)``; Encodingfehler → :class:`CsvSourceError`."""
    encoding = detect_encoding(raw)
    try:
        return raw.decode(encoding), encoding
    except UnicodeDecodeError as exc:
        raise CsvSourceError(
            tr("CSV ist nicht UTF-8: {error}").format(error=exc)
        ) from exc


def parse_csv_text(
    text: str,
    *,
    delimiter: str | None = None,
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...], str]:
    """CSV-Text parsen → Felder, Records, verwendeter Delimiter.

    Die erste Zeile ist der Header (``containsFieldName`` analog P-touch).
    Leere Dateien und fehlende Headerzeilen sind Fehler.
    """
    if not text.strip():
        raise CsvSourceError(tr("CSV ist leer."))
    delim = delimiter if delimiter in _DELIMITERS else sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise CsvSourceError(tr("CSV ist leer.")) from exc
    fields = tuple(cell.strip() for cell in header)
    if not fields or all(not name for name in fields):
        raise CsvSourceError(tr("CSV hat keine Spaltennamen."))
    if len(set(fields)) != len(fields):
        raise CsvSourceError(tr("CSV hat doppelte Spaltennamen."))

    records: list[dict[str, str]] = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        # Zu kurze Zeilen auffuellen; ueberzaehlige Zellen verwerfen.
        values = list(row) + [""] * max(0, len(fields) - len(row))
        records.append(
            {name: values[i] for i, name in enumerate(fields)}
        )
    return fields, tuple(records), delim


def load(path: str | Path, *, delimiter: str | None = None) -> CsvTable:
    """CSV von der Platte laden (Encoding/Delimiter wie D2)."""
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise CsvSourceError(
            tr("Konnte {path} nicht lesen: {error}").format(
                path=file_path, error=exc
            )
        ) from exc
    text, encoding = decode_csv_bytes(raw)
    fields, records, delim = parse_csv_text(text, delimiter=delimiter)
    return CsvTable(
        fields=fields,
        records=records,
        encoding=encoding,
        delimiter=delim,
        content_sha256=content_sha256(raw),
        path=file_path,
    )


def relativize_path(csv_path: str | Path, base: str | Path) -> str:
    """Pfad relativ zu ``base`` (Ordner der ``.qlx``), sonst absolut (D3).

    ``base`` darf die ``.qlx``-Datei (auch noch nicht geschrieben) oder deren
    Ordner sein.
    """
    target = Path(csv_path).expanduser()
    root = Path(base).expanduser()
    if root.is_file() or root.suffix:
        root = root.parent
    try:
        resolved_target = target.resolve()
        resolved_root = root.resolve()
        return str(resolved_target.relative_to(resolved_root))
    except (OSError, ValueError):
        try:
            return str(target if target.is_absolute() else target.resolve())
        except OSError:
            return str(target)


def data_source_dict(
    table: CsvTable,
    *,
    path: str | Path | None = None,
    current_record: int = 0,
    relative_to: str | Path | None = None,
) -> dict[str, Any]:
    """``data_source``-Block fuer Format-2-Dokumente bauen."""
    raw_path = Path(path) if path is not None else table.path
    if raw_path is None:
        raise CsvSourceError(tr("CSV-Pfad fehlt."))
    stored = (
        relativize_path(raw_path, relative_to)
        if relative_to is not None
        else str(raw_path)
    )
    index = int(current_record)
    if index < 0:
        index = 0
    if table.records and index >= len(table.records):
        index = len(table.records) - 1
    return {
        "type": "csv",
        "path": stored,
        "encoding": table.encoding,
        "delimiter": table.delimiter,
        "current_record": index,
        "content_sha256": table.content_sha256,
    }


__all__ = [
    "CsvSourceError",
    "CsvTable",
    "content_sha256",
    "data_source_dict",
    "decode_csv_bytes",
    "detect_encoding",
    "load",
    "parse_csv_text",
    "relativize_path",
    "sniff_delimiter",
]
