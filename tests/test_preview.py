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


def test_preview_is_pixel_identical_to_the_printer_data():
    """Kernversprechen: die Vorschau zeigt *genau* die Druckdaten.

    Der Test faengt das 1-bit-Bild ab, das ``convert`` an den Drucker gibt, und
    vergleicht es Pixel fuer Pixel mit :func:`binarize` - fuer alle
    Threshold-/Dither-Kombinationen.
    """
    from brother_ql.raster import BrotherQLRaster

    from ql_editor.media import get_label
    from ql_editor.printer import PrinterConfig, build_raster

    # Weisser Rand: beim Dithering darf kein Fehler von aussen hineindiffundieren
    # (beim Druck liegt das Bild auf einer weissen 696er-Flaeche).
    base = Image.new("L", (554, 200), 255)
    base.paste(Image.linear_gradient("L").resize((534, 180)), (10, 10))
    render = base.convert("RGB")
    label = get_label("50")
    config = PrinterConfig(model="QL-820NWB", address="tcp://127.0.0.1:9100")

    captured: dict[str, Image.Image] = {}
    original = BrotherQLRaster.add_raster_data

    def spy(self, image_black, image_red=None):
        captured["image"] = image_black.copy()
        return original(self, image_black, image_red)

    BrotherQLRaster.add_raster_data = spy
    try:
        for threshold in (50, 70, 90):
            for dither in (False, True):
                options = PreviewOptions(threshold=threshold, dither=dither)
                build_raster(render, label, config, threshold=threshold, dither=dither)

                # convert liefert 255 = Tinte; binarize 0 = Tinte.
                sent = captured["image"]
                sent_visual = sent.convert("L").point(lambda x: 0 if x else 255, mode="1")
                offset = sent.width - render.width - label.right_margin_dots
                crop = sent_visual.crop((offset, 0, offset + render.width, render.height))

                assert crop.tobytes() == binarize(render, options).tobytes(), (
                    f"Vorschau weicht bei threshold={threshold}, dither={dither} ab"
                )
    finally:
        BrotherQLRaster.add_raster_data = original
