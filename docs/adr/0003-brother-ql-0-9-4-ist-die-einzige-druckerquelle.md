# 3. brother_ql 0.9.4 ist die einzige Druckerquelle

Date: 2026-10-28

## Status

Accepted

Setzt voraus [2. Native PySide6-App ohne Browser und ohne Vendor-Treiber](0002-native-pyside6-app-ohne-browser-und-ohne-vendor-treiber.md)

Zieht nach sich [4. GPL-3.0-or-later wegen brother_ql](0004-gpl-3-0-or-later-wegen-brother-ql.md)

Wird vorausgesetzt von [8. Druckbild exakt in der bedruckbaren Punktzahl](0008-druckbild-exakt-in-der-bedruckbaren-punktzahl.md)

Wird vorausgesetzt von [9. Schnitt und Kopien im Rasterstrom](0009-schnitt-und-kopien-im-rasterstrom.md)

Wird vorausgesetzt von [10. Netzwerkstatus über SNMP, Bandlesen nur über USB](0010-netzwerkstatus-ueber-snmp-bandlesen-nur-ueber-usb.md)

Wird vorausgesetzt von [12. Druckersuche selbst über mDNS und SNMP](0012-druckersuche-selbst-ueber-mdns-und-snmp.md)

## Kontext

`brother_ql` 0.9.4 liefert Modelle, Bänder und die Rasterbefehle. Die Oberfläche, gegen die der erste Entwurf geschrieben wurde, gibt es so nicht mehr: `devicedependent` ist nur noch ein Shim, `label_specs` existiert nicht, Enums sind keine Strings. Die Bibliothek kennt weder den 600-dpi-Modus noch USB-Produktkennungen noch eine Netzwerksuche. Pillow 10 hat `Image.ANTIALIAS` entfernt, `conversion.py` benutzt es noch.

## Entscheidung

Modelle, Bänder und Rasterbefehle kommen aus `brother_ql` 0.9.4. Die Version bleibt gepinnt. Der Code importiert `brother_ql.labels` und `brother_ql.models` direkt. Die Bandwahl hartcodiert keine Modellliste.

Drei Lücken füllt QLInux selbst, weil die Bibliothek sie nicht kennt: `printer.DPI_600_MODELS`, `printer.USB_MODELS` und die Suche in `ql_editor.discovery`. `scripts/patch_brother_ql.py` ersetzt nur das eine Vorkommen von `Image.ANTIALIAS` durch `Image.LANCZOS` und ist idempotent.

`docs/API_NOTES.md` hält die gemessenen Befehle fest. Sie ist die Notiz zur Bibliothek, nicht eine zweite Implementierung.

## Konsequenzen

Ein Upgrade von `brother_ql` ist eine eigene Entscheidung, kein Nebenbei-Bump. Neue Bänder erscheinen von selbst, neue Modelle in den drei gepflegten Listen nicht. Der Patch muss nach jeder Neuinstallation der Bibliothek wieder laufen; `scripts/bootstrap_venv.sh` tut das.
