# Design

## Context

Siehe `proposal.md`. Stand im Code:

- Enter im Druck-Sheet hängt an zwei `QShortcut` (Return, Enter) mit `WindowShortcut`-Kontext am Druck-Panel (`ql_editor/app.py`). Das Panel ist ohne Sheet versteckt, deshalb greift der Kurzbefehl auf der Zeichenfläche nicht. `_on_print_key` klickt einen fokussierten fremden Knopf, sonst startet es `_on_print`.
- Das Sheet (`ql_editor/sheet.py`) setzt beim Öffnen den Fokus auf sich selbst, außer es enthält einen `QDialog`. `QMessageBox` ist einer, darum bleibt bei Meldungen und Rückfragen der Fokus auf der Zeichenfläche.
- Alle Kurzbefehle außerhalb des Sheets filtert `_SheetShortcutFilter`, solange ein Sheet sichtbar ist.
- Die vorhandenen Tests ersetzen `_on_print` durch einen Zähler und prüfen unter Qt offscreen. Sie zeigen, dass der Kurzbefehl feuert, nicht, dass auf einem echten Fenster der Druck startet.

Beobachtet: Strg+P gefolgt von Enter löst `_on_print` aus, offscreen, unter X11 (Ubuntu 24.04, Xfce) und unter Wayland (weston), bei jedem Fokus im Druck-Sheet. Unter Pop!_OS mit COSMIC tut es nichts. Die Ursache ist nicht bekannt, COSMIC stand zum Messen nicht zur Verfügung.

## Goals / Non-Goals

**Goals:**

- Enter im Druck-Sheet startet den Druck auf X11 und Wayland, ohne dass die Zeichenfläche oder ein Feld im Weg ist.
- Rückfragen und Meldungen reagieren auf Enter, ohne dass Enter hinter dem Sheet landet.

**Non-Goals:**

- Neue Tasten, ein anderes Standardverhalten der Rückfragen, Umbau des Druckablaufs.

## Decisions

### 1. Zuerst nachstellen, dann den Weg wählen

Die Umsetzung begann mit einer Messung (X11 und Wayland): Wer hat nach Strg+P den Fokus (`QApplication.focusWidget()`), feuert `_on_print_key`, und was passiert danach in `_on_print`? Die Ursache bestimmt, welcher der Wege unten nötig ist. Ein Fix auf Verdacht kommt nicht in Frage, weil die Tests offscreen schon grün sind.

Kandidaten für die Ursache:

- Der Kurzbefehl wird auf dem echten Fenstersystem nicht zugestellt (Kontext hängt an aktivem Fenster und Sichtbarkeit des Panels; unter Wayland wird die Aktivierung später gemeldet).
- Die Taste kommt an, aber `_on_print` endet still, zum Beispiel weil eine Rückfrage (Störung, falsches Band) das Druck-Sheet verdrängt und Enter dort wirkungslos ist. Das ist die zweite Lücke aus dem Vorschlag.
- Ein Feld im Sheet verschluckt Enter, bevor der Kurzbefehl greift.

### 2. Enter im Sheet statt am Panel

Ist die Zustellung des Kurzbefehls die Ursache, behandelt das Sheet Enter selbst: Es bekommt einen optionalen Aufrufer für „Enter gedrückt“ und fängt `KeyPress` für Return und Enter von Widgets innerhalb des Sheets ab, über denselben gemeinsamen Filter wie die Kurzbefehle. Das Druck-Sheet gibt `_on_print_key` mit. Vorteil: Das Verhalten hängt nicht an der Fensteraktivierung, sondern an dem, was im Sheet geschieht.

Alternative: Kurzbefehle behalten und Kontext auf `ApplicationShortcut` stellen. Verworfen, weil er dann auch bei geschlossenem Sheet feuert und der Schutz „Enter auf der Zeichenfläche druckt nicht“ (Scenario „Sheet zu“) vom Zustand des Panels abhängt.

### 3. Fokus bei Rückfragen

`Sheet.showEvent` setzt den Fokus auf den Standardknopf des enthaltenen `QMessageBox` statt ihn bei der Zeichenfläche zu lassen. Damit löst Enter den Standardknopf aus, und die Taste geht nicht an die Zeichenfläche. Dateidialoge behalten ihr eigenes Fokusverhalten.

### 4. Tests prüfen den Nutzerweg

Neue Tests öffnen das Sheet per Strg+P, schicken Enter an `QApplication.focusWidget()` und prüfen, dass `_start_print` mit dem gerenderten Etikett aufgerufen wird (statt `_on_print` zu ersetzen). Dazu je ein Test pro Fokusziel (Sheet, Kopien, Schwelle, Auswahlfeld, Verlaufstabelle, fremder Knopf) und für die Rückfragen.

## Risks / Trade-offs

- [Offscreen-Tests bilden X11/Wayland nur begrenzt ab] → Die Messung unter Pop!_OS ist Teil der Aufgaben, nicht nur ein Test in der CI.
- [Enter im Sheet fangen kann Felder stören, die Enter selbst brauchen, etwa ein Texteingabefeld] → Der Filter greift nur bei Tasten ohne Modifier und lässt mehrzeilige Eingabefelder aus. Im Druck-Sheet gibt es heute keine.
- [Standardknopf bei „Band prüfen“ ist „Abbrechen“, ein Nutzer, der Enter zum Drucken erwartet, bricht damit ab] → Das ist gewollt: Eine falsche Bandwahl soll nicht durch einen reflexhaften Enter gedruckt werden.
