#!/usr/bin/env python3
"""Bootstrap der Projekt-venv fuer QLInux.

Plattformneutral (Linux, macOS, Windows):

* legt ./.venv an
* installiert die gepinnten Abhaengigkeiten (``requirements-dev.txt``)
* wendet den idempotenten Pillow-10-Patch an

Aufruf:  python scripts/bootstrap_venv.py
         bash scripts/bootstrap_venv.sh     (ruft dieses Skript auf)

``PYTHON`` waehlt den Interpreter, mit dem die venv angelegt wird
(Standard: der Interpreter, der dieses Skript ausfuehrt).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(command: list[str]) -> None:
    subprocess.check_call(command)


def main() -> int:
    python = venv_python()
    creator = os.environ.get("PYTHON") or sys.executable
    print(f">> Projekt:   {ROOT}")
    print(f">> venv:      {VENV}")
    if not python.is_file():
        run([creator, "-m", "venv", str(VENV)])
    run([str(python), "-m", "pip", "install", "--upgrade", "pip", "wheel"])
    print(">> installiere Abhaengigkeiten (gepinnt)")
    run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")])
    print(">> wende brother_ql-Patch an")
    run([str(python), str(ROOT / "scripts" / "patch_brother_ql.py")])
    print(">> Selbsttest")
    run(
        [
            str(python),
            "-c",
            (
                "import brother_ql\n"
                "from brother_ql.labels import LabelsManager\n"
                "from brother_ql.models import ModelsManager\n"
                "print('brother_ql:', brother_ql.__file__)\n"
                "print('Labels:', len(list(LabelsManager().iter_elements())))\n"
                "print('Models:', len(list(ModelsManager().iter_elements())))\n"
                "import PySide6, qrcode, barcode, libusb_package\n"
                "print('PySide6:', PySide6.__version__)\n"
                "print('libusb:', libusb_package.get_library_path())\n"
                "print('OK')\n"
            ),
        ]
    )
    activate = (
        str(VENV / "Scripts" / "activate")
        if sys.platform == "win32"
        else "source .venv/bin/activate"
    )
    print(f">> fertig. venv aktivieren mit: {activate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
