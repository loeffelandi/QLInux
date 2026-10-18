# Hilfe im Programm

Die Hilfe hängt am Menüpunkt Hilfe. Sie ist ein Sheet wie die übrigen
Dialoge, auf Deutsch und auf Englisch. Der Text steht in
`ql_editor/help.py`, die englischen Sätze in `ql_editor/translations.py`.

Ändert sich ein Verhalten oder eine Taste, wird die Hilfe im selben
Schritt mit geändert: beide Sprachen, und die Tastenübersicht. Eine neue
Taste ist erst fertig, wenn sie in dieser Übersicht steht, deutsch und
englisch.

Fett, kursiv und unterstrichen stehen als Strg+B, Strg+I und Strg+U.
Das linke Panel ist F9, das rechte Umschalt+F9. Strg+B und
Strg+Umschalt+B sind keine Panels.

## Grundregel für Sheets

Ein Sheet, das nur etwas zeigt, geht zu, wenn man neben die Karte auf
die Abdunklung klickt. Esc macht dasselbe. Hilfe und Über QLInux sind so
gebaut (`close_on_outside`). Ein Dialog, der eine Antwort braucht,
bleibt offen, bis man ihn beantwortet.
