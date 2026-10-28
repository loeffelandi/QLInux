# 12. Druckersuche selbst über mDNS und SNMP

Date: 2026-10-28

## Status

Accepted

Setzt voraus [3. brother_ql 0.9.4 ist die einzige Druckerquelle](0003-brother-ql-0-9-4-ist-die-einzige-druckerquelle.md)

## Kontext

`brother_ql` 0.9.4 wirft bei der Netzwerksuche `NotImplementedError`. Auf dem Dienst `_pdl-datastream._tcp` melden sich auch Drucker, die keinen QL-Rasterauftrag verstehen. Eine Suche soll den avahi-Daemon nicht stören und sich abbrechen lassen, wenn das Fenster zugeht.

## Entscheidung

QLInux sucht selbst, ohne Zusatzpaket, parallel über zwei Wege. mDNS fragt `_pdl-datastream._tcp.local` mit gesetztem QU-Bit von einem freien Port, bindet also nicht an 5353. SNMP schickt einen Broadcast an UDP 161, Community `public`. Aufgenommen wird nur, was wie ein Brother-QL aussieht. Treffer derselben IP werden zusammengeführt, der lesbare mDNS-Name gewinnt. Die Suche endet nach 0,25 Sekunden Ruhe, spätestens nach 2 Sekunden, und lässt sich abbrechen. Ein unbekanntes QL-Modell bleibt in der Liste; das Modell wählt man dann von Hand.

Eine einzelne Fundstelle wird ausgewählt. Sonst bleibt der letzte Eintrag der Liste die Eingabe einer IP. Eine nackte Adresse wird zu `tcp://…:9100`; ein abweichender Port bleibt stehen.

## Konsequenzen

Es gibt keine Abhängigkeit zu avahi oder pysnmp. Drucker ohne mDNS und ohne SNMP mit Community `public` erscheinen nicht. Für die bleibt die IP-Eingabe.
