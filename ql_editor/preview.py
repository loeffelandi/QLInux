"""Monochrome 1-bit Druckvorschau.

Bildet **exakt** die Binarisierung nach, die
:func:`brother_ql.conversion.convert` fuer den Druck verwendet. Der Nutzer
sieht damit, was der Drucker ausgibt (Threshold + optional Floyd-Steinberg).

Polaritaet:
* ``convert`` erzeugt intern ein ``mode="1"``-Bild, in dem **255 = Tinte**
  bedeutet (bestaetigt per Reader-Roundtrip, siehe Tests).
* Die Vorschau hier liefert die *visuelle* Darstellung: **0 = Tinte (schwarz),
  255 = Papier (weiss)** - so wie das Etikett auf dem Band erscheint.

Die Kernfunktionen (:func:`binarize`, :func:`ink_ratio`) sind Qt-frei und
headless testbar; :class:`PreviewWidget` ist das GUI-Widget.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget


@dataclass(frozen=True)
class PreviewOptions:
    """Parameter der Vorschau - identisch zur Bedeutung in ``convert()``.

    ``threshold``:
        Wie im brother_ql-CLI. Intern invertiert (``100 - threshold``), d. h.
        ein **hoeherer** Wert laesst **mehr** Pixel zu Tinte werden.
    ``dither``:
        Statt hartem Threshold Floyd-Steinberg-Dithering verwenden.
    """

    threshold: int = 70
    dither: bool = False

    def library_threshold(self) -> int:
        """Der Wert, den ``convert`` intern als 0..255-Schwelle nutzt."""
        return min(255, max(0, int((100.0 - self.threshold) / 100.0 * 255.0)))


def binarize(image: Image.Image, options: PreviewOptions | None = None) -> Image.Image:
    """Erzeuge die 1-bit-Vorschau (``mode="1"``, 0 = Tinte, 255 = Papier).

    Repliziert die Schritte aus ``convert()``:

    ``L`` -> invertieren -> (Dither | Threshold) -> in visuelle Polaritaet.
    """
    options = options or PreviewOptions()
    gray = image.convert("L")
    # convert() arbeitet auf dem invertierten Bild und behandelt helle
    # (invertierte) Werte als Tinte.
    inverted = ImageOps.invert(gray)

    if options.dither:
        ink = inverted.convert("1", dither=Image.FLOYDSTEINBERG)  # 255 = Tinte
    else:
        thr = options.library_threshold()
        ink = inverted.point(lambda x: 0 if x < thr else 255, mode="1")  # 255 = Tinte

    # Visuelle Polaritaet: 255 (=Tinte) -> 0 (schwarz), 0 (=Papier) -> 255 (weiss).
    visual = ink.point(lambda x: 0 if x == 255 else 255, mode="1")
    return visual


def preview_to_convert_parity(
    image: Image.Image, options: PreviewOptions | None = None
) -> Image.Image:
    """Intern verwendete 1-bit-Repraesentation (255 = Tinte) wie in ``convert``.

    Nuetzlich fuer Tests der Paritaet: die Binarisierung muss der Bibliothek
    entsprechen. Die UI nutzt :func:`binarize`.
    """
    return ImageOps.invert(binarize(image, options).convert("L")).convert("1")


def ink_ratio(image: Image.Image, options: PreviewOptions | None = None) -> float:
    """Anteil der Tinte (0.0..1.0) im binarisierten Bild - fuer Warnhinweise."""
    visual = binarize(image, options).convert("L")
    histogram = visual.histogram()
    total = sum(histogram)
    if total == 0:
        return 0.0
    ink = histogram[0]  # 0 = Tinte
    return ink / total


def to_qimage(image: Image.Image) -> QImage:
    """Konvertiere die 1-bit-Vorschau in ein ``QImage`` (fuer die GUI)."""
    visual = image if image.mode == "1" else image.convert("1")
    data = visual.tobytes("raw", "1")
    width, height = visual.size
    stride = (width + 7) // 8
    # QImage behaelt keine Referenz auf den Puffer -> kopieren.
    qimg = QImage(data, width, height, stride, QImage.Format.Format_Mono)
    return qimg.copy()


class PreviewWidget(QWidget):
    """Zeigt die monochrome 1-bit-Vorschau (das, was gedruckt wird)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._options = PreviewOptions()
        self._pil_image: Image.Image | None = None
        self._rendered: Image.Image | None = None

        self._info = QLabel("Keine Vorschau")
        self._info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info.setStyleSheet("color:#555; padding:4px;")
        self._canvas = QLabel("Noch nichts zu drucken")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setMinimumSize(120, 90)
        # Wichtig: der QLabel darf seine Pixmap-Groesse NICHT als sizeHint an
        # das Layout weitergeben, sonst waechst das Dock bei jedem Resize
        # (Skalieren auf die eigene Groesse -> Feedback-Schleife).
        self._canvas.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._canvas.setStyleSheet("background:#ffffff; border:1px solid #999;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._info)
        layout.addWidget(self._canvas, 1)

    def set_options(self, options: PreviewOptions) -> None:
        self._options = options
        self._refresh()

    def set_image(self, image: Image.Image | None) -> None:
        self._pil_image = image
        self._refresh()

    def _refresh(self) -> None:
        if self._pil_image is None:
            self._rendered = None
            self._canvas.setPixmap(QPixmap())
            self._canvas.setText("Noch nichts zu drucken")
            self._info.setText("Keine Vorschau")
            return
        visual = binarize(self._pil_image, self._options)
        self._rendered = visual
        self._info.setText(
            f"{visual.width} x {visual.height} px · Tinte "
            f"{ink_ratio(self._pil_image, self._options) * 100:.1f} %"
        )
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._rendered is None:
            return
        pixmap = QPixmap.fromImage(to_qimage(self._rendered))
        scaled = pixmap.scaled(
            self._canvas.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._canvas.setPixmap(scaled)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_pixmap()


__all__ = [
    "PreviewOptions",
    "binarize",
    "preview_to_convert_parity",
    "ink_ratio",
    "to_qimage",
    "PreviewWidget",
]
