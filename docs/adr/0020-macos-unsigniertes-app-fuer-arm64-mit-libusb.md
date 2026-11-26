# 20. macOS: unsigniertes .app für arm64 mit libusb

Date: 2026-11-27

## Status

Accepted

Setzt voraus [5. AppImage statt Debian-Paket](0005-appimage-statt-debian-paket.md)

Setzt voraus [13. Ein USB-Weg, Kernel-Knoten vor libusb](0013-ein-usb-weg-kernel-knoten-vor-libusb.md)

## Kontext

Die Mac-Version soll dieselben Funktionen haben wie die Linux-Version. Ein Entwickler-Konto für Signatur und Notarisierung gibt es nicht. Es gibt keinen Kernel-Knoten für Brother-QL auf macOS, USB läuft nur über libusb, und Homebrew ist beim Nutzer nicht da. Intel-Macs sind für das Projekt nicht mehr von Belang.

## Entscheidung

Die Mac-Version erscheint als `QLInux.app` in einem `.dmg` für Apple Silicon (arm64), gebaut mit PyInstaller (`BUNDLE` in `packaging/ql_editor.spec`) und `packaging/build_macos.sh`. libusb liegt im Bundle; das Skript bricht ab, wenn es auf dem Build-Rechner fehlt, prüft mit `otool` und startet das Programm ohne Homebrew-Pfad. Das Paket bleibt ohne Entwickler-Signatur und ohne Notarisierung; PyInstaller setzt die Ad-hoc-Signatur, ohne die arm64 nicht startet. Die README beschreibt, wie man den ersten Start in den Systemeinstellungen erlaubt. USB geht nur über libusb: Es gibt keinen Rechte-Knopf (udev gilt nur unter Linux), und eine Rechte-Meldung verweist auf „Drucker & Scanner“. Die Info.plist meldet `.qlx` und `.lbx` an und erklärt den Zugriff aufs lokale Netz (`NSLocalNetworkUsageDescription`, `NSBonjourServices`). Die Mindestversion liest der Bau aus den Mach-O-Dateien des Bundles (`LC_BUILD_VERSION`, höchster Wert) und trägt sie in `LSMinimumSystemVersion` ein. Ein lokal gebautes Homebrew-libusb hebt sie auf die macOS-Version des Build-Rechners; das Skript gibt den Wert aus.

## Konsequenzen

Nutzer müssen den ersten Start bestätigen, und die Firewall fragt nach eingehenden Verbindungen für die Druckersuche. Intel-Macs und universal2 sind ausgeschlossen. Hält der Druckdienst von macOS den Drucker, scheitert der USB-Weg mit „Zugriff verweigert“; das lässt sich nur mit einem Gerät prüfen. libusb (LGPL-2.1) gehört in die Lizenzliste der README. Eine Signatur oder Notarisierung kann später dazukommen, ohne dass sich das Paket ändert.
