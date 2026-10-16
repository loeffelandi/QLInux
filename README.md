# QLInux — P-touch-Editor-Klon fuer Brother QL-820NWB

Native Linux-Desktop-App (Python + PySide6), die die Kernfunktionen des
P-touch Editors nachbildet: Band-Auswahl, feste/automatische Laenge, Margins,
freies Canvas fuer Text/Bild/Barcode/QR, monochrome Druckvorschau und
Direktdruck ueber `brother_ql`.

Kein Browser-Tool, kein WebUSB.

## Projektstatus

| Meilenstein | Inhalt | Status |
| --- | --- | --- |
| M1 | Setup, API-Verifikation, Datenmodell | ✅ |
| M2 | Rendering-Kern + Druck-Wrapper (headless) | ✅ |
| M3 | PySide6-GUI (Canvas, Panel, Vorschau) | ⏳ |
| M4 | Vorlagen, Settings, `.deb`-Paket | ⏳ |

## Architektur

Klare Schichtentrennung UI ↔ Rendering ↔ Druck:

```
ql_editor/
  media.py       # Datenmodell (Baender, Modelle, mm<->dots) — kein Qt
  renderer.py    # Szene -> PIL.Image exakter Breite       (M2)
  printer.py     # brother_ql-Wrapper (convert + send)     (M2)
  items.py       # Canvas-Items (Text/Bild/Barcode/QR/Linie) (M3)
  canvas.py      # QGraphicsScene mit fester px-Groesse       (M3)
  media_panel.py # Bandauswahl, Laenge, Auto-Length, Margins  (M3)
  preview.py     # monochrome 1-bit-Vorschau                  (M3)
  templates.py   # Vorlagen (JSON + Assets)                   (M4)
  settings.py    # QSettings (Druckeradresse, letzte Auswahl) (M4)
  app.py         # QApplication / MainWindow                  (M3)
  __main__.py    # Einstiegspunkt                             (M3)
```

## Installation (Entwicklung)

```bash
git clone <repo> QLInux && cd QLInux
bash scripts/bootstrap_venv.sh          # legt .venv an, pinnt brother_ql==0.9.4,
                                        # wendet den Pillow-10-Patch an
source .venv/bin/activate
python -m pytest -q                     # Datenmodell-Tests (headless)
python scripts/verify_api.py            # dokumentiert die reale brother_ql-API
```

Die gepinnten Abhaengigkeiten stehen in `requirements.txt`
(bewusst **nicht** auf eine neuere `brother_ql`-Version anheben — der
Git-Master entfernt `brother_ql.devicedependent` und bricht die App).

## Wichtige Fakten zur Installation

* Zielauflosung 300 dpi: `dots = mm * 300 / 25.4`.
* Das gerenderte Bild ist **immer exakt `dots_printable[0]` px breit**, damit
  `brother_ql` den Resize-Pfad ueberspringt (kein Qualitaetsverlust).
* Details und verifizierte API-Signaturen: siehe [`docs/API_NOTES.md`](docs/API_NOTES.md).
