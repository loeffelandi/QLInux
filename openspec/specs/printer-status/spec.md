# Druckerstatus

## Purpose

Band und Störungen werden dort gelesen, wo der Anschluss sie hergibt. Port 9100 hat keinen Rückkanal. Hauptorte: `ql_editor/printer.py`, `ql_editor/discovery.py`.

## Requirements

### Requirement: Band erkennen nur über USB

„Band erkennen“ SHALL nur über `pyusb` und `linux_kernel` laufen. Über das Netzwerk MUST es keine Bandmeldung aus Port 9100 ableiten.

#### Scenario: Netzwerkdrucker

- **WHEN** „Band erkennen“ für eine `tcp://`-Adresse ausgelöst wird
- **THEN** wird kein Band aus einer Antwort von Port 9100 gesetzt

### Requirement: SNMP vor und nach dem Netzwerkdruck

Für einen Netzwerkdrucker, der SNMP schon beantwortet hat, SHALL die Anwendung vor dem Senden nachfragen, wenn eine Störung gemeldet ist. Nach dem Senden SHALL sie den Auftrag prüfen. Eine Störung danach MUST den Auftrag als Fehler zeichnen. Schweigen MUST ihn als unbestätigt zeichnen und MUST NOT als Fehler gelten. Antwortet der Drucker nie per SNMP, SHALL der Auftrag als gesendet gelten.

#### Scenario: Keine Antwort nach dem Senden

- **WHEN** ein Netzwerkauftrag gesendet wurde und SNMP danach schweigt
- **THEN** steht der Auftrag im Verlauf als unbestätigt

#### Scenario: Störung vor dem Senden

- **WHEN** der gewählte Netzwerkdrucker per SNMP eine Störung meldet und Druck ausgelöst wird
- **THEN** wird vor dem Senden nachgefragt

### Requirement: Gemerkte Band

Nach einem bestätigten Netzwerkauftrag SHALL das eingelegte Band gemerkt werden. Vor dem Druck eines anderen Bandes MUST nachgefragt werden.

#### Scenario: Anderes Band

- **WHEN** ein bestätigter Auftrag ein Band gemerkt hat und danach ein anderes Band gedruckt werden soll
- **THEN** wird vor dem Senden nachgefragt

### Requirement: Abfrage hält das Fenster nicht auf

Die SNMP-Abfrage SHALL nur laufen, solange das Fenster aktiv ist, und MUST das Schließen nicht blockieren.

#### Scenario: Fenster schließen während der Abfrage

- **WHEN** eine Statusabfrage läuft und das Fenster geschlossen wird
- **THEN** schließt das Fenster, ohne auf diese Abfrage zu warten
