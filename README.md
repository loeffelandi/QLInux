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
| M3.11 | Einklappbare Overlay-Panels, Druckqualität, Vorschau in 1:1 | ✅ |
| M3.12 | Auflösung pro Modell (300 × 300 / 300 × 600 dpi), HQ-Schalter, Tintenmenge erklärt | ✅ |
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
  panels.py      # einklappbare Seitenpanels (Hover-Overlay)    (M3.11)
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
* **„Band erkennen"** fragt das eingelegte Band am Drucker ab (Statuskommando
  `ESC i S`, 32-Byte-Antwort) und stellt die Auswahl darauf ein. Das geht
  **nur über USB**: der Netzwerk-Anschluss (TCP 9100) ist eine reine
  Druckschnittstelle ohne Rückkanal - genau das steht auch in `brother_ql`
  selbst (`backends/helpers.py`: *„The network backend doesn't support
  readback"*). Über `tcp://…` antwortet der Drucker nicht (am QL-820NWB
  nachgemessen), die Oberfläche sagt das dann und man wählt das Band von Hand.
  QLInux druckt weiterhin über das Netzwerk - nur die Erkennung braucht USB.
* **Mitte**: Canvas in exakter Bandbreite mit mm-Linealen; der **nicht
  bedruckbare Rand** (~1,5 mm je Seite) ist schraffiert, Items werden darauf
  begrenzt. Um die Designfläche liegt eine **Arbeitsfläche** (8 mm Rand,
  zusätzlich alles, was übersteht): dadurch gibt es **Scrollbalken in beide
  Richtungen** und auch sehr breite Objekte bleiben mit der Maus erreichbar,
  ohne herauszoomen zu müssen. Die Renderquelle bleibt davon unberührt - die
  Szene selbst ist weiterhin exakt die bedruckbare Fläche.
* **Rechts**: Inspector (Eigenschaften des ausgewählten Objekts) + Druckoptionen
  (Auflösung, HQ, Graustufen, Tintenmenge, Schnitt, Drucken).

Der Canvas ist **räumlich WYSIWYG** (Position, Größe, mm, Randbegrenzung).
Was er *nicht* zeigt, ist die **Binarisierung**: der Drucker kennt nur 1 bit
Schwarz/Weiß, während der Canvas mit Antialiasing/Farbe zeichnet. Deshalb gibt
es die **Druckvorschau** als Umschalter (Auge-Symbol in der Toolbar bzw.
`Ctrl+Shift+P`, `Esc` beendet): sie legt das echte, binarisierte 1-bit-Bild
über den Canvas - genau das, was aus dem Drucker kommt (Schwelle + Dithering).
Die Vorschau ist **pixelgleich** mit den Daten, die an den Drucker gehen
(Regressionstest in `tests/test_preview.py`).

Damit der Bildschirm die echten Druckpunkte zeigt, springt die Vorschau beim
Einschalten auf **1:1** (bzw. bleibt vergrößert, wenn schon gezoomt war) und
stellt beim Beenden die vorherige Ansicht wieder her. Grund: ein 1-bit-Bild
verliert beim *Verkleinern* feine Linien - die Vorschau sähe dann schlechter
aus als der Druck. Ist sie kleiner als 100 %, erinnert die Zoomanzeige in der
Statusleiste an `Ctrl+1` (1:1). Im Vorschau-Modus ist die Bearbeitung gesperrt
(Zoom/Pan bleiben möglich).

Im **600-dpi-Modus** rendert die Vorschau mit demselben Faktor wie der Druck
und rechnet das 1-bit-Bild nur für die Anzeige auf Canvas-Größe herunter
(Box-Filter, also Mittelung der gedruckten Punkte). Gezeigt werden damit
weiterhin die echten Druckdaten - nur eben auf 300-dpi-Anzeigeraster; feine
Details erscheinen dabei als Grau statt als harte Punkte.

Das Layout ist **responsiv**: Der Canvas passt sich der Fenstergröße an
(solange kein manueller Zoom gesetzt ist), die Seitenpanels werden bei
Platzmangel scrollbar und die Formulare brechen bei schmalem Fenster um.
Offene Panels sind 300 px breit (gerade so, dass die Formularzeilen des
Inspectors einzeilig bleiben) und schrumpfen bei kleinen Fenstern automatisch;
das Fenster öffnet ohne gespeicherte Geometrie mit 1320 x 860 px.

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

