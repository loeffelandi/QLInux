# 10. Netzwerkstatus über SNMP, Bandlesen nur über USB

Date: 2026-10-28

## Status

Accepted

Setzt voraus [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

## Kontext

Port 9100 des QL-820NWB nimmt den Druck an und antwortet nicht auf die Statusabfrage. Die 32 Statusbytes, aus denen Band und Fehler gelesen werden, kommen über USB. Derselbe Drucker beantwortet SNMP. Ein stilles Netzwerk nach dem Senden ist kein nachgewiesener Fehler. Eine gemeldete Störung soll den Auftrag nicht ungefragt starten.

## Entscheidung

„Band erkennen“ läuft nur über Backends mit Rückkanal (`pyusb`, `linux_kernel`). Für das Netzwerk fragt QLInux SNMP (Community `public`), und nur dann, wenn der Drucker SNMP schon beantwortet hat.

Vor dem Senden wird bei einer gemeldeten Störung nachgefragt. Nach dem Senden gilt der Auftrag als bestätigt, als unbestätigt, wenn keine Antwort kommt, oder als Fehler, wenn SNMP eine Störung meldet. Nach einem bestätigten Auftrag merkt sich QLInux das eingelegte Band und fragt, bevor ein anderes gedruckt wird. Die Abfrage läuft, solange das Fenster aktiv ist, und hält das Schließen nicht auf.

## Konsequenzen

Ohne SNMP bleibt ein Netzwerkauftrag beim Ergebnis „gesendet“. Die gemerkte Band ist eine Erinnerung an den letzten bestätigten Auftrag, keine Messung. USB-Fehler bleiben der bisherige direkte Fehlerweg.
