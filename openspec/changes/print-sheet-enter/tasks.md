# Tasks

## 1. Fehler nachstellen

- [x] 1.1 Strg+P, dann Enter in Ubuntu 24.04 (Xfce, X11) und unter weston (Wayland) mit echten Tasten ausgeführt. Ergebnis: der Druck startet bei jedem Fokus, der Fehler ist dort nicht nachzustellen. Er tritt unter Pop!_OS mit COSMIC auf, das hier nicht verfügbar ist.
- [x] 1.2 Test `test_enter_prints_without_the_window_shortcut` schaltet die Kurzbefehle ab und schickt Enter an das fokussierte Widget. Er scheitert vor dem Fix.

## 2. Enter im Druck-Sheet

- [x] 2.1 Das Sheet fängt Enter selbst ab (`on_enter`, `design.md` Entscheidung 2), zusätzlich zum Kurzbefehl. Verifikation: der Test aus 1.2 ist grün.
- [x] 2.2 Tests für jedes Scenario von „Enter startet den Druck“ in `tests/test_database_ui.py` neben die vorhandenen Enter-Tests: direkt nach dem Öffnen, Feld (Kopien, Schwelle, Auswahlfeld, Verlaufstabelle), anderer Knopf, Ziffernblock-Enter, Druck läuft, Sheet zu. Verifikation: `.venv/bin/python -m pytest -q tests/test_database_ui.py` ist grün.

## 3. Enter in Rückfragen und Meldungen

- [x] 3.1 Beim Öffnen eines Rückfrage- oder Meldungs-Sheets den Fokus auf den Standardknopf setzen (`design.md` Entscheidung 3). Verifikation: nach dem Öffnen ist `QApplication.focusWidget()` der Standardknopf.
- [x] 3.2 Tests in `tests/test_sheet.py` für „Meldung bestätigen“, „Rückfrage zum Band“ (Abbrechen, kein Druck) und „Zeichenfläche bleibt unberührt“ (keine Textbearbeitung). Verifikation: `.venv/bin/python -m pytest -q tests/test_sheet.py` ist grün.

## 4. Abschluss

- [x] 4.1 `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy` und `.venv/bin/python -m pytest -q` laufen ohne Fehler.
- [ ] 4.2 Auf Pop!_OS Strg+P und Enter mit der gebauten App wiederholen. Verifikation: der Druck startet auf X11 und Wayland.

## Workflow follow-up

- Umsetzung auf einem Feature-Branch, nicht auf `main`.
- Change nach Review archivieren, dabei die beiden neuen Anforderungen in `openspec/specs/sheets-and-appearance/spec.md` übernehmen.
