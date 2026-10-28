# Datenbank und Serie

## Purpose

Eine CSV füllt Text, Barcode und QR-Code. Die Tabelle selbst steht nicht in der Etikettdatei. Hauptorte: `ql_editor/csv_source.py`, `ql_editor/merge.py`, `ql_editor/database_panel.py`.

## Requirements

### Requirement: Bindung

Eine Spalte SHALL auf einen Text, Barcode oder QR-Code gezogen werden können und SHALL sonst einen neuen gebundenen Text anlegen. Eine Bindung MUST entweder ein Datenbankfeld oder die Serie sein, nicht beides. Die `.qlx` SHALL den CSV-Pfad relativ zur Datei, einen Inhalts-Hash und den aktuellen Index speichern und MUST NOT den CSV-Inhalt einbetten.

#### Scenario: Spalte auf leere Fläche

- **WHEN** eine Spalte auf eine freie Stelle der Zeichenfläche gezogen wird
- **THEN** entsteht dort ein Text, der an diese Spalte gebunden ist

### Requirement: Vorschau und Druckumfang

Die Zeichenfläche SHALL die erste gewählte Zeile zeigen. Der Druck SHALL die gewählten Zeilen, alle Zeilen oder einen Von-bis-Bereich nehmen. Kopien SHALL dasselbe Bild wiederholen und MUST NOT die Serienlänge erhöhen. Strg-Klick im Gitter SHALL eine Zeile zur Auswahl hinzufügen oder daraus entfernen, Shift-Klick SHALL einen Bereich wählen. Ist danach nichts mehr gewählt, SHALL die zuletzt gewählte Zeile gewählt bleiben.

#### Scenario: Mehrere Zeilen

- **WHEN** im Gitter drei Zeilen gewählt sind und mit „gewählte Datensätze“ gedruckt wird
- **THEN** entstehen drei Etiketten, eines je Zeile
- **AND** die Zeichenfläche zeigt weiter die erste dieser Zeilen

### Requirement: Fehlende CSV

Wird die CSV getrennt oder ist sie beim Öffnen nicht lesbar, MUST die zuletzt eingesetzten Werte auf den Objekten bleiben. Ein abweichender Inhalts-Hash SHALL gemeldet werden. Die Serie im Inspektor SHALL nur angeboten werden, solange eine CSV verbunden ist. Die Mehrfachauswahl MUST NOT in der `.qlx` stehen.

#### Scenario: CSV getrennt

- **WHEN** eine verbundene CSV getrennt wird
- **THEN** zeigen die gebundenen Objekte weiter den zuletzt eingesetzten Text
