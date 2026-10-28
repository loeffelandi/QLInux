# Eine Instanz

## Purpose

Pro Benutzer läuft ein QLInux. Weitere Starts öffnen Dateien im bestehenden Fenster. Hauptorte: `ql_editor/instance.py`, `app.main`.

## Requirements

### Requirement: Zweiter Start

Ein zweiter Start desselben Benutzers SHALL die Dateiliste an die laufende Instanz übergeben und MUST sich danach beenden. Jede übergebene Datei MUST einen eigenen Reiter öffnen. Eine leere Liste SHALL nur das bestehende Fenster nach vorn holen. Der Socket MUST `QLInux-<user>` heißen und die Rechte `0700` haben.

#### Scenario: Doppelklick bei laufender Anwendung

- **WHEN** QLInux läuft und eine `.qlx` über einen zweiten Start übergeben wird
- **THEN** öffnet sich die Datei als neuer Reiter im bestehenden Fenster
- **AND** der zweite Prozess endet

#### Scenario: Zwei Benutzer

- **WHEN** ein anderer Benutzer QLInux startet
- **THEN** erhält er eine eigene Instanz

### Requirement: Verwaister Socket

Ein Socket ohne lebenden Besitzer SHALL einmal entfernt und danach neu angelegt werden. Der Socket eines lebenden Besitzers MUST NOT gelöscht werden.

#### Scenario: Absturz

- **WHEN** der Socket noch liegt, aber kein QLInux mehr läuft, und die Anwendung startet
- **THEN** übernimmt der neue Prozess den Namen und öffnet sein Fenster
