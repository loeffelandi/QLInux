# Proposal

## Why

QLInux läuft heute nur unter Linux: Auslieferung als AppImage, USB-Rechte über udev, Kernel-Knoten `/dev/usb/lp*`, Pfade unter `~/.config`. Die Oberfläche startet auf dem Mac schon, aber ein Brother-QL lässt sich dort weder sauber per USB ansprechen noch als Programm installieren, und die Hilfe nennt Tasten, die es auf dem Mac nicht gibt. Gewünscht ist eine Mac-Version mit demselben Funktionsumfang, soweit macOS ihn zulässt.

## What Changes

- **Paket:** Ein unsigniertes `QLInux.app` für Apple Silicon (arm64), ausgeliefert als `.dmg`. Es entsteht aus demselben PyInstaller-Rezept wie das AppImage. libusb liegt im Bundle. Beim ersten Start warnt Gatekeeper; das Paket ist weder signiert noch notarisiert.
- **Dateien:** `.qlx` und `.lbx` sind beim Programm angemeldet. Ein Doppelklick im Finder, „Öffnen mit“ und Ablegen auf das Dock-Symbol öffnen die Datei als Reiter in der laufenden Instanz. Ein Klick auf das Dock-Symbol bei geschlossenem Fenster holt es zurück.
- **USB:** Auf dem Mac gibt es nur den libusb-Weg. Pro Drucker erscheint ein Eintrag `usb://…`. Bandlesen und Druckbestätigung laufen wie unter Linux über pyusb. „Zugriff einrichten“ und der udev-Hinweis erscheinen auf dem Mac nicht. Ein gesperrter Drucker bekommt eine Meldung, die zu macOS passt.
- **Netzwerk:** Druckersuche per mDNS und SNMP-Broadcast geht auch auf dem Mac, einschließlich der Broadcast-Adresse je Schnittstelle. Das Paket erklärt macOS, wozu es das lokale Netz braucht.
- **Tasten:** Hilfe, Tooltips, Befehlssuche und die README-Tabelle zeigen auf dem Mac die Mac-Symbole (⌘, ⇧, ⌥, ⌫). Das Verhalten bleibt: ⌘ ersetzt Strg, auch bei Mausrad, Klick und Ziehen. Das Programm hat auf dem Mac die Menüleiste von macOS mit Über, Einstellungen und Beenden an den üblichen Stellen.
- **Ablage:** Eigene Vorlagen liegen auf dem Mac unter `~/Library/Application Support/QLInux/templates/`, nicht unter `~/.config`. Auf Linux bleibt es bei `~/.config/QLInux/templates/`.
- **Fehler, die der Mac sichtbar macht:** Die drei Tests, die auf macOS scheitern (Ursprung des eingepassten Etiketts, zwei Touch-Pinch-Tests), werden untersucht und entweder im Programm oder im Test behoben. Die DejaVu-Schrift im Inspektor bekommt eine Ersatzschrift.
- **CI:** Ein macOS-arm64-Job führt dieselbe Suite aus und baut das `.app`.

Nicht Teil dieser Änderung: Signieren und Notarisieren, Intel-Macs (x86_64, universal2), Windows, ein Kernel-Weg für USB auf macOS, ein Mac-App-Store-Paket, Einrichten von CUPS-Treibern.

## Capabilities

### New Capabilities

- `macos-app`: Das Mac-Paket und seine Plattformbestandteile. Start aus dem `.app`, Dateitypen und Finder-Öffnen, Dock, Menüleiste, Mac-Tastenanzeige, Ablageort der Vorlagen, Hinweis zum lokalen Netz.

### Modified Capabilities

- `usb-access`: Die udev-Einrichtung gilt nur unter Linux. Auf dem Mac entfällt der Knopf, und eine Rechte-Meldung verweist nicht auf ihn.
- `printer-discovery`: Ein USB-Eintrag pro Drucker gilt auch ohne Kernel-Knoten. Die Broadcast-Adresse je Schnittstelle gilt auf dem Mac ebenso wie unter Linux.
- `single-instance`: Der zweite Start und ein Finder-Öffnen erreichen dieselbe Instanz. Der Socket liegt auf dem Mac im Benutzerverzeichnis für temporäre Dateien.
- `templates`: Der Ordner der eigenen Vorlagen hängt von der Plattform ab.

## Impact

- `packaging/`: neues Rezept für das `.app` und das `.dmg` neben dem AppImage, Info.plist, `.icns` aus `packaging/make_icon.py`, libusb im Bundle. `packaging/ql_editor.spec` bekommt eine macOS-Variante.
- `ql_editor/app.py` (Start, Öffnen von außen, Menüleiste, Dock), `ql_editor/instance.py`, `ql_editor/printer.py`, `ql_editor/discovery.py`, `ql_editor/access.py`, `ql_editor/media_panel.py`, `ql_editor/templates.py`, `ql_editor/help.py`, `ql_editor/i18n.py`, `ql_editor/inspector.py`.
- Neues Modul für Plattformunterschiede (Tastenanzeige, Ablageorte), damit die Fälle nicht über das Programm verstreut sind.
- `.github/workflows/tests.yml`, `README.md` (Installation, „Modifier keys on the canvas“), `docs/hilfe.md`, `docs/tests.md`, ein ADR für das Paket und den USB-Weg.
- Keine neuen Python-Abhängigkeiten. libusb (BSD/LGPL-2.1) kommt als Bibliothek ins Bundle und muss in die Lizenzliste der README.
