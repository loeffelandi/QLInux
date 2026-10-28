# Vorlagen

## Purpose

Eingebaute und eigene Vorlagen sind normale Etikettdateien ohne Druckermodell. Hauptort: `ql_editor/templates.py`.

## Requirements

### Requirement: Sieben eingebaute Vorlagen

Das Menü SHALL die Vorlagen Adresse, Paket, Kabel, Ordnerrücken, Preisschild, WLAN-QR und Inventar anbieten. Jede MUST 62-mm-Endlosband mit automatischer Länge verwenden und MUST NOT ein Druckermodell enthalten. Die Beispieltexte SHALL der Oberflächensprache folgen. Anwenden SHALL das Modell der aktuellen Oberfläche stehen lassen.

#### Scenario: Modell bleibt

- **WHEN** eine eingebaute Vorlage angewendet wird und bereits ein Modell gewählt ist
- **THEN** bleibt dieses Modell gewählt
- **AND** das Band wird zum 62-mm-Endlosband der Vorlage

### Requirement: Eigene Vorlagen

„Als Vorlage speichern“ SHALL die aktuelle Gestaltung als `.qlx` unter `~/.config/QLInux/templates/` ablegen. Diese Dateien MUST im selben Menü erscheinen. Eine eigene Vorlage SHALL sich wie jede andere `.qlx` kopieren lassen.

#### Scenario: Wieder im Menü

- **WHEN** die aktuelle Gestaltung als Vorlage gespeichert wird
- **THEN** erscheint sie im Vorlagenmenü
- **AND** die Datei liegt unter `~/.config/QLInux/templates/`
