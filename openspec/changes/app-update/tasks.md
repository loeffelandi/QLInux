# Tasks

Voraussetzung: `feature/macos-support` ist in `main`. Die Aufgaben 4 und 5 brauchen `platform_support` und `QLInux.app`.

## 1. Entscheidungen und Abhängigkeit

- [x] 1.1 Zwei ADRs mit `adr new` anlegen und auf Deutsch füllen: „Updates aus GitHub-Releases mit SHA-256-Prüfsumme“ (Entscheidungen 1, 5, 6, 9, 10 des Designs) und „CA-Zertifikate aus certifi für urllib“ (Entscheidung 7). Prüfen: `adr list` nennt beide.
- [x] 1.2 `certifi` in `requirements.txt` pinnen und in `packaging/ql_editor.spec` für AppImage und `QLInux.app` mitnehmen. Prüfen: `bash packaging/build_appimage.sh` bzw. `build_macos.sh` enthält `cacert.pem`, und im gebauten Programm liefert `certifi.where()` eine vorhandene Datei (Selbsttest in `packaging/entrypoint.py` ergänzen, `QLINUX_SELFTEST=certifi`).

## 2. Suche und Vergleich

- [x] 2.1 `ql_editor/updater.py` anlegen: `is_updatable()` (AppImage mit vorhandener `APPIMAGE`-Datei oder gepacktes `QLInux.app`), `parse_version(tag)`, `find_update(release_json, version, arch)` (Datei, `digest`, Entwürfe und Vorabversionen verwerfen) und `fetch_latest()` (HTTPS, `User-Agent: QLInux/<version>`, 5 s Zeitlimit, `certifi`-Kontext, Basisadresse als Modulvariable). Prüfen: `tests/test_updater.py` gegen einen lokalen HTTP-Server mit Release-JSON für neuere, gleiche, ältere Version, fehlende Datei, fehlenden `digest`, kaputten Tag, `http`-Weiterleitung und Zeitüberschreitung.
- [x] 2.2 Die Einstellungen `updates/check_on_start` (Vorgabe an), `updates/last_check` und `updates/skipped_version` in `AppSettings` anlegen. Prüfen: `tests/test_updater.py` prüft Vorgabe, Speichern und Laden dieser Einstellungen.
- [x] 2.3 Die Entscheidung „darf jetzt gesucht werden“ als eigene Funktion (Schalter, 24 Stunden, übersprungene Version, `QLINUX_NO_UPDATE_CHECK`, Quelltext). Prüfen: Tests für jede Kombination aus der Spec, Zeit über eine injizierte Uhr.

## 3. Download und Prüfsumme

- [x] 3.1 `download(url, target, expected_sha256, progress, cancel)` in `updater.py`: lädt in eine Punktdatei im Zielordner, rechnet SHA-256 beim Laden, ruft `progress` auf, löscht die Datei bei Abbruch, Fehler und falscher Summe. Prüfen: Tests mit lokalem Server für Erfolg, falsche Summe, Abbruch mittendrin, abgeschnittene Datei und fehlenden Ordner.

## 4. AppImage ersetzen

- [x] 4.1 `install_appimage(downloaded, target)`: Rechte der alten Datei übernehmen und `os.replace`; ein Ordner ohne Schreibrecht ergibt `UpdateError` mit dem Pfad, ohne Änderung. Prüfen: Tests mit temporärem Ordner für Ersetzen, Rechte, Schreibschutz und dass die alte Datei bei einem Fehler unverändert bleibt.

## 5. QLInux.app ersetzen (macOS)

- [x] 5.1 `install_app(dmg, app_path, expected_version)`: `hdiutil attach` an eigenen Mountpunkt, `ditto` neben die laufende App, `Info.plist` und `codesign --verify --deep` prüfen, umbenennen, alte löschen, bei Fehler zurückbenennen, `hdiutil detach` immer; Reste (`.QLInux-update*`, `.old`) beim Start aufräumen. Prüfen: macOS-Test baut mit `hdiutil create` eine kleine `.dmg` mit einer Test-`.app` und prüft Ersetzen, falsche Version, kaputte Signatur, nicht beschreibbaren Ordner und Rückbenennen bei erzwungenem Fehler; auf anderen Plattformen übersprungen.

