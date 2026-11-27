# 23. Updates aus GitHub-Releases mit SHA-256-Prüfsumme

Date: 2026-11-27

## Status

Accepted

Setzt voraus [5. AppImage statt Debian-Paket](0005-appimage-statt-debian-paket.md)

Setzt voraus [20. macOS: unsigniertes .app für arm64 mit libusb](0020-macos-unsigniertes-app-fuer-arm64-mit-libusb.md)

## Kontext

QLInux kommt als AppImage und als `.dmg`. Wer eine neue Version will, lädt sie von Hand von GitHub und ersetzt die alte. Das Programm soll beim Start selbst nachsehen und das Update auf Wunsch einspielen. Bisher öffnet QLInux keine Verbindung ins Internet. Die Apps sind nicht signiert (ADR 0020), ein Update kann sich also nicht auf eine Signatur stützen. Beide Workflows laden ihre Dateien erst nach der Veröffentlichung einer Release hoch.

## Entscheidung

Die Quelle ist `GET /repos/loeffelandi/QLInux/releases/latest` der GitHub-Schnittstelle. Sie liefert nur veröffentlichte Releases und je Datei den Download-Link und `digest` (`sha256:…`). Der Tag `v<a>.<b>.<c>` ist die Version; nur eine größere Zahl gilt als Update. Gesucht wird `QLInux-<version>-<arch>.AppImage` (`x86_64`, `aarch64`) bzw. `QLInux-<version>-arm64.dmg`. Fehlt die Datei oder ihr `digest`, ist das kein Update und kein Fehler.

Beim Laden rechnet QLInux die SHA-256-Summe mit und vergleicht sie mit `digest`. Fehlt sie oder weicht sie ab, bricht das Update ab und löscht die Datei. Übertragen wird nur über HTTPS, auch bei Weiterleitungen. Das AppImage wird in einem Schritt (`os.replace`) durch die neue Datei ersetzt, `QLInux.app` neben der laufenden App kopiert, auf Version und Signatur geprüft und umbenannt. Schlägt ein Schritt fehl, bleibt die alte Version an ihrem Platz. Der Neustart geht über den normalen Beenden-Weg; ein losgelöster Hilfsprozess wartet auf das Ende der PID und startet die neue Datei mit den gespeicherten Pfaden der offenen Reiter.

Es suchen sich nur das AppImage und `QLInux.app` selbst. Beim Start fragt ein Hintergrundlauf höchstens einmal in 24 Stunden, mit 5 Sekunden Zeitlimit. Der Schalter „Beim Start nach Updates suchen“ ist standardmäßig an, `QLINUX_NO_UPDATE_CHECK=1` schaltet die Suche beim Start ab. Die Abfrage sendet nur `QLInux/<version>` als `User-Agent`.

## Konsequenzen

Die Prüfsumme schützt vor beschädigten Dateien und vor einem Mittelsmann im Netz. Sie schützt nicht vor jemandem, der die Release auf GitHub ändern kann, denn Datei und Summe kommen vom selben Ort. Eine eigene Signatur bräuchte einen Schlüssel in der App und eine zweite Datei je Release. Das kann später dazukommen.

Eine Release ohne Datei für die Plattform bleibt unsichtbar, bis die Workflows sie hochgeladen haben; der nächste Start fragt erneut. Auf dem Mac hat jede ad hoc signierte Version eine andere Signatur: macOS fragt nach einem Update erneut nach dem Zugriff aufs lokale Netz und nach der Firewall. Nach dem Tausch der App lädt der laufende Prozess Qt-Module womöglich aus dem neuen Bündel, deshalb ist „Jetzt neu starten“ die Vorgabe. Der Updater braucht ein beschreibbares Verzeichnis; sonst nennt er den Pfad und ändert nichts. Delta-Updates, Zurückrollen und Update-Kanäle gibt es nicht. Das AppImage behält die zsync-Informationen für externe Werkzeuge wie GearLever.
