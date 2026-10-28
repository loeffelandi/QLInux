#!/usr/bin/env python3
"""Idempotent Pillow-10-Kompatibilitaets-Patch fuer brother_ql.

Die von ``brother_ql`` 0.9.4 ausgelieferte ``conversion.py`` verwendet in
Zeile 112 ``Image.ANTIALIAS``. Dieses Alias wurde in Pillow 10 entfernt.

Dieses Skript ersetzt ausschliesslich dieses Vorkommen durch
``Image.LANCZOS`` - exakt der Patch, der bereits in der Referenz-venv
(``~/Apps/brother_ql_web/.venv``) manuell angewandt wurde.

Das Skript ist idempotent: ist der Patch bereits vorhanden, passiert nichts.
Es wird niemals etwas anderes an der Datei geaendert.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def find_conversion_file() -> Path:
    """Locate ``brother_ql/conversion.py`` in the interpreter's environment."""
    try:
        import brother_ql  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            "brother_ql ist nicht importierbar. Bitte zuerst die venv "
            "aktivieren / Abhaengigkeiten installieren."
        ) from exc
    import brother_ql.conversion as mod

    return Path(mod.__file__)


def apply_patch(conversion_file: Path, *, verbose: bool = True) -> bool:
    """Apply the ANTIALIAS -> LANCZOS patch. Returns True if a change was made."""
    text = conversion_file.read_text(encoding="utf-8")
    if "Image.ANTIALIAS" not in text:
        if verbose:
            print(f"[patch] nichts zu tun: kein Image.ANTIALIAS in {conversion_file}")
        return False

    # Only ever touch the exact attribute reference, never anything else.
    new_text = re.sub(r"\bImage\.ANTIALIAS\b", "Image.LANCZOS", text)
    if new_text == text:
        raise SystemExit("[patch] interner Fehler: Ersetzung ohne Effekt.")
    conversion_file.write_text(new_text, encoding="utf-8")
    if verbose:
        print(
            f"[patch] Image.ANTIALIAS -> Image.LANCZOS angewandt auf {conversion_file}"
        )
    return True


def verify(conversion_file: Path, *, verbose: bool = True) -> None:
    text = conversion_file.read_text(encoding="utf-8")
    if "Image.ANTIALIAS" in text:
        raise SystemExit("[patch] FEHLER: Image.ANTIALIAS ist weiterhin vorhanden.")
    if "Image.LANCZOS" not in text:
        raise SystemExit("[patch] FEHLER: Image.LANCZOS fehlt nach dem Patch.")
    if verbose:
        print("[patch] Verifikation ok: kein ANTIALIAS, LANCZOS vorhanden.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = Path(argv[0]) if argv else find_conversion_file()
    apply_patch(target)
    verify(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
