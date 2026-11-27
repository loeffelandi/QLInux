# Proposal

## Why

QLInux kommt als AppImage und als `.dmg` (macOS). Wer eine neue Version haben will, muss selbst auf GitHub nachsehen, die Datei laden und die alte ersetzen. Viele merken nie, dass es eine neue Version gibt. QLInux soll beim Start selbst nachsehen und das Update auf Wunsch gleich einspielen.

## What Changes

- Beim Start fragt ein Hintergrundlauf die neueste GitHub-Release von `loeffelandi/QLInux` ab, höchstens einmal in 24 Stunden. Der Start wartet nicht darauf, und ein Fehler bleibt still.
- Ist die Release neuer als die laufende Version, erscheint ein Sheet mit den Knöpfen **Jetzt aktualisieren**, **Später** und **Diese Version überspringen**.
- **Jetzt aktualisieren** lädt die passende Datei (AppImage bzw. `.dmg`), prüft sie gegen die SHA-256-Prüfsumme der Release und ersetzt das laufende Programm. Danach fragt QLInux, ob es neu starten soll. Gespeicherte, offene Dateien öffnen sich im neuen Programm wieder.
- Das Hamburger-Menü bekommt **Nach Updates suchen…** (sucht sofort, meldet auch „aktuell“) und den Schalter **Beim Start nach Updates suchen** (Vorgabe an).
- Nur gepackte Programme suchen und aktualisieren sich: das AppImage und `QLInux.app`. Ein Start aus dem Quelltext öffnet keine Verbindung.
- Das Update bricht ab und lässt die installierte Version unberührt, wenn die Prüfsumme fehlt oder nicht stimmt, die Datei nicht beschreibbar ist oder ein Schritt scheitert.

## Capabilities

### New Capabilities

- `app-update`: Suche nach einer neueren GitHub-Release beim Start und von Hand, Hinweis, Download mit Prüfsumme, Ersetzen von AppImage und `QLInux.app`, Neustart, Einstellungen und Datenschutz.

### Modified Capabilities

## Impact

- Neues Modul `ql_editor/updater.py` (Suche, Vergleich, Download, Prüfung, Ersetzen, Neustart), Aufrufe in `ql_editor/app.py` (Start, Menü, Sheets) und drei Einstellungen in `ql_editor/settings.py`.
- Neue Laufzeitabhängigkeit `certifi` (CA-Zertifikate, auch im Bündel). `requirements.txt` pinnt sie, `packaging/ql_editor.spec` nimmt sie mit.
- Erste ausgehende Verbindung zu einem Dritten (`api.github.com`, Download über GitHub). README, Hilfe und ein ADR beschreiben das.
- Release-Vertrag: Tag `v<version>`, Dateinamen `QLInux-<version>-<arch>.AppImage` und `QLInux-<version>-arm64.dmg`. Beide Workflows (`appimage.yml`, `macos.yml`) liefern sie schon so.
- Setzt die macOS-Version voraus (`feature/macos-support`): `platform_support`, `QLInux.app` und die `.dmg`.
