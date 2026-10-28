# USB-Zugriff

## Purpose

Status und Druck über USB brauchen Schreibrecht auf den Geräteknoten, ohne das Gerät für alle zu öffnen. Hauptorte: `ql_editor/access.py`, `scripts/install-udev-rule.sh`.

## Requirements

### Requirement: udev-Regel mit uaccess

Fehlt das Schreibrecht, SHALL die Druckerleiste „Zugriff einrichten“ anbieten. Die Einrichtung MUST `/etc/udev/rules.d/70-brother-ql.rules` anlegen und MUST `TAG+="uaccess"` für Hersteller `04f9` setzen, einmal für `usbmisc`/`lp*` und einmal für das USB-Gerät. Sie MUST NOT die Gruppe `lp` verlangen und MUST NOT den Knoten auf `0666` setzen.

#### Scenario: Regel liegt vor 73

- **WHEN** die Einrichtung durchläuft
- **THEN** heißt die Datei `70-brother-ql.rules`

### Requirement: pkexec nur mit Agent

`pkexec` SHALL nur starten, wenn ein Authentifizierungs-Agent läuft. Sonst SHALL die Anwendung den Terminal-Einzeiler zeigen und MUST NOT auf `pkexec` warten. Ein gestartetes `pkexec` MUST nach 90 Sekunden abgebrochen werden.

#### Scenario: Kein Agent

- **WHEN** „Zugriff einrichten“ ausgelöst wird und kein Authentifizierungs-Agent läuft
- **THEN** erscheint der Terminal-Einzeiler
- **AND** es wird kein `pkexec` gestartet
