# 4. GPL-3.0-or-later wegen brother_ql

Date: 2026-10-28

## Status

Accepted

Folgt aus [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

## Kontext

`brother_ql` steht unter GPL-3.0-or-later. QLInux übernimmt deren Rastercode in den Druckweg und liefert die Bibliothek in der AppImage mit. Eine schwächere oder proprietäre Lizenz wäre mit dieser Abhängigkeit nicht vereinbar.

## Entscheidung

QLInux steht unter GPL-3.0-or-later. Das gilt für den Quelltext, die AppImage und die Metadaten (`LICENSE`, About-Dialog, Metainfo).

## Konsequenzen

Beiträge stehen unter derselben Lizenz. Die Distribution muss den Quelltext erreichbar halten. LGPL-Qt sowie die MIT- und BSD-Bibliotheken daneben bleiben zulässig. Die gLabels-Vorlagen für Avery Zweckform sind ebenfalls GPL-3.0-or-later und passen dazu.
