# Tests so bauen, dass die Suite schnell bleibt

Stand nach dem Aufraeumen im Herbst 2026: `QT_QPA_PLATFORM=offscreen
.venv/bin/python -m pytest -q` liegt bei etwa 13 Sekunden (641 Tests).
Vorher waren es knapp 30 Sekunden, obwohl kein einzelner Test lange
rechnete. Die Zeit steckte in Fenstern, die liegen blieben.

`tests/conftest.py` raeumt das heute nach jedem Test auf. Die Regeln
hier sind trotzdem bindend: der Helfer faengt nur auf, was ein Test
offen gelassen hat. Ein neues Hauptfenster, ein Filter auf der
`QApplication` oder ein `sleep` kostet schon *in* dem Test.

Messen, bevor ein Gefuehl zur Wahrheit wird:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --durations=20
```

Ein neuer Test, der in dieser Liste auftaucht, ist zu gross geraten.

## Das kleinste Objekt, das die Frage beantwortet

`MainWindow()` baut Panels, Werkzeugleiste, Menues, Datenbankleiste und
startet die Druckersuche. Ein Aufruf kostet einige zehn Millisekunden,
dazu Menues und Combo-Popups als weitere Top-Level-Widgets. Dutzende
solcher Tests sind der Grossteil der Suite.

| Frage | Dafuer reicht |
| --- | --- |
| Rechnen, Datei, CSV, Raster, Uebersetzung | die Funktion, kein Qt |
| Ein Objekt zeichnet, klemmt, serialisiert | `LabelCanvas` oder das Item |
| Ein Formularfeld | das Panel allein |
| Menue, Reiter, Druckdialog, echtes Fenster | `MainWindow` |

Wer nur eine reine Funktion prueft und dafuer ein Fenster aufmacht,
verdoppelt Arbeit, die ein bestehender Test schon bezahlt.

## Hauptfenster

* `discover=False`, ausser der Test prueft die Suche beim Start.
  Sonst laeuft ein `QThread`, auch wenn `conftest` die Suche leer
  beantwortet.
* `show()` und `processEvents()` nur, wenn Groesse, Fokus oder ein
  Anstrich zur Aussage gehoeren. Viele Pruefungen gehen ohne beides.
* Gleicher Aufbau, gleiche Aussage: ein Test, nicht fuenf Fenster.
  Ein Helfer wie `_window(qapp)` in der Datei ist willkommen. Ein
  Fenster fuer die ganze Datei oder die Session ist es nicht. Tests
  wuerden sich sonst ueber Auswahl, Undo und Einstellungen verkuppeln.
* Nichts fuer den naechsten Test liegen lassen. `conftest` wirft
  elternlose Top-Level-Widgets mit `deleteLater` weg und bricht eine
  noch laufende Netzsuche ab. `close()` macht das nicht: `close()`
  speichert Einstellungen. Wer das speichern will, ruft `close()`
  selbst auf und prueft davor.

## Kein Filter auf der QApplication

Ein Event-Filter auf der Anwendung sieht jedes Qt-Ereignis und ruft
dafuer nach Python. Das Sheet-Overlay hat genau einen gemeinsamen
Filter (`ql_editor.sheet`), und der haengt nur, solange ein Sheet
sichtbar ist. Nicht pro Sheet einen neuen Filter installieren, und
keinen zweiten Filter fuer Tasten oder das Mausrad auf die Anwendung
legen. Filter gehoeren an das Widget, das sie meinen.

Ein Sheet im Test schliessen, sobald die Aussage geprueft ist. Sonst
laeuft der Filter bis zum Ende des Tests weiter.

## Nicht auf die Uhr warten

`time.sleep` und eine Schleife bis zu einer Deadline sind keine
Synchronisation. Die Scroll-Animation ist im Test abgeschaltet
(`SmoothScroller` mit Dauer 0), damit das Rad sofort einen neuen
Wert setzt. Wer trotzdem 10 ms schlaeft, bis sich eine Scrollbar
bewegt, prueft den Timer und nicht das Verhalten.

Wenn ein Signal ueber den Event-Loop kommt (Socket, `deleteLater`),
ein paar Mal `processEvents()`. Reicht das nicht, ist der Test an
ein Zeitfenster gebunden und wird auf einer langsamen Maschine rot.

Echte Geraete-Timeouts (`probe_status(..., timeout=0.1)`) bleiben,
weil sie das Verhalten der Funktion sind. Zusaetzlich schlafen nicht.

## Kleine Daten

Eine Grenze knapp ueberschreiten reicht. Das Verkleinern grosser
Fotos haengt an `IMAGE_MAX_SIDE_PX`. Ein Bild knapp darueber prueft
dieselbe Aussage wie 6000×4000 und spart das Kodieren. Dasselbe gilt
fuer lange Etiketten, viele Datensaetze und grosse Szenen: so viel,
dass der Zweig greift, und nicht mehr.

## Was die Umgebung schon festlegt

Nicht noch einmal bauen und nicht unterlaufen:

* Offscreen-Qt (`QT_QPA_PLATFORM`, ueberschreibbar nur mit
  `QLINUX_TEST_PLATFORM`).
* `XDG_CONFIG_HOME` zeigt auf ein leeres Temp-Verzeichnis. Tests
  lesen und schreiben nicht die echten Einstellungen.
* Eine `QApplication` fuer die ganze Session (`qapp`). Keine zweite
  erzeugen.
* Die Oberflaeche startet auf Deutsch.
* `discover_network_printers` liefert `[]`. Wer Treffer braucht,
  patcht die Funktion in `ql_editor.app` (und bei Bedarf im
  Medien-Panel) im eigenen Test.
* Kein Test geht ins Netz und keiner oeffnet ein echtes Fenster.
