"""Das Hilfe-Sheet.

Gleiche Form wie „Über QLInux“: ein Sheet im Hauptfenster, kein eigenes
Fenster. Der Text ist absichtlich kurz. Die Tastenübersicht nennt nur, was
der Code wirklich bindet - neue Tasten gehören zuerst hierher, deutsch und
englisch (siehe ``docs/hilfe.md``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .i18n import tr
from .sheet import Sheet, show_widget

_HINT_STYLE = "color:#6b7280;"


def action_shortcuts() -> tuple[tuple[str, str], ...]:
    """Tasten an :class:`QAction`, so wie Qt sie auf Linux legt.

    ``(Taste, was sie tut)`` in der aktuellen Sprache. Die deutschen Texte
    sind die Schlüssel, deshalb stehen sie hier als Literale.
    """
    return (
        (tr("Strg+N"), tr("Neues Etikett")),
        (tr("Strg+O"), tr("Etikett öffnen")),
        (tr("Strg+S"), tr("Etikett speichern")),
        (tr("Strg+Umschalt+S"), tr("Speichern unter…")),
        (tr("Strg+F4"), tr("Reiter schließen")),
        (tr("Strg+Tab"), tr("Nächster Reiter")),
        (tr("Strg+Umschalt+Tab"), tr("Vorheriger Reiter")),
        (tr("Strg+Z"), tr("Rückgängig")),
        (tr("Strg+Y"), tr("Wiederholen")),
        (tr("Entf"), tr("Auswahl löschen")),
        (tr("Strg+0"), tr("Einpassen")),
        (tr("Strg++"), tr("Vergrößern")),
        (tr("Strg+-"), tr("Verkleinern")),
        (tr("Strg+1"), tr("Zoom 1:1")),
        (tr("Strg+B"), tr("Panel links")),
        (tr("Strg+Umschalt+B"), tr("Panel rechts")),
        (tr("Strg+K"), tr("Befehl suchen")),
        (tr("Strg+P"), tr("Drucken")),
        (tr("Strg+Umschalt+P"), tr("Druckvorschau")),
    )


def canvas_shortcuts() -> tuple[tuple[str, str], ...]:
    """Tasten, die der Canvas selbst auswertet, ohne eigene Aktion."""
    return (
        (tr("Esc"), tr("Tippen beenden und die Auswahl aufheben")),
        (tr("Pfeiltasten"), tr("Um einen Punkt verschieben")),
        (tr("Umschalt+Pfeiltasten"), tr("Um zehn Punkte verschieben")),
        (tr("Rücktaste"), tr("Auswahl löschen")),
        (tr("Tab"), tr("Nächste Zelle")),
        (tr("Umschalt+Tab"), tr("Vorherige Zelle")),
        (tr("Eingabe"), tr("Zelle bearbeiten")),
        (tr("F2"), tr("Zelle bearbeiten")),
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

    layout.addWidget(_heading(tr("Auf dem Etikett")))
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

    layout.addWidget(_heading(tr("Drucken")))
    layout.addWidget(
        _body(
            tr(
                "Die Druckvorschau zeigt die Punkte, so wie der Drucker sie "
                "setzt. Esc bringt die normale Ansicht zurück."
            )
        )
    )

    layout.addWidget(_heading(tr("Mit der Maus")))
    layout.addWidget(
        _body(
            tr(
                "Strg und das Mausrad zoomen, Umschalt und das Mausrad "
                "schieben seitlich. Strg+Klick nimmt ein Objekt zur Auswahl "
                "dazu oder wieder weg. In einer Tabelle markiert "
                "Umschalt+Klick mehrere Zellen, Tab und Umschalt+Tab gehen "
                "zur nächsten. Beim Drehen rastet der Winkel auf 90 Grad, "
                "mit gehaltener Umschalttaste in Schritten von 15 Grad."
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
    scroll.setMinimumWidth(460)
    return scroll


def show_help(parent: QWidget) -> Sheet:
    """Das Hilfe-Sheet im Hauptfenster öffnen."""
    return show_widget(parent, title=tr("Hilfe"), content=build_help_content())


def _shortcut_table(rows: tuple[tuple[str, str], ...]) -> QWidget:
    widget = QWidget()
    grid = QGridLayout(widget)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(2)
    grid.setColumnStretch(1, 1)
    for row, (chord, what) in enumerate(rows):
        key = QLabel(chord)
        font = key.font()
        font.setBold(True)
        key.setFont(font)
        grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(_body(what), row, 1)
    return widget


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_HINT_STYLE)
    return label
