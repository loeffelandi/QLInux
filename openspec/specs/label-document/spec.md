# Etikettendatei

## Purpose

Ein Etikett ist eine `.qlx`-Datei. Sie trägt die Gestaltung und lässt Drucker, Fenster und Druckoptionen am Arbeitsplatz. Hauptorte: `ql_editor/document.py`, `ql_editor/settings.py`, `MainWindow._is_document_dirty`.

## Requirements

### Requirement: JSON-Format 2

Das System SHALL ein Etikett als UTF-8-JSON mit Einrückung speichern. Die Datei MUST `format` 2 schreiben und Format 1 sowie Format 2 lesen. Ein höheres `format` MUST mit einem Fehler abgelehnt werden, der auf eine neuere QLInux-Version hinweist.

#### Scenario: Neuere Datei

- **WHEN** eine `.qlx` mit einem `format` größer als 2 geöffnet wird
- **THEN** wird sie nicht geladen
- **AND** die Meldung nennt eine neuere QLInux-Version

### Requirement: Inhalt der Datei

Die Datei MUST Medium, Objekte und die Seriennummerierung enthalten. Hilfslinien SHALL nur geschrieben werden, wenn mindestens eine gültige Linie vorliegt. `data_source` SHALL nur den CSV-Pfad und seine Metadaten enthalten, nicht den CSV-Inhalt. Druckeradresse, Druckoptionen, Fenstergeometrie, Bogenversatz, Systemdrucker und die erste Bogenzelle MUST NOT in der Datei stehen.

#### Scenario: Fremde Datei öffnen

- **WHEN** eine `.qlx` von einem anderen Arbeitsplatz geöffnet wird
- **THEN** bleiben Druckeradresse und Druckoptionen dieses Arbeitsplatzes unverändert

#### Scenario: Hilfslinien

- **WHEN** das Etikett mindestens eine Hilfslinie mit Achse `h` oder `v` und einer numerischen Position hat
- **THEN** stehen diese Linien in der Datei
- **AND** Linien ohne diese Felder werden nicht geschrieben

### Requirement: Ungespeichert-Markierung

Der Fenstertitel MUST ein `*` zeigen, solange die Gestaltung ungespeicherte Änderungen hat oder die Druckeradresse vom gespeicherten Zustand abweicht. Der Reiter MUST das `*` nur für ungespeicherte Gestaltungsänderungen zeigen.

#### Scenario: Nur die Adresse geändert

- **WHEN** die Gestaltung gespeichert ist und nur die Druckeradresse abweicht
- **THEN** zeigt der Fenstertitel ein `*`
- **AND** der Reiter zeigt keins
