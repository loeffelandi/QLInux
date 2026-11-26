# Spec Delta

## MODIFIED Requirements

### Requirement: udev-Regel mit uaccess

Unter Linux SHALL die Druckerleiste „Zugriff einrichten“ anbieten, wenn das Schreibrecht fehlt. Die Einrichtung MUST `/etc/udev/rules.d/70-brother-ql.rules` anlegen und MUST `TAG+="uaccess"` für Hersteller `04f9` setzen, einmal für `usbmisc`/`lp*` und einmal für das USB-Gerät. Sie MUST NOT die Gruppe `lp` verlangen und MUST NOT den Knoten auf `0666` setzen.

#### Scenario: Regel liegt vor 73

- **WHEN** die Einrichtung durchläuft
- **THEN** heißt die Datei `70-brother-ql.rules`

### Requirement: pkexec nur mit Agent

Unter Linux SHALL `pkexec` nur starten, wenn ein Authentifizierungs-Agent läuft. Sonst SHALL die Anwendung den Terminal-Einzeiler zeigen und MUST NOT auf `pkexec` warten. Ein gestartetes `pkexec` MUST nach 90 Sekunden abgebrochen werden.

#### Scenario: Kein Agent

- **WHEN** „Zugriff einrichten“ ausgelöst wird und kein Authentifizierungs-Agent läuft
- **THEN** erscheint der Terminal-Einzeiler
- **AND** es wird kein `pkexec` gestartet

## ADDED Requirements

### Requirement: Kein Rechte-Knopf auf dem Mac

Auf dem Mac MUST die Druckerleiste weder „Zugriff einrichten“ noch einen Terminal-Einzeiler mit `udev`, `sudo` oder `pkexec` anbieten. macOS braucht für den USB-Drucker keine Regel. Die Prüfung des Schreibrechts SHALL dort keinen Wert liefern und MUST NOT einen Fehler zeigen.

#### Scenario: Drucker am Mac angeschlossen

- **WHEN** auf dem Mac ein Brother-QL per USB angeschlossen und gewählt ist
- **THEN** zeigt die Druckerleiste keinen Knopf zum Einrichten des Zugriffs

### Requirement: Meldung bei gesperrtem Drucker auf dem Mac

Scheitert das Öffnen des USB-Druckers auf dem Mac mit „Access denied“, „Permission denied“ oder „busy“, SHALL die Fehlermeldung einen Hinweis tragen, der zu macOS passt: Drucker aus der Systemeinstellung „Drucker & Scanner“ entfernen oder dem Druckdienst entziehen, Kabel neu stecken und erneut drucken. Der Hinweis MUST NOT auf „Zugriff einrichten“ verweisen.

#### Scenario: Drucker durch das System belegt

- **WHEN** der Druck auf dem Mac mit „Access denied“ scheitert
- **THEN** enthält die Meldung den Hinweis auf „Drucker & Scanner“
- **AND** sie verweist nicht auf „Zugriff einrichten“
