"""Einstiegspunkt fuer das PyInstaller-Bundle (AppImage).

Warum eine eigene Datei: ``python -m ql_editor`` funktioniert ueber das Paket,
PyInstaller will aber ein Skript als Startpunkt. Hier steht deshalb nur der
Import - damit die Analyse denselben Weg nimmt wie ein normaler Start.
"""

from __future__ import annotations

import sys

from ql_editor.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
