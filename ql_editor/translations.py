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
    "Panel links ein-/ausklappen (Strg+B)\nEingeklappt bleibt ein Streifen mit Pfeil; er klappt beim Überfahren über dem Canvas auf": (
        "Show/hide left panel (Ctrl+B)\n"
        "When hidden a strip with an arrow remains; it opens when the pointer "
        "moves over the canvas"
    ),
    "Panel rechts ein-/ausklappen (Strg+Shift+B)\nEigenschaften und Druckoptionen": (
        "Show/hide right panel (Ctrl+Shift+B)\nProperties and print options"
    ),
    "Menü": "Menu",
    "Sprache": "Language",
    "Einfügen": "Insert",
    "Bearbeiten": "Edit",
    "Etikett": "Label",
    "Ansicht": "View",
    "Drucken": "Print",
    "Beenden": "Quit",
    "Beenden (Strg+Q)": "Quit (Ctrl+Q)",
    "Über QLInux": "About QLInux",
    "QLInux - P-touch-Editor-Klon für Brother QL-820NWB\n\nBand- und Modellmaße: {labels} Bänder / {models} Modelle (dynamisch aus brother_ql)\nAuflösung: {dpi} dpi": (
        "QLInux - P-touch Editor clone for Brother QL printers\n\n"
        "Label and model sizes: {labels} labels / {models} models "
        "(read from brother_ql)\n"
        "Resolution: {dpi} dpi"
    ),
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
    "Bild…": "Image…",
    "Barcode…": "Barcode…",
    "QR-Code…": "QR code…",
    "Bild wählen": "Choose image",
    "Bilder (*.png *.jpg *.jpeg *.bmp *.gif);;Alle Dateien (*)": (
        "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All files (*)"
    ),
    "Inhalt": "Content",
    "Symbologie": "Symbology",
    "In den Vordergrund": "Bring to front",
    "In den Hintergrund": "Send to back",
    "Löschen": "Delete",
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
    "Die Druckvorschau (Strg+Umschalt+P) zeigt die gewählte Auflösung in echten Druckpunkten.": (
        "The print preview (Ctrl+Shift+P) shows the chosen resolution in real "
        "print dots."
    ),
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
    "Handeingabe": "Manual entry",
    "IP-Adresse von Hand eintragen, wenn die Suche den Drucker nicht findet.": (
        "Enter the IP address by hand if the search does not find the printer."
    ),
    "Per IP-Adresse hinzufügen…": "Add by IP address…",
    "Suche läuft …": "Searching …",
    "Netzwerk wird durchsucht …": "Searching the network …",
    "Kein Drucker gefunden.": "No printer found.",
    "Kein Drucker gewählt.": "No printer selected.",
    "Abbrechen": "Cancel",
    "Öffnen": "Open",
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
    "Laenge": "Length",
    "Auto Length (Inhalt)": "Auto length (content)",
    "nur Inhalt": "content only",
    "Gesamtlänge (inkl. Rand)": "Total length (incl. margins)",
    "Bedeutung": "Meaning",
    "Ergebnis": "Result",
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
    "Nicht bedruckbar": "Not printable",
    "mm": "mm",
    "{value} mm": "{value} mm",
    "{mm} mm je Seite (schraffiert)": "{mm} mm per side (hatched)",
    "Margins (mm)": "Margins (mm)",
    "links": "left",
    "rechts": "right",
    "oben": "top",
    "unten": "bottom",
    "{width} mm {kind}": "{width} mm {kind}",
    "{width} x {height} mm {kind}": "{width} x {height} mm {kind}",
    "{width} x {height} mm Inhalt\n→ Etikett ~{total} mm": (
        "{width} x {height} mm content\n→ label ~{total} mm"
    ),
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
    "X (Dots)": "X (dots)",
    "Y (Dots)": "Y (dots)",
    "Linienbreite": "Line width",
    "Gefüllt": "Filled",
    "Klartext": "Plain text",
    "Objekt": "Object",
    # -- Druckoptionen ------------------------------------------------------
    "Druckoptionen": "Print options",
    "Drucken": "Print",
    "Drucken (Ctrl+P)": "Print (Ctrl+P)",
    "Auflösung": "Resolution",
    "Tintenmenge": "Ink amount",
    "Tintenmenge (ohne Wirkung)": "Ink amount (no effect)",
    "Graustufen (Dithering)": "Grayscale (dithering)",
    "Hohe Druckqualität (HQ)": "High print quality (HQ)",
    "Kopien": "Copies",
    "Wie oft dieses Etikett gedruckt wird - als ein Auftrag.": (
        "How many times this label is printed - as one job."
    ),
    "Zuschnitt": "Cutting",
    "Nach jeder Kopie": "After each copy",
    "Nur am Ende": "Only at the end",
    "Nicht schneiden": "Do not cut",
    "Nach jeder Kopie: einzelne Etiketten.\nNur am Ende: die Kopien hängen zusammen und werden zuletzt getrennt - nur bei mehreren Kopien.\nNicht schneiden: der Streifen bleibt am Band.": (
        "After each copy: separate labels.\n"
        "Only at the end: the copies stay together and are separated last - "
        "only with more than one copy.\n"
        "Do not cut: the strip stays attached to the tape."
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
    "Rotdruck ist mit Band {label!r} ({name}) nicht moeglich.": (
        "Red printing is not possible with label {label!r} ({name})."
    ),
    "Modell {model!r} unterstuetzt keinen Rotdruck.": (
        "Model {model!r} does not support red printing."
    ),
    "Konvertierung fehlgeschlagen: {error}": "Conversion failed: {error}",
    "Kopienzahl muss mindestens 1 sein.": "There has to be at least one copy.",
    "Höchstens {max} Kopien pro Auftrag.": "At most {max} copies per job.",
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
    "Unbekannter Item-Typ: {kind!r}": "Unknown item type: {kind!r}",
}
