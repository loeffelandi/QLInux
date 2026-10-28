# 16. Avery Zweckform aus gLabels in echter Größe

Date: 2026-10-28

## Status

Accepted

## Kontext

Dieselbe Gestaltung soll einen Avery-Zweckform-Bogen füllen und an einen normalen Drucker oder in ein PDF gehen. Die Maße der A4-Vorlagen, darunter die Adressetiketten 3474 und 3475, stammen aus gLabels. Ein Einpassen in den bedruckbaren Bereich des Druckers würde die Stanzung gegen den Inhalt verschieben.

## Entscheidung

Das Ziel „Etikettenbogen“ macht die Zeichenfläche zu einem Etikett der gewählten Vorlage, nicht zur ganzen Seite. PDF und Systemdruck behalten die Seitengröße. Ein Versatz von höchstens 20 mm je Richtung schiebt den ganzen Bogen, wenn der Drucker nicht am Papierrand anfängt. Die erste Zelle gilt nur für die erste Seite, weitere Seiten beginnen bei der ersten Zelle. Kopien belegen die nächsten Zellen desselben Datensatzes. Höchstens 2000 Etiketten pro Auftrag.

Versatz, Systemdrucker und erste Zelle sind Einstellungen dieser Maschine. Die gewählte Vorlage hängt am Reiter und wird mit den Fenstereinstellungen gemerkt. Sie steht nicht in der `.qlx`.

## Konsequenzen

Das README sagt, das Produkt gehöre zum geöffneten Etikett. Die Datei trägt es nicht. Wer eine `.qlx` an einem anderen Arbeitsplatz öffnet, bekommt den dort gemerkten Bogen. Die Stanzung bleibt nur dann deckungsgleich, wenn niemand die Seite skaliert.
