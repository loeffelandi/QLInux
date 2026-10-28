# 15. Vorlagen sind gewöhnliche .qlx ohne Modell

Date: 2026-10-28

## Status

Accepted

Setzt voraus [6. Etikett als .qlx, die Maschine bleibt draußen](0006-etikett-als-qlx-maschine-bleibt-draussen.md)

## Kontext

Die mitgelieferten Etiketten (Adresse, Paket, Kabel, Ordnerrücken, Preisschild, WLAN-QR, Inventar) sollen auf jedem Endlosband benutzbar sein. Eine Vorlage, die ein Druckermodell festschreibt, würde den Drucker des Empfängers mit umstellen. Eigene Vorlagen sollen sich wie normale Dateien kopieren und verschicken lassen.

## Entscheidung

Vorlagen sind `.qlx`-Dateien ohne Modell, auf 62-mm-Endlosband mit automatischer Länge. Sieben sind eingebaut. Eigene liegen unter `~/.config/QLInux/templates/`. Die Beispieltexte folgen der Oberflächensprache. Anwenden übernimmt das Medium der Vorlage und lässt das Modell der aktuellen Oberfläche stehen.

## Konsequenzen

Eine eigene Vorlage ist eine gewöhnliche Etikettdatei. Der Ordnerrücken ist entlang des Bandes ausgerichtet, die übrigen quer. Wer eine Vorlage auf ein Die-cut-Band zieht, verlässt diese Annahme; die Vorlage selbst schreibt das Band nicht auf ein Modell fest.