## 6. Neustart

- [x] 6.1 `restart_after_exit(executable, paths)` startet einen losgelösten `sh -c`, der auf das Ende der PID wartet und die neue Datei (AppImage-Pfad bzw. `open -n QLInux.app --args …`) mit den Pfaden startet. Prüfen: Test mit einem Stellvertreter-Programm, das seine Argumente in eine Datei schreibt, nachdem der Testprozess beendet ist.
- [x] 6.2 In `MainWindow` den Neustart über `close()` anstoßen und den Hilfsprozess nur starten, wenn das Fenster wirklich schließt. Prüfen: GUI-Test, dass bei „Abbrechen“ auf die Frage nach ungespeicherten Änderungen kein Hilfsprozess startet und das Fenster offen bleibt.

## 7. Oberfläche

- [x] 7.1 Beim Start nach dem Zeigen des Fensters den Hintergrundlauf starten (Thread, Signal zurück in den GUI-Thread), `last_check` nur nach vollständiger Antwort setzen. Prüfen: GUI-Test mit lokalem Server: Hinweis erscheint nach dem Start, ohne Netz öffnet das Fenster ohne Meldung, zweiter Start am selben Tag fragt nicht.
- [x] 7.2 Sheet „Update verfügbar“ mit **Jetzt aktualisieren**, **Später**, **Diese Version überspringen**, danach Fortschritts-Sheet mit Abbruch, Fehler-Sheet und Frage „Jetzt neu starten?“. Prüfen: GUI-Tests für jeden Knopf; ein Test, dass „Diese Version überspringen“ `updates/skipped_version` setzt und der nächste Start schweigt, eine neuere Version aber meldet.
- [x] 7.3 Hamburger-Menü: **Nach Updates suchen…** und abhakbar **Beim Start nach Updates suchen**, beide auch in der Befehlspalette, beide nur bei `is_updatable()`. Prüfen: GUI-Test für Sichtbarkeit (AppImage-Umgebung gesetzt bzw. nicht), Schalter schreibt die Einstellung, Suche von Hand zeigt „QLInux ist aktuell“ und die Fehlermeldung ohne Netz.

## 8. Texte und Dokumentation

- [x] 8.1 Neue deutsche `tr()`-Texte in `ql_editor/translations.py` auf Englisch nachziehen. Prüfen: `tests/test_i18n.py` ist grün.
- [x] 8.2 README (Abschnitt Install: Selbst-Update, Schalter, `QLINUX_NO_UPDATE_CHECK`, erste ausgehende Verbindung und was sie sendet; Hinweis auf die erneute Netzfreigabe auf dem Mac nach einem Update) und `docs/hilfe.md` ergänzen. Prüfen: `tests/test_help.py` ist grün, der Hilfetext nennt den Menüeintrag.

## 9. Abnahme

- [x] 9.1 Von Hand: ein Test-AppImage und eine Test-`QLInux.app` mit älterer Version laden von einem lokalen Server, aktualisieren sich und starten die neue Version mit zwei offenen Dateien. Prüfen: Version im Über-Fenster stimmt, beide Reiter sind offen, die alte Datei ist ersetzt. Stand 27.11.: `QLInux.app` (macOS) und AppImage (aarch64, Ubuntu 24.04 in der VM) von Hand geprüft: Update, Austausch der Datei, Neustart mit zwei Dateien.
- [x] 9.2 `ruff check .`, `ruff format --check .`, `mypy` und `python -m pytest -q` laufen sauber. Prüfen: alle vier Befehle melden keinen Fehler.

## Workflow follow-up

- Nach der Abnahme `/opsx-archive` für `app-update`.
- Beim ersten Release mit der Funktion von Hand aktualisieren; ab dem nächsten Release bietet QLInux das Update selbst an.
