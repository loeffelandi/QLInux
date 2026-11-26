# Spec Delta

## MODIFIED Requirements

### Requirement: Ein Sheet

Dialoge SHALL als Sheet im Hauptfenster erscheinen. Sichtbar SHALL immer nur eines sein. Ein neues Sheet MUST das vorherige schließen. Dateidialoge MUST NOT native Fenster sein. Solange ein Sheet offen ist, MUST die Kurzbefehle der Anwendung nicht greifen, außer die Aktion gehört zum Sheet.

Auf dem Mac gilt das für Dialoge mit eigenem Inhalt (Hilfe, Über, Druck, Auswahl). Datei-, Meldungs- und Eingabedialoge SHALL dort als Systemdialog erscheinen, fensterweit modal am Hauptfenster (Sheet des Systems). Ein Systemdialog MUST NOT ein eigenes Overlay im Fenster sein. Die Rückmeldung an das Programm (Auswahl, gedrückter Knopf, Abbruch mit Esc) MUST dieselbe sein wie unter Linux.

Das Druck-Sheet SHALL die 1-bit-Vorschau, Qualität und Ausgabe, Kopien, Schnitt und den Druckverlauf dieser Sitzung zeigen. Der Druck MUST von dort starten.

#### Scenario: Zweites Sheet

- **WHEN** ein Sheet offen ist und ein anderes geöffnet wird
- **THEN** ist nur noch das neue Sheet sichtbar

#### Scenario: Etikett öffnen auf dem Mac

- **WHEN** auf dem Mac „Öffnen…“ gewählt wird
- **THEN** erscheint der Öffnen-Dialog des Systems als Sheet am Fenster
- **AND** nach der Auswahl öffnet sich die Datei wie unter Linux

#### Scenario: Rückfrage beim Schließen auf dem Mac

- **WHEN** ein Reiter ungespeicherte Änderungen hat und das Fenster geschlossen wird
- **THEN** fragt ein Systemdialog mit „Speichern“, „Verwerfen“ und „Abbrechen“
- **AND** Esc zählt als „Abbrechen“

#### Scenario: Linux bleibt beim Overlay

- **WHEN** unter Linux ein Dialog erscheint
- **THEN** ist er ein Overlay im Hauptfenster, kein eigenes Fenster
