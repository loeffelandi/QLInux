"""Das „Über QLInux"-Sheet.

Ein eigenes Modul, weil der Text lang ist: QLInux ist nicht auf ein Modell
zugeschnitten - es kann *alle* Drucker, die die Bibliothek ``brother_ql``
kennt. Dazu die Danksagung an die Bibliotheken und der Lizenzhinweis.

Gezeigt wird ein **Sheet** im Hauptfenster (siehe :mod:`ql_editor.sheet`),
kein eigenes Fenster.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import __version__, media
from .i18n import tr
from .sheet import Sheet, show_widget

#: Quelltext, Fehler, Lizenz - eine Adresse fuer alles.
PROJECT_URL = "https://github.com/loeffelandi/QLInux"

#: Entwickler (Haus) und Adresse.
DEVELOPER = "Sustain – Andreas Schäfer"
DEVELOPER_URL = "https://www.sustain-vt.de"

#: Schriftfarbe der Nebenzeilen (wie die Hinweise im Panel).
_HINT_STYLE = "color:#6b7280;"


def credits() -> tuple[tuple[str, str, str, str], ...]:
    """Bibliotheken, ohne die QLInux nicht drucken wuerde.

    ``(Name, Autor, Lizenz, Beitrag)`` - Name und Lizenz bleiben stehen (das
    sind Eigennamen bzw. Rechtstexte), Autor- und Beitragstext laufen durch
    :func:`tr`. Bewusst eine Funktion: die Sprache steht erst zur Laufzeit
    fest, und beim Umschalten wird die Oberflaeche neu gebaut.
    """
    return (
        (
            "brother_ql",
            "Philipp Klaus",
            "GPL-3.0-or-later",
            tr("Druckerbefehle, Band- und Modellmaße"),
        ),
        (
            "Qt for Python (PySide6)",
            "The Qt Company",
            "LGPL-3.0",
            tr("Oberfläche (Fenster, Canvas, Sheets)"),
        ),
        (
            "Pillow",
            tr("Fredrik Lundh und Mitwirkende"),
            "MIT-CMU",
            tr("Rendering und Rasterdaten"),
        ),
        (
            "pyusb",
            tr("Wander Lairson Costa und Mitwirkende"),
            "BSD-3-Clause",
            tr("USB-Anschluss"),
        ),
        (
            "qrcode",
            tr("Lincoln Loop und Mitwirkende"),
            "BSD-3-Clause",
            tr("QR-Codes"),
        ),
        (
            "python-barcode",
            tr("Thorsten Weimann und Mitwirkende"),
            "MIT",
            tr("Barcodes"),
        ),
    )


def build_about_content() -> QWidget:
    """Inhalt des Über-Sheets: Modellliste, Lizenz, Danksagung, Entwickler."""
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    # Feste Breite: sonst entscheidet die Laenge der Modellliste ueber die
    # Breite des Sheets, und die Aufzaehlung wird seitenweise umbrochen.
    content.setMinimumWidth(460)

    subtitle = QLabel(
        tr(
            "Etiketten gestalten und direkt drucken – für Brother-QL-Drucker "
            "und andere, die die Bibliothek brother_ql unterstützt."
        )
    )
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    # -- Drucker -----------------------------------------------------------
    layout.addWidget(_heading(tr("Unterstützte Drucker")))
    models = ", ".join(spec.identifier for spec in media.all_models())
    layout.addWidget(
        _body(
            tr("Alle {models} Modelle, die brother_ql kennt (nichts vorbelegt):")
            .format(models=len(media.all_models()))
        )
    )
    layout.addWidget(_body(models))
    layout.addWidget(
        _body(
            tr(
                "Dazu {labels} Bandtypen mit ihren Maßen, ebenfalls aus der "
                "Bibliothek. Die Auswahl im Panel richtet sich nach dem "
                "gewählten Modell."
            ).format(labels=len(media.all_labels()))
        )
    )

    # -- Lizenz ------------------------------------------------------------
    layout.addWidget(_heading(tr("Freie Software")))
    layout.addWidget(
        _body(
            tr(
                "QLInux steht unter der GNU General Public License, Version 3 "
                "oder später (GPL-3.0-or-later) - so offen wie die "
                "Bibliothek, auf der es aufbaut."
            )
        )
    )
    layout.addWidget(
        _link(
            tr("Lizenztext"),
            f"{PROJECT_URL}/blob/main/LICENSE",
        )
    )

    # -- Danksagung --------------------------------------------------------
    layout.addWidget(_heading(tr("Dank an")))
    for name, author, license_id, contribution in credits():
        line = QLabel(
            f"<b>{name}</b> – {author} ({license_id}): {contribution}"
        )
        line.setWordWrap(True)
        line.setStyleSheet(_HINT_STYLE)
        layout.addWidget(line)

    # -- Entwickler --------------------------------------------------------
    layout.addWidget(_heading(tr("Entwickelt von")))
    layout.addWidget(
        _rich(
            f"<b>{DEVELOPER}</b> · "
            f'<a href="{DEVELOPER_URL}">{DEVELOPER_URL.replace("https://", "")}</a>'
        )
    )
    layout.addWidget(_link(tr("Quelltext und Fehler melden"), PROJECT_URL))
    layout.addWidget(_body(f"{tr('Version')} {__version__}"))
    return content


def show_about(parent: QWidget) -> Sheet:
    """Das Über-Sheet im Hauptfenster öffnen."""
    return show_widget(
        parent, title=tr("Über QLInux"), content=build_about_content()
    )


# --------------------------------------------------------------- Bausteine --
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


def _rich(html: str) -> QLabel:
    label = QLabel(html)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction
    )
    return label


def _link(text: str, url: str) -> QLabel:
    return _rich(f'<a href="{url}">{text}</a>')
