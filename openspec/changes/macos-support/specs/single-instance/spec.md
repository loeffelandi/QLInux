# Spec Delta

## ADDED Requirements

### Requirement: Öffnen durch das System

Dateien, die das Betriebssystem an die laufende Instanz übergibt statt an einen neuen Prozess (auf dem Mac ein Finder-Öffnen), SHALL sich wie ein zweiter Start verhalten: jede Etikettendatei öffnet einen eigenen Reiter, das Fenster kommt nach vorn. Wird die Datei beim Start übergeben, bevor das Fenster steht, SHALL sie nach dem Aufbau des Fensters geöffnet werden. Eine Datei, die schon in einem Reiter offen ist, MUST diesen Reiter wählen und MUST keinen zweiten öffnen.

#### Scenario: Datei kommt vor dem Fenster

- **WHEN** ein Finder-Doppelklick QLInux startet und die Datei vor dem ersten Fenster gemeldet wird
- **THEN** öffnet sich die Datei als Reiter, sobald das Fenster steht

#### Scenario: Datei ist schon offen

- **WHEN** eine `.qlx` in einem Reiter offen ist und dieselbe Datei im Finder doppelt angeklickt wird
- **THEN** wird der vorhandene Reiter gewählt
- **AND** es gibt keinen zweiten Reiter derselben Datei

### Requirement: Socket auf dem Mac

Auf dem Mac SHALL der Socket `QLInux-<user>` im Verzeichnis für temporäre Dateien des Benutzers liegen und die Rechte `0700` haben. Ein verwaister Socket nach einem Absturz MUST wie unter Linux einmal entfernt werden.

#### Scenario: Absturz auf dem Mac

- **WHEN** der Socket noch liegt, aber kein QLInux mehr läuft, und die Anwendung startet
- **THEN** übernimmt der neue Prozess den Namen und öffnet sein Fenster
