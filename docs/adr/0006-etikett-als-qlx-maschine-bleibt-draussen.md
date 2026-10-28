# 6. Etikett als .qlx, die Maschine bleibt draußen

Date: 2026-10-28

## Status

Accepted

Wird vorausgesetzt von [7. Brother-.lbx nur importieren](0007-brother-lbx-nur-importieren.md)

Wird vorausgesetzt von [15. Vorlagen sind gewöhnliche .qlx ohne Modell](0015-vorlagen-sind-gewoehnliche-qlx-ohne-modell.md)

Wird vorausgesetzt von [17. CSV-Bindung behält den letzten Wert](0017-csv-bindung-behaelt-den-letzten-wert.md)

## Kontext

Ein Etikett soll weitergegeben werden können, ohne den Drucker des Empfängers umzustellen. Adresse, Druckoptionen, Fenstergröße und Bogeneinstellungen gehören zum Arbeitsplatz, nicht zur Gestaltung.

## Entscheidung

Das Etikett ist eine `.qlx`-Datei: JSON, eingerückt, UTF-8, Format 2. Format 1 bleibt lesbar. Neuere Formate werden abgelehnt, mit dem Hinweis auf eine neuere QLInux-Version.

Die Datei trägt Medium (Modell, Band, Ausrichtung, Länge, Ränder, Farbe), die Objekte, die Seriennummerierung, optionale Hilfslinien und optional `data_source` (CSV-Pfad und Metadaten, nicht den Dateiinhalt). Sie trägt nicht Druckeradresse, Druckoptionen, Fenstergeometrie, Bogenversatz, Systemdrucker oder die erste Zelle eines Bogens.

Ungespeicherte Änderungen an der Gestaltung markieren Fenstertitel und Reiter mit `*`. Eine vom Gespeicherten abweichende Druckeradresse markiert nur den Fenstertitel.

## Konsequenzen

Öffnen einer fremden Datei lässt den eigenen Drucker in Ruhe. Das Modell steht trotzdem im Medium, weil Bandliste und zweifarbiger Druck davon abhängen. Die gewählte Avery-Vorlage hängt nicht an der Datei; das ist in [16. Avery Zweckform aus gLabels in echter Größe](0016-avery-zweckform-aus-glabels-in-echter-groesse.md) festgehalten.
