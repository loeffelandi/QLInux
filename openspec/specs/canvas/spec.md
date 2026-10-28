# Zeichenfläche

## Purpose

Die Zeichenfläche trägt die Objekte, die Ränder, die Hilfslinien und die Bearbeitung. Hauptorte: `ql_editor/canvas.py`, `ql_editor/items.py`, `ql_editor/history.py`, `ql_editor/media.py`.

## Requirements

### Requirement: Objektarten

Die Zeichenfläche SHALL Text, Bilder, QR-Codes, Barcodes, Linien, Rechtecke, Formen, Tabellen, Datum/Uhrzeit und Clipart tragen. Verschieben, Skalieren, Drehen, Ausrichten, Umordnen, Undo und Redo MUST für die Gestaltung gelten.

#### Scenario: Undo stellt die Gestaltung zurück

- **WHEN** ein Objekt verschoben und Undo ausgelöst wird
- **THEN** steht die Gestaltung wieder so wie vor dem Verschieben

### Requirement: Ränder beginnen bei null

Nutzer-Ränder SHALL bei 0 mm beginnen. Vorschub und der nicht bedruckbare Streifen des Druckers MUST NOT als Nutzer-Rand gelten.

#### Scenario: Neues Etikett

- **WHEN** ein neues Etikett angelegt wird
- **THEN** stehen alle vier Nutzer-Ränder auf 0 mm

### Requirement: Ränder verschieben und kürzen

Links und oben SHALL die Objekte mitziehen, sodass ihr Abstand zum Rand bleibt, und den gestrichelten Rahmen mitbewegen. Bei automatischer Länge SHALL der untere Rand die Länge setzen, wenn das Band quer liegt, und der rechte Rand, wenn es längs liegt. Inhalt jenseits eines Randes MUST weder in der Vorschau noch im Druck erscheinen.

#### Scenario: Inhalt hinter dem Rand

- **WHEN** ein Objekt über den rechten Rand hinausragt
- **THEN** fehlt dieser Teil in Vorschau und Druck
- **AND** die Bandbreite bleibt unverändert

### Requirement: Schraffur ist die Druckzone

Die Schraffur auf der Zeichenfläche MUST die nicht bedruckbare Zone des Druckers markieren und MUST NOT den Bereich hinter einem Nutzer-Rand schraffieren.

#### Scenario: Rand ohne Schraffur

- **WHEN** ein Nutzer-Rand größer als 0 mm ist
- **THEN** bleibt die Fläche hinter diesem Rand unschraffiert
- **AND** der nicht bedruckbare Streifen des Druckers bleibt schraffiert

### Requirement: Hilfslinien und Einrasten

Eine Hilfslinie SHALL von oben aus dem Lineal nach unten oder von links aus dem Lineal nach rechts gezogen werden und SHALL durch Zurückziehen auf dasselbe Lineal wieder verschwinden. Hilfslinien MUST mit dem Etikett gespeichert werden. Verschieben und Skalieren SHALL an Hilfslinien, am Etikett und an anderen Objekten einrasten. Ein einzelnes Objekt SHALL sich am Randrahmen ausrichten, mehrere am gemeinsamen Auswahlrahmen.

#### Scenario: Hilfslinie bleibt in der Datei

- **WHEN** eine Hilfslinie gesetzt und das Etikett gespeichert und wieder geöffnet wird
- **THEN** liegt die Hilfslinie an derselben Position

### Requirement: Drehen

Ohne Shift SHALL eine Drehung an den nächsten 90 Grad kleben, bis der Zeiger sich deutlich davon entfernt. Mit Shift SHALL in 15-Grad-Schritten gedreht werden.

#### Scenario: Shift beim Drehen

- **WHEN** ein Objekt bei gehaltenem Shift gedreht wird
- **THEN** rastet der Winkel in 15-Grad-Schritten ein

### Requirement: Zusatztasten

Strg mit dem Mausrad und eine Zweifinger-Zoomgeste SHALL die Ansicht zoomen. Shift mit dem Mausrad SHALL waagerecht rollen. Strg-Klick SHALL ein Objekt zur Auswahl hinzufügen oder daraus entfernen. Strg-Ziehen SHALL das gewählte Objekt duplizieren und die Kopie verschieben. Pfeiltasten SHALL um einen Punkt verschieben, mit Shift um zehn. Die mittlere Maustaste SHALL die Ansicht verschieben.

#### Scenario: Strg-Ziehen

- **WHEN** ein gewähltes Objekt mit gehaltener Strg-Taste gezogen wird
- **THEN** bleibt das Original liegen
- **AND** die Kopie folgt dem Zeiger
