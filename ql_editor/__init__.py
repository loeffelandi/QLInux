"""QLInux - P-touch-Editor-Klon fuer Brother-QL-Drucker.

Reines Python, native GUI (PySide6), Rendering via Pillow, Druck via brother_ql.

Das Paket ist in klar getrennte Schichten gegliedert:

* :mod:`ql_editor.media`     - Datenmodell (Baender, Modelle, Masseinheiten) - keine Qt
* :mod:`ql_editor.lbx`       - Brother-P-touch-Dateien (``.lbx``) importieren
* :mod:`ql_editor.renderer`  - Szene -> ``PIL.Image`` in exakter Zielbreite
* :mod:`ql_editor.printer`   - brother_ql-Wrapper (verbinden, konvertieren, senden)
* :mod:`ql_editor.stationery` - Avery-Zweckform-Bögen (gLabels-Maße)
* :mod:`ql_editor.sheet_output` - Bogen als PDF oder über den Systemdrucker
* :mod:`ql_editor.app`       - QApplication / MainWindow (GUI)
* :mod:`ql_editor.about`     - "Über QLInux" (Modelle, Lizenzen, Dank)
* :mod:`ql_editor.help`      - Hilfe (kurzer Text, Tastenübersicht)
"""

from __future__ import annotations

import logging as _logging

# `brother_ql.devicedependent` ist in 0.9.4 nur noch ein deprecated Shim und
# loggt beim Import eine Warnung. Fuer Endnutzer ist das reines Rauschen Wir
# stufen den Logger stumm - an den Daten aendert das nichts.
_logging.getLogger("brother_ql.devicedependent").setLevel(_logging.ERROR)

__all__ = ["APP_NAME", "__version__"]

__version__ = "0.4.0"
APP_NAME = "QLInux"
