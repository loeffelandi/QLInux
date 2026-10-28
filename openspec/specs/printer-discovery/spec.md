# Druckersuche

## Purpose

Netzwerkdrucker werden ohne Adresskenntnis gefunden. USB-Geräte erscheinen über ihren einen Anschluss. Hauptorte: `ql_editor/discovery.py`, `ql_editor/printer.py`.

## Requirements

### Requirement: mDNS und SNMP gemeinsam

Die Suche SHALL `_pdl-datastream._tcp.local` per mDNS und einen SNMP-Broadcast an UDP 161 mit Community `public` parallel fragen. Sie MUST NOT Port 5353 belegen. Aufgenommen SHALL nur werden, was wie ein Brother-QL aussieht. Dieselbe IP SHALL ein Eintrag sein, der lesbare mDNS-Name gewinnt. Die Suche MUST nach 0,25 Sekunden ohne weitere Antwort enden, spätestens nach 2 Sekunden, und MUST abbrechbar sein.

#### Scenario: Fremder Drucker auf demselben Dienst

- **WHEN** ein Drucker den PDL-Dienst meldet und nicht wie ein Brother-QL aussieht
- **THEN** erscheint er nicht in der Liste

#### Scenario: Ein Treffer

- **WHEN** die Suche genau einen Brother-QL findet
- **THEN** wird dieser Eintrag ausgewählt

### Requirement: Adresse von Hand

Ist die Liste leer, SHALL ihr letzter Eintrag die Eingabe einer Adresse anbieten. Eine Adresse ohne Port SHALL zu `tcp://…:9100` werden. Ein angegebener anderer Port MUST erhalten bleiben. IPv6 MUST NOT am Doppelpunkt zerschnitten werden.

#### Scenario: Nur die IP

- **WHEN** `192.168.1.20` eingegeben wird
- **THEN** lautet die Druckeradresse `tcp://192.168.1.20:9100`

### Requirement: Ein USB-Eintrag

Die Liste SHALL pro USB-Drucker einen Anschluss zeigen. Das MUST der Kernel-Knoten sein, solange er existiert, und sonst `usb://` ohne Seriennummer. Eine Netzwerkadresse SHALL das Modell nicht festlegen.

#### Scenario: Kernel-Knoten vorhanden

- **WHEN** für einen Drucker `/dev/usb/lp*` und `usb://` derselben Kennung sichtbar sind
- **THEN** bietet die Liste nur den Kernel-Knoten an
