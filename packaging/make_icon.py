"""App-Symbol und Dateitypsymbole erzeugen (``assets/*.png``).

Ein Aufruf, feste Ausgabe - so ist das Symbol reproduzierbar und nicht ein
Binaerblob, den niemand mehr aendern kann:

    .venv/bin/python packaging/make_icon.py

Gezeichnet wird bewusst schlicht (ein Etikettenstreifen mit "QL"): es muss bei
32 px in einer Fensterliste genauso lesbar sein wie bei 256 px im Dock.

Dazu kommen die Symbole fuer die Dateitypen ``.qlx`` und ``.lbx``: ein Blatt
mit Eselsohr, unten ein Streifen mit dem Kuerzel, in 256 und 128 px. Die
Dateinamen stehen in ``packaging/ql-editor-mime.xml``.

Auf dem Mac entstehen daraus zusaetzlich ``.icns``-Dateien (``iconutil``),
neu gezeichnet in jeder Stufe, nicht hochskaliert. Ohne ``iconutil`` (Linux)
bleiben die vorhandenen ``.icns`` unveraendert. Die PNGs entstehen nur, wenn
"DejaVu Sans" installiert ist (auf dem Mac meist nicht): sonst wuerden sie mit
einer anderen Schrift neu gezeichnet.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
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

#: Stufen eines ``.iconset``: (Kantenlaenge in Pixel, Dateiname).
ICONSET_LEVELS = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


def _canvas(size: int) -> tuple[QImage, QPainter]:
    """Leeres Bild der Kantenlaenge ``size``; gemalt wird weiter in 256er-Einheiten."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    if size != SIZE:
        painter.scale(size / SIZE, size / SIZE)
    return image, painter


def build_icon(size: int = SIZE) -> QImage:
    image, painter = _canvas(size)
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


def build_mime_icon(badge: str, color: str, size: int = SIZE) -> QImage:
    image, painter = _canvas(size)
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


def write_icns(target: Path, draw) -> bool:
    """``.icns`` aus einem Zeichner ``draw(size) -> QImage`` bauen (nur macOS)."""
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        print(f"uebersprungen (kein iconutil): {target}")
        return True
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{target.stem}.iconset"
        iconset.mkdir()
        for size, name in ICONSET_LEVELS:
            if not draw(size).save(str(iconset / name)):
                print(f"konnte {iconset / name} nicht schreiben", file=sys.stderr)
                return False
        result = subprocess.run(
            [iconutil, "-c", "icns", "-o", str(target), str(iconset)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        print(f"iconutil: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"geschrieben: {target}")
    return True


def main() -> int:
    # Die QApplication muss leben, solange das Icon gezeichnet wird.
    app = QApplication.instance() or QApplication([])  # noqa: F841
    if "DejaVu Sans" in QFontDatabase.families():
        if not write_pngs():
            return 1
    else:
        # Ohne die Schrift sehen die PNGs anders aus als die eingecheckten.
        print("uebersprungen (DejaVu Sans fehlt): PNGs bleiben unveraendert")
    if not write_icns(TARGET.with_suffix(".icns"), build_icon):
        return 1
    for name, (badge, color) in MIME_ICONS.items():
        target = (MIME_TARGET_DIR / name).with_suffix(".icns")
        if not write_icns(
            target,
            lambda size, badge=badge, color=color: build_mime_icon(badge, color, size),
        ):
            return 1
    return 0


def write_pngs() -> bool:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if not build_icon().save(str(TARGET)):
        print(f"konnte {TARGET} nicht schreiben", file=sys.stderr)
        return False
    print(f"geschrieben: {TARGET} ({SIZE}x{SIZE})")
    MIME_TARGET_DIR.mkdir(parents=True, exist_ok=True)
    MIME_SMALL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (badge, color) in MIME_ICONS.items():
        image = build_mime_icon(badge, color)
        target = MIME_TARGET_DIR / name
        if not image.save(str(target)):
            print(f"konnte {target} nicht schreiben", file=sys.stderr)
            return False
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
            return False
        print(f"geschrieben: {small_target} ({MIME_SMALL}x{MIME_SMALL})")
    return True
