## ADDED Requirements

### Requirement: Enter startet den Druck

Solange das Druck-Sheet offen ist, SHALL Enter (Haupttastatur und Ziffernblock) den Druck auslösen, egal welches Element im Sheet den Fokus hat. Hat ein anderer Knopf den Fokus, MUST er statt des Drucks den Klick bekommen. Läuft schon ein Druck, MUST Enter nichts auslösen. Ist das Sheet zu, MUST Enter den Druck nicht auslösen.

#### Scenario: Enter direkt nach dem Öffnen

- **WHEN** das Druck-Sheet per Strg+P geöffnet wird und Enter gedrückt wird, ohne vorher ein Feld anzuklicken
- **THEN** startet der Druck

#### Scenario: Enter in einem Feld

- **WHEN** der Fokus in einem Feld des Sheets steht (Kopien, Schwelle, Auswahlfeld, Verlaufstabelle) und Enter gedrückt wird
- **THEN** startet der Druck

#### Scenario: Enter auf einem anderen Knopf

- **WHEN** ein Knopf im Sheet den Fokus hat, der nicht der Druckknopf ist, und Enter gedrückt wird
- **THEN** wird dieser Knopf geklickt
- **AND** der Druck startet nicht

#### Scenario: Druck läuft

- **WHEN** ein Druck läuft und Enter im Sheet gedrückt wird
- **THEN** startet kein zweiter Druck

#### Scenario: Sheet zu

- **WHEN** das Druck-Sheet geschlossen ist und Enter auf der Zeichenfläche gedrückt wird
- **THEN** startet kein Druck

### Requirement: Enter in Rückfragen und Meldungen

Solange ein Rückfrage- oder Meldungs-Sheet offen ist, SHALL Enter den Standardknopf des Sheets auslösen. Enter MUST NOT die Zeichenfläche hinter dem Sheet erreichen. Bei „Drucker prüfen“ und „Band prüfen“ ist der Standardknopf „Abbrechen“.

#### Scenario: Meldung bestätigen

- **WHEN** eine Meldung mit „OK“ offen ist und Enter gedrückt wird
- **THEN** schließt das Sheet

#### Scenario: Rückfrage zum Band

- **WHEN** „Band prüfen“ offen ist und Enter gedrückt wird
- **THEN** wird abgebrochen
- **AND** es startet kein Druck

#### Scenario: Zeichenfläche bleibt unberührt

- **WHEN** auf der Zeichenfläche ein Objekt gewählt ist und ein Rückfrage-Sheet offen ist und Enter gedrückt wird
- **THEN** startet keine Textbearbeitung
