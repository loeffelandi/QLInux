"""App-Symbol und Dateitypsymbole erzeugen (``assets/*.png``).

Ein Aufruf, feste Ausgabe - so ist das Symbol reproduzierbar und nicht ein
Binaerblob, den niemand mehr aendern kann:

    .venv/bin/python packaging/make_icon.py

Gezeichnet wird bewusst schlicht (ein Etikettenstreifen mit "QL"): es muss bei
32 px in einer Fensterliste genauso lesbar sein wie bei 256 px im Dock.

Dazu kommen die Symbole fuer die Dateitypen ``.qlx`` und ``.lbx``: ein Blatt
mit Eselsohr, unten ein Streifen mit dem Kuerzel, in 256 und 128 px. Die
Dateinamen stehen in ``packaging/ql-editor-mime.xml``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication

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

#: Dateitypsymbole: Dateiname -> (Kuerzel auf dem Streifen, Farbe des Streifens).
MIME_ICONS = {
    "application-x-qlinux-label.png": ("QLX", ACCENT),
    "application-x-brother-lbx.png": ("LBX", "#1f5fa8"),
}
MIME_TARGET_DIR = ROOT / "assets" / "mimetypes"
#: Zusaetzlich zu 256, damit Dateimanager nicht nur die grosse Stufe skalieren.
MIME_SMALL = 128
MIME_SMALL_DIR = MIME_TARGET_DIR / "128"


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
    painter.drawRoundedRect(QRectF(26, SIZE * 0.30, SIZE - 52, SIZE * 0.40), 18, 18)

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


def build_mime_icon(badge: str, color: str) -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # Blatt mit abgeknicktem Eck oben rechts.
    fold = 56
    page = QPainterPath()
    page.moveTo(32, 8)
    page.lineTo(SIZE - 32 - fold, 8)
    page.lineTo(SIZE - 32, 8 + fold)
    page.lineTo(SIZE - 32, SIZE - 8)
    page.lineTo(32, SIZE - 8)
    page.closeSubpath()
    painter.setPen(QPen(QColor(EDGE), 4))
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(page)

    corner = QPainterPath()
    corner.moveTo(SIZE - 32 - fold, 8)
    corner.lineTo(SIZE - 32 - fold, 8 + fold)
    corner.lineTo(SIZE - 32, 8 + fold)
    corner.closeSubpath()
    painter.setBrush(QColor("#d5dde5"))
    painter.drawPath(corner)

    # Zeilen als Andeutung des Inhalts.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(EDGE))
    for y in (96, 120):
        painter.drawRoundedRect(QRectF(56, y, 120, 12), 6, 6)

    # Streifen mit Kuerzel unten - das unterscheidet die Dateitypen.
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(40, 160, SIZE - 80, 64), 12, 12)
    font = QFont("DejaVu Sans")
    font.setBold(True)
    font.setPixelSize(44)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        QRectF(40, 160, SIZE - 80, 64), Qt.AlignmentFlag.AlignCenter, badge
    )
    painter.end()
    return image


def main() -> int:
    # Die QApplication muss leben, solange das Icon gezeichnet wird.
    app = QApplication.instance() or QApplication([])  # noqa: F841
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if not build_icon().save(str(TARGET)):
        print(f"konnte {TARGET} nicht schreiben", file=sys.stderr)
        return 1
    print(f"geschrieben: {TARGET} ({SIZE}x{SIZE})")
    MIME_TARGET_DIR.mkdir(parents=True, exist_ok=True)
    MIME_SMALL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (badge, color) in MIME_ICONS.items():
        image = build_mime_icon(badge, color)
        target = MIME_TARGET_DIR / name
        if not image.save(str(target)):
            print(f"konnte {target} nicht schreiben", file=sys.stderr)
            return 1
        print(f"geschrieben: {target} ({SIZE}x{SIZE})")
        small = image.scaled(
            MIME_SMALL,
            MIME_SMALL,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        small_target = MIME_SMALL_DIR / name
        if not small.save(str(small_target)):
            print(f"konnte {small_target} nicht schreiben", file=sys.stderr)
            return 1
        print(f"geschrieben: {small_target} ({MIME_SMALL}x{MIME_SMALL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
