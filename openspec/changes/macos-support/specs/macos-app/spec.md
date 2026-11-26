# Spec Delta

## Purpose

Die Mac-Version von QLInux: Auslieferung als Programmpaket, Anmeldung der Dateitypen, Verhalten von Dock und Menüleiste und die Tasten, wie ein Mac-Benutzer sie erwartet. Alles andere Verhalten ist mit Linux identisch und steht in den übrigen Specs.

## ADDED Requirements

### Requirement: Programmpaket für Apple Silicon

Die Mac-Version SHALL als `QLInux.app` in einem `.dmg` für Apple Silicon (arm64) erscheinen. Das Paket MUST ohne installiertes Python und ohne Homebrew laufen und MUST libusb enthalten. Es SHALL unsigniert sein. Die README SHALL beschreiben, wie man die Gatekeeper-Warnung beim ersten Start bestätigt.

#### Scenario: Start ohne Entwicklungsumgebung

- **WHEN** das `.app` aus dem `.dmg` in den Programme-Ordner kopiert und gestartet wird
- **THEN** öffnet sich das Hauptfenster
- **AND** ein angeschlossener Brother-QL wird per USB gefunden, ohne dass Homebrew oder libusb installiert sind

#### Scenario: Erster Start

- **WHEN** das Paket zum ersten Mal gestartet wird
- **THEN** zeigt macOS die Warnung für nicht signierte Programme
- **AND** die README nennt den Weg, den Start zu erlauben

### Requirement: Dateitypen im Finder

Das Paket SHALL `.qlx` und `.lbx` als Dateitypen von QLInux anmelden, mit denselben Symbolen wie unter Linux. Ein Doppelklick, „Öffnen mit“ und das Ablegen einer Datei auf das Programm- oder Dock-Symbol SHALL die Datei als Reiter öffnen. Mehrere Dateien SHALL mehrere Reiter ergeben. Dateien anderer Typen MUST ignoriert werden.

#### Scenario: Doppelklick bei geschlossenem Programm

- **WHEN** QLInux nicht läuft und im Finder eine `.qlx` doppelt angeklickt wird
- **THEN** startet QLInux und die Datei steht in einem Reiter

#### Scenario: Doppelklick bei laufendem Programm

- **WHEN** QLInux läuft und im Finder eine `.lbx` doppelt angeklickt wird
- **THEN** öffnet sich die Datei als neuer Reiter im bestehenden Fenster
- **AND** es startet keine zweite Instanz

### Requirement: Dock-Symbol

Ein Klick auf das Dock-Symbol SHALL das Fenster nach vorn holen, auch wenn es verkleinert ist. Das Schließen des Fensters SHALL QLInux beenden, wie unter Linux. Ein Beenden mit ⌘Q MUST wie das Schließen des Fensters fragen, wenn ungespeicherte Änderungen vorliegen.

#### Scenario: Verkleinertes Fenster

- **WHEN** das Fenster im Dock verkleinert ist und das Dock-Symbol angeklickt wird
- **THEN** erscheint das Fenster wieder

#### Scenario: Beenden mit offenen Änderungen

- **WHEN** ein Reiter ungespeicherte Änderungen hat und ⌘Q gedrückt wird
- **THEN** fragt QLInux wie beim Schließen, ob gespeichert werden soll
- **AND** bei „Abbrechen“ läuft das Programm weiter

### Requirement: Menüleiste von macOS

QLInux SHALL auf dem Mac die Menüleiste des Systems zeigen, mit dem Menü „QLInux“ am üblichen Platz. Dort MUST „Über QLInux“ und „QLInux beenden“ stehen. Das Hamburger-Menü im Fenster MUST NOT dieselben Einträge doppelt anbieten. Der Aufbau der Werkzeugleiste und der Befehlssuche bleibt wie unter Linux.

#### Scenario: Über-Fenster

- **WHEN** im Menü „QLInux“ der Eintrag „Über QLInux“ gewählt wird
- **THEN** erscheint dasselbe Sheet wie unter Linux

### Requirement: Tasten in Mac-Schreibweise

