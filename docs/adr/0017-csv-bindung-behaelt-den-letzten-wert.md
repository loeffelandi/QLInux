# 17. CSV-Bindung behält den letzten Wert

Date: 2026-10-28

## Status

Accepted

Setzt voraus [6. Etikett als .qlx, die Maschine bleibt draußen](0006-etikett-als-qlx-maschine-bleibt-draussen.md)

## Kontext

Ein Etikett soll Werte aus einer CSV zeigen, ohne die Tabelle in die Datei einzubetten. Wird die CSV getrennt oder ist sie beim Öffnen nicht lesbar, soll das Etikett nicht leer werden. Eine Seriennummer und ein Datenbankfeld am selben Objekt würden zwei Quellen für denselben Text bedeuten.

## Entscheidung

Die `.qlx` speichert den CSV-Pfad relativ zur Datei, einen Inhalts-Hash und den aktuellen Index. Eine Bindung an Text, Barcode oder QR-Code ist entweder ein Datenbankfeld oder die Serie, nicht beides. Die Zeichenfläche zeigt die erste gewählte Zeile. Der Druck nimmt die Auswahl, alle Zeilen oder einen Bereich. Kopien wiederholen das Bild und zählen nicht in die Serienlänge. Fehlt die CSV oder wird sie getrennt, bleiben die zuletzt eingesetzten Werte auf den Objekten. Die Mehrfachauswahl im Gitter wird nicht mitgespeichert.

## Konsequenzen

Eine weitergegebene `.qlx` trägt die Bindung und den letzten Text, aber nicht die Tabelle. Ein abweichender Hash wird gemeldet, der Text bleibt der der Datei, bis die neue CSV gelesen ist. Die Serie im Inspektor gibt es nur, solange eine CSV verbunden ist.
