# Spec Delta

## ADDED Requirements

### Requirement: Bogenzeichnung der ersten Zelle

Solange das Ziel „Etikettenbogen“ ist, SHALL unter „Erstes Etikett“ eine Zeichnung der gewählten Vorlage stehen. Jedes Feld SHALL seine Nummer tragen, bei 1 links oben, zeilenweise. Die Form SHALL der Vorlage folgen: Rechteck, abgerundete Ecken oder ein Ring mit Loch.

#### Scenario: Nummer auf einem 3-mal-8-Bogen

- **WHEN** die Vorlage 3475 gezeigt wird
- **THEN** trägt das Feld in der zweiten Zeile und zweiten Spalte die Nummer 5

#### Scenario: Klick ins Loch eines CD-Etiketts

- **WHEN** eine CD-Vorlage gezeigt wird und das Loch eines Rings angeklickt wird
- **THEN** wird die Nummer dieses Etiketts die erste Zelle

### Requirement: Klick und Zahl bleiben gleich

Ein Klick auf ein Feld SHALL die erste Zelle auf diese Nummer setzen, auch wenn sie vor der bisherigen liegt. Das Zahlenfeld und die Zeichnung SHALL dieselbe Zahl zeigen. Eine geänderte Zahl SHALL die Zeichnung neu setzen. Felder vor der Zahl SHALL schon bedruckt aussehen, das gewählte Feld SHALL hervorgehoben sein, die übrigen SHALL leer bleiben.

#### Scenario: Klick auf ein früheres Feld

- **WHEN** die erste Zelle 8 ist und Feld 3 angeklickt wird
- **THEN** ist die erste Zelle 3
- **AND** Feld 3 ist hervorgehoben
- **AND** die Felder 1 und 2 sehen schon bedruckt aus

#### Scenario: Zahl im Feld ändern

- **WHEN** „Erstes Etikett“ auf 4 gesetzt wird
- **THEN** ist Feld 4 hervorgehoben
- **AND** die Felder 1 bis 3 sehen schon bedruckt aus

### Requirement: Die Zeichnung folgt der Vorlage

Ein Wechsel der Vorlage SHALL die Zeichnung auf deren Raster umstellen. Liegt die bisherige erste Zelle über der Feldzahl der neuen Vorlage, SHALL sie auf das letzte Feld geklemmt werden.

#### Scenario: Kleinere Vorlage

- **WHEN** die erste Zelle 20 ist und eine Vorlage mit 8 Feldern gewählt wird
- **THEN** ist die erste Zelle 8
- **AND** die Zeichnung zeigt 8 Felder
