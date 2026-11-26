# 22. Auf dem Mac Systemdialoge statt Sheets

Date: 2026-11-27

## Status

Accepted

Ergänzt [14. Dialoge als Sheets im Hauptfenster](0014-dialoge-als-sheets-im-hauptfenster.md)

## Kontext

ADR 0014 legt Dialoge als Overlay in das Hauptfenster, weil eigene Fenster unter Wayland und in kachelnden Oberflächen nicht zuverlässig im Vordergrund bleiben. Auf dem Mac gibt es dieses Problem nicht, und das System hat echte Sheets. Ein Overlay-Dateidialog ist dort die größte Abweichung von dem, was ein Mac-Nutzer erwartet: keine Seitenleiste des Finders, keine Tags, kein iCloud-Ordner.

## Entscheidung

Auf dem Mac erscheinen Datei-, Meldungs- und Eingabedialoge als Systemdialog, fensterweit modal am Hauptfenster (`NSOpenPanel`, `NSSavePanel`, `NSAlert`). `sheet._open_sheet` leitet dort jeden `QDialog` an `_open_native` und gibt ein `_NativeSheet` mit `closed`, `close_sheet()` und `isVisible()` zurück, damit die Aufrufer gleich bleiben. NSAlert hat keine Titelleiste: der Titel wird zur Überschrift, der Text zum Erläuterungstext. Dialoge mit eigenem Inhalt (Hilfe, Über, Druck, Auswahl) bleiben auch dort ein Overlay. Unter Linux ändert sich nichts.

## Konsequenzen

Die Dialoge sehen auf dem Mac aus wie die des Systems; Symbole an den Knöpfen und der Titel einer Meldung erscheinen nicht. Die Tests prüfen den Pfad mit gesetzter Plattform; der echte Dialog läuft nur auf einem Mac. Zwei Dialoge am selben Fenster stellt macOS hintereinander, das Overlay hat dagegen immer nur eines.
