# API-Notizen: verifizierte `brother_ql`-Fakten (0.9.4)

Diese Datei dokumentiert die **tatsaechlich installierte** API. Sie wurde vor
dem ersten Code-Schritt verifiziert (siehe `scripts/verify_api.py`). Das ist
bewusst *die einzige Quelle der Wahrheit* - der uebrige Code raet nie.

Reproduzierbar mit:

```bash
source .venv/bin/activate
python scripts/verify_api.py
```

## Umgebung

| Punkt | Wert |
| --- | --- |
| OS | Pop!_OS (Ubuntu 24.04), Python 3.12.3 |
| Projekt-venv | `./.venv` (eigene venv, Web-venv bleibt unangetastet) |
| `brother_ql` | **0.9.4** (gepinnt, nicht upgraden) |
| Pillow | 12.3.0 |
| PySide6 | 6.12.0 |
| Drucker | QL-820NWB, `tcp://192.168.178.62:9100` |
| Auflosung | 300 dpi → `DOTS_PER_MM = 300/25.4 ≈ 11.811` |

> Hinweis: Der Drucker war aus der Build-Umgebung **nicht** per TCP erreichbar
> (`192.168.178.62:9100`). Der Druckpfad ist daher gegen die Bibliothek
> unit-getestet, aber nicht live gegen den Drucker.

### Live-Statusabfrage (Readback)

Port `9100` des QL-820NWB ist offen (TCP-Connect erfolgreich), liefert aber
**keine Statusantwort** auf `ESC i S` (`1B 69 53`) - weder allein noch nach
`ESC @` / Moduswechsel. Das deckt sich mit der Notiz in
`brother_ql.backends.helpers.send`, dass das Netzwerk-Backend kein Readback
unterstuetzt.

Konsequenz fuer die App: die Funktion "Band erkennen" versucht die Abfrage
(`ql_editor.printer.detect_label`) und faellt bei fehlender Antwort **sauber
auf manuelle Auswahl zurueck** (Rueckgabe ``None``, kein Absturz).

## Abweichungen zur Aufgabenbeschreibung (wichtig!)

Die Aufgabenbeschreibung nennt eine aeltere API-Oberflaeche. Real vorhanden ist:

1. **`brother_ql.devicedependent` existiert noch, ist aber deprecated** und nur
   ein Shim ueber die modernen Module `brother_ql.labels` und
   `brother_ql.models`. Beim Import wird eine Deprecation-Warnung geloggt.
   → Unser Code importiert **direkt** aus `brother_ql.labels` /
   `brother_ql.models` (keine Warnung, keine Shimbruchstelle).
2. `from brother_ql.devicedependent import label_specs` **gibt es nicht**.
   Vorhanden sind `label_type_specs`, `label_sizes`, `models`.
3. `brother_ql.__version__` existiert **nicht** → Version via
   `importlib.metadata.version("brother_ql")` (ergibt `0.9.4`).
4. In `label_type_specs[i]` sind `kind` (ein `FormFactor`) und `color`
   (ein `Color`) **Enums**, keine Strings. `restrict_printers` ist eine
   **leere Liste** `[]` (nicht `None`) bei uneingeschraenkten Baendern.

## Verifizierte Signaturen

```python
BrotherQLRaster.__init__(self, model='QL-500')

convert(qlr, images, label, **kwargs)
#   kwargs: cut, dither, compress, red, rotate, dpi_600, hq, threshold
#   threshold-Default = 70 (wird intern invertiert: 100-x)

send(instructions, printer_identifier=None, backend_identifier=None, blocking=True)
#   -> dict: instructions_sent, outcome, printer_state, did_print, ready_for_next_job
#   Netzwerk-Backend hat kein Readback: kehrt nach write() zurueck (outcome='sent')
```

Importe, die real funktionieren:

```python
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
from brother_ql.labels import LabelsManager, FormFactor, Color
from brother_ql.models import ModelsManager
```

## Band-Datenmodell (`label_type_specs` → `LabelSpec`)

| Aufgabenfeld | reales Feld | Beispiel "50" |
| --- | --- | --- |
| `tape_size` | `tape_size` | `(50, 0)` |
| `dots_printable` | `dots_printable` | `(554, 0)` → **Canvas-Breite** |
| `dots_total` | `dots_total` | `(590, 0)` |
| `feed_margin` | `feed_margin` | `35` |
| `right_margin_dots` | `offset_r` / `right_margin_dots` | `12` |
| `kind` | `form_factor` (`FormFactor`) | `ENDLESS` |
| `restrict_printers` | `restricted_to_models` | `[]` (= alle Modelle) |
| `color` | `color` (`Color`) | `BLACK_WHITE` |

Verifizierte druckbare Breiten bei 300 dpi (nur Kontrolle, Code liest dynamisch):

| Band | Dots | | Band | Dots |
| --- | --- | --- | --- | --- |
| 12 mm | 106 | | 62 mm | 696 |
| 29 mm | 306 | | 102 mm | 1164 |
| 38 mm | 413 | | | |
| 50 mm | 554 | | | |
| 54 mm | 590 | | | |

## Kernprinzip (Resize vermeiden)

`convert()` behandelt den Bildpfad je Bandtyp unterschiedlich:

* **Endlos:** ist `im.size[0] != dots_printable[0]`, wird mit `Image.LANCZOS`
  resized **und gewarnt** (`'Need to resize the image...'`). Das ist genau der
  Pfad, der den ANTIALIAS-Patch beruehrt.
* **Die-cut/Rund:** die Bildmasse muessen **exakt** `dots_printable` entsprechen,
  sonst `ValueError("Bad image dimensions: ...")`.

→ **Das gerenderte Bild ist immer exakt `dots_printable[0]` px breit.**
Intern polstert `convert()` auf die Geraetebreite
`number_bytes_per_row * 8 = 720` px (QL-820NWB) und setzt den Offset
`720 - breite - right_margin_dots`. Die Bildhoehe bestimmt die Etikettenlaenge.

## Pillow-10-Patch

Von Haus aus nutzt `conversion.py` Zeile 112 `Image.ANTIALIAS` (in Pillow ≥ 10
entfernt). Der Patch setzt genau dieses eine Vorkommen auf `Image.LANCZOS`.

* `scripts/patch_brother_ql.py` ist **idempotent** und aendert sonst nichts.
* Das PyPI-Sdist 0.9.4 ist bis auf diese eine Zeile **byte-identisch** mit der
  installierten Referenzkopie (verifiziert) → der Patch reproduziert den
  Bestandszustand exakt.

Verifikation nach Installation:

```
Image.LANCZOS vorhanden:   True
Image.ANTIALIAS vorhanden: False
```
