# Spec Delta

## ADDED Requirements

### Requirement: USB ohne Kernel-Knoten

Auf einem System ohne Kernel-Treiberknoten für Drucker, etwa dem Mac, SHALL die Liste den USB-Drucker über `usb://` mit Hersteller und Produkt zeigen, ohne Seriennummer. Schlägt die USB-Suche fehl, etwa weil libusb fehlt, SHALL die Liste leer bleiben und MUST NOT einen Fehler zeigen.

#### Scenario: Ein Drucker am Mac

- **WHEN** auf dem Mac ein QL-700 per USB angeschlossen ist
- **THEN** bietet die Liste genau einen Eintrag `usb://0x04f9:0x2042` an
- **AND** der Eintrag nennt das Modell QL-700

#### Scenario: libusb nicht ladbar

- **WHEN** die USB-Suche mit einem Fehler der Bibliothek endet
- **THEN** bleibt die Liste der USB-Drucker leer
- **AND** die Netzwerksuche läuft weiter

### Requirement: Broadcast je Schnittstelle

Die SNMP-Suche SHALL ihr Paket an `255.255.255.255` und zusätzlich an die Broadcast-Adresse jeder aktiven Schnittstelle senden, unter Linux und auf dem Mac. Eine Schnittstelle ohne Broadcast-Adresse MUST übersprungen werden. Dieselbe Adresse MUST nur einmal angesprochen werden.

#### Scenario: Zwei Netze

- **WHEN** der Rechner mit einem WLAN (192.168.178.0/24) und einem Kabel (10.0.0.0/24) verbunden ist
- **THEN** geht das Suchpaket an beide Broadcast-Adressen und an `255.255.255.255`

#### Scenario: Schnittstelle ohne Broadcast

- **WHEN** eine Schnittstelle, etwa `lo0`, keine Broadcast-Adresse hat
- **THEN** wird sie übersprungen
- **AND** die Suche an die übrigen Adressen läuft weiter
