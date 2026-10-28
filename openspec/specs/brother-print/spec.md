# Band und Brother-Druck

## Purpose

Band, Auflösung, Schnitt, Kopien und die 1-bit-Vorschau folgen `brother_ql` und den in QLInux ergänzten Befehlen. Hauptorte: `ql_editor/media.py`, `ql_editor/printer.py`, `ql_editor/preview.py`, `ql_editor/renderer.py`.

## Requirements

### Requirement: Band aus der Bibliothek

Modelle und Bänder SHALL aus `brother_ql` kommen. Die Anwendung MUST NOT eine eigene Modellliste für die Bandwahl führen. Rot SHALL nur wählbar sein, wenn Modell und Band zweifarbigen Druck können. Die feste Länge in der Oberfläche SHALL die Gesamtlänge einschließlich der Ränder sein. Bei einem Die-cut- oder runden Band SHALL die Länge die des Bandes sein.

#### Scenario: Modell ohne Rot

- **WHEN** das gewählte Modell oder das Band keinen zweifarbigen Druck kann
- **THEN** lässt sich Rot nicht einschalten

### Requirement: Exaktes Druckbild und 600 dpi

Das gerenderte Bild MUST exakt die bedruckbare Breite des Bandes haben. 600 dpi SHALL nur für QL-800, QL-810W und QL-820NWB angeboten werden und MUST beide Achsen mit Faktor 2 rendern. 600 dpi MUST NOT eine Qualitätsstufe sein. Der Schalter „Qualität vor Tempo“ SHALL getrennt davon bleiben.

#### Scenario: Anderes Modell

- **WHEN** ein Modell außerhalb von QL-800, QL-810W und QL-820NWB gewählt ist
- **THEN** bietet die Auflösung 600 dpi nicht an

### Requirement: Schnitt und Kopien

Ein Auftrag SHALL nach jedem Etikett, nur am Ende oder gar nicht schneiden. Zwischen den Kopien MUST `0x0C` stehen und nur die letzte Seite MUST mit `0x1A` enden. Die Seitenzahl eines Auftrags MUST NOT über 99 liegen. Auf einem Modell ohne Schneider MUST jeder Zuschnitt außer „keins“ ein sichtbarer Fehler sein und MUST NOT stillschweigend drucken.

#### Scenario: Nur am Ende

- **WHEN** mehrere Kopien mit Schnitt „nur am Ende“ erzeugt werden
- **THEN** endet nur die letzte Seite mit `0x1A`
- **AND** die Seiten davor enden mit `0x0C`

### Requirement: Vorschau ist das Druckbild

Die Vorschau SHALL dieselben 1-bit-Daten zeigen wie der Druck, einschließlich Schwelle und Dithering. Die 1:1-Einblendung auf der Zeichenfläche SHALL dieses Bild in der bedruckbaren Fläche zeichnen. Liegt der Zoom darunter, SHALL das Einschalten der Einblendung auf 100 Prozent gehen.

#### Scenario: Dieselbe Schwelle

- **WHEN** die Schwelle im Druck-Sheet geändert wird
- **THEN** ändern sich Vorschau und das Bild, das an `convert()` ginge, gemeinsam
