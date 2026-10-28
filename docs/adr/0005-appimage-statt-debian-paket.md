# 5. AppImage statt Debian-Paket

Date: 2026-10-28

## Status

Accepted

Setzt voraus [2. Native PySide6-App ohne Browser und ohne Vendor-Treiber](0002-native-pyside6-app-ohne-browser-und-ohne-vendor-treiber.md)

## Kontext

PySide6 und `python-barcode` liegen nicht in den Debian-Archiven. Ein `.deb` müsste die Qt-Laufzeit trotzdem mitbringen und bräuchte root zur Installation. Die App soll ohne Installation starten, auf x86_64 und auf aarch64.

## Entscheidung

Die Distribution ist eine AppImage pro Architektur, gebaut mit PyInstaller und `appimagetool` (`packaging/build_appimage.sh`). Ein `.deb` ist nicht vorgesehen. QtWebEngine, QML/Quick, Multimedia, SQL und Charts werden nicht eingebunden. Die XCB-Bibliotheken, die Qt zum Öffnen eines Fensters braucht, müssen auf der Build-Maschine installiert sein und mit ins Paket. Ein veröffentlichtes Release baut beide Architekturen.

Die aarch64-Datei setzt glibc 2.39 oder neuer voraus. Einstellungen bleiben unter `~/.config/QLInux`, damit AppImage und ein Lauf aus dem Quelltext dieselben Werte teilen. `.qlx` und `.lbx` sind als Dateitypen der AppImage registriert.

## Konsequenzen

Die Datei ist groß, startet aber ohne root. Raspberry Pi OS Bookworm und andere Systeme mit älterem glibc starten die aarch64-Datei nicht. Fehlen die XCB-Bibliotheken beim Bauen, startet die AppImage ohne Fenster.
