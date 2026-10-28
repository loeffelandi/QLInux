# Brother-lbx-Import

## Purpose

P-touch-Dateien werden gelesen und als neues, ungespeichertes Etikett weiterbearbeitet. Zurückgeschrieben wird nicht. Hauptort: `ql_editor/lbx.py`.

## Requirements

### Requirement: Nur Import

Das System SHALL eine `.lbx` lesen und das Ergebnis wie ein neues Etikett behandeln, das noch keinen Speicherpfad hat. Speichern MUST nach einer `.qlx` fragen und MUST NOT in die `.lbx` zurückschreiben. Eine Datei ohne ZIP-Struktur oder ohne `label.xml` MUST abgelehnt werden.

#### Scenario: Speichern nach dem Import

- **WHEN** eine `.lbx` geöffnet und danach gespeichert wird
- **THEN** entsteht eine `.qlx`
- **AND** die ursprüngliche `.lbx` bleibt unverändert

### Requirement: Übernommene und ausgelassene Objekte

Das System SHALL Band, Ausrichtung, Text, Bilder, Linien und Rahmen übernehmen. Text aus einer Kabelvorlage SHALL übernommen werden, die Vorlage selbst MUST NOT. Datenbank-Textfelder SHALL als gebundener Text ankommen. Barcodes, Tabellen, Datum und Uhrzeit, Beschnitt und Rot auf zweifarbigem Band MUST NOT übernommen werden. Jede Auslassung MUST nach dem Import in einem Hinweis stehen.

Die Drehung in der Datei ist gegen den Uhrzeigersinn. Das System SHALL sie für die Zeichenfläche umkehren.

#### Scenario: Fehlender Barcode

- **WHEN** die `.lbx` einen Barcode enthält
- **THEN** fehlt der Barcode auf dem Etikett
- **AND** der Hinweis nach dem Import nennt ihn

#### Scenario: Drehung

- **WHEN** ein Objekt in der `.lbx` um 90 Grad gegen den Uhrzeigersinn gedreht ist
- **THEN** steht es auf der Zeichenfläche um 90 Grad im Uhrzeigersinn gedreht

### Requirement: CSV neben der Datei

Das System SHALL die CSV zuerst am gespeicherten Pfad suchen und danach neben der `.lbx`. Ist keine CSV lesbar, MUST Bindung und der zuletzt eingesetzte Text erhalten bleiben, und der Hinweis MUST das nennen.

#### Scenario: CSV fehlt

- **WHEN** eine `.lbx` Datenbankfelder nennt und keine CSV lesbar ist
- **THEN** bleiben die Bindungen auf den Textobjekten
- **AND** der zuletzt eingesetzte Text bleibt stehen
