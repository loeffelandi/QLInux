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
| M3.x | Canvas-Editing, Icons, Druckvorschau, weiches Scrollen, Sheets | ✅ |
| M4 | Vorlagen, Settings, `.deb`-Paket | ⏳ |

## Architektur

Klare Schichtentrennung UI ↔ Rendering ↔ Druck:

```
ql_editor/
  media.py       # Datenmodell (Baender, Modelle, Laenge/Ausrichtung) — kein Qt
  renderer.py    # Szene -> PIL.Image exakter Breite       (M2)
  printer.py     # brother_ql-Wrapper (convert + send)     (M2)
  items.py       # Canvas-Items (Text/Bild/Barcode/QR/Linie) (M3)
  canvas.py      # QGraphicsScene mit fester px-Groesse       (M3)
  media_panel.py # Bandauswahl, Ausrichtung, Laenge, Margins  (M3)
  preview.py     # 1-bit-Binarisierung (Kernfunktionen)        (M3)
  icons.py       # programmatisch gezeichnete Vektor-Icons     (M3)
  sheet.py       # Dialoge als Overlay im Fenster (kein 2. Fenster) (M3.8)
  widgets.py     # Wheel-Guard + weiches Scrollen               (M3.7)
  inspector.py   # kontextabhaengige Eigenschaften              (M3.1)
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

* **Links**: Bandauswahl (dynamisch, nach Modell gefiltert), **Ausrichtung**
  (quer / längs des Bandes, zwei Knöpfe in der Gruppe „Band"), Länge
  (Auto Length / fest, Gesamt- oder Inhaltsmaß), Margins, Farbe.
* **Mitte**: Canvas in exakter Bandbreite mit mm-Linealen; der **nicht
  bedruckbare Rand** (~1,5 mm je Seite) ist schraffiert, Items werden darauf
  begrenzt.
* **Rechts**: Inspector (Eigenschaften des ausgewählten Objekts) + Druckoptionen
  (Threshold, Dither, Schnitt, Drucken).

Der Canvas ist **räumlich WYSIWYG** (Position, Größe, mm, Randbegrenzung).
Was er *nicht* zeigt, ist die **Binarisierung**: der Drucker kennt nur 1 bit
Schwarz/Weiß, während der Canvas mit Antialiasing/Farbe zeichnet. Deshalb gibt
es die **Druckvorschau** als Umschalter (Auge-Symbol in der Toolbar bzw.
`Ctrl+Shift+P`, `Esc` beendet): sie legt das echte, binarisierte 1-bit-Bild
über den Canvas - genau das, was aus dem Drucker kommt (Threshold + Dither).
Im Vorschau-Modus ist die Bearbeitung gesperrt (Zoom/Pan bleiben möglich).

Das Layout ist **responsiv**: Der Canvas passt sich der Fenstergröße an
(solange kein manueller Zoom gesetzt ist), die Seitenpanels werden bei
Platzmangel scrollbar und die Formulare brechen bei schmalem Fenster um.
Die Seitenpanels starten mit großzügigen Standardbreiten (Band/Drucker 300 px,
Eigenschaften 380 px) und das Fenster öffnet ohne gespeicherte Geometrie mit
1320 x 860 px.

### Dialoge als Sheet (statt eigenem Fenster)
Alle Dialoge (Bildauswahl, Eingaben, Meldungen) laufen als **Sheet innerhalb
des Hauptfensters** (`ql_editor/sheet.py`): Der Hintergrund wird abgedunkelt,
die Bedienung dahinter ist gesperrt, `Esc` schließt.

Der Grund ist Wayland: Ein eigener Dialog ist dort ein zweites Top-Level-Fenster.
Der Compositor verwaltet es selbst - unter COSMIC bleibt es als eigenes Fenster
im Vordergrund und lässt sich nicht "wegklicken". Qt 6.12 meldet Dialoge zudem
nicht über das Protokoll `xdg-dialog-v1` an, sodass Tiling-Compositor sie wie
normale Fenster behandeln. Ein Overlay *im* Fenster umgeht das komplett: es gibt
kein zweites Fenster, das der Fenstermanager verwalten könnte. Solange ein Sheet
offen ist, werden auch App-Tastenkürzel (Ctrl+P, Entf, ...) geschluckt.

### Bedienung (wie eine Desktop-App)
Die Oberfläche ist **icon-basiert**: die Toolbar zeigt nur Icons (mit Tooltips),
und jeder Menü- sowie Kontextmenü-Eintrag hat ein Icon. Die Icons werden zur
Laufzeit gezeichnet (`ql_editor/icons.py`), einheitlich in Strichstärke und
Eckenradius, und passen sich der Palette an (hell/dunkel) - es gibt keine
externen Icon-Dateien.

Eine **klassische Menüleiste gibt es nicht**. Alle Befehle liegen in einem
**Hamburger-Menü** (`main_menu_button`, links in der Toolbar): ein flaches
Menü mit Abschnittsüberschriften (Einfügen / Bearbeiten / Ansicht / Drucken),
Icons und Shortcuts. Hintergrund: Unter Linux/Wayland gibt es (anders als unter
macOS) keinen globalen Menübalken; ein Menü-Knopf in der Toolbar ist dort die
übliche, moderne Lösung. Die Einträge teilen sich die `QAction`s mit der
Toolbar, bleiben also immer synchron.

* **Doppelklick ins Leere** legt ein Textfeld an und startet die Bearbeitung.
* **Doppelklick auf Text** editiert inline (Esc beendet).
* **Ziehen** verschiebt das Objekt; bei Mehrfachauswahl bewegt sich die
  ganze Auswahl gemeinsam. Objekte **rasten magnetisch** an Bandkanten,
  Bandmitte und anderen Objekten ein - die Einrastlinien werden während
  des Ziehens angezeigt (an Objekten/Zentren/Seiten).
* **8 Anfasser** (Ecken + Kanten) am ausgewählten Objekt ändern Größe und
  Proportion; die **gegenüberliegende Kante bleibt verankert**. Der runde
  Griff **über** dem Objekt dreht es (Shift rastet auf 15°).
  (Text = Schriftgröße, QR bleibt quadratisch, Barcode = Höhe.)
* **Mehrfachauswahl**: Gummiband auf freier Fläche, **Ctrl + Klick**
  schaltet einzelne Objekte zur Auswahl hinzu/ab.
* **Drag & Drop**: Bilddateien aus dem Dateimanager auf den Canvas ziehen
  (werden am Mauszeiger zentriert); Textabwürfe (z. B. aus einem Editor)
  legen ein Textfeld an.
* **Pfeiltasten** verschieben (mit Shift 10 Dots), **Entf** löscht.
* **Druckvorschau** (Auge-Symbol, `Ctrl+Shift+P`): zeigt die echte 1-bit-Ausgabe
  über dem Canvas; `Esc` beendet sie. Threshold/Dither wirken sofort.
* **Ausrichtung** (Gruppe „Band" im linken Panel, auch im Hamburger-Menü):
  * *quer zum Band* (Voreinstellung): der Inhalt läuft über die Bandbreite,
    die Etikettenlänge ergibt sich aus der **Inhaltshöhe** - spart Band bei
    langen, flachen Inhalten (z. B. einer Textzeile).
  * *längs des Bandes*: der Inhalt läuft in Bandrichtung, die Etikettenlänge
    ergibt sich aus der **Inhaltsbreite** - spart Band bei hohen, mehrzeiligen
    Inhalten, weil die Bandbreite dann als Höhenbudget dient.
    Der Canvas dreht sich mit (das Band läuft senkrecht, die Randbegrenzung
    wandert an die Bandkanten oben/unten); für den Druck wird die Szene um
    90° gedreht, sodass das Bild weiterhin exakt bandbreit ist.
* **Mausrad** über dem Canvas: scrollt weich (animiert), wenn es etwas zu
  scrollen gibt, sonst zoomt es; **Ctrl + Rad** zoomt immer, **Shift + Rad**
  scrollt horizontal, **mittlere Maustaste ziehen** verschiebt den Ausschnitt.
  Trackpads werden über `pixelDelta` fein unterstützt.
  Zusätzlich: Zoom −/Einpassen/+ in der Toolbar (Ctrl+0 = einpassen).
* **Mausrad** über einem Seitenpanel scrollt das Panel - auch wenn der Zeiger
  über einem Feld steht; ein Feld ändert seinen Wert nur, wenn es den Fokus
  hat (kein versehentliches Verstellen).
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
* **Ausrichtung** (`ql_editor.media.Orientation`): Die bedruckbare Bandbreite
  (`dots_printable[0]`) ist immer die Grenze quer zum Band - die Laenge selbst
  ist unabhaengig davon in Bandrichtung definiert (`label_length_dots`). Nur
  die Canvas-Achse wechselt (`canvas_size_for_orientation`), und bei `ALONG`
  dreht der Renderer das Ergebnis einmal um 90° (reine Pixel-Permutation,
  daher zeigt die Druckvorschau dieselben Pixel nur canvas-ausgerichtet).
* Details und verifizierte API-Signaturen: siehe [`docs/API_NOTES.md`](docs/API_NOTES.md).
