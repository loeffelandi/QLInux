"""App-Symbol erzeugen (``assets/ql-editor.png``).

Ein Aufruf, feste Ausgabe - so ist das Symbol reproduzierbar und nicht ein
Binaerblob, den niemand mehr aendern kann:

    .venv/bin/python packaging/make_icon.py

Gezeichnet wird bewusst schlicht (ein Etikettenstreifen mit "QL"): es muss bei
32 px in einer Fensterliste genauso lesbar sein wie bei 256 px im Dock.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "assets" / "ql-editor.png"

#: Groesse des Symbols (Pixel, quadratisch).
SIZE = 256
#: Eckenradius des Hintergrunds.
CORNER = 48
#: Farben: dunkler Grund, heller Streifen, Akzent wie die rote Schrift.
BACKGROUND = "#1f2933"
STRIP = "#f7fafc"
EDGE = "#9aa5b1"
ACCENT = "#c1292e"


def build_icon() -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, SIZE, SIZE), CORNER, CORNER)

    # Etikettenstreifen, schraeg wie ein abgeschnittenes Band.
    painter.setBrush(QColor(STRIP))
    painter.setPen(QColor(EDGE))
    pen = painter.pen()
    pen.setWidth(3)
    painter.setPen(pen)
    painter.drawRoundedRect(
        QRectF(26, SIZE * 0.30, SIZE - 52, SIZE * 0.40), 18, 18
    )

    # "QL" - fett und gross, damit es auch klein lesbar bleibt.
    font = QFont("DejaVu Sans")
    font.setBold(True)
    font.setPixelSize(int(SIZE * 0.28))
    painter.setFont(font)
    painter.setPen(QColor(BACKGROUND))
    painter.drawText(
        QRectF(26, SIZE * 0.28, SIZE - 52 - 26, SIZE * 0.42),
        Qt.AlignmentFlag.AlignCenter,
        "QL",
    )

    # Akzent rechts: das abgeschnittene Bandende (rot wie die rote Schrift).
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    right = SIZE - 26
    painter.drawPolygon(
        [
            QPointF(right - 18, SIZE * 0.30),
            QPointF(right, SIZE * 0.50),
            QPointF(right - 18, SIZE * 0.70),
        ]
    )
    painter.end()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication([])
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if not build_icon().save(str(TARGET)):
        print(f"konnte {TARGET} nicht schreiben", file=sys.stderr)
        return 1
    print(f"geschrieben: {TARGET} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
