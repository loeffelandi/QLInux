# 9. Schnitt und Kopien im Rasterstrom

Date: 2026-10-28

## Status

Accepted

Setzt voraus [8. Druckbild exakt in der bedruckbaren Punktzahl](0008-druckbild-exakt-in-der-bedruckbaren-punktzahl.md)

Setzt voraus [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

## Kontext

Drei Schnittarten werden gebraucht: nach jedem Etikett, nur am Ende, gar nicht. `brother_ql` schreibt den Autocut-Befehl nur bei `cut=True`. Fehlt er, gilt das Druckermenü, und das steht ab Werk auf Schneiden. Jede Seite endet in der Bibliothek mit `0x1A`. Der Drucker behandelt das als Auftragsende und schneidet danach, unabhängig von den Schnitt-Bits. Modelle ohne Schneider weisen den Autocut-Befehl zurück; `convert()` verschluckt diesen Fehler.

## Entscheidung

Der Rasterstrom wird immer mit `cut=True` erzeugt. `_JobRaster` setzt die Bits für Autocut und „Cut at end“ je Modus, bei jeder Seite erneut, weil der Kopf sich pro Etikett wiederholt. Zwischen den Kopien steht `0x0C`, nur die letzte Seite endet mit `0x1A`. Ein Auftrag hat höchstens 99 Seiten. Jeder Zuschnitt außer „keins“ ist auf einem Modell ohne Schneider ein sichtbarer Fehler, kein stiller Druck.

## Konsequenzen

Der Menü-Default des Druckers wird überschrieben, auch für „nicht schneiden“. Die drei Modi sind am QL-820NWB gemessen. Andere Modelle folgen derselben Befehlsreferenz der QL-800-Reihe, nicht einer zweiten Implementierung.