* **Doppelklick ins Leere** legt ein Textfeld an und startet die Bearbeitung -
  **leer und ohne Markierung**: der Cursor blinkt, getippt wird sofort der
  eigene Text. Bleibt das Feld leer (Klick daneben oder `Esc`), wird es wieder
  verworfen, statt als unsichtbares Objekt liegen zu bleiben.
* **Doppelklick auf Text** editiert inline und **markiert den ganzen Text**
  (zum Ersetzen/Umbenennen) - auch bei einem Doppelklick im bereits offenen
  Feld. Ein *einfacher* Klick im offenen Feld setzt den Cursor genau.
  `Esc` beendet die Bearbeitung.
* **Ziehen** verschiebt das Objekt; bei Mehrfachauswahl bewegt sich die
  ganze Auswahl gemeinsam. Objekte **rasten magnetisch** an Bandkanten,
  Bandmitte und anderen Objekten ein - die Einrastlinien werden während
  des Ziehens angezeigt (an Objekten/Zentren/Seiten).
* **8 Anfasser** (Ecken + Kanten) am ausgewählten Objekt ändern Größe und
  Proportion; der **gegenüberliegende Griff bleibt in Szenenkoordinaten
  stehen** - auch bei gedrehten und skalierten Objekten (ein gedrehtes Bild
  wächst also dorthin, wo der Zeiger zieht). Der Mauszeiger dreht sich mit dem
  Objekt mit. Bei Text skaliert die Höhe die Schrift, die Breite setzt die
  Umbruchbreite. Der runde Griff **über** dem Objekt dreht es **um seine
  Mitte** (Shift rastet auf 15°); der Mauszeiger zeigt dort ein gezeichnetes
  **Rotations-Symbol** (Qt hat keinen passenden System-Cursor, ein Fadenkreuz
  würde nichts über „drehen" sagen - siehe `ql_editor/icons.cursor`).
* **Bilder** werden beim Einfügen (Toolbar, Kontextmenü oder Drag & Drop) auf
  die **Bandbreite verkleinert**, wenn sie größer sind - nie vergrößert, immer
  im Seitenverhältnis. Ein 2400-px-Foto landet damit direkt passend auf dem
  Etikett statt am Bandrand abgeschnitten zu werden. Die Größe steht im
  Inspector in **Millimetern** (Breite/Höhe bleiben im Verhältnis).
* **Mehrfachauswahl**: Gummiband auf freier Fläche, **Ctrl + Klick**
  schaltet einzelne Objekte zur Auswahl hinzu/ab.
* **Drag & Drop**: Bilddateien aus dem Dateimanager auf den Canvas ziehen
  (werden am Mauszeiger zentriert); Textabwürfe (z. B. aus einem Editor)
  legen ein Textfeld an.
* **Pfeiltasten** verschieben (mit Shift 10 Dots), **Entf** löscht.
* **Druckvorschau** (Auge-Symbol, `Ctrl+Shift+P`): zeigt die echte 1-bit-Ausgabe
  über dem Canvas, beim Einschalten auf 1:1 (`Ctrl+1`); `Esc` beendet sie.
  Schwelle/Dithering wirken sofort, „Tinte: x %" zeigt den Anteil der
  bedruckten Fläche.
* **Auflösung** (rechts unter „Druckoptionen"): eine Liste mit genau den
  Auflösungen, die der **gewählte Drucker** kann. Was ein Drucker kann, steht in
  seinen Datenblättern - abfragen lässt es sich nicht (die Statusantwort kennt
  nur Band und Fehler), deshalb pflegt `ql_editor/printer.py` die Fähigkeit als
  Tabelle (`DPI_600_MODELS`).
  * *300 × 300 dpi*: die Standardauflösung des Druckkopfs (quer und in
    Bandlaufrichtung 300 dpi) - Vorgabe.
  * *300 × 600 dpi*: der **High-Resolution-Modus** des Druckers. Er setzt die
    Zeilen **in Bandlaufrichtung** mit halbem Abstand (600 statt 300 dpi), quer
    zur Bandbreite bleibt es bei 300 dpi - deshalb steht dort bewusst nicht
    einfach „600 dpi". Das Etikett wird dafür in beiden Achsen mit doppelter
    Auflösung gerendert (echte Vektorpixel, kein Hochskalieren) und behält seine
    Länge. Nur Modelle mit belegtem High-Resolution-Modus bieten die Auflösung
    an (QL-800, QL-810W, QL-820NWB - die Datenblätter der übrigen Modelle nennen
    nur den 300-dpi-Druckkopf); sie braucht doppelt so viele Zeilen und druckt
    deshalb langsamer.
  Die **Druckvorschau zeigt genau die gewählte Auflösung**: sie rendert mit
  demselben Faktor wie der Druckpfad und mittelt das feinere 1-bit-Bild nur für
  die Anzeige auf Canvas-Größe.
* **Hohe Druckqualität (HQ)**: ein eigener Schalter, **keine** Auflösung. Er
  setzt `pquality` - „Qualität vor Tempo". Der Drucker arbeitet dann langsamer
  und setzt die Punkte gleichmäßiger; die Auflösung ändert er nicht. Das kann
  jedes Modell, deshalb ist es ein Häkchen und keine Liste.
* **Tintenmenge** (Standard 70 %, einstellbar von 40 % bis 90 %): Der Drucker
  kennt nur Schwarz oder Weiß - jede weiche Kante und jeder Grauton im Design
  muss zu einem von beidem werden. Das Feld ist der Schnitt: 70 % heißt „alles
  ab etwa 30 % Schwärze wird Tinte". Höher = mehr Tinte (auch hellgraue Ränder
  werden schwarz, kräftigere und etwas breitere Schrift); niedriger = weniger
  Tinte (nur dunkle Punkte werden schwarz, feiner - dünne Striche können
  ausfransen). Die Extremwerte (alles schwarz bzw. nur reines Schwarz) sind
  bewusst nicht wählbar. „Tinte: x %" zeigt sofort, was der Wert bewirkt.
* **Graustufen (Dithering)**: für Fotos und Bilder - Grautöne werden gepunktet
  statt hart geschwellt. Dann ist die Tintenmenge **wirkungslos** (die
  Bibliothek ignoriert sie); das Feld wird ausgegraut, statt still nichts zu
  tun.
* Alle Druckoptionen werden gemerkt. Die Werte gehen 1:1 an den Drucker: die
  Vorschau zeigt genau das Ergebnis.
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
* **Mausrad** über dem Canvas: scrollt weich (animiert), sobald man über die
  Etikettengröße hinausgezoomt hat, sonst zoomt es; **Ctrl + Rad** zoomt immer,
  **Shift + Rad** scrollt horizontal, **mittlere Maustaste ziehen** verschiebt
  den Ausschnitt. Trackpads werden über `pixelDelta` fein unterstützt.
  Zusätzlich: Zoom −/Einpassen/+ in der Toolbar (Ctrl+0 = einpassen), und die
  **Scrollbalken** des Canvas für beide Richtungen.
* **Mausrad** über einem Seitenpanel scrollt das Panel - auch wenn der Zeiger
  über einem Feld steht; ein Feld ändert seinen Wert nur, wenn es den Fokus
  hat (kein versehentliches Verstellen).
* **Seitenpanels einklappen** (kleine Bildschirme): Der **Pfeil im Panel**
  (senkrechte Tab-Leiste am Außenrand) klappt das jeweilige Panel auf den
  schmalen Streifen zusammen - zusätzlich im Hamburger-Menü unter *Ansicht* und
  per **`Ctrl+B`** (links) / **`Ctrl+Shift+B`** (rechts). Die Pfeile sitzen
  bewusst *in* den Panels, nicht in der Toolbar.
  Ist ein Panel eingeklappt, bleibt der Streifen mit Pfeil sichtbar; **beim
  Überfahren klappt das Panel als Overlay über dem Canvas auf** (mit Schatten,
  der Canvas behält seine Breite) und beim Verlassen wieder ein. Solange im
  aufgeklappten Panel gearbeitet wird (Fokus im Formularfeld), bleibt es
  stehen. Sind beide Panels eingeklappt, steht der Canvas in voller
  Fensterbreite (die effektive Mindestbreite des Fensters sinkt dadurch von
  ~730 auf 640 px). Der Zustand wird beim Beenden gemerkt und beim nächsten
  Start wiederhergestellt.
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
