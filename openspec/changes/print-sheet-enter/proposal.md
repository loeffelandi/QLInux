# Proposal

## Why

Issue #102: Wer das Druck-Sheet öffnet (Strg+P) und Enter drückt, erwartet, dass der Druck startet. Unter Pop!_OS passiert nichts. Der Code kennt Enter im Druck-Sheet schon (`_on_print_key` in `ql_editor/app.py`, eingeführt mit „Print on Enter right after opening the print sheet“), und die Tests dazu laufen unter Qt offscreen grün. Das Verhalten ist aber nirgends als Anforderung festgehalten, und die Tests prüfen nur den Kurzbefehl, nicht den Weg bis zum Druck auf einem echten Fenster. Ohne Anforderung gibt es keinen Maßstab dafür, was „kaputt“ heißt.

Beim Nachstellen ist zusätzlich aufgefallen: In den Rückfrage-Sheets („Drucker prüfen“, „Band prüfen“, „Keine Druckeradresse“ und die übrigen `ask_*`/`show_message`-Sheets) bleibt der Fokus auf der Zeichenfläche. Enter löst dort den Standardknopf nicht aus und erreicht die Zeichenfläche hinter dem Sheet.

## What Changes

- **Enter im Druck-Sheet:** Enter und Enter auf dem Ziffernblock lösen den Druck aus, egal welches Element im Sheet den Fokus hat. Hat ein anderer Knopf den Fokus, bekommt er den Klick. Während ein Druck läuft, passiert nichts.
- **Enter in Rückfragen und Meldungen:** Enter löst den Standardknopf des Sheets aus. Bei „Drucker prüfen“ und „Band prüfen“ ist das „Abbrechen“. Enter erreicht die Zeichenfläche hinter einem offenen Sheet nie.
- **Ursache:** Sie ist noch nicht gefunden. Der erste Schritt der Umsetzung ist, den Fehler unter Pop!_OS (X11 und Wayland) nachzustellen. Erst danach wird der Weg gewählt (siehe `design.md`).
- **Tests:** Sie prüfen, was der Nutzer tut: Sheet per Strg+P öffnen, Taste an das fokussierte Widget schicken, Druckauftrag prüfen. Nicht nur, dass der Kurzbefehl existiert.

Nicht Teil dieser Änderung: andere Tasten im Druck-Sheet, ein anderer Standardknopf bei den Rückfragen, Änderungen am Druckablauf selbst (Bandprüfung, Störungsabfrage).

## Capabilities

### New Capabilities

Keine.

### Modified Capabilities

- `sheets-and-appearance`: Das Druck-Sheet startet den Druck auf Enter. Rückfragen und Meldungen lösen auf Enter den Standardknopf aus, und Enter erreicht nie die Zeichenfläche dahinter.

## Impact

- Code: `ql_editor/sheet.py` (Fokus und Tastenbehandlung des Sheets), `ql_editor/app.py` (`_on_print_key`, Druck-Panel).
- Tests: `tests/test_database_ui.py`, `tests/test_sheet.py`.
- Doku: `README.md`, Tabelle „Modifier keys on the canvas“, nur falls eine Taste mit Modifier dazukommt. Das ist nicht vorgesehen.
- Betroffene Plattformen: alle. Gemeldet unter Pop!_OS. Die Änderung `macos-support` berührt dieselbe Stelle nicht.
