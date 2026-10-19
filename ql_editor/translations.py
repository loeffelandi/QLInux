"""Englische Texte zur deutschen Oberflaeche.

Schluessel ist **immer** der deutsche Originaltext aus dem Quelltext (siehe
:mod:`ql_editor.i18n`). Platzhalter wie ``{address}`` muessen erhalten bleiben;
ein Test prueft, dass zu jedem ``tr(...)`` im Quelltext ein Eintrag existiert
und dass die Platzhalter gleich bleiben.

Texte, die in beiden Sprachen gleich lauten (Einheiten, "USB", Produktnamen),
stehen bewusst mit identischem Wert hier - so ist die Liste vollstaendig und
der Test bleibt einfach.
"""

from __future__ import annotations

EN: dict[str, str] = {
    # -- Fenster, Menue, Panels ---------------------------------------------
    "QLInux - P-touch Editor": "QLInux - P-touch Editor",
    "Band & Drucker": "Label & printer",
    "Eigenschaften & Druck": "Properties & print",
    "Panel links": "Left panel",
    "Panel rechts": "Right panel",
    "Panel links ein-/ausklappen (F9)\nEingeklappt bleibt ein Streifen mit Pfeil; er klappt beim Überfahren über dem Canvas auf": (
        "Show/hide left panel (F9)\n"
        "When hidden a strip with an arrow remains; it opens when the pointer "
        "moves over the canvas"
    ),
    "Panel rechts ein-/ausklappen (Umschalt+F9)\nEigenschaften und Druckoptionen": (
        "Show/hide right panel (Shift+F9)\nProperties and print options"
    ),
    "Fett (Strg+B)": "Bold (Ctrl+B)",
    "Kursiv (Strg+I)": "Italic (Ctrl+I)",
    "Unterstrichen (Strg+U)": "Underline (Ctrl+U)",
    "Menü": "Menu",
    "Befehle…": "Commands…",
    "Befehle": "Commands",
    "Befehle (Strg+K)": "Commands (Ctrl+K)",
    "Befehl suchen": "Find a command",
    "Barcode und QR-Code": "Barcode and QR code",
    "Barcode oder QR-Code einfügen": "Insert a barcode or QR code",
    "Sprache": "Language",
    "Erscheinungsbild": "Appearance",
    "Wie das System": "Follow the system",
    "Hell": "Light",
    "Dunkel": "Dark",
    "Qualität": "Quality",
    "Ausgabe": "Output",
    "Lage": "Position",
    "Einfügen": "Insert",
    "Bearbeiten": "Edit",
    "Rückgängig": "Undo",
    "Wiederholen": "Redo",
    "Rückgängig (Strg+Z)": "Undo (Ctrl+Z)",
    "Wiederholen (Strg+Umschalt+Z)": "Redo (Ctrl+Shift+Z)",
    "Links ausrichten": "Align left",
    "Horizontal zentrieren": "Align center horizontally",
    "Rechts ausrichten": "Align right",
    "Oben ausrichten": "Align top",
    "Vertikal zentrieren": "Align center vertically",
    "Unten ausrichten": "Align bottom",
    "Ausrichten": "Align",
    "Ebenen": "Layers",
    "Eigenschaften": "Properties",
    "Ränder": "Margins",
    "Reihenfolge": "Order",
    "Etikett": "Label",
    "Ansicht": "View",
    "Drucken": "Print",
    "Beenden": "Quit",
    "Beenden (Strg+Q)": "Quit (Ctrl+Q)",
    "Über QLInux": "About QLInux",
    "Hilfe": "Help",
    "Links wählst du Drucker und Band. Das Etikett liegt in der Mitte, die Eigenschaften des Markierten rechts, zusammen mit dem Druck. Esc schließt diese Hilfe.": (
        "On the left you pick the printer and the tape. The label sits in the "
        "middle, and the properties of whatever is selected sit on the right, "
        "together with printing. Esc closes this help."
    ),
    "Auf dem Etikett": "On the label",
    "Doppelklick auf die freie Fläche setzt ein Textfeld. Ein Objekt ziehst du mit der Maus. Die Pfeiltasten schieben es um einen Punkt, mit gehaltener Umschalttaste um zehn. Esc beendet das Schreiben im Feld und hebt die Auswahl auf.": (
        "Double-click the empty area to place a text box. Drag an object to "
        "move it. The arrow keys nudge it by one dot, and holding Shift moves "
        "it by ten. Esc stops typing in a field and clears the selection."
    ),
    "Die Druckvorschau zeigt die Punkte, so wie der Drucker sie setzt. Esc bringt die normale Ansicht zurück.": (
        "Print preview shows the dots the way the printer lays them down. "
        "Esc brings the normal view back."
    ),
    "Mit der Maus": "With the pointer",
    "Strg und das Mausrad zoomen, Umschalt und das Mausrad schieben seitlich. Strg+Klick nimmt ein Objekt zur Auswahl dazu oder wieder weg. Strg gedrückt halten und ein markiertes Objekt ziehen lässt das Original liegen und bewegt die Kopie. In einer Tabelle markiert Umschalt+Klick mehrere Zellen, Tab und Umschalt+Tab gehen zur nächsten. In der Datenbank-Tabelle nimmt Strg+Klick eine Zeile dazu oder weg, Umschalt+Klick wählt einen Bereich. Beim Drehen rastet der Winkel auf 90 Grad, mit gehaltener Umschalttaste in Schritten von 15 Grad.": (
        "Ctrl and the wheel zoom, Shift and the wheel scroll sideways. "
        "Ctrl+click adds an object to the selection or drops it again. "
        "Holding Ctrl and dragging a selected object leaves the original in "
        "place and moves a copy. In a table, Shift+click marks several cells, "
        "and Tab and Shift+Tab move to the next one. In the database grid, "
        "Ctrl+click adds or removes a row and Shift+click selects a range. "
        "While rotating, the angle "
        "snaps to 90 degrees, and holding Shift steps by 15 degrees."
    ),
    "Tasten": "Keys",
    "Neues Etikett": "New label",
    "Nächster Reiter": "Next tab",
    "Vorheriger Reiter": "Previous tab",
    "Auswahl löschen": "Delete the selection",
    "Zoom 1:1": "Zoom 1:1",
    "Strg+N": "Ctrl+N",
    "Strg+O": "Ctrl+O",
    "Strg+S": "Ctrl+S",
    "Strg+Umschalt+S": "Ctrl+Shift+S",
    "Strg+F4": "Ctrl+F4",
    "Strg+Tab": "Ctrl+Tab",
    "Strg+Umschalt+Tab": "Ctrl+Shift+Tab",
    "Strg+Z": "Ctrl+Z",
    "Strg+Y": "Ctrl+Y",
    "Entf": "Del",
    "Strg+0": "Ctrl+0",
    "Strg++": "Ctrl++",
    "Strg+-": "Ctrl+-",
    "Strg+1": "Ctrl+1",
    "Strg+C": "Ctrl+C",
    "Strg+X": "Ctrl+X",
    "Strg+V": "Ctrl+V",
    "Strg+D": "Ctrl+D",
    "Strg+B": "Ctrl+B",
    "Strg+I": "Ctrl+I",
    "Strg+U": "Ctrl+U",
    "F9": "F9",
    "Umschalt+F9": "Shift+F9",
    "Strg+K": "Ctrl+K",
    "Strg+P": "Ctrl+P",
    "Strg+Umschalt+P": "Ctrl+Shift+P",
    "Esc": "Esc",
    "Tippen beenden und die Auswahl aufheben": "Stop typing and clear the selection",
    "Pfeiltasten": "Arrow keys",
    "Um einen Punkt verschieben": "Move by one dot",
    "Umschalt+Pfeiltasten": "Shift+arrow keys",
    "Um zehn Punkte verschieben": "Move by ten dots",
    "Rücktaste": "Backspace",
    "Tab": "Tab",
    "Nächste Zelle": "Next cell",
    "Umschalt+Tab": "Shift+Tab",
    "Vorherige Zelle": "Previous cell",
    "Eingabe": "Enter",
    "Zelle bearbeiten": "Edit the cell",
    "F2": "F2",
    "Etiketten gestalten und direkt drucken – für Brother-QL-Drucker und andere, die die Bibliothek brother_ql unterstützt.": (
        "Design labels and print them directly – on Brother QL printers and "
        "any other model the brother_ql library supports."
    ),
    "Unterstützte Drucker": "Supported printers",
    "Alle {models} Modelle, die brother_ql kennt (nichts vorbelegt):": (
        "All {models} models known to brother_ql (none hard-coded):"
    ),
    "Dazu {labels} Bandtypen mit ihren Maßen, ebenfalls aus der Bibliothek. Die Auswahl im Panel richtet sich nach dem gewählten Modell.": (
        "Plus {labels} label types with their sizes, also from the library. "
        "The panel offers the ones that fit the selected model."
    ),
    "Freie Software": "Free software",
    "QLInux steht unter der GNU General Public License, Version 3 oder später (GPL-3.0-or-later).": (
        "QLInux is released under the GNU General Public License, version 3 or "
        "later (GPL-3.0-or-later)."
    ),
    "Lizenztext": "License text",
    "Dank an": "Thanks to",
    "Druckerbefehle, Band- und Modellmaße": (
        "Printer commands, label and model sizes"
    ),
    "Oberfläche (Fenster, Canvas, Sheets)": (
        "User interface (windows, canvas, sheets)"
    ),
    "Fredrik Lundh und Mitwirkende": "Fredrik Lundh and contributors",
    "Rendering und Rasterdaten": "Rendering and raster data",
    "Wander Lairson Costa und Mitwirkende": (
        "Wander Lairson Costa and contributors"
    ),
    "USB-Anschluss": "USB connection",
    "Lincoln Loop und Mitwirkende": "Lincoln Loop and contributors",
    "QR-Codes": "QR codes",
    "Thorsten Weimann und Mitwirkende": "Thorsten Weimann and contributors",
    "Barcodes": "Barcodes",
    "Entwickelt von": "Developed by",
    "Quelltext und Fehler melden": "Source code and bug reports",
    "Version": "Version",
    "{panel} einklappen ({shortcut})": "Collapse {panel} ({shortcut})",
    "{panel} ausklappen ({shortcut})": "Expand {panel} ({shortcut})",
    # -- Werkzeuge ----------------------------------------------------------
    "Text": "Text",
    "Bild": "Image",
    "Barcode": "Barcode",
    "QR-Code": "QR code",
    "Linie": "Line",
    "Rahmen": "Frame",
    "Text einfügen": "Insert text",
    "Text einfügen (Doppelklick auf den Canvas)": (
        "Insert text (double-click on the canvas)"
    ),
    "Bild einfügen": "Insert image",
    "Barcode einfügen": "Insert barcode",
    "QR-Code einfügen": "Insert QR code",
    "Linie einfügen": "Insert line",
    "Rahmen einfügen": "Insert frame",
    "Tabelle einfügen": "Insert table",
    "Zeile darüber": "Row above",
    "Spalte links": "Column to the left",
    "Zeile löschen": "Delete row",
    "Spalte löschen": "Delete column",
    "Zellen verbinden": "Merge cells",
    "Umschalt-Klick markiert mehrere Zellen": "Shift-click selects several cells",
    "Verbindung aufheben": "Unmerge cells",
    "Höhen verteilen": "Distribute heights",
    "Breiten verteilen": "Distribute widths",
    "Feste Tabellengröße": "Fixed table size",
    "Feste Größe: eine Spalte oder Zeile wächst auf Kosten der Nachbarn": (
        "Fixed size: a column or row grows at the expense of its neighbours"
    ),
    "Füllung": "Fill",
    "Keine Füllung": "No fill",
    "Schwarz": "Black",
    "Hellgrau": "Light grey",
    "Grau": "Grey",
    "Dunkelgrau": "Dark grey",
    "Waagerecht": "Horizontal",
    "Senkrecht": "Vertical",
    "Diagonal": "Diagonal",
    "Kreuz": "Cross",
    "Punktmuster": "Dot pattern",
    "Linienart": "Line style",
    "Durchgezogen": "Solid",
    "Gestrichelt": "Dashed",
    "Gepunktet": "Dotted",
    "Keine Linie": "No line",
    "Textausrichtung": "Text alignment",
    "Linksbündig": "Align left",
    "Zentriert": "Centered",
    "Rechtsbündig": "Align right",
    "Blocksatz": "Justify",
    "Oben": "Top",
    "Mitte": "Middle",
    "Unten": "Bottom",
    "Unterstrichen": "Underline",
    "Zeilenhöhe": "Row height",
    "Spaltenbreite": "Column width",
    "Mehrere Zellen": "Multiple cells",
    "Bild…": "Image…",
    "Barcode…": "Barcode…",
    "QR-Code…": "QR code…",
    "Bild wählen": "Choose image",
    "Bilder (*.png *.webp *.jpg *.jpeg *.bmp *.gif);;Alle Dateien (*)": (
        "Images (*.png *.webp *.jpg *.jpeg *.bmp *.gif);;All files (*)"
    ),
    "Inhalt": "Content",
    "Symbologie": "Symbology",
    "In den Vordergrund": "Bring to front",
    "In den Hintergrund": "Send to back",
    "Eine Ebene nach vorn": "Bring forward",
    "Eine Ebene nach hinten": "Send backward",
    "An Hilfslinien ausrichten": "Align to guides",
    "Layout": "Layout",
    "Löschen": "Delete",
    "Kopieren": "Copy",
    "Ausschneiden": "Cut",
    "Duplizieren": "Duplicate",
    "Kopieren (Strg+C)": "Copy (Ctrl+C)",
    "Ausschneiden (Strg+X)": "Cut (Ctrl+X)",
    "Duplizieren (Strg+D)": "Duplicate (Ctrl+D)",
    "Strg+Ziehen": "Ctrl+drag",
    "Ausgewähltes Objekt duplizieren": "Duplicate the selected object",
    "Löschen (Entf)": "Delete (Del)",
    # -- Zoom und Vorschau --------------------------------------------------
    "Zoom 100 %": "Zoom 100 %",
    "1:1": "1:1",
    "Zoom {percent} %": "Zoom {percent} %",
    "Mausrad scrollt – Strg + Mausrad (oder Zoomgeste) zoomt": (
        "Mouse wheel scrolls - Ctrl + wheel (or a pinch gesture) zooms"
    ),
    "· Vorschau: 1:1 für Details (Strg+1)": "· Preview: 1:1 for detail (Ctrl+1)",
    "Einpassen": "Fit",
    "Shift: 15°-Schritte": "Shift: 15° steps",
    "Strg+Klick: zur Auswahl hinzufügen": "Ctrl+click: add to selection",
    "Strg+Rad: zoomen": "Ctrl+wheel: zoom",
    "Zoom: Einpassen (Ctrl+0)": "Zoom: fit (Ctrl+0)",
    "Vergrößern": "Zoom in",
    "Vergrößern (Strg ++)": "Zoom in (Ctrl ++)",
    "Verkleinern": "Zoom out",
    "Verkleinern (Strg +-)": "Zoom out (Ctrl +-)",
    "Zoom 1:1 (Strg+1) - echte Druckpunkte,\nso wie der Drucker sie setzt": (
        "Zoom 1:1 (Ctrl+1) - real print dots,\nexactly as the printer places them"
    ),
    "Druckvorschau": "Print preview",
    "Druckvorschau: echte 1-bit-Ausgabe (Ctrl+Shift+P)": (
        "Print preview: real 1-bit output (Ctrl+Shift+P)"
    ),
    "Druckvorschau aktiv - echte 1-bit-Ausgabe bei 1:1 (Esc beendet)": (
        "Print preview active - real 1-bit output at 1:1 (Esc exits)"
    ),
    "Druckvorschau aus": "Print preview off",
    # -- Druckerauswahl -----------------------------------------------------
    "Drucker": "Printer",
    "Modell": "Model",
    "Anschluss": "Connection",
    "Netzwerk": "Network",
    "USB": "USB",
    "Netzwerkdrucker": "Network printer",
    "Zugriff": "Access",
    "Zugriff einrichten": "Set up access",
    "Band": "Label",
    "Band erkennen": "Detect label",
    "Gerät": "Device",
    "manuell": "manual",
    "IP-Adresse von Hand eintragen, wenn die Suche den Drucker nicht findet.": (
        "Enter the IP address by hand if the search does not find the printer."
    ),
    "Per IP-Adresse hinzufügen…": "Add by IP address…",
    "Suche läuft …": "Searching …",
    "Netzwerk wird durchsucht …": "Searching the network …",
    "Kein Drucker gefunden.": "No printer found.",
    "Kein Drucker gewählt.": "No printer selected.",
    "Gespeicherten Drucker nicht gefunden, {host} gewählt.": (
        "Saved printer not found, selected {host}."
    ),
    "Gleicher Drucker, Port {port}.": "Same printer, port {port}.",
    "Drucker gefunden": "Printer found",
    "Das Etikett ist für {label_model} ausgelegt, gefunden wurde {printer_model}. Band und Ränder bleiben, wenn du das Etikett behältst.": (
        "This label is laid out for {label_model}; the printer that was found is a {printer_model}. "
        "Tape and margins stay as they are if you keep the label."
    ),
    "Etikett behalten": "Keep label",
    "An den Drucker anpassen": "Match the printer",
    "Abbrechen": "Cancel",
    "Öffnen": "Open",
    "Speichern": "Save",
    "Datei": "File",
    "Öffnen…": "Open…",
    "Neu": "New",
    "Neues Etikett (Strg+N)": "New label (Ctrl+N)",
    "Reiter schließen": "Close tab",
    "Reiter schließen (Strg+W)": "Close tab (Ctrl+W)",
    "Etikett schließen": "Close label",
    "Verwerfen": "Discard",
    "Änderungen an „{name}“ speichern?": "Save changes to “{name}”?",
    "Etikett bereits geöffnet: {name}": "Label already open: {name}",
    "Etikett öffnen (Strg+O)": "Open label (Ctrl+O)",
    "Etikett speichern (Strg+S)\nPfeil: Speichern unter… (Strg+Umschalt+S)": (
        "Save label (Ctrl+S)\nArrow: Save as… (Ctrl+Shift+S)"
    ),
    "Speichern unter…": "Save as…",
    "Etikett unter neuem Namen speichern (Strg+Umschalt+S)": (
        "Save label under a new name (Ctrl+Shift+S)"
    ),
    "Unbenannt": "Untitled",
    "Etikett öffnen": "Open label",
    "Etikett speichern": "Save label",
    "QLInux-Etiketten (*{suffix})": "QLInux labels (*{suffix})",
    "Alle Etiketten (*{suffix} *{lbx});;QLInux-Etiketten (*{suffix});;Brother P-touch (*{lbx})": (
        "All labels (*{suffix} *{lbx});;QLInux labels (*{suffix});;Brother P-touch (*{lbx})"
    ),
    "Etikett geöffnet: {name}": "Label opened: {name}",
    "Importiert: {name}": "Imported: {name}",
    "Brother P-touch": "Brother P-touch",
    "{path} ist keine Brother-P-touch-Datei: {error}": (
        "{path} is not a Brother P-touch file: {error}"
    ),
    "{path} enthält kein label.xml.": "{path} does not contain label.xml.",
    "{path} enthält kein Etikett.": "{path} does not contain a label.",
    "Tabelle": "Table",
    "Zelle": "Cell",
    "Datenbankfeld": "Database field",
    "CSV zur Datenbank nicht gefunden: {path}": "Database CSV not found: {path}",
    "CSV zur Datenbank nicht gefunden.": "Database CSV not found.",
    "CSV zur Datenbank nicht lesbar: {error}": "Database CSV could not be read: {error}",
    "Kabelvorlage": "Cable template",
    "Datum/Uhrzeit": "Date/time",
    "Aktuelles Datum und aktuelle Uhrzeit einfügen": "Insert the current date and time",
    "Anzeige": "Display",
    "Datum": "Date",
    "Uhrzeit": "Time",
    "Beides": "Both",
    "Datumsformat": "Date format",
    "Uhrzeitformat": "Time format",
    "Aktuell": "Current",
    "Zeigt die jetzige Zeit und übernimmt sie auch beim Drucken.": (
        "Shows the current time and uses it when printing too."
    ),
    "Versatz": "Offset",
    "Nach": "After",
    "Vor": "Before",
    "Minuten": "Minutes",
    "Stunden": "Hours",
    "Tage": "Days",
    "Wochen": "Weeks",
    "Monate": "Months",
    "Jahre": "Years",
    "Januar": "January",
    "Februar": "February",
    "März": "March",
    "April": "April",
    "Mai": "May",
    "Juni": "June",
    "Juli": "July",
    "August": "August",
    "September": "September",
    "Oktober": "October",
    "November": "November",
    "Dezember": "December",
    "Montag": "Monday",
    "Dienstag": "Tuesday",
    "Mittwoch": "Wednesday",
    "Donnerstag": "Thursday",
    "Freitag": "Friday",
    "Samstag": "Saturday",
    "Sonntag": "Sunday",
    "Clip Art": "Clip art",
    "Clip Art einfügen": "Insert clip art",
    "Symbol": "Symbol",
    "Austauschen…": "Replace…",
    "Seitenverhältnis festhalten": "Keep aspect ratio",
    "Kategorie": "Category",
    "Alle": "All",
    "Hinweise": "Signs",
    "Pfeile": "Arrows",
    "Formen": "Shapes",
    "Alltag": "Everyday",
    "Achtung": "Caution",
    "Info": "Info",
    "Verbot": "Prohibited",
    "Haken": "Check",
    "Raute": "Diamond",
    "Pfeil hoch": "Arrow up",
    "Pfeil runter": "Arrow down",
    "Eckpfeil": "Corner arrow",
    "Herz": "Heart",
    "Plus": "Plus",
    "Kreis": "Circle",
    "Ring": "Ring",
    "Blitz": "Bolt",
    "Haus": "Home",
    "Schloss": "Lock",
    "Telefon": "Phone",
    "Brief": "Envelope",
    "Schlüssel": "Key",
    "Uhr": "Clock",
    "Zahnrad": "Gear",
    "Flamme": "Flame",
    "Tropfen": "Drop",
    "Blatt": "Leaf",
    "Glocke": "Bell",
    "Zeichnung": "Drawing",
    "Nicht übernommen: {kind} ({count}×)": "Not imported: {kind} ({count}×)",
    "Nicht übernommen: {kind}": "Not imported: {kind}",
    "Nicht übernommen: {kind} – {recovered} enthaltene Objekte übernommen": (
        "Not imported: {kind} – kept {recovered} objects inside it"
    ),
    "Bildzuschnitt nicht übernommen: {name}": "Image crop not imported: {name}",
    "Zweifarbiges Etikett – Rot wird nicht übernommen.": (
        "Two-colour label – red is not imported."
    ),
    "Kein passendes Band für {size} mm – {name} wird verwendet.": (
        "No matching tape for {size} mm – using {name}."
    ),
    "Bild ohne Datei – nicht übernommen.": "Image without a file – not imported.",
    "Bild {name} konnte nicht gelesen werden: {error}": (
        "Could not read image {name}: {error}"
    ),
    "Etikett gespeichert: {name}": "Label saved: {name}",
    "Konnte {path} nicht speichern: {error}": "Could not save {path}: {error}",
    "Konnte {path} nicht lesen: {error}": "Could not read {path}: {error}",
    "{path} ist kein QLInux-Dokument: {error}": (
        "{path} is not a QLInux document: {error}"
    ),
    "{path} ist kein QLInux-Dokument.": "{path} is not a QLInux document.",
    "{path} ist kein QLInux-Dokument: Objektliste fehlt.": (
        "{path} is not a QLInux document: no list of objects."
    ),
    "Unbekanntes Format ({number}) - bitte mit einer neueren QLInux-Fassung öffnen.": (
        "Unknown format ({number}) – please open it with a newer QLInux version."
    ),
    "CSV ist nicht UTF-8: {error}": "CSV is not UTF-8: {error}",
    "CSV ist leer.": "CSV is empty.",
    "CSV hat keine Spaltennamen.": "CSV has no column names.",
    "CSV hat leere Spaltennamen.": "CSV has empty column names.",
    "CSV hat doppelte Spaltennamen.": "CSV has duplicate column names.",
    "CSV-Pfad fehlt.": "CSV path is missing.",
    # -- Vorlagen (Beispieltexte der eingebauten Vorlagen) -------------------
    "Adressetikett": "Address label",
    "Paketmarke": "Parcel label",
    "Kabel": "Cable",
    "Ordnerrücken": "Folder spine",
    "Preisschild": "Price tag",
    "WLAN-QR": "WiFi QR",
    "Inventar": "Inventory",
    "Absender: Firma Muster, Musterweg 1": "Sender: Sample Ltd, 1 Sample Road",
    "Empfänger": "Recipient",
    "Vorname Nachname": "First name Surname",
    "Straße 12": "12 Sample Street",
    "12345 Stadt": "12345 Sample Town",
    "An": "To",
    "12345 Stadt, Straße 12": "12345 Sample Town, 12 Sample Street",
    "Kabel 12": "Cable 12",
    "Patchfeld A → Switch 3": "Patch panel A → Switch 3",
    "Aktenzeichen 2026-01": "Reference 2026-01",
    "Rechnungen": "Invoices",
    "bis 31.12.2026": "until 2026-12-31",
    "9,90 €": "9.90 €",
    "inkl. MwSt.": "incl. VAT",
    "WLAN": "WiFi",
    "MeinWLAN": "MyNetwork",
    "Passwort: geheim": "Password: secret",
    "Vorlage braucht einen Namen.": "A template needs a name.",
    "Vorlagen": "Templates",
    "Vorlage laden": "Load template",
    "Vorlage anlegen: {name}": "Create label from template: {name}",
    "Vorlage angelegt: {name}": "Created from template: {name}",
    "Vorlage geöffnet: {name}": "Template opened: {name}",
    "Eigene Vorlage öffnen": "Open your own template",
    "Als Vorlage speichern…": "Save as template…",
    "Als Vorlage speichern": "Save as template",
    "Das aktuelle Etikett als Vorlage ablegen": (
        "Store the current label as a template"
    ),
    "Name der Vorlage:": "Template name:",
    "Vorlage gespeichert: {name}": "Template saved: {name}",
    "Keine Netzwerk-Drucker gefunden.": "No network printers found.",
    "Netzwerk nach Druckern durchsuchen (mDNS und SNMP).": (
        "Search the network for printers (mDNS and SNMP)."
    ),
    "Gefundene Netzwerk-Drucker. Die Auswahl setzt IP-Adresse und – "
    "wenn das Gerät sein Modell meldet – auch das Modell.": (
        "Found network printers. Choosing one sets the IP address and - "
        "if the device reports its model - the model as well."
    ),
    "gefunden über {source}": "found via {source}",
    "{count} Netzwerk-Drucker gefunden": "{count} network printers found",
    "Netzwerk-Drucker gefunden: {device}": "Network printer found: {device}",
    "USB suchen": "Search USB",
    "Kein USB-Drucker gefunden": "No USB printer found",
    "Kein USB-Drucker gefunden. Kabel und Strom prüfen.": (
        "No USB printer found. Check the cable and power."
    ),
    "Bitte Gerät wählen": "Please choose a device",
    "– nicht angeschlossen": "– not connected",
    "Kernel-Anschluss": "kernel device",
    "USB-Drucker übernommen: {device}": "USB printer selected: {device}",
    "{count} USB-Drucker gefunden": "{count} USB printers found",
    "bitte in der Liste wählen.": "please choose one from the list.",
    "Angeschlossene USB-Drucker suchen und in die Liste eintragen.": (
        "Look for attached USB printers and add them to the list."
    ),
    "Angeschlossene USB-Drucker. Die Auswahl setzt Adresse und – wenn sie sich aus der USB-Kennung ableiten lässt – auch das Modell.": (
        "Attached USB printers. Choosing one sets the address and - when it can "
        "be derived from the USB ID - the model as well."
    ),
    "Richtet eine udev-Regel ein, die den USB-Drucker für dich freigibt (das System fragt nach dem Passwort).": (
        "Sets up a udev rule that unlocks the USB printer for you (the system "
        "asks for your password)."
    ),
    "Band am Drucker erfragen (Statusabfrage).": (
        "Ask the printer for the label (status query)."
    ),
    "IP-Adresse oder Name des Druckers, z. B. 192.168.178.62.\nDer Druckport {port} wird automatisch ergänzt; ein anderer Port geht als 192.168.178.62:9101.": (
        "IP address or name of the printer, e.g. 192.168.178.62.\n"
        "Port {port} is added automatically; another port works as "
        "192.168.178.62:9101."
    ),
    "Drucker im Netzwerk (WLAN/LAN).\nEs genügt die IP-Adresse - der Druckport {port} wird automatisch ergänzt.": (
        "Printer on the network (WLAN/LAN).\n"
        "The IP address is enough - port {port} is added automatically."
    ),
    "Drucker am USB-Kabel.\n„Suchen“ liest die angeschlossenen Geräte ein; nur über USB geht auch die Band-Erkennung.": (
        "Printer on the USB cable.\n"
        "“Search” reads the attached devices; only over USB does label "
        "detection work."
    ),
    "Keine Druckeradresse": "No printer address",
    "Im Panel unter „Drucker“ Anschluss und Adresse wählen.": (
        "In the panel under “Printer”, choose a connection and an address."
    ),
    # -- Band, Laenge, Margins ----------------------------------------------
    "Länge": "Length",
    "Länge": "Length",
    "Automatische Länge": "Automatic length",
    "Farbe": "Color",
    "schwarz": "black",
    "rot": "red",
    "schwarz/rot": "black/red",
    "(schwarz/rot)": "(black/red)",
    "Ausrichtung": "Orientation",
    "Quer zum Band": "Across the tape",
    "Längs des Bandes": "Along the tape",
    "quer zum Band": "across the tape",
    "längs des Bandes": "along the tape",
    "Ausrichtung: quer zum Band\nDer Inhalt läuft über die Bandbreite; die Länge ergibt sich aus der Inhaltshöhe (spart Band bei langen, flachen Inhalten).": (
        "Orientation: across the tape\n"
        "The content runs across the tape width; the length follows the content "
        "height (saves tape with long, flat content)."
    ),
    "Ausrichtung: längs des Bandes\nDer Inhalt läuft in Bandrichtung; die Länge ergibt sich aus der Inhaltsbreite (spart Band bei hohen, mehrzeiligen Inhalten).": (
        "Orientation: along the tape\n"
        "The content runs along the tape; the length follows the content width "
        "(saves tape with tall, multi-line content)."
    ),
    "mm": "mm",
    "{value} mm": "{value} mm",
    "Ränder (mm)": "Margins (mm)",
    "links": "left",
    "rechts": "right",
    "oben": "top",
    "unten": "bottom",
    "{width} mm {kind}": "{width} mm {kind}",
    "{width} x {height} mm {kind}": "{width} x {height} mm {kind}",
    "Endlos": "Continuous",
    "Die-cut": "Die-cut",
    "Rund (Die-cut)": "Round (die-cut)",
    # -- Inspector ----------------------------------------------------------
    "Nichts ausgewählt": "Nothing selected",
    "Schrift": "Font",
    "Fett": "Bold",
    "Kursiv": "Italic",
    "Größe (px)": "Size (px)",
    "Drehung": "Rotation",
    "Breite": "Width",
    "Höhe": "Height",
    "Größe (Dots)": "Size (dots)",
    "Höhe (Dots)": "Height (dots)",
    "X": "X",
    "Y": "Y",
    "Linienbreite": "Line width",
    "Gefüllt": "Filled",
    "Invertiert": "Inverted",
    "Textausrichtung": "Text alignment",
    "Umbruch": "Wrap",
    "Unterstrichen": "Underlined",
    "Durchgestrichen": "Strikethrough",
    "Zeichenabstand": "Letter spacing",
    "Zeilenabstand": "Line spacing",
    "Aufzählung": "List",
    "Keine": "None",
    "Punkte": "Bullets",
    "Nummern": "Numbers",
    "Textrichtung": "Text direction",
    "Horizontal": "Horizontal",
    "Vertikal": "Vertical",
    "Links": "Left",
    "Mitte": "Center",
    "Rechts": "Right",
    "Oben": "Top",
    "Unten": "Bottom",
    "Vertikal ausrichten": "Vertical alignment",
    "Breite automatisch": "Automatic width",
    "Höhe automatisch": "Automatic height",
    "Form": "Shape",
    "Ellipse": "Ellipse",
    "Dreieck": "Triangle",
    "Stern": "Star",
    "Pfeil rechts": "Arrow right",
    "Pfeil links": "Arrow left",
    "Doppelpfeil": "Double arrow",
    "Formen einfügen": "Insert shapes",
    "Klartext": "Plain text",
    "Objekt": "Object",
    # -- Druckoptionen ------------------------------------------------------
    "Drucken": "Print",
    "Druckvorschau, Einstellungen und Verlauf": "Print preview, settings and history",
    "Druckdialog": "Print dialog",
    "Druckdialog (Ctrl+P)": "Print dialog (Ctrl+P)",
    "Druckverlauf anzeigen": "Show print history",
    "Druckverlauf dieser Sitzung anzeigen": "Show print history of this session",
    "Druckverlauf": "Print history",
    "Zeit": "Time",
    "Status": "Status",
    "Schließen": "Close",
    "Gedruckt": "Printed",
    "An Drucker gesendet": "Sent to printer",
    "Drucker meldet einen Fehler": "Printer reports an error",
    "Nicht gesendet": "Not sent",
    "Auflösung": "Resolution",
    "Tintenmenge": "Ink amount",
    "Tintenmenge (ohne Wirkung)": "Ink amount (no effect)",
    "Graustufen (Dithering)": "Grayscale (dithering)",
    "Hohe Druckqualität (HQ)": "High print quality (HQ)",
    "Kopien": "Copies",
    "Wie oft jedes Etikett gedruckt wird - identische Kopien in einem Auftrag.": (
        "How many times each label is printed - identical copies in one job."
    ),
    "Zuschnitt": "Cutting",
    "Jede Kopie": "Each copy",
    "Am Ende": "At end",
    "Aus": "Off",
    "Nach jeder Kopie: einzelne Etiketten.\nNur am Ende: die Etiketten hängen zusammen und werden zuletzt getrennt - nur bei mehreren Etiketten.\nNicht schneiden: der Streifen bleibt am Band.": (
        "After each copy: separate labels.\n"
        "Only at the end: the labels stay together and are separated last - "
        "only with more than one label.\n"
        "Do not cut: the strip stays attached to the tape."
    ),
    "Welche Datensätze gedruckt werden: die gewählte Zeile, alle oder ein Bereich. Ohne CSV bleibt es ein Etikett.": (
        "Which records to print: the selected row, all of them, or a range. "
        "Without a CSV it stays one label."
    ),
    "Ausgewählte Datensätze": "Selected Record(s)",
    "Die in der Tabelle gewählten Zeilen (Strg/Umschalt für mehrere).": (
        "The rows selected in the table (Ctrl/Shift for several)."
    ),
    "Alle Datensätze": "All Records",
    "Jede Zeile der verbundenen CSV.": "Every row of the connected CSV.",
    "Datensatzbereich": "Record Range",
    "Von–bis, 1 ist die erste Zeile, beide Grenzen zählen.": (
        "From–to; 1 is the first row, and both ends count."
    ),
    "Von": "From",
    "Erster Datensatz, 1 ist die erste Zeile.": (
        "First record; 1 is the first row."
    ),
    "Bis": "To",
    "Letzter Datensatz, einschließlich.": "Last record, inclusive.",
    "Sende {count} Etiketten an {address}…": (
        "Sending {count} labels to {address}…"
    ),
    "Tinte: –": "Ink: –",
    "Tinte: {value} %": "Ink: {value} %",
    "600 dpi nur in Bandlaufrichtung; quer bleiben es 300 dpi.": (
        "600 dpi only along the tape; across it stays 300 dpi."
    ),
    "Auch möglich: 300 × 600 dpi (feiner längs, druckt langsamer).": (
        "Also available: 300 × 600 dpi (finer along the tape, prints slower)."
    ),
    "{model}: 300 × 300 dpi - mehr kann dieser Druckkopf nicht.": (
        "{model}: 300 × 300 dpi - that is all this print head can do."
    ),
    "Ohne HQ druckt der Drucker schneller.": "Without HQ the printer is faster.",
    "{label}: {detail}.": "{label}: {detail}.",
    "Standard des Druckkopfs - quer und in Bandlaufrichtung 300 dpi": (
        "Print head default - 300 dpi across and along the tape"
    ),
    "High-Resolution-Modus: quer 300 dpi, in Bandlaufrichtung 600 dpi - feinere Zeilen, druckt langsamer": (
        "High-resolution mode: 300 dpi across, 600 dpi along the tape - finer "
        "lines, prints slower"
    ),
    "Der Drucker arbeitet dann mit Vorrang für Qualität statt Tempo (das pquality-Flag aus der Brother-Rasterreferenz).\nDie Auflösung ändert das nicht - die steht im Feld darüber.": (
        "The printer then favours quality over speed (the pquality flag from "
        "Brother's raster reference).\n"
        "The resolution does not change - that is the field above."
    ),
    "Graustufen werden gepunktet statt hart geschwellt - für Fotos.\nOhne Dithering entscheidet die Tintenmenge unten, welche Helligkeit Tinte wird.": (
        "Grays are dotted instead of hard-thresholded - for photos.\n"
        "Without dithering the ink amount below decides which brightness "
        "becomes ink."
    ),
    "Wie viel Tinte der Drucker setzt.\n\nDer Drucker kennt nur Schwarz oder Weiß: jede weiche Kante und jeder Grauton\nim Design muss zu einem von beidem werden. Die Tintenmenge ist der Schnitt:\n70 % (Standard) = alles ab etwa 30 % Schwärze wird Tinte - gut für Text.\nhöher = mehr Tinte: auch hellgraue Ränder werden schwarz, die Schrift wird\nkräftiger und etwas breiter.\nniedriger = weniger Tinte: nur dunkle Punkte werden schwarz, feiner - dünne\nStriche können ausfransen.\nEinstellbar von {low} % (fein) bis {high} % (kräftig).\nWirkt nur ohne Dithering.": (
        "How much ink the printer lays down.\n\n"
        "The printer only knows black or white: every soft edge and every gray\n"
        "in the design has to become one of the two. The ink amount is the cut:\n"
        "70 % (default) = everything from about 30 % blackness becomes ink - "
        "good for text.\n"
        "higher = more ink: even light gray edges turn black, the type becomes\n"
        "heavier and slightly wider.\n"
        "lower = less ink: only dark dots turn black, finer - thin strokes may\n"
        "fray.\n"
        "Adjustable from {low} % (fine) to {high} % (strong).\n"
        "Only takes effect without dithering."
    ),
    "Anteil der bedruckten Fläche - sofort sichtbar, was Tintenmenge und Dithering bewirken.": (
        "Share of the printed area - shows at once what ink amount and dithering "
        "do."
    ),
    # -- Meldungen ----------------------------------------------------------
    "Rendern": "Rendering",
    "Etikett konnte nicht gerendert werden:\n{error}": (
        "The label could not be rendered:\n{error}"
    ),
    "Renderfehler: {error}": "Render error: {error}",
    "Unerwarteter Fehler: {error}": "Unexpected error: {error}",
    "Abfrage fehlgeschlagen:\n{error}": "Query failed:\n{error}",
    "Band erkannt: {name}": "Label detected: {name}",
    "Kein Band gemeldet. Bitte von Hand wählen.": (
        "No label reported. Please choose one manually."
    ),
    "Kein Zugriff auf den USB-Drucker.\nIm Panel unter „Drucker“: „Zugriff einrichten“.": (
        "No access to the USB printer.\n"
        "In the panel under “Printer”: “Set up access”."
    ),
    "Kein Zugriff auf {address}.": "No access to {address}.",
    "Sende an {address}…": "Sending to {address}…",
    "Sende {count} Kopien an {address}…": "Sending {count} copies to {address}…",
    "Druckauftrag gesendet (outcome={outcome}).": (
        "Print job sent (outcome={outcome})."
    ),
    "Druck fehlgeschlagen.": "Printing failed.",
    "Druckfehler": "Print error",
    "USB-Zugriff": "USB access",
    "{model} (USB)": "{model} (USB)",
    "USB-Zugriff eingerichtet – der Drucker ist freigegeben.": (
        "USB access set up - the printer is unlocked."
    ),
    "Zugriff einrichten: Passwort-Dialog …": "Setting up access: password prompt …",
    "Zugriff einrichten: Rechte werden geprüft …": (
        "Setting up access: checking permissions …"
    ),
    "Rechte noch nicht aktiv – Drucker kurz ab- und anstecken.": (
        "Permissions not active yet - unplug and replug the printer briefly."
    ),
    "Kein Passwort-Dialog erschienen.": "No password prompt appeared.",
    "Kein Passwort-Dialog (polkit-Agent) vorhanden.": (
        "No password prompt (polkit agent) available."
    ),
    "Kein Passwort-Dialog (polkit-Agent) vorhanden.\n\nEinmalig im Terminal:\n\n    {command}": (
        "No password prompt (polkit agent) available.\n\n"
        "Once in a terminal:\n\n    {command}"
    ),
    "Regel ist schon eingerichtet – Drucker kurz ab- und anstecken.": (
        "The rule is already in place - unplug and replug the printer briefly."
    ),
    "{reason}\n\nEinmalig im Terminal ausführen:\n\n    {command}": (
        "{reason}\n\nRun once in a terminal:\n\n    {command}"
    ),
    "Abgebrochen.": "Cancelled.",
    "Der Helfer für die udev-Regel fehlt.": "The helper for the udev rule is missing.",
    "pkexec (polkit) ist nicht installiert.": "pkexec (polkit) is not installed.",
    "Einrichten fehlgeschlagen (Code {code}).": "Setup failed (code {code}).",
    "Einrichten fehlgeschlagen (Code {code}):\n\n{error}": (
        "Setup failed (code {code}):\n\n{error}"
    ),
    "Einrichten fehlgeschlagen:\n\n{error}": "Setup failed:\n\n{error}",
    "unbekannter Fehler": "unknown error",
    "Fehlende Rechte am USB-Drucker.\nIm Panel unter „Drucker“: „Zugriff einrichten“.": (
        "Missing permissions for the USB printer.\n"
        "In the panel under “Printer”: “Set up access”."
    ),
    # -- Fehler aus der Druck-/Render-Schicht --------------------------------
    "Unbekanntes Druckermodell: {model!r}": "Unknown printer model: {model!r}",
    "Bildbreite {width} px != {expected} px (Band {label!r}, Faktor {scale}). Bitte ueber den Renderer erzeugen.": (
        "Image width {width} px != {expected} px (label {label!r}, factor "
        "{scale}). Please create it through the renderer."
    ),
    "Bildhöhe {height} px != {expected} px (Band {label!r}, Faktor {scale}). Bitte ueber den Renderer erzeugen.": (
        "Image height {height} px != {expected} px (label {label!r}, factor "
        "{scale}). Please create it through the renderer."
    ),
    "libusb": "libusb",
    "Rotdruck ist mit Band {label!r} ({name}) nicht moeglich.": (
        "Red printing is not possible with label {label!r} ({name})."
    ),
    "Modell {model!r} unterstuetzt keinen Rotdruck.": (
        "Model {model!r} does not support red printing."
    ),
    "Konvertierung fehlgeschlagen: {error}": "Conversion failed: {error}",
    "Kopienzahl muss mindestens 1 sein.": "There has to be at least one copy.",
    "Höchstens {max} Kopien pro Auftrag.": "At most {max} copies per job.",
    "Höchstens {max} Seiten pro Auftrag (Datensätze × Serie × Kopien).": (
        "At most {max} pages per job (records × serial × copies)."
    ),
    "Keine Etiketten zum Drucken.": "No labels to print.",
    "Keine Datensätze im Druckbereich.": "No records in the print range.",
    "Unbekannter Druckbereich: {scope!r}.": "Unknown print range: {scope!r}.",
    "Datensatzbereich braucht ganze Zahlen.": "Record range needs whole numbers.",
    "Barcode '{value}' lässt sich nicht drucken.": (
        "Barcode '{value}' cannot be printed."
    ),
    "Unbekannter Zuschnitt: {mode!r}": "Unknown cutting: {mode!r}",
    "Modell {model!r} hat keine Schneideeinrichtung - Zuschnitt auf „{none}“ stellen.": (
        "Model {model!r} has no cutter - set cutting to “{none}”."
    ),
    "Senden fehlgeschlagen: {error}": "Sending failed: {error}",
    "Drucker {address!r} nicht erreichbar: {error}": (
        "Printer {address!r} not reachable: {error}"
    ),
    "Unbekanntes Band: {label!r}": "Unknown label: {label!r}",
    "Unbekanntes Modell: {model!r}": "Unknown model: {model!r}",
    "QImage ist leer (isNull).": "QImage is empty (isNull).",
    "Ungueltige Canvas-Groesse: {width} x {height} Dots.": (
        "Invalid canvas size: {width} x {height} dots."
    ),
    "sceneRect der Szene ist leer oder ungueltig.": (
        "The scene's sceneRect is empty or invalid."
    ),
    "Bildbreite {width} px entspricht nicht der Bandbreite {expected} px (Band {label!r}, Faktor {scale}). Das wuerde brother_ql zum Resize zwingen.": (
        "Image width {width} px does not match the tape width {expected} px "
        "(label {label!r}, factor {scale}). That would force brother_ql to "
        "resize."
    ),
    # -- Objekte ------------------------------------------------------------
    "Bild konnte nicht geladen werden: {path}": "Image could not be loaded: {path}",
    "Barcode '{value}' ({symbology}): {error}": (
        "Barcode '{value}' ({symbology}): {error}"
    ),
    "Eingabe '{value}' passt nicht zur Symbologie - gedruckt würde '{full}'.": (
        "Input '{value}' does not fit the symbology - '{full}' would be printed."
    ),
    "Unbekannter Item-Typ: {kind!r}": "Unknown item type: {kind!r}",
    "Datenbank-Binding braucht einen Spaltennamen.": (
        "Database binding needs a column name."
    ),
    "Unbekannte Binding-Quelle: {source!r}.": (
        "Unknown binding source: {source!r}."
    ),
    # -- Datenbank-Merge (M2) -----------------------------------------------
    "Datenbank": "Database",
    "Keine CSV verbunden": "No CSV connected",
    "CSV": "CSV",
    "Text, Barcode oder QR auf das Etikett legen und den Spaltenkopf (○) darauf ziehen. Zeile wählen = Live-Vorschau.": (
        "Add text, a barcode or a QR code to the label, then drag a column header (○) "
        "onto it. Select a row for live preview."
    ),
    "Andere…": "Other…",
    "Trennen": "Disconnect",
    "Datensatz {current} / {total}": "Record {current} / {total}",
    "Auf Text, Barcode oder QR ziehen": "Drag onto text, barcode or QR",
    "CSV verbinden": "Connect CSV",
    "CSV verbinden…": "Connect CSV…",
    "CSV-Datei mit dem Etikett verbinden": "Connect a CSV file to the label",
    "Datenbank ein- oder ausblenden": "Show or hide the database",
    "CSV-Dateien (*.csv);;Alle Dateien (*)": "CSV files (*.csv);;All files (*)",
    "(keine)": "(none)",
    "Verbindung lösen": "Remove link",
    "Serie ist an diesem Objekt aktiv. Ein Datenbankfeld ersetzt die Serie.": (
        "Numbering is active on this object. A database field replaces it."
    ),
    "Schnappschuss aus der Datenbank. Ein Record-Wechsel überschreibt ihn; manuelles Ändern löst die Verbindung nicht.": (
        "Snapshot from the database. Changing the record overwrites it; "
        "editing by hand does not remove the link."
    ),
    "Serien-Index darf nicht negativ sein.": "Serial index must not be negative.",
    "Serien-Anzahl muss mindestens 1 sein.": "Serial count must be at least 1.",
    "Serie": "Numbering",
    "Start": "Start",
    "Anzahl": "Count",
    "Schritt": "Step",
    "Präfix": "Prefix",
    "Suffix": "Suffix",
    "Stellen": "Digits",
    "Führende Nullen; 0 lässt die Zahl, wie sie ist.": (
        "Leading zeros; 0 leaves the number as it is."
    ),
    "Datenbankfeld und Serie schließen sich an diesem Objekt aus.": (
        "A database field and numbering cannot both be used on this object."
    ),
    "Objekt {kind!r} unterstuetzt keinen Merge.": (
        "Object {kind!r} does not support merge."
    ),
    "CSV nicht geladen: {error}": "CSV not loaded: {error}",
    "CSV-Inhalt hat sich geändert (Hash weicht ab).": (
        "CSV content has changed (hash mismatch)."
    ),
}
