# 19. Deutsch und Englisch, Erscheinungsbild folgt dem System

Date: 2026-10-28

## Status

Accepted

## Kontext

Die Oberfläche soll auf Deutsch und Englisch benutzbar sein, ohne die Anwendung neu zu starten. Hell und dunkel sollen dem System folgen können, ohne dass die Zeichenfläche ihre eigenen Farben verliert.

## Entscheidung

Die Quellsprache ist Deutsch. Englisch steht in `ql_editor/translations.py`. Der Wechsel baut die Oberfläche neu auf. Dabei geht der Undo-Stapel verloren. Der Druckverlauf dieser Sitzung bleibt. Das Erscheinungsbild ist System, Hell oder Dunkel, über eine eigene Fusion-Palette. Folgt es dem System, zieht ein Wechsel der Desktop-Farben nach. Die Zeichenfläche übernimmt diese Palette nicht.

## Konsequenzen

Ein Sprachwechsel ist keine Undo-Operation. Jeder neue sichtbare Text braucht den deutschen Quelltext und einen englischen Eintrag. Die Zeichenfläche bleibt in beiden Erscheinungsbildern lesbar, auch wenn der Rest der Anwendung die Systemfarben übernimmt.
