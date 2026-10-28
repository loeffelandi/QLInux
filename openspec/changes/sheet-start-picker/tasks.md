# Tasks

## 1. Zeichnung

- [x] 1.1 `SheetStartPicker` in `ql_editor/sheet_picker.py` anlegen: Raster über `slot_origin`, Nummern ab 1 zeilenweise, Rechteck, abgerundete Ecken und CD-Ring, graue Felder vor der Startzahl, hervorgehobenes gewähltes Feld, leerer Rest, Treffer über die Außenform. Prüfen: das Widget lässt sich mit einer Vorlage 3475 und einer CD-Vorlage bauen, ohne `sheet_output` zu importieren.
- [x] 1.2 In `tests/test_stationery.py` prüfen, dass die Mitte von Feld 5 bei 3475 (3×8) die Nummer 5 trifft und ein Klick ins Loch einer CD-Vorlage dieses Etikett trifft. Prüfen: die beiden Tests laufen grün.

## 2. Linkes Panel

- [x] 2.1 Die Zeichnung in `_build_sheet_box` unter „Erstes Etikett“ einsetzen. Klick setzt das Spin-Feld, `valueChanged` und Vorlagenwechsel setzen die Zeichnung, Signale nicht im Kreis. Die bestehende Klemmung der Startzahl bleibt am Spin-Feld. Prüfen: ein Testfenster im Ziel Etikettenbogen zeigt die Zeichnung, ein Klick ändert `sheet_start`, Tippen im Spin-Feld hebt dasselbe Feld hervor, und bei Brother QL ist der Kasten samt Zeichnung unsichtbar.
- [x] 2.2 Diesen Ablauf in `tests/test_stationery.py` neben den bestehenden Sichtbarkeitstests des Avery-Kastens ablegen. Prüfen: der neue Test läuft grün.

## 3. Texte

- [x] 3.1 Im README am Absatz zum ersten Etikett und in der Hilfe links einen Satz ergänzen, dass man das erste freie Feld auf der Bogenzeichnung anklickt. Neue deutsche `tr()`-Texte in `ql_editor/translations.py` auf Englisch nachziehen. Prüfen: `tests/test_i18n.py` ist grün und der Hilfetext enthält den neuen Satz auf Deutsch und Englisch.
