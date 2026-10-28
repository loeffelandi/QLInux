# 14. Dialoge als Sheets im Hauptfenster

Date: 2026-10-28

## Status

Accepted

## Kontext

Eigene Fenster geraten unter Wayland und bei kachelnden Oberflächen hinter das Hauptfenster oder neben den Arbeitsfluss. Drucken braucht die Vorschau und die Optionen gleichzeitig, Öffnen und Speichern einen Dateidialog, der zum restlichen Fenster passt.

## Entscheidung

Dialoge sind Sheets im Hauptfenster. Sichtbar ist immer nur eines; ein neues schließt das vorherige. Dateidialoge sind keine nativen Fenster. Das Druck-Sheet zeigt die 1-bit-Vorschau, Qualität und Ausgabe, Kopien, Schnitt und den Druckverlauf dieser Sitzung. Der Druck startet von dort, nicht von der Werkzeugleiste allein.

Solange ein Sheet offen ist, gelten die Kurzbefehle der Anwendung nicht, außer die Aktion gehört zum Sheet.

## Konsequenzen

Es gibt keinen zweiten Fenstertitel und keinen Dialog, der auf einem anderen Arbeitsbereich hängen bleibt. Ein Ablauf, der zwei Sheets zugleich bräuchte, muss sie nacheinander öffnen.
