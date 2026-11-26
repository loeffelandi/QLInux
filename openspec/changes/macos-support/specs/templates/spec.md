# Spec Delta

## MODIFIED Requirements

### Requirement: Eigene Vorlagen

„Als Vorlage speichern“ SHALL die aktuelle Gestaltung als `.qlx` im Ordner `templates` der Benutzerdaten ablegen: unter Linux `~/.config/QLInux/templates/` (bzw. `$XDG_CONFIG_HOME/QLInux/templates/`), auf dem Mac `~/Library/Application Support/QLInux/templates/`. Diese Dateien MUST im selben Menü erscheinen. Eine eigene Vorlage SHALL sich wie jede andere `.qlx` kopieren lassen.

#### Scenario: Wieder im Menü

- **WHEN** die aktuelle Gestaltung als Vorlage gespeichert wird
- **THEN** erscheint sie im Vorlagenmenü
- **AND** die Datei liegt unter `~/.config/QLInux/templates/`

#### Scenario: Vorlage auf dem Mac

- **WHEN** auf dem Mac die aktuelle Gestaltung als Vorlage gespeichert wird
- **THEN** erscheint sie im Vorlagenmenü
- **AND** die Datei liegt unter `~/Library/Application Support/QLInux/templates/`
