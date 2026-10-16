"""Tests fuer :mod:`ql_editor.preview` (monochrome 1-bit-Vorschau)."""

from __future__ import annotations

import pytest
from PIL import Image

from ql_editor.preview import (
    PreviewOptions,
    binarize,
    ink_ratio,
    preview_to_convert_parity,
    to_qimage,
)


def test_binarize_mode_and_size():
    img = Image.new("L", (50, 20), 255)
    out = binarize(img)
    assert out.mode == "1"
    assert out.size == (50, 20)


def test_white_stays_paper_black_becomes_ink():
    white = Image.new("L", (10, 10), 255)
    black = Image.new("L", (10, 10), 0)
    assert binarize(white).convert("L").getextrema() == (255, 255)  # nur Papier
    assert binarize(black).convert("L").getextrema() == (0, 0)      # nur Tinte


def test_threshold_boundary_matches_convert():
    # Default threshold=70 -> interne Schwelle 76 -> Tinte fuer L <= 179.
    opts = PreviewOptions(threshold=70)
    assert opts.library_threshold() == 76

    dark_enough = Image.new("L", (1, 1), 179)
    too_light = Image.new("L", (1, 1), 180)
    assert binarize(dark_enough, opts).convert("L").getpixel((0, 0)) == 0     # Tinte
    assert binarize(too_light, opts).convert("L").getpixel((0, 0)) == 255     # Papier


def test_higher_threshold_means_more_ink():
    img = Image.new("L", (1, 1), 200)
    # threshold=70 -> Schwelle 76 -> invertiert 55 < 76 -> Papier.
    assert binarize(img, PreviewOptions(threshold=70)).convert("L").getpixel((0, 0)) == 255
    # threshold=90 -> Schwelle 25 -> invertiert 55 >= 25 -> Tinte.
    assert binarize(img, PreviewOptions(threshold=90)).convert("L").getpixel((0, 0)) == 0


def test_dither_produces_mixed_output():
    gradient = Image.linear_gradient("L").resize((80, 40))
    out = binarize(gradient, PreviewOptions(dither=True))
    assert out.mode == "1"
    ratio = ink_ratio(gradient, PreviewOptions(dither=True))
    assert 0.0 < ratio < 1.0


def test_ink_ratio_extremes():
    assert ink_ratio(Image.new("L", (20, 20), 255)) == 0.0
    assert ink_ratio(Image.new("L", (20, 20), 0)) == 1.0


def test_parity_polarity_matches_convert():
    # preview_to_convert_parity: 255 = Tinte (wie in convert intern).
    black = Image.new("L", (4, 4), 0)
    white = Image.new("L", (4, 4), 255)
    assert preview_to_convert_parity(black).convert("L").getextrema() == (255, 255)
    assert preview_to_convert_parity(white).convert("L").getextrema() == (0, 0)


def test_to_qimage_size(qapp):
    visual = binarize(Image.new("L", (30, 12), 128))
    qimg = to_qimage(visual)
    assert qimg.width() == 30
    assert qimg.height() == 12
    assert not qimg.isNull()


def test_to_qimage_is_drawable(qapp):
    """Regression: das QImage muss von QPainter zeichenbar sein.

    Ein aus Python-Bytes konstruiertes ``Format_Mono``-Bild hat hier einen
    Segmentation Fault beim Zeichnen ausgeloest - deshalb Grayscale8.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter, QPixmap

    visual = binarize(Image.linear_gradient("L").resize((40, 20)))
    qimg = to_qimage(visual)

    pixmap = QPixmap(80, 40)
    pixmap.fill()
    painter = QPainter(pixmap)
    painter.drawImage(QRectF(0, 0, 40, 20), qimg)
    painter.end()
    assert not pixmap.isNull()
