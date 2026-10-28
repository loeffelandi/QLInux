# 2. Native PySide6-App ohne Browser und ohne Vendor-Treiber

Date: 2026-10-28

## Status

Accepted

Wird vorausgesetzt von [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

Wird vorausgesetzt von [5. AppImage statt Debian-Paket](0005-appimage-statt-debian-paket.md)

## Kontext

QLInux ist ein Etiketteneditor für Brother-QL-Drucker auf dem Linux-Desktop. P-touch Editor läuft dort nicht nativ. Ein Browser mit WebUSB oder ein Treiber von Brother würde Verteilung und Gerätezugriff an Voraussetzungen knüpfen, die ein einzelner Arbeitsplatz nicht mitbringen soll.

## Entscheidung

QLInux ist eine native Anwendung in Python mit PySide6. Es gibt keinen Browser, kein WebUSB und keinen Vendor-Treiber. Gedruckt wird mit den Rasterbefehlen der Bibliothek, über TCP 9100 oder USB.

Die Tests laufen ohne Fenster: `tests/conftest.py` erzwingt die Qt-Plattform `offscreen` und legt `XDG_CONFIG_HOME` in ein temporäres Verzeichnis, damit ein Lauf die Einstellungen des Nutzers nicht anfasst.

## Konsequenzen

Die Qt-Laufzeit muss mitgeliefert werden. Dialoge, Zeichenfläche und Tests hängen an Qt. Dafür bleibt der Druckweg eine direkte Geräteverbindung, und die Oberfläche kann Sheets im Hauptfenster nutzen statt eigener Fenster.
