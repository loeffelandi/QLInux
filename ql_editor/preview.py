"""Monochrome 1-bit Druckvorschau (Kernfunktionen).

Bildet **exakt** die Binarisierung nach, die
:func:`brother_ql.conversion.convert` fuer den Druck verwendet. Damit laesst
sich zeigen, was der Drucker ausgibt (Threshold + optional Floyd-Steinberg).

Polaritaet:
* ``convert`` erzeugt intern ein ``mode="1"``-Bild, in dem **255 = Tinte**
  bedeutet (bestaetigt per Reader-Roundtrip, siehe Tests).
* :func:`binarize` liefert die *visuelle* Darstellung: **0 = Tinte (schwarz),
  255 = Papier (weiss)** - so wie das Etikett auf dem Band erscheint.

Alle Funktionen hier sind Qt-frei und headless testbar. Die Darstellung
uebernimmt der Canvas selbst (Druckvorschau-Modus), siehe
:mod:`ql_editor.canvas`.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps
from PySide6.QtGui import QImage

#: Standard-Schwelle in Prozent - identisch zum brother_ql-CLI (``-t``) und
#: zum Default in :mod:`ql_editor.printer`.
DEFAULT_THRESHOLD = 70


@dataclass(frozen=True)
class PreviewOptions:
    """Parameter der Vorschau - identisch zur Bedeutung in ``convert()``.

    ``threshold``:
        Wie im brother_ql-CLI. Intern invertiert (``100 - threshold``), d. h.
        ein **hoeherer** Wert laesst **mehr** Pixel zu Tinte werden.
    ``dither``:
        Statt hartem Threshold Floyd-Steinberg-Dithering verwenden.
    """

    threshold: int = DEFAULT_THRESHOLD
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
    """Konvertiere die 1-bit-Vorschau in ein ``QImage`` (fuer den Canvas).

    Bewusst ``Format_Grayscale8``: kompakt (1 Byte/Pixel) und von
    ``QPainter`` zuverlaessig zeichenbar. Ein aus einem Python-Puffer
    konstruiertes ``Format_Mono``-Bild fuehrt in dieser Qt-Version beim
    Zeichnen zu einem Segmentation Fault (siehe Tests).
    """
    gray = image if image.mode == "L" else image.convert("L")
    data = gray.tobytes("raw", "L")
    width, height = gray.size
    # QImage behaelt keine Referenz auf den Puffer -> kopieren.
    qimg = QImage(data, width, height, width, QImage.Format.Format_Grayscale8)
    return qimg.copy()


__all__ = [
    "PreviewOptions",
    "binarize",
    "preview_to_convert_parity",
    "ink_ratio",
    "to_qimage",
]
