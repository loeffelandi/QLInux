# Spec Delta

## Purpose

QLInux sucht beim Start und auf Wunsch nach einer neueren GitHub-Release und spielt sie auf Wunsch selbst ein, ohne dass der Nutzer eine Datei von Hand laden muss. Nur gepackte Programme (AppImage, `QLInux.app`) nehmen daran teil.

## ADDED Requirements

### Requirement: Wer sich aktualisiert

Nur das AppImage und `QLInux.app` SHALL nach Updates suchen und sich aktualisieren. Ein Start aus dem Quelltext oder aus einer anderen Installation MUST keine Verbindung zu GitHub öffnen und MUST weder den Menüeintrag noch den Schalter für Updates zeigen.

#### Scenario: Start aus dem Quelltext

- **WHEN** QLInux mit `python -m ql_editor` aus einem Checkout startet
- **THEN** erfolgt keine Netzwerkanfrage nach einem Update
- **AND** das Hamburger-Menü enthält weder „Nach Updates suchen…“ noch „Beim Start nach Updates suchen“

#### Scenario: Start als AppImage

- **WHEN** QLInux als AppImage startet
- **THEN** gilt die Suche beim Start

### Requirement: Suche beim Start

Beim Start SHALL QLInux im Hintergrund die neueste veröffentlichte Release von `loeffelandi/QLInux` abfragen, höchstens einmal in 24 Stunden und nur, wenn der Schalter „Beim Start nach Updates suchen“ an ist. Der Start des Fensters MUST nicht auf die Antwort warten. Die Abfrage SHALL nach 5 Sekunden aufgeben, und ein Fehler MUST ohne Meldung bleiben.

#### Scenario: Kein Netz

- **WHEN** QLInux ohne Netzwerk startet
- **THEN** öffnet sich das Fenster ohne Verzögerung und ohne Fehlermeldung

#### Scenario: Zweite Suche am selben Tag

- **WHEN** die letzte vollständige Abfrage weniger als 24 Stunden her ist und QLInux startet
- **THEN** erfolgt keine neue Abfrage

#### Scenario: Schalter aus

- **WHEN** „Beim Start nach Updates suchen“ aus ist und QLInux startet
- **THEN** erfolgt keine Abfrage

### Requirement: Neuere Version erkennen

Eine Release SHALL als Update gelten, wenn ihre Version numerisch größer ist als die laufende. Der Tag `v<Zahl>.<Zahl>.<Zahl>` ist die Version. Entwürfe, Vorabversionen und nicht lesbare Tags MUST ignoriert werden. Fehlt der Release die Datei für diese Plattform oder ihre Prüfsumme, MUST sie wie „kein Update“ behandelt und der Zeitpunkt der Suche nicht gemerkt werden.

#### Scenario: Neue Release

- **WHEN** `v0.5.0` die neueste Release ist und `0.4.1` läuft
- **THEN** gilt `0.5.0` als Update

#### Scenario: Release ohne Datei für diese Plattform

- **WHEN** die Release veröffentlicht ist, die Datei für diese Plattform aber noch nicht hochgeladen wurde
- **THEN** zeigt QLInux keinen Hinweis
- **AND** der nächste Start fragt erneut

#### Scenario: Gleiche oder ältere Version

- **WHEN** die neueste Release der laufenden Version entspricht oder älter ist
- **THEN** zeigt QLInux keinen Hinweis

### Requirement: Hinweis auf das Update

Gibt es ein Update, SHALL QLInux nach dem Öffnen des Fensters ein Sheet zeigen. Es nennt die neue und die laufende Version und bietet **Jetzt aktualisieren**, **Später** und **Diese Version überspringen**. Eine übersprungene Version MUST beim Start nicht mehr gemeldet werden, eine noch neuere Version dagegen schon.

#### Scenario: Später

- **WHEN** der Nutzer **Später** wählt
- **THEN** schließt das Sheet, und der nächste Start nach Ablauf der 24 Stunden meldet dieselbe Version wieder

#### Scenario: Version überspringen

- **WHEN** der Nutzer **Diese Version überspringen** wählt und `0.5.0` ist das Update
- **THEN** meldet QLInux `0.5.0` beim Start nicht mehr
- **AND** eine spätere Version `0.5.1` wird gemeldet

### Requirement: Suche von Hand

Das Hamburger-Menü SHALL **Nach Updates suchen…** enthalten. Der Eintrag fragt sofort, auch ohne die 24-Stunden-Sperre und auch bei ausgeschaltetem Start-Schalter, und MUST das Ergebnis melden: das Update-Sheet, „QLInux ist aktuell“ oder einen Fehler, der sagt, dass GitHub nicht erreichbar war. Übersprungene Versionen MUST bei der Suche von Hand wieder erscheinen.

#### Scenario: Aktuell

- **WHEN** der Nutzer **Nach Updates suchen…** wählt und die neueste Release der laufenden Version entspricht
- **THEN** zeigt QLInux die Meldung „QLInux ist aktuell“

#### Scenario: GitHub nicht erreichbar

