"""Einstiegspunkt fuer das PyInstaller-Bundle (AppImage).

Warum eine eigene Datei: ``python -m ql_editor`` funktioniert ueber das Paket,
PyInstaller will aber ein Skript als Startpunkt. Hier steht deshalb nur der
Import - damit die Analyse denselben Weg nimmt wie ein normaler Start.
"""

from __future__ import annotations

import os
import sys


def _selftest_libusb() -> int:
    """Prueft fuer den Bau, ob pyusb libusb im Bundle findet (kein Fenster)."""
    from usb.backend import libusb1

    backend = libusb1.get_backend()
    if backend is None:
        print("libusb nicht gefunden", file=sys.stderr)
        return 1
    print(f"libusb gefunden: {libusb1._lib._name}")
    return 0


if __name__ == "__main__":
    if os.environ.get("QLINUX_SELFTEST") == "libusb":
        raise SystemExit(_selftest_libusb())
    from ql_editor.app import main

    raise SystemExit(main(sys.argv))
