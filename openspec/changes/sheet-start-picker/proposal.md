# Proposal

## Why

Auf einem angefangenen Avery-Zweckform-Bogen zählt man die freien Felder heute von links oben und tippt die Zahl ins Spin-Feld „Erstes Etikett“. Auf einem 24er- oder 40er-Bogen verliert man dabei leicht die Stelle. Die Startzahl selbst ist schon entschieden: sie gilt nur für die erste Seite.

## What Changes

- Im Kasten „Avery Zweckform“ erscheint unter dem Spin-Feld eine Zeichnung des Bogens. Jedes Feld trägt seine Nummer, 1 links oben, zeilenweise.
- Felder vor der Startzahl sehen schon bedruckt aus, das gewählte Feld ist hervorgehoben, der Rest bleibt leer.
- Ein Klick auf ein Feld setzt die Startzahl. Tippen im Spin-Feld zeichnet dieselbe Auswahl neu.
- Die Belegung des Auftrags ändert sich nicht: die Startzahl verschiebt nur die erste Seite, weitere Seiten beginnen beim ersten Feld. Gespeichert bleibt sie als Einstellung dieser Maschine, nicht in der `.qlx`.

## Capabilities

### New Capabilities

### Modified Capabilities

- `zweckform-sheets`: Die erste Zelle lässt sich auf einer nummerierten Zeichnung des Bogens wählen. Spin-Feld und Zeichnung zeigen dieselbe Zahl. Die bisherige Belegung der Seiten bleibt.

## Impact

- Linkes Panel, Kasten Avery Zweckform in `ql_editor/app.py`. Die Zeichnung wird ein eigenes Widget, das die Vorlage nur malt und nicht druckt.
- `print/sheet_start` und `plan_sheet` bleiben die Quelle der Belegung. ADR 0016 gilt weiter; diese Änderung fügt keine neue Architekturentscheidung hinzu.
- Hilfe und README nennen die Zeichnung an der Stelle, die das erste Etikett schon beschreibt. Neue Oberflächentexte laufen durch `tr()`.