- **WHEN** der Nutzer **Nach Updates suchen…** wählt und es kein Netz gibt
- **THEN** zeigt QLInux eine Meldung, dass die Suche nicht möglich war

### Requirement: Download und Prüfsumme

**Jetzt aktualisieren** SHALL die Datei der Release laden und ihre SHA-256-Summe mit der Angabe der Release vergleichen. Stimmt sie nicht oder fehlt sie, MUST das Update abbrechen, die geladene Datei löschen und die installierte Version unberührt lassen. Alle Verbindungen MUST verschlüsselt sein und das Zertifikat der Gegenstelle prüfen. Das Sheet SHALL den Fortschritt zeigen und einen Abbruch erlauben.

#### Scenario: Falsche Prüfsumme

- **WHEN** die geladene Datei nicht zur Prüfsumme der Release passt
- **THEN** meldet QLInux einen Fehler
- **AND** die installierte Version bleibt unverändert
- **AND** die geladene Datei ist gelöscht

#### Scenario: Abbruch

- **WHEN** der Nutzer den Download abbricht
- **THEN** bleibt die installierte Version unverändert
- **AND** die halb geladene Datei ist gelöscht

### Requirement: AppImage ersetzen

Läuft QLInux als AppImage, SHALL das Update die Datei, aus der es gestartet wurde, in einem Schritt durch die neue ersetzen und ihr die Ausführrechte lassen. Ist das Verzeichnis oder die Datei nicht beschreibbar, MUST QLInux den Pfad nennen und nichts ändern.

#### Scenario: Ersetzen

- **WHEN** das geladene AppImage geprüft ist
- **THEN** liegt am Pfad des laufenden AppImage die neue Version, ausführbar
- **AND** die laufende Instanz arbeitet weiter

#### Scenario: Nicht beschreibbarer Ordner

- **WHEN** das AppImage in einem Ordner liegt, in den der Nutzer nicht schreiben darf
- **THEN** nennt die Fehlermeldung den Pfad
- **AND** nichts wird geändert

### Requirement: QLInux.app ersetzen

Läuft QLInux als `QLInux.app`, SHALL das Update die `.dmg` laden, die enthaltene App neben die laufende kopieren, prüfen, dass sie die erwartete Version trägt und ihre Signatur gültig ist, und sie dann an die Stelle der laufenden App setzen. Das Image MUST danach wieder ausgeworfen werden. Ist der Ordner der App nicht beschreibbar, MUST QLInux den Pfad nennen und nichts ändern. Schlägt ein Schritt fehl, MUST die alte App an ihrem Platz bleiben.

#### Scenario: Ersetzen

- **WHEN** die geladene `.dmg` geprüft ist
- **THEN** liegt an der Stelle der laufenden `QLInux.app` die neue Version
- **AND** das Image ist ausgeworfen

#### Scenario: Kopieren scheitert

- **WHEN** das Kopieren der neuen App halb fertig abbricht
- **THEN** ist die alte `QLInux.app` unverändert
- **AND** liegt keine halbe App neben ihr

### Requirement: Neustart nach dem Update

Nach einem eingespielten Update SHALL QLInux fragen, ob es neu starten soll. Bei **Jetzt neu starten** MUST QLInux den normalen Beenden-Weg gehen, einschließlich der Frage nach ungespeicherten Änderungen, und danach die neue Version starten. Offene Dateien mit gespeichertem Pfad öffnen sich dort wieder. Bricht der Nutzer das Beenden ab, bleibt das Update installiert und wirkt beim nächsten Start.

#### Scenario: Neustart mit offenen Dateien

- **WHEN** zwei gespeicherte Etiketten offen sind und der Nutzer **Jetzt neu starten** wählt
- **THEN** startet die neue Version und öffnet beide Dateien als Reiter

#### Scenario: Ungespeicherte Änderungen

- **WHEN** ein Reiter ungespeicherte Änderungen hat und der Nutzer **Jetzt neu starten** wählt
- **THEN** fragt QLInux wie beim Beenden nach dem Speichern
- **AND** bei **Abbrechen** bleibt QLInux offen, und das Update ist installiert

### Requirement: Einstellungen und Datenschutz

Der Schalter „Beim Start nach Updates suchen“ SHALL standardmäßig an sein, in den Einstellungen dieser Maschine stehen und nicht in der `.qlx`. Die Abfrage MUST nur den Programmnamen mit Version im `User-Agent` mitsenden und keine Kennung, keine Druckerdaten und keine Dateinamen. Die Umgebungsvariable `QLINUX_NO_UPDATE_CHECK=1` MUST jede Suche beim Start abschalten.

#### Scenario: Erster Start

- **WHEN** QLInux zum ersten Mal als AppImage oder `QLInux.app` startet
- **THEN** ist „Beim Start nach Updates suchen“ an

#### Scenario: Umgebungsvariable

- **WHEN** `QLINUX_NO_UPDATE_CHECK=1` gesetzt ist und QLInux startet
- **THEN** erfolgt keine Abfrage, auch wenn der Schalter an ist
