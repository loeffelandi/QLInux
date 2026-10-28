# Sheets, Sprache und Erscheinungsbild

## Purpose

Dialoge liegen im Hauptfenster. Die Oberfläche spricht Deutsch und Englisch und folgt auf Wunsch dem Erscheinungsbild des Systems. Hauptorte: `ql_editor/sheet.py`, `ql_editor/i18n.py`, `ql_editor/theme.py`.

## Requirements

### Requirement: Ein Sheet

Dialoge SHALL als Sheet im Hauptfenster erscheinen. Sichtbar SHALL immer nur eines sein. Ein neues Sheet MUST das vorherige schließen. Dateidialoge MUST NOT native Fenster sein. Solange ein Sheet offen ist, MUST die Kurzbefehle der Anwendung nicht greifen, außer die Aktion gehört zum Sheet.

Das Druck-Sheet SHALL die 1-bit-Vorschau, Qualität und Ausgabe, Kopien, Schnitt und den Druckverlauf dieser Sitzung zeigen. Der Druck MUST von dort starten.

#### Scenario: Zweites Sheet

- **WHEN** ein Sheet offen ist und ein anderes geöffnet wird
- **THEN** ist nur noch das neue Sheet sichtbar

### Requirement: Zwei Sprachen

Die Oberfläche SHALL Deutsch und Englisch anbieten und SHALL zur Laufzeit wechseln. Der Wechsel MUST die Oberfläche neu aufbauen. Dabei MUST der Undo-Stapel verloren gehen. Der Druckverlauf dieser Sitzung MUST erhalten bleiben.

#### Scenario: Sprache wechseln

- **WHEN** die Sprache von Deutsch auf Englisch gestellt wird
- **THEN** sind die sichtbaren Texte Englisch
- **AND** der bisherige Undo-Stapel ist leer

### Requirement: Erscheinungsbild

Das Erscheinungsbild SHALL System, Hell oder Dunkel sein. Steht es auf System, SHALL ein Wechsel der Desktop-Farben die Anwendung nachziehen. Die Zeichenfläche MUST diese Palette nicht übernehmen.

#### Scenario: Systemwechsel

- **WHEN** das Erscheinungsbild auf System steht und der Desktop von Hell auf Dunkel wechselt
- **THEN** wechselt die Anwendung auf die dunkle Palette
- **AND** die Zeichenfläche behält ihre eigenen Farben
