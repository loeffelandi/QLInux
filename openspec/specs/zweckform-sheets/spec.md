# Avery-Zweckform-Bögen

## Purpose

Dieselbe Gestaltung füllt einen Avery-Zweckform-Bogen und geht an einen normalen Drucker oder in ein PDF in echter Größe. Hauptorte: `ql_editor/stationery.py`, `ql_editor/sheet_output.py`.

## Requirements

### Requirement: Ein Etikett der Vorlage

Die Maße SHALL aus den gLabels-A4-Vorlagen in `ql_editor/data/zweckform-iso-templates.xml` kommen. Das Ziel „Etikettenbogen“ SHALL die Zeichenfläche zu einem Etikett der gewählten Vorlage machen, nicht zur ganzen Seite. Brother-Band, Brother-Drucker und die Längenwahl SHALL dabei beiseite treten.

#### Scenario: Ziel umschalten

- **WHEN** das Ziel auf „Etikettenbogen“ gestellt und eine Vorlage gewählt wird
- **THEN** hat die Zeichenfläche die Größe eines Etiketts dieser Vorlage

### Requirement: Füllen des Bogens

Mit verbundener CSV SHALL die gewählten Zeilen, alle Zeilen oder ein Von-bis-Bereich den Bogen füllen, ein Datensatz je Etikett. Kopien SHALL denselben Datensatz in die nächsten Zellen legen. Die erste Zelle SHALL nur die erste Seite verschieben. Weitere Seiten MUST bei der ersten Zelle beginnen. Ein Auftrag MUST NOT mehr als 2000 Etiketten umfassen.

#### Scenario: Teilweise benutzter Bogen

- **WHEN** die erste Zelle nicht die erste des Bogens ist
- **THEN** beginnt die erste Seite bei dieser Zelle
- **AND** die nächste Seite beginnt bei der ersten Zelle

### Requirement: Echte Seitengröße

PDF und Systemdruck MUST die Seitengröße der Vorlage beibehalten und MUST NOT die Seite in den bedruckbaren Bereich einpassen. Der Versatz SHALL den ganzen Bogen schieben und MUST NOT über 20 mm je Richtung hinausgehen.

#### Scenario: Versatz

- **WHEN** ein Versatz von 3 mm gesetzt und ein PDF geschrieben wird
- **THEN** bleibt die Seite in der Größe der Vorlage
- **AND** der Inhalt ist um 3 mm verschoben

### Requirement: Was zum Arbeitsplatz gehört

Versatz, Systemdrucker und erste Zelle SHALL Einstellungen dieser Maschine sein und MUST NOT in der `.qlx` stehen. Die gewählte Vorlage SHALL am Reiter und in den Fenstereinstellungen liegen und MUST NOT in der `.qlx` stehen.

#### Scenario: Datei ohne Bogen

- **WHEN** eine `.qlx` auf einem anderen Arbeitsplatz geöffnet wird
- **THEN** gelten dort Versatz, Systemdrucker, erste Zelle und die dort gemerkte Vorlage