Auf dem Mac SHALL jede angezeigte Taste (Hilfe, Tooltips, Befehlssuche, Hinweise in der Statusleiste) in Mac-Schreibweise stehen: ⌘ für Strg, ⇧ für Umschalt bzw. Shift, ⌥ für Alt, ⌫ und ⌦ für Rücktaste und Entf, ⌃ für die Control-Taste. Das Verhalten SHALL mit Linux übereinstimmen, wobei ⌘ die Rolle von Strg übernimmt: ⌘-Mausrad zoomt, ⌘-Klick ergänzt die Auswahl, ⌘-Ziehen dupliziert. Auf Linux MUST die Anzeige unverändert „Strg“ lauten.

#### Scenario: Hilfe auf dem Mac

- **WHEN** die Hilfe auf dem Mac geöffnet wird
- **THEN** steht neben „Etikett speichern“ ⌘S und neben „Duplizieren“ ⌘D
- **AND** die Hilfe enthält das Wort „Strg“ nirgends

#### Scenario: Hilfe unter Linux

- **WHEN** die Hilfe unter Linux geöffnet wird
- **THEN** steht neben „Etikett speichern“ Strg+S

### Requirement: Tasten, die macOS selbst belegt

Auf dem Mac SHALL der Wechsel zwischen Reitern ⌃Tab und ⌃⇧Tab sein, weil ⌘Tab dem Programmwechsel gehört. „Reiter schließen“ SHALL ⌘W sein. „Wiederholen“ SHALL ⇧⌘Z sein. Rücktaste und Entf SHALL beide das gewählte Objekt löschen. Die Panels SHALL zusätzlich über ihre Knöpfe in der Werkzeugleiste erreichbar bleiben, weil F9 auf vielen Mac-Tastaturen die fn-Taste braucht.

#### Scenario: Reiter wechseln

- **WHEN** zwei Reiter offen sind und ⌃Tab gedrückt wird
- **THEN** wird der nächste Reiter aktiv
- **AND** der Programmwechsel von macOS startet nicht

#### Scenario: Objekt löschen mit der Rücktaste

- **WHEN** ein Objekt gewählt ist und ⌫ gedrückt wird
- **THEN** wird das Objekt gelöscht

### Requirement: Zugriff auf das lokale Netz

Das Paket SHALL macOS beim ersten Zugriff erklären, wozu QLInux das lokale Netz braucht: zum Suchen und Ansprechen von Brother-Druckern. Wird der Zugriff verweigert, SHALL die Druckersuche eine Liste ohne Netzwerkdrucker liefern und MUST NOT hängen. Die Druckerleiste SHALL dann auf die Systemeinstellung „Lokales Netzwerk“ hinweisen.

#### Scenario: Zugriff verweigert

- **WHEN** der Benutzer den Zugriff auf das lokale Netz verweigert hat und die Druckersuche läuft
- **THEN** endet die Suche innerhalb der üblichen Zeit
- **AND** die Druckerleiste nennt die Systemeinstellung „Lokales Netzwerk“

### Requirement: Eigene Daten im Benutzerordner

Auf dem Mac SHALL QLInux Einstellungen und eigene Vorlagen im Benutzerordner `~/Library` ablegen und MUST NOT `~/.config` anlegen. Dasselbe `.qlx` SHALL sich zwischen Mac und Linux ohne Umwandlung austauschen lassen, auch mit Bildern, Barcodes und Datenbankbindung.

#### Scenario: Datei vom Linux-Rechner

- **WHEN** eine unter Linux gespeicherte `.qlx` auf dem Mac geöffnet wird
- **THEN** zeigt die Zeichenfläche dieselben Objekte an denselben Stellen
- **AND** der gespeicherte Druckeranschluss wird nicht übernommen

### Requirement: Zoomgeste am Zeiger

Die Zoomgeste des Trackpads SHALL den Ausschnitt um die Stelle unter dem Zeiger zoomen. Der Punkt der Zeichenfläche unter dem Zeiger MUST nach dem Zoomen dort bleiben.

#### Scenario: Pinch über einer Ecke

- **WHEN** die Zeichenfläche vergrößert ist und der Zeiger über einem Objekt steht
- **AND** die Geste zoomt hinein
- **THEN** bleibt dasselbe Objekt unter dem Zeiger
- **AND** der Ausschnitt springt nicht in die obere linke Ecke
