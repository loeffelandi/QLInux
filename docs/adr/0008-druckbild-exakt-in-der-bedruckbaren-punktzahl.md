# 8. Druckbild exakt in der bedruckbaren Punktzahl

Date: 2026-10-28

## Status

Accepted

Setzt voraus [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

Wird vorausgesetzt von [9. Schnitt und Kopien im Rasterstrom](0009-schnitt-und-kopien-im-rasterstrom.md)

## Kontext

`convert()` verkleinert ein Endlosbild, dessen Breite nicht `dots_printable` ist, und lehnt Die-cut-Bilder mit anderen Maßen ab. Der 600-dpi-Modus der QL-800-Reihe verdoppelt nur die Zeilen in Laufrichtung. `convert()` halbiert danach die Breite, bevor es auf die Gerätebreite aufpolstert.

## Entscheidung

Das gerenderte Bild hat immer exakt die bedruckbare Breite des Bandes. Für 600 dpi rendert QLInux beide Achsen mit Faktor 2, damit nach dem Halbieren die Breite stimmt und die Zeilenzahl doppelt bleibt. Den Modus bieten nur QL-800, QL-810W und QL-820NWB an. Er ist keine Qualitätsstufe; „Qualität vor Tempo“ bleibt ein eigener Schalter.

Die Vorschau binarisiert mit derselben Schwelle wie `convert()` und mittelt das 600-dpi-Bild für die Anzeige herunter. Sie zeigt die Druckdaten, nicht eine zweite Gestaltung.

## Konsequenzen

Es gibt keinen zweiten Resize und keine Warnung „Need to resize“. Modelle außerhalb der drei genannten bieten 600 dpi nicht an. Vorschub und der nicht bedruckbare Streifen am Bandrand bleiben Sache der Bibliothek und sind keine Nutzer-Ränder.
