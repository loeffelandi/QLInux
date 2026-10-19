"""Das Hilfe-Sheet.

Gleiche Form wie „Über QLInux": ein Sheet im Hauptfenster, kein eigenes
Fenster. Der Text ist absichtlich kurz. Die Tastenübersicht steht auf
Deutsch und Englisch (siehe ``docs/hilfe.md``). Ein Klick auf die
Abdunklung schließt das Sheet, genau wie Esc.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .i18n import paste_label, tr
from .icons import icon
from .sheet import Sheet, show_widget

_HINT_STYLE = "color:#6b7280;"
_ICON_PX = 20


def action_shortcuts() -> tuple[tuple[str | None, str, str], ...]:
    """Tasten der Befehle, in der aktuellen Sprache.

    ``(Icon oder None, Taste, was sie tut)``. Die deutschen Texte sind die
    Schlüssel und stehen deshalb als Literale. Fett, kursiv und unterstrichen
    sind Strg+B, Strg+I und Strg+U. Die Panels sind F9 und Umschalt+F9.
    """
    return (
        ("new", tr("Strg+N"), tr("Neues Etikett")),
        ("open", tr("Strg+O"), tr("Etikett öffnen")),
        ("save", tr("Strg+S"), tr("Etikett speichern")),
        ("save_as", tr("Strg+Umschalt+S"), tr("Speichern unter…")),
        ("close", tr("Strg+F4"), tr("Reiter schließen")),
        ("chevron_right", tr("Strg+Tab"), tr("Nächster Reiter")),
        ("chevron_left", tr("Strg+Umschalt+Tab"), tr("Vorheriger Reiter")),
        ("undo", tr("Strg+Z"), tr("Rückgängig")),
        ("redo", tr("Strg+Y"), tr("Wiederholen")),
        ("delete", tr("Entf"), tr("Auswahl löschen")),
        ("copy", tr("Strg+C"), tr("Kopieren")),
        ("cut", tr("Strg+X"), tr("Ausschneiden")),
        ("paste", tr("Strg+V"), paste_label()),
        ("duplicate", tr("Strg+D"), tr("Duplizieren")),
        ("bold", tr("Strg+B"), tr("Fett")),
        ("italic", tr("Strg+I"), tr("Kursiv")),
        ("underline", tr("Strg+U"), tr("Unterstrichen")),
        ("zoom_fit", tr("Strg+0"), tr("Einpassen")),
        ("zoom_in", tr("Strg++"), tr("Vergrößern")),
        ("zoom_out", tr("Strg+-"), tr("Verkleinern")),
        ("zoom_100", tr("Strg+1"), tr("Zoom 1:1")),
        ("panel_left", tr("F9"), tr("Panel links")),
        ("panel_right", tr("Umschalt+F9"), tr("Panel rechts")),
        ("menu", tr("Strg+K"), tr("Befehl suchen")),
        ("print", tr("Strg+P"), tr("Druckdialog")),
        ("preview", tr("Strg+Umschalt+P"), tr("Druckvorschau")),
    )


def canvas_shortcuts() -> tuple[tuple[str | None, str, str], ...]:
    """Tasten, die der Canvas selbst auswertet, ohne eigene Aktion."""
    return (
        (None, tr("Esc"), tr("Tippen beenden und die Auswahl aufheben")),
        (None, tr("Pfeiltasten"), tr("Um einen Punkt verschieben")),
        (None, tr("Umschalt+Pfeiltasten"), tr("Um zehn Punkte verschieben")),
        ("delete", tr("Rücktaste"), tr("Auswahl löschen")),
        (None, tr("Strg+Ziehen"), tr("Ausgewähltes Objekt duplizieren")),
        (None, tr("Tab"), tr("Nächste Zelle")),
        (None, tr("Umschalt+Tab"), tr("Vorherige Zelle")),
        ("text", tr("Eingabe"), tr("Zelle bearbeiten")),
        ("text", tr("F2"), tr("Zelle bearbeiten")),
    )


def build_help_content() -> QWidget:
    """Inhalt des Hilfe-Sheets."""
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    body.setMinimumWidth(440)

    layout.addWidget(
        _body(
            tr(
                "Links wählst du Drucker und Band. Das Etikett liegt in der "
                "Mitte, die Eigenschaften des Markierten rechts, zusammen "
                "mit dem Druck. Esc schließt diese Hilfe."
            )
        )
    )

    layout.addWidget(_heading(tr("Auf dem Etikett"), "label"))
    layout.addWidget(
        _body(
            tr(
                "Doppelklick auf die freie Fläche setzt ein Textfeld. Ein "
                "Objekt ziehst du mit der Maus. Die Pfeiltasten schieben es "
                "um einen Punkt, mit gehaltener Umschalttaste um zehn. Esc "
                "beendet das Schreiben im Feld und hebt die Auswahl auf."
            )
        )
    )

    layout.addWidget(_heading(tr("Drucken"), "print"))
    layout.addWidget(
        _body(
            tr(
                "Die Druckvorschau zeigt die Punkte, so wie der Drucker sie "
                "setzt. Esc bringt die normale Ansicht zurück."
            )
        )
    )

    layout.addWidget(_heading(tr("Mit der Maus"), "zoom_in"))
    layout.addWidget(
        _body(
            tr(
                "Strg und das Mausrad zoomen, Umschalt und das Mausrad "
                "schieben seitlich. Strg+Klick nimmt ein Objekt zur Auswahl "
                "dazu oder wieder weg. Strg gedrückt halten und ein markiertes "
                "Objekt ziehen lässt das Original liegen und bewegt die Kopie. "
                "In einer Tabelle markiert Umschalt+Klick mehrere Zellen, Tab "
                "und Umschalt+Tab gehen zur nächsten. In der Datenbank-Tabelle "
                "nimmt Strg+Klick eine Zeile dazu oder weg, Umschalt+Klick "
                "wählt einen Bereich. Beim Drehen rastet der "
                "Winkel auf 90 Grad, mit gehaltener Umschalttaste in Schritten "
                "von 15 Grad."
            )
        )
    )

    layout.addWidget(_heading(tr("Tasten")))
    layout.addWidget(_shortcut_table(action_shortcuts() + canvas_shortcuts()))

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(body)
    scroll.setMinimumWidth(480)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    scroll.viewport().setAutoFillBackground(False)
    body.setAutoFillBackground(False)
    return scroll


def show_help(parent: QWidget) -> Sheet:
    """Das Hilfe-Sheet im Hauptfenster öffnen.

    Esc und ein Klick auf die Abdunklung schließen es.
    """
    return show_widget(
        parent,
        title=tr("Hilfe"),
        content=build_help_content(),
        close_on_outside=True,
    )


def _shortcut_table(
    rows: tuple[tuple[str | None, str, str], ...],
) -> QWidget:
    widget = QWidget()
    grid = QGridLayout(widget)
    grid.setContentsMargins(0, 4, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(5)
    grid.setColumnStretch(2, 1)
    sample = QLabel()
    font = sample.font()
    font.setBold(True)
    sample.setFont(font)
    width = max(sample.fontMetrics().horizontalAdvance(chord) for _, chord, _ in rows)
    for row, (name, chord, what) in enumerate(rows):
        grid.addWidget(_icon(name), row, 0, Qt.AlignmentFlag.AlignVCenter)
        key = QLabel(chord)
        font = key.font()
        font.setBold(True)
        key.setFont(font)
        key.setMinimumWidth(width)
        grid.addWidget(key, row, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(_body(what), row, 2)
    return widget


def _icon(name: str | None) -> QLabel:
    label = QLabel()
    label.setFixedSize(_ICON_PX, _ICON_PX)
    if name:
        label.setPixmap(icon(name).pixmap(_ICON_PX, _ICON_PX))
    return label


def _heading(text: str, name: str | None = None) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 10, 0, 0)
    layout.setSpacing(8)
    if name:
        layout.addWidget(_icon(name))
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    layout.addWidget(label)
    layout.addStretch(1)
    return row


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_HINT_STYLE)
    return label
