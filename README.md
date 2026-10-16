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
| M3 | PySide6-GUI (Canvas, Panel, Vorschau) | ✅ |
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

## Starten (GUI)

```bash
source .venv/bin/activate
python -m ql_editor
```

* **Links**: Bandauswahl (dynamisch, nach Modell gefiltert), Länge
  (Auto Length / fest, Gesamt- oder Inhaltsmaß), Margins, Farbe.
* **Mitte**: Canvas in exakter Bandbreite mit mm-Linealen; der **nicht
  bedruckbare Rand** (~1,5 mm je Seite) ist schraffiert, Items werden darauf
  begrenzt.
* **Rechts**: Inspector (Eigenschaften des ausgewählten Objekts) + monochrome
  1-bit-Vorschau + Druckoptionen (Threshold, Dither, Schnitt).

Das Layout ist **responsiv**: Der Canvas passt sich der Fenstergröße an
(solange kein manueller Zoom gesetzt ist), die Seitenpanels werden bei
Platzmangel scrollbar und die Formulare brechen bei schmalem Fenster um.

### Bedienung (wie eine Desktop-App)
* **Doppelklick ins Leere** legt ein Textfeld an und startet die Bearbeitung.
* **Doppelklick auf Text** editiert inline (Esc beendet).
* **Eckgriff ziehen** ändert die Größe des ausgewählten Objekts
  (Text = Schriftgröße, QR bleibt quadratisch, Barcode = Höhe).
* **Pfeiltasten** verschieben (mit Shift 10 Dots), **Entf** löscht.
* **Mausrad** über dem Canvas: scrollt, wenn es etwas zu scrollen gibt,
  sonst zoomt es; **Ctrl + Rad** zoomt immer, **Shift + Rad** scrollt
  horizontal, **mittlere Maustaste ziehen** verschiebt den Ausschnitt.
  Zusätzlich: Zoom −/Einpassen/+ in der Toolbar (Ctrl+0 = einpassen).
* **Rechtsklick** öffnet das Kontextmenü (Einfügen, Reihenfolge, Löschen).
* Der **Inspector** zeigt kontextabhängig die passenden Eigenschaften
  (Text/Schrift/Farbe, Barcode-Inhalt/Symbologie, QR-Inhalt, Position, Drehung).

Headless-Druckpfad (ohne GUI) zum Testen:

```bash
python scripts/print_test.py --label 50 --length-mm 40 --dry-run --save /tmp/x.png
```

## Wichtige Fakten zur Installation

* Zielauflosung 300 dpi: `dots = mm * 300 / 25.4`.
* Das gerenderte Bild ist **immer exakt `dots_printable[0]` px breit**, damit
  `brother_ql` den Resize-Pfad ueberspringt (kein Qualitaetsverlust).
* **Laengen-Semantik** (`ql_editor.media.LengthMode`): Das Laengenfeld meint
  standardmaessig das **fertige Etikett** (`FINISHED`) inkl. Vorschub/Schnittrand.
  Bei Endlosband fuegt der Drucker `2*feed_margin + CUT_OFFSET_DOTS`
  (~7 mm) hinzu; der Inhalt wird entsprechend reduziert. Mit `CONTENT` gilt
  stattdessen 1:1 der bedruckte Inhalt (z. B. 40 mm -> Canvas 554x472 px).
* Details und verifizierte API-Signaturen: siehe [`docs/API_NOTES.md`](docs/API_NOTES.md).
