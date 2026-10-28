# Design

## Context

Siehe proposal.md, Why. Die erste Zelle ist `print/sheet_start`, ein Spin-Feld im Kasten Avery Zweckform, und gilt in `plan_sheet` nur für die erste Seite (ADR 0016). Das linke Panel ist 300 px breit, der Inhalt scrollt. Vorlagen sind regelmäßige Raster, bis 5×16 Felder, plus CD-Ringe mit Loch.

## Goals / Non-Goals

**Goals:**

- Eine Zeichnung, die dieselbe Startzahl zeigt und setzt wie das Spin-Feld.
- Treffer und Form aus den Maßen der Vorlage, ohne den Druckweg anzufassen.

**Non-Goals:**

- Keine neue Architekturentscheidung und kein neues ADR. ADR 0016 bleibt.
- `plan_sheet`, die Obergrenze von 2000 Etiketten und der Versatz bleiben.
- Die Startzahl wandert nicht in die `.qlx`.
- Die Druckvorschau im Druckdialog bleibt das Raster mit den echten Etiketten, nicht diese Zeichnung.

## Decisions

1. **Eigenes Widget `SheetStartPicker` in `ql_editor/sheet_picker.py`.** Es malt nur und kennt keinen Drucker. `sheet_output.py` bleibt für PDF und Systemdruck. Alternative: die Seitenvorschau wiederverwenden. Die malt Etikettenbilder und graue Umrisse, keine Nummern, und hängt am Auftrag.

2. **Das Spin-Feld bleibt die Quelle.** Ein Klick setzt seinen Wert. `valueChanged` zeichnet die Auswahl neu. Signale werden dabei kurz gesperrt, damit sich die beiden nicht im Kreis schreiben. Alternative: das Spin-Feld entfernen. Tippen einer bekannten Zahl und die bestehende Einstellung fielen weg.

3. **Die Zeichnung steht im linken Kasten, unter „Erstes Etikett“.** Der Kasten ist schon ausgeblendet, solange das Ziel Brother QL ist. Alternative: ein eigenes Sheet. Der Klick wäre dann ein zweiter Schritt, obwohl die Zahl schon im Panel steht.

4. **Treffer über die Außenform.** Ein Klick ins CD-Loch trifft dasselbe Etikett. Gezeichnet wird der Ring mit Loch, das Rechteck oder die abgerundeten Ecken, über `slot_origin`. Nummern bleiben auch beim dichtesten Raster sichtbar, die Schrift schrumpft mit dem Feld. Farben kommen aus der Palette.

5. **Die Höhe folgt der Seitenproportion und der Breite des Kastens.** Das Panel scrollt. Alternative: feste kleine Kacheln ohne Seitenrand. Dann sähe ein CD-Bogen aus wie ein Adressbogen.

## Risks / Trade-offs

- [80 Nummern auf schmalem Panel werden klein] → Schrift skaliert mit dem Feld, fällt aber nicht weg. Das Spin-Feld bleibt für die genaue Zahl.
- [Zwei Widgets schreiben dieselbe Zahl] → dieselbe Zahl ignorieren und Signale sperren.
- [Qt klemmt das Spin-Feld beim Vorlagenwechsel selbst] → die Zeichnung liest danach den geklemmten Wert, sie klemmt nicht noch einmal.

## Migration Plan

Keine Datenwanderung. `print/sheet_start` bleibt. Rückbau heißt, die Zeichnung aus dem Kasten zu nehmen; die Zahl und der Druck bleiben.

## Open Questions

Keine.
