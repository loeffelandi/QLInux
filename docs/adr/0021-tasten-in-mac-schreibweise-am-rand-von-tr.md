# 21. Tasten in Mac-Schreibweise am Rand von tr()

Date: 2026-11-27

## Status

Accepted

## Kontext

Qt bildet `Ctrl` auf dem Mac auf ⌘ ab, `Alt` auf ⌥. Kürzel und Mausgesten verhalten sich also richtig; falsch ist die Anzeige. Rund sechzig Tooltips, die Hilfe, die Befehlssuche und `paste_hint()` sagen „Strg“. `QKeySequence.toString(NativeText)` an jeder Stelle gäbe auf dem Mac Symbole, unter Linux aber Qts Sprache statt der Sprache der Oberfläche, und es änderte sechzig Stellen.

## Entscheidung

`tr()` und `paste_hint()` wandeln ihr Ergebnis auf dem Mac mit `platform_support.mac_keys()` um: `Strg`/`Ctrl`→⌘, `Umschalt`/`Shift`→⇧, `Alt`→⌥, `Entf`/`Del`→⌫. Kombinationen mit einer Taste werden zusammengezogen (⇧⌘S), Kombinationen mit einem Wort bekommen einen Strich (⌘-Klick). Eine Tabelle mit Sonderfällen geht vor: ⌃Tab und ⌃⇧Tab für den Reiterwechsel, weil ⌘Tab dem Programmwechsel gehört, ⌘W statt Strg+F4, ⇧⌘Z statt Strg+Y. Der Reiterwechsel selbst liegt auf `Meta+Tab` (in Qt die Control-Taste). Ein Test schickt alle Texte aus `translations.py` durch `tr()` und verlangt, dass „Strg“ und „Ctrl“ nicht übrig bleiben. Unter Linux bleibt alles, wie es war.

## Konsequenzen

Neue Texte mit Tastenkürzeln brauchen nichts Besonderes, solange sie „Strg+…“ schreiben. Ein Wort „Strg“ im Fließtext würde ersetzt; der Test fängt das. Die Umwandlung ist eine Textersetzung und kennt keine Tastenbelegung: ändert sich eine Belegung, ändert sich auch die Tabelle der Sonderfälle.
