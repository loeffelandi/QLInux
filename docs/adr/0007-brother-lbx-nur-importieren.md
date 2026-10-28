# 7. Brother-.lbx nur importieren

Date: 2026-10-28

## Status

Accepted

Setzt voraus [6. Etikett als .qlx, die Maschine bleibt draußen](0006-etikett-als-qlx-maschine-bleibt-draussen.md)

## Kontext

Bestehende P-touch-Dateien sollen in QLInux weiterbearbeitet werden können. `.lbx` ist ein ZIP mit `label.xml` und deckt Objektarten ab, die QLInux nicht vollständig abbildet. Zurückschreiben würde ein zweites Format pflegen, das nur teilweise verstanden ist.

## Entscheidung

`.lbx` wird nur gelesen. Das Ergebnis ist ein neues, noch nicht gespeichertes Etikett; Speichern fragt nach einer `.qlx` und schreibt nicht in die `.lbx` zurück.

Übernommen werden Band, Ausrichtung, Text, Bilder, Linien und Rahmen. Text aus einer Kabelvorlage kommt mit, die Vorlage selbst nicht. Datenbank-Textfelder werden zu gebundenem Text. Die CSV wird am gespeicherten Pfad gesucht, danach neben der `.lbx`. Die Drehung in der Datei läuft gegen den Uhrzeigersinn und wird für Qt umgekehrt.

Nicht übernommen und danach in einem Hinweis aufgezählt: Barcodes, Tabellen, Datum und Uhrzeit, Beschnitt und Rot auf zweifarbigem Band. Gemischte Schriftstile in einem Kasten fallen auf die Grundschrift zurück. Text wird nicht wie in P-touch in den Kasten eingepasst.

## Konsequenzen

Ein Roundtrip nach P-touch Editor gibt es nicht. Was der Hinweis aufzählt, muss neu gesetzt werden. Fehlt die CSV, bleiben Bindung und der zuletzt eingesetzte Text erhalten.
