# 18. Eine laufende Instanz pro Benutzer

Date: 2026-10-28

## Status

Accepted

## Kontext

Zwei Fenster desselben Benutzers teilen sich Einstellungen und Drucker. Ein Doppelklick im Dateimanager soll die Datei öffnen und nicht ein zweites QLInux starten. Ein zweiter Start ohne Datei soll das bestehende Fenster nach vorn holen.

## Entscheidung

Pro Benutzer gibt es einen lokalen Socket `QLInux-<user>` mit den Rechten `0700`. Der zweite Prozess übergibt die Dateiliste als JSON und beendet sich. Eine leere Liste holt nur das Fenster nach vorn. Jede übergebene Datei öffnet einen eigenen Reiter. Ein verwaister Socket wird einmal entfernt. Der Socket eines lebenden Besitzers wird nicht gelöscht. Unter Wayland kann der Compositor das Anheben ignorieren; dafür gibt es keinen zweiten Mechanismus.

## Konsequenzen

Zwei Benutzer an einem Rechner haben je eine Instanz. Ein Absturz blockiert den Namen nicht dauerhaft. Auf Wayland kommt das bestehende Fenster nicht verlässlich nach vorn, die Datei öffnet sich trotzdem darin.
